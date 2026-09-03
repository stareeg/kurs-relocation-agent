"""Сборка и запуск бота (задача 2.6). `run_bot()` зовут `python -m bot_app` и контейнерная
команда образа (deploy/Dockerfile → `uv run --no-sync python -m bot_app`).

Доступ — «оператор» (IsAdmin: DB-owner ∪ env-allowlist) для большинства команд; узкий
список функций открыт ЛЮБОМУ активному
«аккаунту» (IsAccount) — self-serve `/start` и токен входа в веб. Приват-режим
(bot_private_only) обеспечивает outer-middleware ниже: при BOT_PRIVATE_ONLY=true любые
апдейты из не-личных чатов (группы/конфы) отбрасываются до роутеров. Пуш-нотификации
(дайджест/cost) идут напрямую send'ом. HITL-роутер и watch-петля удалены в R-12.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Dispatcher
from aiogram.enums import ChatType
from aiogram.types import BotCommand, CallbackQuery, Message, TelegramObject

from bot_app.api_client import CopilotApiClient
from bot_app.config import BotSettings, get_bot_settings
from bot_app.handlers import (
    auto_apply,
    basic,
    debrief,
    forwarded,
    menu,
    salary_calibration,
    vacancy_actions,
)
from bot_app.services import prep_scheduler
from bot_app.services.prep_scheduler import prep_reminder_loop
from bot_app.services.salary_calib_orchestrator import salary_calib_orchestrator
from bot_app.services.scheduler import register_bot_schedules
from bot_app.session import NETWORK_BACKOFF, create_bot
from core.app import wire_default_ports
from core.app.background import start_background_runtime, stop_background_runtime
from core.platform.observability import event
from core.platform.tasks import get_runtime

logger = logging.getLogger(__name__)

# Управление ботом — через inline-меню, не командами. В «/»-меню клиента остаётся только
# /start (точка входа); всё остальное — кнопки в сообщении меню.
BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Запустить бота"),
]


class _LogUpdateMiddleware(BaseMiddleware):
    """Входящие апдейты — только в файл (DEBUG), терминал держим чистым."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        logger.debug("апдейт %s", getattr(event, "event_type", "?"))
        return await handler(event, data)


class _PrivateOnlyMessageMiddleware(BaseMiddleware):
    def __init__(self, settings: BotSettings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and (
            self._settings.bot_private_only
            and event.chat is not None
            and event.chat.type != ChatType.PRIVATE
        ):
            return None
        return await handler(event, data)


class _PrivateOnlyCallbackMiddleware(BaseMiddleware):
    def __init__(self, settings: BotSettings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery):
            chat = getattr(event.message, "chat", None)
            if (
                self._settings.bot_private_only
                and chat is not None
                and chat.type != ChatType.PRIVATE
            ):
                with contextlib.suppress(Exception):
                    await event.answer()
                return None
        return await handler(event, data)


class _AccountLlmContextMiddleware(BaseMiddleware):
    """Этап 5 fix (LLM key routing gap, память project_openrouter_key_flow_2026_08_05) —
    зеркало `api.main.account_llm_context_middleware` для бота: без этого LLM-вызовы внутри
    обработки апдейта видели один ключ OpenRouter на весь процесс (`core.platform.config.
    runtime`), независимо от того, чей это апдейт. Любой активный аккаунт (owner ИЛИ member,
    `bot_app.access.resolve_account`, кэш 15 с) — Этап 5 обслуживает и self-serve друзей, не
    только владельца. Регистрируется ПОСЛЕ приват-режима (см. `run_bot`) — незачем резолвить
    аккаунт для апдейта, который всё равно отсекается группой/конфой.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        token = None
        if user is not None:
            from bot_app.access import resolve_account
            from core.config import set_current_account_id
            from core.platform.repo.settings import prime_runtime_openrouter_key_for_account

            account = await resolve_account(user_id=user.id)
            if account is not None:
                try:
                    await prime_runtime_openrouter_key_for_account(account.id)
                except Exception as exc:  # noqa: BLE001 — недоступный PG не должен ронять апдейт
                    logger.debug("account_llm_context: prime не удался: %s", exc)
                token = set_current_account_id(account.id)
                if isinstance(event, Message):
                    text = (event.text or event.caption or "").strip()
                    if text and event.chat is not None and event.chat.type == ChatType.PRIVATE:
                        try:
                            from core.platform.admin.service import record_inbound_user_telegram

                            await record_inbound_user_telegram(account.id, text)
                        except Exception as exc:  # noqa: BLE001 — лента поддержки не роняет апдейт
                            logger.debug("admin inbox: входящее не записалось: %s", exc)
        try:
            return await handler(event, data)
        finally:
            if token is not None:
                from core.config import reset_current_account_id

                reset_current_account_id(token)


async def run_bot() -> None:
    settings = get_bot_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    # A-10: бот зовёт домены напрямую (HR-пайплайн, калибровка) — порты должны быть связаны
    # даже если процесс поднят без API.
    wire_default_ports()

    bot = create_bot(settings)
    dp = Dispatcher()
    client = CopilotApiClient(settings)
    dp["api_client"] = client

    dp.update.outer_middleware(_LogUpdateMiddleware())
    # Приват-режим: при BOT_PRIVATE_ONLY=true игнорируем всё из групп/конф (отвечаем только в
    # личке). Гейт стоит до роутеров. Выключить — BOT_PRIVATE_ONLY=false в .env (рестарт).
    dp.message.outer_middleware(_PrivateOnlyMessageMiddleware(settings))
    dp.callback_query.outer_middleware(_PrivateOnlyCallbackMiddleware(settings))
    # Этап 5 fix: per-апдейт account-контекст для LLM key routing — после приват-режима
    # (незачем резолвить аккаунт для апдейта, который и так отсекается).
    dp.message.outer_middleware(_AccountLlmContextMiddleware())
    dp.callback_query.outer_middleware(_AccountLlmContextMiddleware())

    # Порядок важен: menu (hub-кнопки + pending-input flow) →
    # prep_scheduler (callback пуш-напоминания) / debrief (self-debrief callback'и) →
    # salary_calibration (always-on захват постов с вилками) → forwarded
    # (HR-пайплайн, включая self-debrief автодетект) → vacancy_actions → basic последним
    # (fallback). menu рано: /start и pending-input раньше HR-периметра.
    dp.include_router(menu.router)
    dp.include_router(prep_scheduler.router)
    dp.include_router(debrief.router)
    dp.include_router(salary_calibration.router)
    dp.include_router(forwarded.router)
    dp.include_router(vacancy_actions.router)
    dp.include_router(auto_apply.router)
    dp.include_router(basic.router)

    # Best-effort: при недоступном Telegram (нет сети/VPN, Errno 10060) не валим старт —
    # long-polling ниже сам ретраит getUpdates по NETWORK_BACKOFF и подключится, когда сеть вернётся.
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as exc:  # noqa: BLE001 — сетевой сбой не должен ронять бота на старте
        event(
            logger,
            "ЗАПУСК",
            "Telegram недоступен на старте (%s). Polling будет ретраить подключение",
            exc,
            level=logging.WARNING,
        )

    try:
        await bot.set_my_commands(BOT_COMMANDS)
    except Exception as exc:  # noqa: BLE001 — список команд не критичен для polling
        event(
            logger,
            "ЗАПУСК",
            "setMyCommands пропущен (%s)",
            exc,
            level=logging.WARNING,
        )

    # AUTH-1: кэш username бота в PG — фронт рисует deep-link t.me/<bot> на странице входа,
    # не дожидаясь первого live getMe из /api/telegram/status. Best-effort.
    try:
        me = await bot.get_me()
        if me.username:
            from core.domains.profile.telegram_link import set_bot_identity

            await set_bot_identity(me.username)
    except Exception as exc:  # noqa: BLE001 — сеть/PG не критичны для старта
        event(
            logger,
            "ЗАПУСК",
            "кэш username бота не обновлён (%s)",
            exc,
            level=logging.WARNING,
        )

    # Калибровка: восстановить зависшие батчи из Postgres (best-effort). Сбор вилок теперь
    # always-on — без ручного режима, активных сессий для догона очереди нет.
    salary_calib_orchestrator.attach(bot)
    try:
        await salary_calib_orchestrator.recover_on_startup()
    except Exception as exc:  # noqa: BLE001 — стартап не валим из-за недоступного PG
        event(
            logger,
            "ЗАПУСК",
            "калибровка: восстановление пропущено (%s)",
            exc,
            level=logging.WARNING,
        )

    loop_tasks: list[asyncio.Task] = []

    # Prep-напоминания за час до собеса (chat_id берётся из самих напоминаний в PG, не из конфига).
    loop_tasks.append(asyncio.create_task(prep_reminder_loop(bot), name="prep_reminder_loop"))

    # Кроны в общей очереди: tg_cleanup 4:30, interview_stages_sweep 9:00, tg_push on-demand.
    # Рассылки (дайджест/discovery/attention_reminders) product-но выключены.
    register_bot_schedules(bot)
    own_tasks_runtime = False
    if not get_runtime().running:
        # Режим `python -m bot_app` без API lifespan — поднимаем воркер сами.
        pool = None
        try:
            from core.platform.db.pool import get_pool

            pool = get_pool()
        except RuntimeError:
            try:
                from core.platform.db.pool import init_pool

                pool = await init_pool()
            except Exception as exc:  # noqa: BLE001
                event(
                    logger,
                    "БД",
                    "очередь задач без Postgres: %s",
                    exc,
                    level=logging.WARNING,
                )
                pool = None
        await start_background_runtime(pool)
        own_tasks_runtime = True

    # Этап 4 (план §6): резюме владельца в holder этого процесса — на VM бот и API живут в
    # разных контейнерах (deploy/compose.yaml, отдельный `bot`-сервис), поэтому holder,
    # залитый api.main lifespan, сюда не долетает; грузим тем же best-effort кодом. Идемпотентно
    # (повторный вызов из другого процесса просто перечитывает ту же строку), поэтому порядок
    # старта api/bot неважен.
    try:
        from core.domains.profile.structured_store import load_resume_into_runtime
        from core.platform.db.pool import get_pool
        from core.platform.repo.accounts import resolve_default_account_id

        await load_resume_into_runtime(account_id=await resolve_default_account_id(), db=get_pool())
    except Exception as exc:  # noqa: BLE001 — нет PG/аккаунта на старте не должно ронять бота
        event(logger, "БД", "резюме из БД не загружено: %s", exc, level=logging.WARNING)

    event(logger, "ЗАПУСК", "бот запущен, API %s", settings.backend_url)
    if settings.telegram_proxy:
        event(logger, "ЗАПУСК", "Telegram proxy: %s", settings.telegram_proxy.split("@")[-1])
    if settings.telegram_api_base:
        event(logger, "ЗАПУСК", "Telegram API base: %s", settings.telegram_api_base)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            backoff_config=NETWORK_BACKOFF,
            polling_timeout=30,
        )
    finally:
        if own_tasks_runtime:
            with contextlib.suppress(Exception):
                await stop_background_runtime()
        for task in loop_tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await client.aclose()
        await bot.session.close()
