"""Self-debrief после собеса: пассивный детект из forwarded.py (DR-3a/DR-3b).

`/debrief`-команда и menu:debrief:*-пикер снесены в DR-3b — та же операция «вручную выбрать
вакансию + вставить транскрипт» уже есть на фронте (вкладка «Разбор»). Единственное, что
не дублируется фронтом — пассивный автодетект self-debrief из пересланного/вставленного текста
(`detect_self_debrief` в `hr_segmenter.py`, вызов из `forwarded.py`), поэтому этот путь остаётся.
Разбор + персист — `core.domains.pipeline.hr_segmenter` (поверх
`core.domains.preparation.interview.analyze_debrief` +
`core.domains.opportunities.enrichment`).
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot_app.access import resolve_owner_account_id
from bot_app.config import get_bot_settings
from bot_app.filters import IsAdmin
from bot_app.storage import debrief_sessions
from bot_app.telegram_send import safe_send
from bot_app.utils import esc
from core.domains.pipeline.hr_segmenter import resolve_vacancy_for_debrief, run_debrief
from core.domains.preparation.models import SIGNAL_LABELS

logger = logging.getLogger(__name__)
router = Router(name="debrief")


def _build_summary_card(vacancy_id: str, analysis: dict) -> str:
    signal = analysis.get("next_steps_signal") or "unknown"
    signal_label = SIGNAL_LABELS.get(signal, signal)
    impression = analysis.get("overall_impression") or "?"
    summary = (analysis.get("summary") or "").strip() or "—"
    weak = analysis.get("weak_answers") or []
    strong = analysis.get("strong_answers") or []

    lines = [
        f"🎙 <b>Разбор собеса · {esc(vacancy_id)}</b>",
        f"Впечатление: <b>{impression}/10</b> · {esc(signal_label)}",
        "",
        f"💬 {esc(summary)}",
    ]
    if weak:
        top_weak = weak[:3]
        lines.append("")
        lines.append("<b>Топ-замечания:</b>")
        for item in top_weak:
            q = (item.get("question") or "").strip()[:200]
            wrong = (item.get("what_went_wrong") or "").strip()[:300]
            lines.append(f"• <i>{esc(q)}</i>")
            if wrong:
                lines.append(f"  ↳ {esc(wrong)}")
    if strong:
        lines.append("")
        lines.append("<b>Сильные ответы:</b>")
        for item in strong[:3]:
            lines.append(f"• {esc(str(item)[:300])}")
    return "\n".join(lines)


def _summary_keyboard(vacancy_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📚 Темы для подготовки",
                    callback_data=f"debrief:topics:{vacancy_id}",
                ),
                InlineKeyboardButton(
                    text="🔍 Полный разбор",
                    callback_data=f"debrief:full:{vacancy_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📝 Сгенерировать prep по темам",
                    callback_data=f"debrief:prep:{vacancy_id}",
                )
            ],
        ]
    )


async def _send_debrief_result(chat_id: int, bot: Bot, vacancy_id: str, result: dict) -> None:
    if result.get("error") == "not_found":
        await safe_send(
            bot,
            chat_id,
            f"⚠ Вакансия <code>{esc(vacancy_id)}</code> не найдена в БД. "
            "Сначала оцените её через расширение.",
            parse_mode="HTML",
        )
        return
    if result.get("error") == "bad_request":
        await safe_send(
            bot,
            chat_id,
            f"⚠ {esc(str(result.get('detail') or 'Транскрипт некорректен.'))}",
            parse_mode="HTML",
        )
        return
    if result.get("error") == "llm":
        await safe_send(
            bot,
            chat_id,
            f"⚠ Ошибка LLM: {esc(str(result.get('detail') or 'нет деталей'))}",
            parse_mode="HTML",
        )
        return

    analysis = result.get("analysis") or {}
    interview_id = result.get("interview_id")

    debrief_sessions.remember(
        chat_id,
        debrief_sessions.DebriefState(
            vacancy_id=vacancy_id,
            analysis=analysis,
            interview_id=interview_id,
        ),
    )

    await safe_send(
        bot,
        chat_id,
        _build_summary_card(vacancy_id, analysis),
        parse_mode="HTML",
        reply_markup=_summary_keyboard(vacancy_id),
        disable_web_page_preview=True,
    )


async def handle_self_debrief_text(
    text: str,
    chat_id: int,
    bot: Bot,
    *,
    vacancy_id: str | None = None,
) -> bool:
    """Точка входа для self-debrief из forwarded-хендлера.

    Возвращает True, если debrief удалось обработать (или вакансия не найдена,
    что всё равно «съедает» это сообщение). False — если просили резолвить, но
    не получилось → пусть отрабатывает HR-pipeline.
    """
    account_id = await resolve_owner_account_id()
    if account_id is None:
        return False

    if vacancy_id is None:
        resolved = await resolve_vacancy_for_debrief(text, account_id=account_id)
        vacancy_id = resolved.vacancy_id
        if vacancy_id is None:
            return False

    try:
        result = await run_debrief(vacancy_id, text, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("self-debrief failed: %s", exc)
        await safe_send(
            bot,
            chat_id,
            f"⚠ Не удалось разобрать debrief: <code>{esc(str(exc))}</code>",
            parse_mode="HTML",
        )
        return True

    await _send_debrief_result(chat_id, bot, vacancy_id, result)
    return True


# ----- Callbacks (карточка self-debrief) -----


@router.callback_query(IsAdmin(), F.data.startswith("debrief:topics:"))
async def cb_topics(query: CallbackQuery, bot: Bot) -> None:
    if not query.message:
        await query.answer()
        return
    state = debrief_sessions.get(query.message.chat.id)
    if state is None:
        await query.answer("Разбор устарел.", show_alert=True)
        return
    topics = state.analysis.get("topics_to_study") or []
    await query.answer()
    if not topics:
        await safe_send(
            bot,
            query.message.chat.id,
            "📚 Список тем для подготовки пуст — модель не выделила пробелов.",
        )
        return
    lines = ["📚 <b>Что подучить</b>", ""]
    for topic in topics:
        lines.append(f"• {esc(str(topic))}")
    await safe_send(bot, query.message.chat.id, "\n".join(lines), parse_mode="HTML")


@router.callback_query(IsAdmin(), F.data.startswith("debrief:full:"))
async def cb_full(query: CallbackQuery, bot: Bot) -> None:
    if not query.message:
        await query.answer()
        return
    state = debrief_sessions.get(query.message.chat.id)
    if state is None:
        await query.answer("Разбор устарел.", show_alert=True)
        return
    weak = state.analysis.get("weak_answers") or []
    strong = state.analysis.get("strong_answers") or []
    questions = state.analysis.get("questions_asked") or []
    await query.answer()

    if questions:
        q_lines = ["❓ <b>Что спрашивали</b>", ""]
        for q in questions[:12]:
            q_lines.append(f"• {esc(str(q))}")
        await safe_send(bot, query.message.chat.id, "\n".join(q_lines), parse_mode="HTML")

    if weak:
        chunks = ["🔻 <b>Слабые ответы и как улучшить</b>", ""]
        for item in weak:
            q = (item.get("question") or "").strip()[:300]
            wrong = (item.get("what_went_wrong") or "").strip()[:600]
            improve = (item.get("how_to_improve") or "").strip()[:600]
            chunks.append(f"<b>Вопрос:</b> {esc(q)}")
            if wrong:
                chunks.append(f"<i>Что не так:</i> {esc(wrong)}")
            if improve:
                chunks.append(f"<i>Как лучше:</i> {esc(improve)}")
            chunks.append("")
        body = "\n".join(chunks).strip()
        for start in range(0, len(body), 3800):
            await safe_send(
                bot, query.message.chat.id, body[start : start + 3800], parse_mode="HTML"
            )

    if strong:
        s_lines = ["🟢 <b>Сильные ответы</b>", ""]
        for item in strong:
            s_lines.append(f"• {esc(str(item))}")
        await safe_send(bot, query.message.chat.id, "\n".join(s_lines), parse_mode="HTML")


@router.callback_query(IsAdmin(), F.data.startswith("debrief:prep:"))
async def cb_prep(query: CallbackQuery, bot: Bot) -> None:
    if not query.message:
        await query.answer()
        return
    state = debrief_sessions.get(query.message.chat.id)
    if state is None:
        await query.answer("Разбор устарел.", show_alert=True)
        return
    await query.answer()
    web = get_bot_settings().web_url.rstrip("/")
    await safe_send(
        bot,
        query.message.chat.id,
        (
            f"📝 Подготовку по этой вакансии генерируй во вкладке «Технички» на дэшборде:\n"
            f"<code>{esc(web)}/jobs/{esc(state.vacancy_id)}</code> → «Технички»\n"
            f"Темы из debrief модель учтёт через резюме/инструкции."
        ),
        parse_mode="HTML",
    )
