"""Callback-действия карточки вакансии — Отклик/Пропустить с причиной/Вернуть.

Кнопки — `bot_app.services.vacancy_card`. Запись в домен — через `core.app.channels`:
тот же сценарий, что и веб (`skip_via` / `set_stage_via`), без дубля логики
в хендлере. Бот только отвечает в Telegram.
"""

from __future__ import annotations

import contextlib
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot_app.access import resolve_account
from bot_app.filters import IsAccount
from bot_app.services.vacancy_card import (
    SELF_REJECT_REASONS,
    build_skip_reason_keyboard,
    build_vacancy_actions_keyboard,
)
from bot_app.utils import esc
from core.app.channels import TELEGRAM, set_stage_via, skip_via, unskip_via
from core.domains.opportunities.jobs import Job, get_job
from core.kernel.errors import DomainError, StorageUnavailable

logger = logging.getLogger(__name__)
router = Router(name="vacancy_actions")


def _job_id(data: str, idx: int = 2) -> int | None:
    parts = data.split(":")
    if len(parts) <= idx or not parts[idx].isdigit():
        return None
    return int(parts[idx])


async def _resolve_account_id(query: CallbackQuery) -> int | None:
    """Аккаунт текущего события (Этап 5: любой активный, не только владелец)."""
    if query.from_user is None:
        return None
    account = await resolve_account(user_id=query.from_user.id)
    return account.id if account is not None else None


async def _append_status(query: CallbackQuery, job: Job, note: str, *, keyboard) -> None:
    """Дописать статус-строку под карточкой и обновить клавиатуру (без пересборки всей карточки).

    Текст — ``edit_text``; PNG — ``edit_caption`` (иначе suppress глотает сбой и
    клавиатура «Отклик/Пропустить» не сменяется).
    """
    from bot_app.tg_util import editable_message

    message = editable_message(query.message)
    if message is None:
        return
    with contextlib.suppress(Exception):
        if message.photo:
            base = esc(message.caption or "")
            caption = f"{base}\n\n{note}" if base else note
            await message.edit_caption(
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            await message.edit_text(
                f"{message.html_text}\n\n{note}",
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )


@router.callback_query(IsAccount(), F.data.startswith("vac:apply:"))
async def cb_vacancy_apply(query: CallbackQuery) -> None:
    job_id = _job_id(query.data or "")
    if job_id is None:
        await query.answer("Битый callback")
        return
    account_id = await _resolve_account_id(query)
    if account_id is None:
        await query.answer("Сначала получи токен — «Токен авторизации»", show_alert=True)
        return
    job = await get_job(job_id, account_id=account_id)
    if job is None or job.id is None:
        await query.answer("Вакансия не найдена", show_alert=True)
        return

    try:
        job = await set_stage_via(TELEGRAM, job.id, "Отклик", account_id=account_id)
    except StorageUnavailable:
        await query.answer("⚠️ Postgres недоступен, не записано", show_alert=True)
        return
    except DomainError as exc:
        await query.answer(exc.message or "не удалось", show_alert=True)
        return

    await query.answer("Отмечено: Отклик ✅")
    await _append_status(
        query,
        job,
        "✅ <b>Статус: Отклик</b>",
        keyboard=build_vacancy_actions_keyboard(job, applied=True),
    )


@router.callback_query(IsAccount(), F.data.startswith("vac:skip:"))
async def cb_vacancy_skip_menu(query: CallbackQuery) -> None:
    job_id = _job_id(query.data or "")
    if job_id is None:
        await query.answer("Битый callback")
        return
    from bot_app.tg_util import editable_message

    msg = editable_message(query.message)
    if msg is not None:
        with contextlib.suppress(Exception):
            await msg.edit_reply_markup(reply_markup=build_skip_reason_keyboard(job_id))
    await query.answer()


@router.callback_query(IsAccount(), F.data.startswith("vac:back:"))
async def cb_vacancy_skip_back(query: CallbackQuery) -> None:
    job_id = _job_id(query.data or "")
    if job_id is None:
        await query.answer("Битый callback")
        return
    account_id = await _resolve_account_id(query)
    job = await get_job(job_id, account_id=account_id) if account_id is not None else None
    from bot_app.tg_util import editable_message

    msg = editable_message(query.message)
    if job is not None and msg is not None:
        with contextlib.suppress(Exception):
            await msg.edit_reply_markup(reply_markup=build_vacancy_actions_keyboard(job))
    await query.answer()


@router.callback_query(IsAccount(), F.data.startswith("vac:skipr:"))
async def cb_vacancy_skip_reason(query: CallbackQuery) -> None:
    parts = (query.data or "").split(":")
    if len(parts) != 4 or not parts[2].isdigit() or not parts[3].isdigit():
        await query.answer("Битый callback")
        return
    job_id, ridx = int(parts[2]), int(parts[3])
    reason = (
        SELF_REJECT_REASONS[ridx] if 0 <= ridx < len(SELF_REJECT_REASONS) else "Избегать компанию"
    )
    account_id = await _resolve_account_id(query)
    if account_id is None:
        await query.answer("Сначала получи токен — «Токен авторизации»", show_alert=True)
        return

    try:
        job = await skip_via(TELEGRAM, job_id, reason, account_id=account_id)
    except StorageUnavailable:
        await query.answer("⚠️ Postgres недоступен, не записано", show_alert=True)
        return
    except DomainError as exc:
        await query.answer(exc.message or "не удалось", show_alert=True)
        return

    await query.answer(f"Пропущено: {reason}")
    await _append_status(
        query,
        job,
        f"⛔ <b>Пропущено:</b> {esc(reason)}",
        keyboard=build_vacancy_actions_keyboard(job, skipped=True),
    )


@router.callback_query(IsAccount(), F.data.startswith("vac:unskip:"))
async def cb_vacancy_unskip(query: CallbackQuery) -> None:
    job_id = _job_id(query.data or "")
    if job_id is None:
        await query.answer("Битый callback")
        return
    account_id = await _resolve_account_id(query)
    if account_id is None:
        await query.answer("Сначала получи токен — «Токен авторизации»", show_alert=True)
        return

    try:
        job = await unskip_via(TELEGRAM, job_id, account_id=account_id)
    except StorageUnavailable:
        await query.answer("⚠️ Postgres недоступен, не записано", show_alert=True)
        return
    except DomainError as exc:
        await query.answer(exc.message or "не удалось", show_alert=True)
        return

    await query.answer("Возвращено в воронку")
    await _append_status(
        query,
        job,
        "↩ <b>Возвращено в воронку</b>",
        keyboard=build_vacancy_actions_keyboard(job),
    )
