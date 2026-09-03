"""TG-клей prep-напоминаний: петля отправки + callback-кнопки.

Планирование — ``core.domains.preparation.prep_reminders``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot_app.filters import IsAdmin
from bot_app.tg_util import editable_message
from bot_app.utils import esc
from core.domains.preparation import prep as prep_repo
from core.domains.preparation.interview import (
    generate_prep_questions,
    load_record,
    match_company_profile,
)
from core.domains.preparation.models import CATEGORY_LABELS, STAGE_LABELS
from core.domains.preparation.prep import PrepReminder
from core.domains.preparation.prep_reminders import (
    schedule_prep_reminders_from_actions as _schedule_from_actions,
)
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)
router = Router(name="prep_scheduler")

_LOOP_INTERVAL_SEC = 60.0
_LLM_FAIL = (LlmError,)


async def schedule_prep_reminders_from_actions(
    analysis: object,
    actions: object,
    *,
    chat_id: int,
    account_id: int,
) -> None:
    """Обёртка канала: напоминание уходит В ЧАТ, где реально шёл разбор HR-переписки.

    Этап 5 fix (найдено при попытке открыть HR-пайплайн для self-serve друзей): раньше
    безусловно подставлялся chat_id ОПЕРАТОРА (`push_chat_id()`, DB-owner ∪ env, TB-1.5) —
    HR-форвард друга планировал бы напоминание, которое звонит владельцу, а не самому другу.
    Вызывающая сторона (`bot_app.handlers.forwarded`) уже знает свой chat_id.
    """
    await _schedule_from_actions(
        analysis,
        actions,
        chat_id=chat_id,
        account_id=account_id,
    )


def _build_reminder_text(reminder: PrepReminder) -> str:
    company = reminder.company or "?"
    position = reminder.position or ""
    when = reminder.interview_dt.strftime("%d.%m.%Y %H:%M") if reminder.interview_dt else "?"
    extra = f" — {esc(position)}" if position else ""
    return (
        f"⏰ <b>Через час: собес с {esc(company)}{extra}</b>\n"
        f"Когда: {esc(when)}\n\n"
        "Запустить тренировку?"
    )


def _build_reminder_keyboard(reminder: PrepReminder) -> InlineKeyboardMarkup:
    vacancy_id = reminder.vacancy_id
    stage = reminder.stage or "screening"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Запустить /prep",
                    callback_data=f"prep_remind:start:{vacancy_id}:{stage}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📋 Только список",
                    callback_data=f"prep_remind:list:{vacancy_id}:{stage}",
                ),
                InlineKeyboardButton(
                    text="❌ Не сейчас",
                    callback_data="prep_remind:dismiss",
                ),
            ],
        ]
    )


async def _fire_one(bot: Bot, reminder: PrepReminder) -> None:
    if reminder.id is None:
        logger.warning("Prep reminder без id, пропуск")
        return
    reminder_id = reminder.id
    try:
        await bot.send_message(
            chat_id=reminder.chat_id,
            text=_build_reminder_text(reminder),
            parse_mode="HTML",
            reply_markup=_build_reminder_keyboard(reminder),
        )
        await prep_repo.mark_reminder_fired(reminder_id)
    except TelegramAPIError as exc:
        logger.warning("Prep reminder #%s send failed: %s", reminder_id, exc)
        await prep_repo.mark_reminder_fired(reminder_id)
    except Exception as exc:  # noqa: BLE001 — не валим петлю на одном напоминании
        logger.error("Prep reminder #%s unexpected: %s", reminder.id, exc)


async def prep_reminder_loop(bot: Bot) -> None:
    """Фоновая таска: раз в минуту разбираем due-очередь."""
    event(logger, "ЗАПУСК", "prep-reminder петля стартует, интервал %.0fс", _LOOP_INTERVAL_SEC)
    while True:
        await asyncio.sleep(_LOOP_INTERVAL_SEC)
        try:
            due = await prep_repo.load_due_reminders()
            for reminder in due:
                await _fire_one(bot, reminder)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — БД могла отвалиться, повторим на след. тике
            logger.warning("Prep reminder loop tick: %s", exc)


async def _generate_and_save(vacancy_id: str, stage: str, *, account_id: int) -> list[dict] | None:
    record = await load_record(vacancy_id, account_id=account_id)
    if record is None:
        return None

    profile = await match_company_profile(
        record.company, record.vacancy_text or "", account_id=account_id
    )
    try:
        questions = await generate_prep_questions(record, stage, profile, account_id=account_id)
    except _LLM_FAIL as exc:
        logger.warning("prep reminder: генерация вопросов упала: %s", exc)
        return []

    q_dicts = [q.model_dump() for q in questions]
    try:
        await prep_repo.save_prep_session(
            prep_repo.PrepSession(
                vacancy_id=vacancy_id,
                stage=stage,
                questions=q_dicts,
                responses=[],
                status="generated",
            ),
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001 — персист best-effort
        logger.warning("prep reminder: сохранение сессии не удалось: %s", exc)
    return q_dicts


def _format_questions(stage: str, questions: list[dict]) -> str:
    stage_label = STAGE_LABELS.get(stage, stage)
    lines = [f"📋 <b>Вопросы под этап: {esc(stage_label)}</b>", ""]
    by_cat: dict[str, list[dict]] = {}
    for q in questions:
        by_cat.setdefault(q["category"], []).append(q)
    for cat, items in by_cat.items():
        lines.append(f"<b>{esc(CATEGORY_LABELS.get(cat, cat))}</b>")
        for q in items:
            lines.append(f"• {esc(q['text'])}")
            if q.get("hint"):
                lines.append(f"  <i>↳ {esc(q['hint'])}</i>")
        lines.append("")
    return "\n".join(lines).strip()


@router.callback_query(IsAdmin(), F.data.startswith("prep_remind:"))
async def cb_prep_reminder(query: CallbackQuery) -> None:
    if not query.data or not query.message:
        await query.answer()
        return
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "dismiss":
        await query.answer("Окей, без подготовки")
        msg = editable_message(query.message)
        if msg is not None:
            with contextlib.suppress(Exception):
                await msg.edit_reply_markup(reply_markup=None)
        return

    if action not in ("start", "list") or len(parts) < 4:
        await query.answer("Битый callback")
        return

    vacancy_id, stage = parts[2], parts[3]

    await query.answer("Генерирую вопросы…")
    msg = editable_message(query.message)
    if msg is not None:
        with contextlib.suppress(Exception):
            await msg.edit_reply_markup(reply_markup=None)

    from bot_app.access import resolve_owner_account_id

    account_id = await resolve_owner_account_id()
    if account_id is None:
        await query.message.answer("⚠ Аккаунт владельца не найден.")
        return

    questions = await _generate_and_save(vacancy_id, stage, account_id=account_id)
    if questions is None:
        await query.message.answer(
            "⚠ Вакансия не найдена в БД — сначала оцени её через расширение."
        )
        return
    if not questions:
        await query.message.answer(
            "⚠ Модель не вернула вопросы. Открой вкладку «Технички» на дэшборде и попробуй там."
        )
        return

    body = _format_questions(stage, questions)
    for start in range(0, len(body), 3800):
        await query.message.answer(body[start : start + 3800], parse_mode="HTML")
