"""Доставка «отправить себе в Telegram» из веба.

Очередь: API (`POST /api/telegram/push`) → `platform.tasks` kind=`tg_push`.
Этот модуль регистрирует handler в процессе бота и шлёт владельцу компактное сообщение.

Ограничение: пуш доставляется только пока крутится процесс бота. В режиме одного процесса
(бот в том же контейнере) — ок. В API-only (`uvicorn api.main:app`) задача лежит в очереди до
`python -m bot_app`. Handler не зовётся из lifespan API.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_app.config import get_bot_settings, push_chat_id
from bot_app.services.card_replace import send_or_replace_score_card
from bot_app.services.menu_manager import after_score, idle, show_menu
from bot_app.telegram_send import safe_send
from bot_app.utils import esc
from core.domains.offers.store import Offer, load_offer
from core.domains.opportunities.jobs import Job, get_job_by_vacancy_id
from core.domains.opportunities.models import ScoreResult
from core.domains.preparation.models import STAGE_LABELS
from core.domains.preparation.prep import load_prep_history
from core.domains.preparation.screening_questions import (
    SavedScreeningQuestions,
    get_screening_questions,
)
from core.domains.profile.telegram_push import (
    ADMIN_MESSAGE_KIND,
    KEY_REQUEST_KIND,
    PUSH_KINDS,
    TG_PUSH_KIND,
)
from core.platform.observability import event

logger = logging.getLogger(__name__)

# Telegram hard limit 4096; оставляем запас под HTML-разметку.
_MAX_TEXT = 3500
_MAX_PITCH = 900
_MAX_PREP_QUESTIONS = 12
_MAX_HR_QUESTIONS = 3

_OFFER_STATUS_RU = {
    "thinking": "думаю",
    "accepted": "принял",
    "declined": "отклонил",
}
_WORK_FORMAT_RU = {
    "remote": "удалёнка",
    "hybrid": "гибрид",
    "office": "офис",
}


@dataclass(frozen=True)
class PushText:
    """Готовый текст + опциональная https-кнопка на веб-раздел."""

    text: str
    reply_markup: InlineKeyboardMarkup | None = None


_BOT: Bot | None = None


def _https_button(text: str, url: str) -> InlineKeyboardButton | None:
    url = (url or "").strip()
    if url.startswith("https://"):
        return InlineKeyboardButton(text=text, url=url)
    return None


def _web_path_keyboard(label: str, path: str) -> InlineKeyboardMarkup | None:
    web = get_bot_settings().web_url.rstrip("/")
    btn = _https_button(label, f"{web}{path}")
    if btn is None:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


def _job_heading(job: Job | None, vacancy_id: str) -> str:
    if job is None:
        return esc(vacancy_id)
    company = (job.company or "").strip() or "?"
    title = (job.title or "").strip() or "вакансия"
    return f"{esc(company)} — {esc(title)}"


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _clip_message(text: str) -> str:
    return _truncate(text, _MAX_TEXT)


def format_screening_push(
    pack: SavedScreeningQuestions | None,
    *,
    vacancy_id: str,
    job: Job | None = None,
    web_url: str = "",
) -> PushText:
    """Компактный питч + до 3 HR-вопросов из сохранённого пака (без LLM)."""
    heading = _job_heading(job, vacancy_id)
    kb = None
    if web_url:
        btn = _https_button(
            "Открыть скрининг",
            f"{web_url.rstrip('/')}/screening?vacancy={vacancy_id}",
        )
        if btn is not None:
            kb = InlineKeyboardMarkup(inline_keyboard=[[btn]])

    if pack is None or not (
        (pack.oral_pitch or "").strip() or pack.hr_questions or (pack.why_company or "").strip()
    ):
        return PushText(
            text=_clip_message(
                f"<b>Скрининг</b> · {heading}\n\nПакет ещё не собран — открой раздел в вебе."
            ),
            reply_markup=kb,
        )

    lines = [f"<b>Скрининг</b> · {heading}", ""]
    pitch = _truncate(pack.oral_pitch or "", _MAX_PITCH)
    if pitch:
        lines.append("<b>Устный рассказ</b>")
        lines.append(esc(pitch))
        lines.append("")
    why = _truncate((pack.why_company or "").strip(), 400)
    if why:
        lines.append("<b>Почему компания</b>")
        lines.append(esc(why))
        lines.append("")

    hr_lines: list[str] = []
    for item in (pack.hr_questions or [])[:_MAX_HR_QUESTIONS]:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question") or "").strip()
        if not q:
            continue
        hr_lines.append(f"• {esc(_truncate(q, 280))}")
    if hr_lines:
        lines.append("<b>Вопросы HR</b>")
        lines.extend(hr_lines)

    return PushText(text=_clip_message("\n".join(lines).strip()), reply_markup=kb)


def format_prep_push(
    questions: list[dict[str, Any]],
    *,
    vacancy_id: str,
    stage: str,
    job: Job | None = None,
    web_url: str = "",
) -> PushText:
    """Список сохранённых вопросов по этапу (без LLM / без emoji-категорий)."""
    heading = _job_heading(job, vacancy_id)
    stage_label = STAGE_LABELS.get(stage, stage or "этап")
    kb = None
    if web_url:
        btn = _https_button(
            "Открыть техничку",
            f"{web_url.rstrip('/')}/tech?vacancy={vacancy_id}",
        )
        if btn is not None:
            kb = InlineKeyboardMarkup(inline_keyboard=[[btn]])

    lines = [f"<b>Техничка</b> · {heading}", f"Этап: {esc(stage_label)}", ""]
    items = [q for q in questions if isinstance(q, dict) and str(q.get("text") or "").strip()]
    if not items:
        lines.append("Сохранённых вопросов нет — открой раздел в вебе.")
        return PushText(text=_clip_message("\n".join(lines)), reply_markup=kb)

    for q in items[:_MAX_PREP_QUESTIONS]:
        lines.append(f"• {esc(_truncate(str(q['text']).strip(), 320))}")
    if len(items) > _MAX_PREP_QUESTIONS:
        lines.append(f"…ещё {len(items) - _MAX_PREP_QUESTIONS} в вебе")
    return PushText(text=_clip_message("\n".join(lines)), reply_markup=kb)


def format_offer_push(
    offer: Offer | None,
    *,
    vacancy_id: str,
    job: Job | None = None,
    web_url: str = "",
) -> PushText:
    """Компактная карточка оффера (без LLM-сравнения — сравнение в вебе)."""
    heading = _job_heading(job, vacancy_id)
    if offer is not None:
        company = (offer.company or "").strip()
        position = (offer.position or "").strip()
        if company or position:
            heading = f"{esc(company or '?')} — {esc(position or 'оффер')}"

    kb = None
    if web_url:
        btn = _https_button("Открыть офферы", f"{web_url.rstrip('/')}/offers")
        if btn is not None:
            kb = InlineKeyboardMarkup(inline_keyboard=[[btn]])

    if offer is None:
        return PushText(
            text=_clip_message(
                f"<b>Оффер</b> · {heading}\n\nОффер ещё не сохранён — открой раздел в вебе."
            ),
            reply_markup=kb,
        )

    lines = [f"<b>Оффер</b> · {heading}", ""]
    status = _OFFER_STATUS_RU.get(offer.status, offer.status)
    lines.append(f"Статус: {esc(status)}")

    if offer.base_salary is not None:
        period = "/мес" if offer.base_salary_period == "month" else "/год"
        tax = "на руки" if offer.base_salary_tax_basis == "net" else "гросс"
        money = f"{offer.base_salary:,}".replace(",", " ")
        lines.append(f"База: {esc(money)} {esc(offer.base_salary_currency)}{period} ({tax})")
    if offer.bonus_monthly_equiv:
        bonus = f"{offer.bonus_monthly_equiv:,}".replace(",", " ")
        lines.append(f"Премия ≈ {esc(bonus)}/мес")
    elif (offer.bonus or "").strip():
        lines.append(f"Бонус: {esc(_truncate(offer.bonus, 200))}")
    if offer.signon:
        signon = f"{offer.signon:,}".replace(",", " ")
        lines.append(f"Sign-on: {esc(signon)}")
    fmt = _WORK_FORMAT_RU.get(offer.work_format, "")
    if fmt:
        lines.append(f"Формат: {esc(fmt)}")
    if (offer.location or "").strip():
        lines.append(f"Локация: {esc(offer.location.strip())}")
    if offer.vacation_days:
        lines.append(f"Отпуск: {offer.vacation_days} дн.")
    if (offer.notes or "").strip():
        lines.append("")
        lines.append(esc(_truncate(offer.notes, 400)))
    lines.append("")
    lines.append("Сравнение с другими — в вебе.")
    return PushText(text=_clip_message("\n".join(lines)), reply_markup=kb)


async def _load_job(vacancy_id: str, *, account_id: int | None) -> Job | None:
    try:
        if account_id is None:
            return None
        return await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — PG down не валит воркер
        logger.warning("tg_push: job load failed vid=%s: %s", vacancy_id, exc)
        return None


async def _load_offer(vacancy_id: str, *, account_id: int | None) -> Offer | None:
    try:
        if account_id is None:
            return None
        return await load_offer(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — PG down не валит воркер
        logger.warning("tg_push: offer load failed vid=%s: %s", vacancy_id, exc)
        return None


async def _send_vacancy_card(
    bot: Bot, chat_id: int, vacancy_id: str, *, account_id: int | None
) -> None:
    job = await _load_job(vacancy_id, account_id=account_id)
    if job is None:
        kb = _web_path_keyboard("Открыть вакансию", f"/jobs/{vacancy_id}")
        await safe_send(
            bot,
            chat_id,
            f"Вакансия <code>{esc(vacancy_id)}</code> не найдена.",
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True,
        )
        await show_menu(bot, chat_id, idle())
        return

    score: ScoreResult | None = None
    if job.score:
        try:
            score = ScoreResult.model_validate(job.score)
        except Exception as exc:  # noqa: BLE001 — битый jsonb
            logger.warning("tg_push: score invalid vid=%s: %s", vacancy_id, exc)

    if score is None:
        kb = _web_path_keyboard("Открыть вакансию", f"/jobs/{vacancy_id}")
        await safe_send(
            bot,
            chat_id,
            f"<b>{_job_heading(job, vacancy_id)}</b>\n\nСкора нет — открой карточку в вебе.",
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True,
        )
        await show_menu(bot, chat_id, after_score(vacancy_id))
        return

    await send_or_replace_score_card(
        bot,
        chat_id,
        job=job,
        score=score,
        header="Из веба",
    )
    await show_menu(bot, chat_id, after_score(vacancy_id))


async def _send_text_push(bot: Bot, chat_id: int, msg: PushText) -> None:
    await safe_send(
        bot,
        chat_id,
        msg.text,
        parse_mode="HTML",
        reply_markup=msg.reply_markup,
        disable_web_page_preview=True,
    )
    await show_menu(bot, chat_id, idle())


def format_chat_summary_push(
    text: str, *, vacancy_id: str, job: Job | None, web_url: str
) -> PushText:
    """Готовый LLM-текст (собран один раз на клике в API, см. `enqueue_tg_push(text=...)`) —
    здесь только заголовок + https-кнопка, без пересборки содержимого."""
    heading = _job_heading(job, vacancy_id)
    kb = None
    if web_url:
        btn = _https_button(
            "Открыть скрининг",
            f"{web_url.rstrip('/')}/screening?vacancy={vacancy_id}",
        )
        if btn is not None:
            kb = InlineKeyboardMarkup(inline_keyboard=[[btn]])
    body = esc(text.strip()) if text.strip() else "Саммари пустое."
    return PushText(
        text=_clip_message(f"<b>О чём говорили</b> · {heading}\n\n{body}"),
        reply_markup=kb,
    )


async def _dispatch(
    bot: Bot,
    chat_id: int,
    kind: str,
    vacancy_id: str,
    *,
    account_id: int | None,
    text: str | None = None,
) -> None:
    web = get_bot_settings().web_url
    job = await _load_job(vacancy_id, account_id=account_id)

    if kind == "screening_chat_summary":
        msg = format_chat_summary_push(text or "", vacancy_id=vacancy_id, job=job, web_url=web)
        await _send_text_push(bot, chat_id, msg)
        return

    if kind == "vacancy_card":
        await _send_vacancy_card(bot, chat_id, vacancy_id, account_id=account_id)
        return

    if kind == "screening_pack":
        pack = (
            await get_screening_questions(vacancy_id, account_id=account_id) if account_id else None
        )
        msg = format_screening_push(pack, vacancy_id=vacancy_id, job=job, web_url=web)
        await _send_text_push(bot, chat_id, msg)
        return

    if kind == "prep_questions":
        history = (
            await load_prep_history(vacancy_id, limit=1, account_id=account_id)
            if account_id
            else []
        )
        stage = history[0].stage if history else "tech"
        questions = list(history[0].questions) if history else []
        msg = format_prep_push(
            questions,
            vacancy_id=vacancy_id,
            stage=stage,
            job=job,
            web_url=web,
        )
        await _send_text_push(bot, chat_id, msg)
        return

    if kind == "offer_summary":
        offer = await _load_offer(vacancy_id, account_id=account_id)
        msg = format_offer_push(offer, vacancy_id=vacancy_id, job=job, web_url=web)
        await _send_text_push(bot, chat_id, msg)
        return

    logger.warning("tg_push: неизвестный kind=%s", kind)


async def _resolve_recipient(payload: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """(account_id, chat_id) получателя.

    M7 (plans/multitenancy_gaps_2026_08_06.md §3.11): `payload["account_id"]` — СВОЙ аккаунт
    вызывающего, который положил туда `core.domains.profile.telegram_push.enqueue_tg_push`
    (после фикса роутера `/api/telegram/push`) — доставка идёт в ЕГО чат, не владельца.
    Легаси-задачи без этого поля (в очереди на момент деплоя фикса) резолвятся по-старому —
    `push_chat_id()` (DB-owner ∪ env).
    """
    raw_account_id = payload.get("account_id")
    if isinstance(raw_account_id, int):
        from core.platform.repo.accounts import get_account_by_id

        account = await get_account_by_id(raw_account_id)
        if account is None or account.status != "active" or account.telegram_chat_id is None:
            return raw_account_id, None
        return raw_account_id, int(account.telegram_chat_id)

    from bot_app.access import resolve_owner_account_id

    account_id = await resolve_owner_account_id()
    chat_id = await push_chat_id()
    return account_id, chat_id


async def handle_tg_push(payload: Mapping[str, Any]) -> None:
    """Обработчик очереди `tg_push` (payload: kind + vacancy_id [+ account_id, M7])."""
    bot = _BOT
    if bot is None:
        logger.warning("tg_push: бот не привязан — задача пропущена")
        return

    kind = str(payload.get("kind") or "").strip()
    vacancy_id = str(payload.get("vacancy_id") or "").strip()
    if kind == KEY_REQUEST_KIND:
        # Заявка на ключ: получатель — оператор установки, не автор заявки.
        _, chat_id = await _resolve_recipient(payload)
        raw_text = payload.get("text")
        body = raw_text.strip() if isinstance(raw_text, str) else ""
        if chat_id is None or not body:
            logger.warning("tg_push: заявку на ключ доставить некому (chat_id=%s)", chat_id)
            return
        await safe_send(
            bot,
            chat_id,
            _clip_message(f"<b>Заявка на ключ OpenRouter</b>\n\n{esc(body)}"),
            parse_mode="HTML",
        )
        event(logger, "ЗАДАЧА", "tg_push доставлен kind=%s", KEY_REQUEST_KIND)
        return
    if kind == ADMIN_MESSAGE_KIND:
        account_id, chat_id = await _resolve_recipient(payload)
        if chat_id is None:
            logger.warning(
                "tg_push: нет chat_id получателя kind=admin_message account_id=%s",
                account_id,
            )
            return
        raw_text = payload.get("text")
        body = raw_text.strip() if isinstance(raw_text, str) else ""
        if not body:
            logger.warning("tg_push: пустой admin_message account_id=%s", account_id)
            return
        text = f"<b>Администратор</b>\n\n{esc(body)}"
        await safe_send(bot, chat_id, _clip_message(text), parse_mode="HTML")
        event(logger, "ЗАДАЧА", "tg_push доставлен kind=admin_message account_id=%s", account_id)
        return
    if kind not in PUSH_KINDS or not vacancy_id:
        logger.warning("tg_push: битый payload=%s", dict(payload))
        return

    account_id, chat_id = await _resolve_recipient(payload)
    if chat_id is None:
        logger.warning(
            "tg_push: нет chat_id получателя kind=%s vid=%s account_id=%s",
            kind,
            vacancy_id,
            account_id,
        )
        return

    raw_text = payload.get("text")
    text = raw_text if isinstance(raw_text, str) else None

    try:
        await _dispatch(bot, chat_id, kind, vacancy_id, account_id=account_id, text=text)
    except Exception:
        logger.exception("tg_push failed kind=%s vid=%s", kind, vacancy_id)
        raise

    event(logger, "ЗАДАЧА", "tg_push доставлен kind=%s vid=%s", kind, vacancy_id)


def register_tg_push(bot: Bot) -> None:
    """Привязать Bot и зарегистрировать handler `tg_push` в общей очереди."""
    global _BOT
    from core.platform.tasks import register_handler

    _BOT = bot
    register_handler(TG_PUSH_KIND, handle_tg_push)
    event(logger, "ЗАПУСК", "handler tg_push зарегистрирован")


__all__ = [
    "PushText",
    "format_chat_summary_push",
    "format_offer_push",
    "format_prep_push",
    "format_screening_push",
    "handle_tg_push",
    "register_tg_push",
]
