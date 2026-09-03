"""Текстовая карточка HR-разбора для Telegram.

Сверху — компактный блок «Контакт» (@ / ссылка / имя + привязка к вакансии),
затем intent и краткая суть, дальше детали с текстовыми подписями без эмодзи-забора.
Клавиатура: deeplink на тред/черновик, hrres-подтверждение, «Указать @HR».
Рендер клавиатуры — чистый (токены передаёт вызывающий); persist контакта — async.
"""

from __future__ import annotations

import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_app.utils import esc
from core.domains.pipeline.hr_identity import hr_link_display, normalize_hr_link
from core.domains.pipeline.hr_orchestrator import HrBatchResult
from core.domains.pipeline.models import INTENT_LABELS, HrMessageAnalysis
from core.domains.preparation.models import STAGE_TYPE_LABELS

logger = logging.getLogger(__name__)

FORMAT_LABELS = {"online": "онлайн", "offline": "офлайн", "unknown": "не указан"}
SALARY_MATCH_LABELS = {"yes": "да", "no": "нет", "unclear": "неясно"}
SOURCE_LABELS = {"telegram": "Telegram", "email": "Email", "other": "Inbound", "hh": "hh"}

_UNKNOWN_COMPANY = "Неизвестная компания"
_UNKNOWN_POSITION = "Неизвестная позиция"

# Callback: Указать @HR → pending-input (токен = hr_pending).
CB_SET_CONTACT_PREFIX = "hrcard:contact:"


def _format_dt(dt) -> str:
    if dt:
        return dt.strftime("%d.%m.%Y %H:%M (МСК)")
    return "не указано"


def _contact_bits(analysis: HrMessageAnalysis) -> list[str]:
    """HTML-фрагменты контакта: @username / ссылка / имя — без дублей."""
    bits: list[str] = []
    seen: set[str] = set()

    def add_html(fragment: str, *keys: str) -> None:
        for key in keys:
            k = key.strip().lower()
            if k:
                if k in seen:
                    return
                seen.add(k)
        if fragment:
            bits.append(fragment)

    hr = (analysis.hr_link or "").strip()
    if hr.startswith("tg:@") and not hr.startswith("tg:@http"):
        user = hr[4:]
        add_html(
            f'<a href="https://t.me/{esc(user)}">@{esc(user)}</a>',
            f"@{user}",
            f"tg:@{user}",
            f"https://t.me/{user}",
        )
    elif hr.startswith("mail:"):
        email = hr[5:]
        add_html(f'<a href="mailto:{esc(email)}">{esc(email)}</a>', email, f"mail:{email}")
    elif hr.startswith("tel:"):
        phone = hr[4:]
        add_html(esc(phone), phone, f"tel:{phone}")
    elif hr.startswith("name:"):
        name = hr[5:].strip()
        add_html(esc(name), name, f"name:{name}")
    elif hr:
        disp = hr_link_display(hr)
        if disp.startswith("http"):
            add_html(f'<a href="{esc(disp)}">{esc(disp)}</a>', disp, hr)
        else:
            add_html(esc(disp or hr), disp or hr, hr)

    name = (analysis.interviewer_name or "").strip()
    if name:
        add_html(esc(name), name)

    contact = (analysis.contact or "").strip()
    if contact:
        # Сырой contact — только если даёт новое (не уже покрытый hr_link/имя).
        canon = normalize_hr_link(contact)
        keys = [contact]
        if canon:
            keys.append(canon)
            if canon.startswith(("tg:@", "mail:", "tel:", "name:")):
                keys.append(canon.split(":", 1)[1])
                if canon.startswith("tg:@"):
                    keys.append(f"@{canon[4:]}")
                    keys.append(f"https://t.me/{canon[4:]}")
        add_html(esc(contact), *keys)

    return bits


def _binding_html(analysis: HrMessageAnalysis, *, pending_vacancy_id: str = "") -> str:
    """Куда привязан разбор: ссылка на вакансию / компания — роль / не привязано."""
    company = (analysis.company or "").strip()
    position = (analysis.position or "").strip()
    title_parts: list[str] = []
    if company and company != _UNKNOWN_COMPANY:
        title_parts.append(company)
    if position and position != _UNKNOWN_POSITION:
        title_parts.append(position)
    title = " — ".join(title_parts)

    if analysis.vacancy_url:
        label = title or ("Вакансия на hh.ru" if analysis.vacancy_id else "Ссылка на вакансию")
        return f'<a href="{esc(analysis.vacancy_url)}">{esc(label)}</a>'
    if analysis.vacancy_id:
        url = f"https://hh.ru/vacancy/{analysis.vacancy_id}"
        label = title or f"Вакансия {analysis.vacancy_id}"
        return f'<a href="{esc(url)}">{esc(label)}</a>'
    if pending_vacancy_id:
        url = f"https://hh.ru/vacancy/{pending_vacancy_id}"
        hint = title or f"Вакансия {pending_vacancy_id}"
        return f'предположительно <a href="{esc(url)}">{esc(hint)}</a>'
    if title:
        return esc(title)
    return "не привязано"


def _contact_block(analysis: HrMessageAnalysis, *, pending_vacancy_id: str = "") -> list[str]:
    bits = _contact_bits(analysis)
    contact_line = " · ".join(bits) if bits else "не указан"
    return [
        "<b>Контакт</b>",
        contact_line,
        f"Привязка: {_binding_html(analysis, pending_vacancy_id=pending_vacancy_id)}",
    ]


def format_hr_card(batch: HrBatchResult) -> str:
    """Полный HTML-текст HR-карточки для Telegram (parse_mode=HTML)."""
    analysis = batch.primary
    actions = batch.actions
    intent_label = INTENT_LABELS.get(analysis.intent, analysis.intent)
    fmt = FORMAT_LABELS.get(analysis.format, analysis.format)
    pending = actions.pending_resolve_vacancy_id or ""

    lines = _contact_block(analysis, pending_vacancy_id=pending)
    lines.append("")
    lines.append(f"<b>{esc(intent_label)}</b>")
    if analysis.summary:
        lines.append(esc(analysis.summary))

    detail: list[str] = []
    if analysis.company and analysis.company != _UNKNOWN_COMPANY:
        # В привязке уже может быть — оставляем для сканирования без клика по ссылке.
        detail.append(f"Компания: {esc(analysis.company)}")
    if analysis.position and analysis.position != _UNKNOWN_POSITION:
        detail.append(f"Позиция: {esc(analysis.position)}")
    if analysis.salary_text:
        detail.append(f"Зарплата: {esc(analysis.salary_text)}")
    if analysis.salary_hr_range and analysis.salary_hr_range != analysis.salary_text:
        detail.append(f"ЗП от HR: {esc(analysis.salary_hr_range)}")
    if analysis.salary_match:
        match_label = SALARY_MATCH_LABELS.get(analysis.salary_match, analysis.salary_match)
        detail.append(f"Match зарплаты: {esc(match_label)}")
    if analysis.format_clarified:
        detail.append(f"Формат (HR): {esc(analysis.format_clarified)}")
    if analysis.team_size:
        detail.append(f"Команда: {esc(analysis.team_size)}")
    if analysis.stage_type:
        stage_label = STAGE_TYPE_LABELS.get(analysis.stage_type, analysis.stage_type)
        detail.append(f"Этап: {esc(stage_label)}")

    if detail:
        lines.append("")
        lines.extend(detail)

    if analysis.interview_stages:
        lines.append("")
        lines.append("<b>Этапы</b>")
        for stage in analysis.interview_stages:
            label = STAGE_TYPE_LABELS.get(stage.stage_type, stage.stage_type)
            when = (
                stage.scheduled_at.strftime("%d.%m.%Y %H:%M") if stage.scheduled_at else "дата TBD"
            )
            lines.append(f"• {esc(label)} — {esc(when)} ({esc(stage.format)})")

    if analysis.is_inbound:
        src = SOURCE_LABELS.get(analysis.source, analysis.source)
        lines.append(f"Источник: {esc(src)} (без hh в сообщении)")
    elif analysis.is_cold_hh_outreach:
        lines.append("Cold outreach: вакансия с hh.ru (не было в «Просмотрах»)")

    # Ссылку на вакансию уже показали в «Привязка» — не дублируем.

    if analysis.is_interview_event or analysis.interview_dt:
        lines.append(f"Когда: {_format_dt(analysis.interview_dt)}")
        if analysis.is_past_interview:
            lines.append("✓ Этап в прошлом → статус «done»")
        lines.append(f"Формат: {esc(fmt)}")
        # Имя интервьюера уже в блоке «Контакт» — здесь не дублируем.

    if analysis.debrief_summary:
        preview = analysis.debrief_summary[:400]
        if len(analysis.debrief_summary) > 400:
            preview += "…"
        lines.append("")
        lines.append(f"<b>Дебриф</b>: {esc(preview)}")

    if actions.notes:
        lines.append("")
        lines.append("<b>Действия</b>")
        for note in actions.notes:
            lines.append(f"• {esc(note)}")

    return "\n".join(lines)


def has_actionable_hr_contact(analysis: HrMessageAnalysis) -> bool:
    """Есть ли @username / email / телефон (не только имя из privacy-скрытого форварда)."""
    for raw in (analysis.hr_link, analysis.contact):
        key = normalize_hr_link(raw or "")
        if key.startswith(("tg:@", "mail:", "tel:")):
            return True
    return False


def needs_manual_hr_contact(analysis: HrMessageAnalysis) -> bool:
    """Показать «Указать @HR»: privacy спрятал отправителя / в тексте нет контакта."""
    return not has_actionable_hr_contact(analysis)


def _https_button(text: str, url: str) -> InlineKeyboardButton | None:
    url = (url or "").strip()
    if url.startswith("https://"):
        return InlineKeyboardButton(text=text, url=url)
    return None


def _chat_url(web_url: str, vacancy_id: str) -> str:
    return f"{(web_url or '').rstrip('/')}/chat?vacancy={vacancy_id}"


def vacancy_id_for_card(batch: HrBatchResult) -> str:
    """Id для deeplink: подтверждённый или pending-resolve."""
    return (batch.primary.vacancy_id or batch.actions.pending_resolve_vacancy_id or "").strip()


def build_hr_card_keyboard(
    batch: HrBatchResult,
    *,
    web_url: str = "",
    resolve_token: str = "",
    contact_token: str = "",
) -> InlineKeyboardMarkup | None:
    """Кнопки под HR-карточкой.

    - [Открыть тред] [Черновик ответа] — https deeplink на /chat?vacancy= (если есть id);
    - при pending_resolve + resolve_token: [Это вакансия …] [Не та вакансия] (hrres);
    - при отсутствии контакта + contact_token: [Указать @HR].
    """
    rows: list[list[InlineKeyboardButton]] = []
    vid = vacancy_id_for_card(batch)
    pending = (batch.actions.pending_resolve_vacancy_id or "").strip()

    if vid:
        chat = _chat_url(web_url, vid)
        url_row: list[InlineKeyboardButton] = []
        for label in ("Открыть тред", "Черновик ответа"):
            btn = _https_button(label, chat)
            if btn:
                url_row.append(btn)
        if url_row:
            rows.append(url_row)

    if pending and resolve_token:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Это вакансия {pending}",
                    callback_data=f"hrres:ok:{resolve_token}",
                ),
                InlineKeyboardButton(
                    text="Не та вакансия",
                    callback_data=f"hrres:no:{resolve_token}",
                ),
            ]
        )

    if needs_manual_hr_contact(batch.primary) and contact_token:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Указать @HR",
                    callback_data=f"{CB_SET_CONTACT_PREFIX}{contact_token}",
                )
            ]
        )

    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def hr_contact_display(hr_key: str) -> str:
    """Короткая подпись сохранённого контакта для ответа бота."""
    if hr_key.startswith("tg:@"):
        return f"@{hr_key[4:]}"
    if hr_key.startswith("mail:"):
        return hr_key[5:]
    if hr_key.startswith("tel:"):
        return hr_key[4:]
    if hr_key.startswith("name:"):
        return hr_key[5:]
    return hr_key


async def save_manual_hr_contact(
    raw: str,
    *,
    vacancy_id: str = "",
    company: str = "",
    position: str = "",
    account_id: int,
) -> tuple[str | None, str]:
    """Нормализовать ввод аккаунта и сохранить в registry/enrichment/тред.

    Returns:
        (hr_key, "") при успехе; (None, сообщение_ошибки) при мусоре на входе.
    """
    key = normalize_hr_link(raw)
    if not key or not key.startswith(("tg:@", "mail:", "tel:")):
        return None, "Не похоже на контакт. Пришли @username, t.me/…, email или телефон."

    vid = (vacancy_id or "").strip()
    if not vid:
        # Без вакансии только подтверждаем разбор — реестр требует vacancy_id.
        return key, ""

    try:
        from core.domains.opportunities.enrichment import merge_enrichment
        from core.domains.pipeline.hr_registry import register_hr_vacancy_link
        from core.domains.pipeline.hr_threads import get_or_create_thread, update_thread

        await register_hr_vacancy_link(
            hr_key=key,
            vacancy_id=vid,
            company=company,
            position=position,
            hr_link=key,
            account_id=account_id,
        )
        await merge_enrichment(vid, hr_link=key, account_id=account_id)

        display = hr_contact_display(key)
        thread = await get_or_create_thread(
            vid, company=company, contact_name=display, account_id=account_id
        )
        if thread.id is not None:
            await update_thread(thread.id, contact_name=display, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — ответ владельцу, не роняем хендлер
        logger.warning("save_manual_hr_contact failed vid=%s: %s", vid, exc)
        return None, f"Не удалось сохранить: {exc}"

    return key, ""


__all__ = [
    "CB_SET_CONTACT_PREFIX",
    "FORMAT_LABELS",
    "SALARY_MATCH_LABELS",
    "build_hr_card_keyboard",
    "format_hr_card",
    "has_actionable_hr_contact",
    "hr_contact_display",
    "needs_manual_hr_contact",
    "save_manual_hr_contact",
    "vacancy_id_for_card",
]
