"""Автоматический разбор очереди калибровки: debounce → LLM → отчёты (порт S11).

TG-оркестратор калибровки: debounce/отправка в боте, пайплайн — market.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot

from bot_app.config import get_bot_settings
from bot_app.services import salary_calib_pipeline as pipeline
from bot_app.storage import salary_calib_sessions
from bot_app.telegram_send import safe_send
from bot_app.utils import esc
from core.domains.market.salary_calib import (
    count_queue,
    count_samples,
    fetch_relevant_samples,
    get_meta,
    requeue_processing,
    retry_error_queue,
    set_meta,
)
from core.domains.market.salary_calibration import (
    build_benchmark_insights,
    export_calibration_snapshot,
)
from core.platform.repo.accounts import get_account_by_telegram_chat_id

logger = logging.getLogger(__name__)


class SalaryCalibOrchestrator:
    def __init__(self) -> None:
        self._bot: Bot | None = None
        self._process_lock = asyncio.Lock()
        self._debounce_tasks: dict[int, asyncio.Task] = {}
        self._running_chats: set[int] = set()

    def attach(self, bot: Bot) -> None:
        self._bot = bot

    def _meta_key(self, chat_id: int, suffix: str) -> str:
        return f"chat_{chat_id}_{suffix}"

    async def _last_reported_relevant(self, chat_id: int) -> int:
        account = await get_account_by_telegram_chat_id(chat_id)
        if account is None:
            return 0
        raw = await get_meta(
            self._meta_key(chat_id, "last_reported_relevant"), "0", account_id=account.id
        )
        try:
            return int(raw)
        except ValueError:
            return 0

    async def _set_last_reported_relevant(self, chat_id: int, value: int) -> None:
        account = await get_account_by_telegram_chat_id(chat_id)
        if account is None:
            return
        await set_meta(
            self._meta_key(chat_id, "last_reported_relevant"), str(value), account_id=account.id
        )

    async def recover_on_startup(self) -> None:
        """После рестарта: сессии из БД, зависшие батчи, необработанная очередь."""
        _, recovered, retried = await asyncio.gather(
            salary_calib_sessions.load_from_db(),
            requeue_processing(),
            retry_error_queue(max_items=30),
        )
        if recovered or retried:
            logger.info(
                "Salary calib recovery: processing→pending=%d, error→pending=%d",
                recovered,
                retried,
            )

        settings = get_bot_settings()
        if not settings.salary_calib_auto:
            return

        pending = await count_queue(status="pending")
        if pending <= 0:
            return

        for chat_id in salary_calib_sessions.list_active():
            logger.info(
                "Salary calib: авто-догон очереди для chat=%s (%d pending)", chat_id, pending
            )
            await self.schedule_processing(chat_id, delay_sec=3.0)

    async def on_session_enabled(self, chat_id: int) -> None:
        settings = get_bot_settings()
        pending = await count_queue(status="pending")
        if pending > 0 and settings.salary_calib_auto:
            await self.schedule_processing(chat_id, delay_sec=2.0)

    async def on_session_disabled(self, chat_id: int) -> None:
        task = self._debounce_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        if get_bot_settings().salary_calib_auto:
            await self._drain_queue(chat_id, final=True)

    async def on_post_enqueued(self, chat_id: int) -> None:
        settings = get_bot_settings()
        if not settings.salary_calib_auto:
            return
        if not salary_calib_sessions.is_active(chat_id):
            return
        await self.schedule_processing(chat_id, delay_sec=settings.salary_calib_debounce_sec)

    async def schedule_processing(self, chat_id: int, *, delay_sec: float) -> None:
        old = self._debounce_tasks.pop(chat_id, None)
        if old and not old.done():
            old.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await old

        async def _run() -> None:
            await asyncio.sleep(delay_sec)
            self._debounce_tasks.pop(chat_id, None)
            pending = await count_queue(status="pending")
            if pending < get_bot_settings().salary_calib_min_pending:
                return
            await self._drain_queue(chat_id, final=False)

        self._debounce_tasks[chat_id] = asyncio.create_task(_run())

    async def run_manual_flush(self, chat_id: int, *, on_progress) -> tuple[int, int, int]:
        """Ручной /calib flush — сразу без debounce."""
        return await self._drain_queue(chat_id, final=True, on_progress=on_progress, force=True)

    async def _drain_queue(
        self,
        chat_id: int,
        *,
        final: bool,
        on_progress=None,
        force: bool = False,
    ) -> tuple[int, int, int]:
        if self._bot is None:
            logger.warning("Salary calib orchestrator: bot not attached")
            return 0, 0, 0

        bot = self._bot

        if chat_id in self._running_chats and not force:
            return 0, 0, 0

        if not final and not salary_calib_sessions.is_active(chat_id):
            return 0, 0, 0

        self._running_chats.add(chat_id)
        proc, rel, err = 0, 0, 0

        try:
            pending_before = await count_queue(status="pending")
            if pending_before == 0:
                return 0, 0, 0

            await safe_send(
                bot,
                chat_id,
                esc(f"⏳ Разбираю {pending_before} постов (LLM, батчи по 10)…"),
            )

            async with self._process_lock:

                async def _progress(p: int, r: int, e: int) -> None:
                    if on_progress:
                        await on_progress(p, r, e)
                    elif p and p % 10 == 0:
                        await safe_send(
                            bot,
                            chat_id,
                            esc(f"… {p} постов, релевантных {r}, ошибок {e}"),
                        )

                proc, rel, err = await pipeline.process_pending_queue(on_progress=_progress)

            await self._notify_batch_done(chat_id, proc, rel, err, final=final)
            await self._maybe_auto_analyze(chat_id, final=final)
            return proc, rel, err
        finally:
            self._running_chats.discard(chat_id)

    async def _notify_batch_done(
        self,
        chat_id: int,
        proc: int,
        rel: int,
        err: int,
        *,
        final: bool,
    ) -> None:
        if self._bot is None:
            return
        if proc == 0 and err == 0:
            return

        bot = self._bot

        total_rel = await count_samples(relevant_only=True)
        pending = await count_queue(status="pending")
        tail = (
            "Продолжайте пересылать — разбор запустится сам через ~25 с."
            if not final
            else await pipeline.status_text()
        )

        await safe_send(
            bot,
            chat_id,
            esc(
                f"✅ Готово: {proc} постов, +{rel} релевантных, ошибок {err}.\n"
                f"Всего релевантных в базе: {total_rel}.\n"
                f"В очереди: {pending} pending.\n{tail}"
            ),
        )

    async def _maybe_auto_analyze(self, chat_id: int, *, final: bool) -> None:
        total_rel = await count_samples(relevant_only=True)
        last = await self._last_reported_relevant(chat_id)
        delta = total_rel - last
        threshold = get_bot_settings().salary_calib_analyze_every
        if not final and delta < threshold:
            return
        if total_rel < 5:
            return

        await self._send_analyze_report(chat_id, reason="auto")
        await self._set_last_reported_relevant(chat_id, total_rel)

    async def send_analyze_report(self, chat_id: int, *, reason: str = "manual") -> None:
        await self._send_analyze_report(chat_id, reason=reason)

    async def _send_analyze_report(self, chat_id: int, *, reason: str) -> None:
        if self._bot is None:
            return

        account = await get_account_by_telegram_chat_id(chat_id)
        if account is None:
            logger.warning("Salary calib: нет аккаунта для chat=%s, сводка не отправлена", chat_id)
            return

        settings = get_bot_settings()
        samples = await fetch_relevant_samples(account_id=account.id)
        report = await pipeline.analyze_report(account_id=account.id)
        insights = build_benchmark_insights(samples)

        try:
            export_calibration_snapshot(
                samples,
                report_text=report,
                insights_text=insights,
                export_path=settings.salary_calib_export_path,
            )
        except OSError as exc:
            logger.warning("Salary calib export failed: %s", exc)

        header = "📊 Авто-сводка" if reason == "auto" else "📊 Сводка"
        text = f"{header}\n\n{report}"
        if insights:
            text += f"\n\n{insights}"
        text += f"\n\n💾 {settings.salary_calib_export_path}"

        if len(text) > 4000:
            text = text[:3990] + "\n…"
        await safe_send(self._bot, chat_id, esc(text))


salary_calib_orchestrator = SalaryCalibOrchestrator()
