"""Обработчик HR-переписки: только личка, батчинг, без flood (порт `bot.handlers.forwarded`, S11).

Полный HR-пайплайн переехал в bot_app (S11): пересланное/вставленное HR-сообщение →
guard-скан периметра (журнал inbox.jsonl, пилот 2.7) → батчинг → segmenter+parser+actions →
карточка с кнопкой подтверждения слабой привязки vacancy_id. Self-debrief перехватывается до
HR-парсера. DR-3b: авто-черновик ответа HR снесён (фронтовый Чат по вакансии его превзошёл).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import time
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

from bot_app.access import resolve_account
from bot_app.filters import (
    IsAccount,
    IsGetmatchPost,
    IsHrInput,
    IsVacancyChannelPost,
    IsVacancyUrl,
)
from bot_app.handlers.debrief import handle_self_debrief_text
from bot_app.services.batch_cleanup import plan_batch_cleanup, run_auto_cleanup
from bot_app.services.batch_summary import (
    BatchScoreRow,
    count_batch_stats,
    format_batch_summary,
    is_card_worthy,
    progress_text,
    row_from_score,
)
from bot_app.services.card_replace import send_or_replace_score_card
from bot_app.services.forward_batcher import ForwardBatcher
from bot_app.services.hr_card import (
    CB_SET_CONTACT_PREFIX,
    build_hr_card_keyboard,
    format_hr_card,
    needs_manual_hr_contact,
    vacancy_id_for_card,
)
from bot_app.services.prep_scheduler import schedule_prep_reminders_from_actions
from bot_app.storage import hr_pending
from bot_app.storage.message_registry import KIND_HR_CARD, KIND_PROGRESS
from bot_app.telegram_send import safe_reply, safe_send, send_typing
from bot_app.tg_util import editable_message
from bot_app.utils import esc
from core.domains.opportunities import VacancyInput, score_and_persist
from core.domains.opportunities.jobs import (
    SOURCE_GETMATCH,
    SOURCE_HABR,
    SOURCE_TELEGRAM_CHANNEL,
    SOURCE_VACANCY_PAGE,
    Job,
    extract_getmatch_numeric_id_from_text,
    get_job_by_vacancy_id,
)
from core.domains.opportunities.models import ScoreResult
from core.domains.opportunities.persist import ScoredJob
from core.domains.pipeline.channel_vacancy_parser import parse_channel_vacancy_post
from core.domains.pipeline.hr_identity import telegram_forward_hr_hint
from core.domains.pipeline.hr_orchestrator import HrBatchResult, process_hr_batch
from core.domains.pipeline.hr_segmenter import detect_self_debrief
from core.domains.pipeline.vacancy_links import (
    extract_primary_vacancy_id,
    listing_url_for_vacancy_id,
)
from core.kernel import ports

logger = logging.getLogger(__name__)
router = Router(name="forwarded")

# (text, message_id) — склейка в on_batch как раньше (\n\n, якорь = последний id).
_hr_batcher: ForwardBatcher[tuple[str, int]] = ForwardBatcher(name="hr")


@dataclass(frozen=True)
class VacancyForwardItem:
    """Элемент батча пересланных вакансий: message_id + text + source + origin."""

    message_id: int
    text: str
    source: str
    origin: str  # стабильный ключ форварда (_forwarded_post_vacancy_id)
    vacancy_id_prefix: str
    fallback_company: str
    header: str


_vacancy_batcher: ForwardBatcher[VacancyForwardItem] = ForwardBatcher(name="vacancy")

# Как в discovery: не чаще раза в 2с edit одного progress-сообщения.
_PROGRESS_EDIT_THROTTLE_SEC = 2.0

# Антибот hh/getmatch или пустой HTML — не считаем фичу гарантированной (риск TB-0.6).
_URL_FETCH_FALLBACK = "Не удалось скачать вакансию по ссылке. Пришли текст вакансии пересылкой."
# Шаг 5: html-скрейпинг hh с VM выключен; api.hh.ru молчит → только браузер с расширением.
_HH_OPEN_IN_BROWSER = "hh не отдал вакансию. Откройте ссылку в браузере с расширением."


def _url_fetch_fallback(source_name: str) -> str:
    if source_name == "hh":
        return _HH_OPEN_IN_BROWSER
    return _URL_FETCH_FALLBACK


# Имя VacancySource из `_vacancy_ref_from_url_text` → канон jobs.source.
# Фолбэк — SOURCE_VACANCY_PAGE (клик «Оценить» на hh).
_VACANCY_SOURCE_BY_NAME = {
    "getmatch": SOURCE_GETMATCH,
    "habr": SOURCE_HABR,
}


def _vacancy_ref_from_url_text(text: str) -> tuple[str, str, str] | None:
    """Из текста со ссылкой → (vacancy_id, имя VacancySource, заголовок карточки)."""
    gm = extract_getmatch_numeric_id_from_text(text)
    if gm:
        return f"gm_{gm}", "getmatch", "Вакансия с getmatch.ru"
    from core.domains.opportunities.sources.habr import extract_habr_numeric_id_from_text

    habr = extract_habr_numeric_id_from_text(text)
    if habr:
        return f"habr_{habr}", "habr", "Вакансия с career.habr.com"
    hh = extract_primary_vacancy_id(text)
    if hh and hh.isdigit():
        return hh, "hh", "Вакансия с hh.ru"
    return None


async def _send_scored_card(
    bot: Bot,
    chat_id: int,
    *,
    reply_to_message_id: int | None,
    job: Job,
    score: ScoreResult,
    header: str,
    refresh_menu: bool = True,
) -> None:
    await send_or_replace_score_card(
        bot,
        chat_id,
        job=job,
        score=score,
        header=header,
        reply_to_message_id=reply_to_message_id,
    )
    if not refresh_menu:
        return
    from bot_app.services.menu_manager import after_score, show_menu

    await show_menu(bot, chat_id, after_score(job.vacancy_id or ""))


def _build_response(batch: HrBatchResult) -> str:
    """TB-7.1: карточка через format_hr_card (контакт сверху, без эмодзи-забора)."""
    return format_hr_card(batch)


async def _build_inline_keyboard(
    batch: HrBatchResult, chat_id: int, reply_msg_id: int, *, account_id: int
) -> InlineKeyboardMarkup | None:
    """TB-7.2: тред/черновик + hrres + «Указать @HR» при отсутствии контакта."""
    from bot_app.config import get_bot_settings

    actions = batch.actions
    analysis = batch.primary
    need_resolve = bool(actions.pending_resolve_vacancy_id)
    need_contact = needs_manual_hr_contact(analysis)

    resolve_token = ""
    contact_token = ""
    if need_resolve or need_contact:
        token = await hr_pending.save(
            hr_pending.PendingHrContext(
                analysis=analysis,
                pending_resolve_vacancy_id=actions.pending_resolve_vacancy_id,
                telegram_msg_id=reply_msg_id,
                chat_id=chat_id,
            ),
            account_id=account_id,
        )
        if need_resolve:
            resolve_token = token
        if need_contact:
            contact_token = token

    return build_hr_card_keyboard(
        batch,
        web_url=get_bot_settings().web_url,
        resolve_token=resolve_token,
        contact_token=contact_token,
    )


async def _process_hr_text(
    text: str, chat_id: int, reply_msg_id: int, bot: Bot, *, account_id: int
) -> None:
    """Сегментация + parse + действия на батч HR-сообщений.

    Если эвристика распознала self-debrief — перехватываем до HR-парсера.
    """
    await bot.send_chat_action(chat_id, "typing")

    if detect_self_debrief(text):
        handled = await handle_self_debrief_text(text, chat_id, bot)
        if handled:
            return
        # vacancy_id не нашли — пусть обычный pipeline отработает (вдруг это всё-таки HR).

    batch = await process_hr_batch(text, reply_msg_id, account_id=account_id)
    await schedule_prep_reminders_from_actions(
        batch.primary, batch.actions, chat_id=chat_id, account_id=account_id
    )
    reply = _build_response(batch)
    keyboard = await _build_inline_keyboard(batch, chat_id, reply_msg_id, account_id=account_id)

    try:
        await safe_send(
            bot,
            chat_id,
            reply,
            reply_to_message_id=reply_msg_id,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard,
            track_kind=KIND_HR_CARD,
            vacancy_id=vacancy_id_for_card(batch) or None,
        )
    except Exception as exc:  # noqa: BLE001 — ответ best-effort
        logger.error("Не удалось отправить ответ HR: %s", exc)
        return

    from bot_app.services.menu_manager import after_hr, show_menu

    await show_menu(bot, chat_id, after_hr(vacancy_id_for_card(batch)))


def _prepend_hr_forward_hint(message: Message, text: str) -> str:
    """Метка HR из пересылки Telegram — для колонки «Ссылка HR»."""
    hint = telegram_forward_hr_hint(message)
    if not hint or not hint.startswith("tg:@"):
        return text
    username = hint[4:]
    marker = f"[HR Telegram: @{username}]"
    if marker in text:
        return text
    return f"{marker}\n\n{text}"


async def _apply_confirmed_resolve(
    ctx: hr_pending.PendingHrContext, bot: Bot, *, account_id: int
) -> str:
    """После подтверждения подставляем vacancy_id и заново запускаем apply_hr_actions."""
    from core.domains.pipeline.hr_actions import apply_hr_actions

    confirmed_analysis = ctx.analysis.model_copy(
        update={
            "vacancy_id": ctx.pending_resolve_vacancy_id,
            "vacancy_url": listing_url_for_vacancy_id(ctx.pending_resolve_vacancy_id),
            "resolve_confidence": 1.0,
            "resolve_via": "url_in_text",
        }
    )
    result = await apply_hr_actions(confirmed_analysis, ctx.telegram_msg_id, account_id=account_id)
    await schedule_prep_reminders_from_actions(
        confirmed_analysis, result, chat_id=ctx.chat_id, account_id=account_id
    )
    notes = result.notes[:6]
    body = "\n".join(f"• {esc(n)}" for n in notes) if notes else "—"
    return (
        f"Привязка подтверждена: <b>{esc(ctx.pending_resolve_vacancy_id)}</b>\n"
        f"<b>Применено:</b>\n{body}"
    )


@router.callback_query(IsAccount(), F.data.startswith(CB_SET_CONTACT_PREFIX))
async def cb_ask_hr_contact(query: CallbackQuery, bot: Bot) -> None:
    """TB-7.2: «Указать @HR» → pending-input, аккаунт присылает контакт текстом."""
    from bot_app.handlers.menu import set_pending
    from bot_app.services.menu_manager import after_hr, show_menu

    if not query.data or query.from_user is None:
        await query.answer()
        return
    token = query.data[len(CB_SET_CONTACT_PREFIX) :]
    account = await resolve_account(user_id=query.from_user.id)
    ctx = await hr_pending.get(token, account_id=account.id) if account is not None else None
    if ctx is None:
        await query.answer(
            "Запрос устарел. Перешли HR-сообщение ещё раз.",
            show_alert=True,
        )
        return

    chat_id = query.message.chat.id if query.message else ctx.chat_id
    analysis = ctx.analysis
    vid = (analysis.vacancy_id or ctx.pending_resolve_vacancy_id or "").strip()
    set_pending(
        chat_id,
        "hr_contact",
        vacancy_id=vid,
        company=analysis.company or "",
        position=analysis.position or "",
        token=token,
    )
    await query.answer()
    await safe_send(
        bot,
        chat_id,
        "Пришли @username HR (или ссылку t.me/… / email / телефон).",
        parse_mode="HTML",
    )
    await show_menu(bot, chat_id, after_hr(vid))


@router.callback_query(IsAccount(), F.data.startswith("hrres:"))
async def cb_resolve_confirm(query: CallbackQuery, bot: Bot) -> None:
    if not query.data or query.from_user is None:
        await query.answer()
        return
    parts = query.data.split(":", 2)
    if len(parts) != 3:
        await query.answer("Битый callback")
        return
    _, action, token = parts
    account = await resolve_account(user_id=query.from_user.id)
    if account is None:
        await query.answer("Запрос устарел. Перешлите HR-сообщение ещё раз.", show_alert=True)
        return
    account_id = account.id
    ctx = await hr_pending.pop(token, account_id=account_id)
    if ctx is None:
        await query.answer("Запрос устарел. Перешлите HR-сообщение ещё раз.", show_alert=True)
        return

    from bot_app.services.menu_manager import after_hr, idle, member_home, show_menu

    home = idle() if account.role == "owner" else member_home()

    if action == "no":
        await query.answer("Привязка отменена")
        msg = editable_message(query.message)
        if msg is not None:
            try:
                await msg.edit_reply_markup(reply_markup=None)
                await safe_send(
                    bot,
                    msg.chat.id,
                    f"Не привязал к вакансии {esc(ctx.pending_resolve_vacancy_id)}. "
                    "Укажите id в переписке отдельно, если нужно.",
                    parse_mode="HTML",
                )
                await show_menu(bot, msg.chat.id, home)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cb_resolve_confirm edit failed: %s", exc)
        return

    # action == "ok"
    await query.answer("Применяю…")
    try:
        reply = await _apply_confirmed_resolve(ctx, bot, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("apply_confirmed_resolve failed")
        reply = f"Ошибка при применении: <code>{esc(str(exc))}</code>"
    msg = editable_message(query.message)
    if msg is not None:
        with contextlib.suppress(Exception):
            await msg.edit_reply_markup(reply_markup=None)
        try:
            await safe_send(
                bot,
                msg.chat.id,
                reply,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            await show_menu(bot, msg.chat.id, after_hr(ctx.pending_resolve_vacancy_id or ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cb_resolve_confirm send failed: %s", exc)


def _forwarded_post_vacancy_id(message: Message, prefix: str) -> str:
    """Синтетический vacancy_id для пересланного поста без hh-ссылки (канал ИЛИ getmatch-бот).

    Детерминирован по происхождению форварда — повторная пересылка того же поста апдейтит запись
    (`save_job` upsert по vacancy_id), а не плодит дубликаты. Читает **только `forward_origin`**
    (Bot API 7.0+) — см. пояснение в `IsVacancyChannelPost`, старые `forward_from_chat`/
    `forward_from_message_id` Telegram больше не заполняет.

    Канал (`MessageOriginChannel`) даёт `chat.id`+`message_id` — точный ключ исходного поста.
    Бот в личке (`MessageOriginUser`, кейс getmatch) `message_id` не отдаёт вовсе — берём
    `sender_user.id`+`date` исходного сообщения (та же пара при повторной пересылке). Без
    метаданных форварда (Telegram иногда их прячет) — фолбэк на хэш текста, тоже детерминированный.
    """
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        origin_type = getattr(origin, "type", None)
        if origin_type == "channel":
            chat = getattr(origin, "chat", None)
            msg_id = getattr(origin, "message_id", None)
            if chat is not None and getattr(chat, "id", None) is not None and msg_id:
                return f"{prefix}_{abs(chat.id)}_{msg_id}"
        sender_user = getattr(origin, "sender_user", None)
        date = getattr(origin, "date", None)
        if sender_user is not None and getattr(sender_user, "id", None) is not None and date:
            ts = int(date.timestamp()) if hasattr(date, "timestamp") else int(date)
            return f"{prefix}_{sender_user.id}_{ts}"
    text = (message.text or message.caption or "").strip()
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


async def _score_vacancy_forward_item(
    item: VacancyForwardItem, *, account_id: int
) -> ScoredJob | None:
    """Parse + score_and_persist одного поста. None при сбое (уже залогирован)."""
    extract = await parse_channel_vacancy_post(item.text)

    vacancy_id: str
    if item.source == SOURCE_GETMATCH:
        # GM-9: numeric_id из ссылки → тот же vacancy_id, что у расширения (`gm_{id}`).
        numeric_id = extract_getmatch_numeric_id_from_text(item.text)
        if numeric_id:
            vacancy_id = f"{item.vacancy_id_prefix}_{numeric_id}"
        else:
            vacancy_id = item.origin
            logger.warning(
                "getmatch post without numeric_id in text, using fallback vacancy_id=%s",
                vacancy_id,
            )
    else:
        vacancy_id = item.origin

    vac = VacancyInput(
        text=item.text,
        vacancy_id=vacancy_id,
        title=extract.position or None,
        company=extract.company or item.fallback_company or None,
        salary_text=extract.salary_text or None,
        work_format=extract.work_format or None,
        source=item.source,
    )
    try:
        return await score_and_persist(vac, account_id=account_id)
    except Exception:  # noqa: BLE001 — батч/одиночный сами решают, как сообщить
        logger.exception("forwarded vacancy score/persist failed (source=%s)", item.source)
        return None


def _row_from_scored(scored: ScoredJob) -> BatchScoreRow:
    job, score = scored.job, scored.score
    return row_from_score(
        score,
        company=(job.company or "").strip(),
        title=(job.title or "").strip(),
        vacancy_id=job.vacancy_id or "",
    )


async def _process_vacancy_forward_item(
    item: VacancyForwardItem,
    *,
    bot: Bot,
    chat_id: int,
    account_id: int,
) -> None:
    """Скоринг одного пересланного поста → карточка (одиночный путь TB-4.2)."""
    await bot.send_chat_action(chat_id, "typing")
    scored = await _score_vacancy_forward_item(item, account_id=account_id)
    if scored is None:
        await safe_send(
            bot,
            chat_id,
            "Не удалось оценить вакансию.",
            reply_to_message_id=item.message_id,
        )
        return

    await _send_scored_card(
        bot,
        chat_id,
        reply_to_message_id=item.message_id,
        job=scored.job,
        score=scored.score,
        header=item.header,
    )


async def _process_vacancy_forward_batch(
    items: list[VacancyForwardItem],
    *,
    bot: Bot,
    chat_id: int,
    account_id: int,
) -> None:
    """Батч ≥2: один progress → скоринг → сводка → карточки apply+ → меню."""
    total = len(items)
    if total < 2:
        if items:
            await _process_vacancy_forward_item(
                items[0], bot=bot, chat_id=chat_id, account_id=account_id
            )
        return

    await bot.send_chat_action(chat_id, "typing")
    progress_msg = await safe_send(
        bot,
        chat_id,
        progress_text(0, total),
        track_kind=KIND_PROGRESS,
    )
    last_edit = 0.0

    async def _edit_progress(done: int, *, force: bool = False) -> None:
        nonlocal last_edit
        if progress_msg is None:
            return
        if not force and (time.monotonic() - last_edit) < _PROGRESS_EDIT_THROTTLE_SEC:
            return
        last_edit = time.monotonic()
        try:
            await progress_msg.edit_text(progress_text(done, total))
        except TelegramBadRequest:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("vacancy batch progress edit failed: %s", exc)

    scored_pairs: list[tuple[VacancyForwardItem, ScoredJob]] = []
    errors = 0
    try:
        for i, item in enumerate(items, start=1):
            scored = await _score_vacancy_forward_item(item, account_id=account_id)
            if scored is None:
                errors += 1
            else:
                scored_pairs.append((item, scored))
            await _edit_progress(i)
        await _edit_progress(total, force=True)
    finally:
        if progress_msg is not None:
            with contextlib.suppress(Exception):
                await bot.delete_message(chat_id, progress_msg.message_id)

    rows = [_row_from_scored(s) for _, s in scored_pairs]
    summary = format_batch_summary(rows, errors=errors)
    forward_ids = [item.message_id for item in items]
    cleanup = await plan_batch_cleanup(chat_id, forward_ids)
    await safe_send(bot, chat_id, summary, reply_markup=cleanup.reply_markup)
    # auto: исходники сразу после сводки (карточки без reply_to — оригинал уже удалён).
    await run_auto_cleanup(bot, cleanup, chat_id)
    reply_to_forwards = cleanup.mode != "auto"

    anchor_vid = ""
    for item, scored in scored_pairs:
        if not is_card_worthy(scored.score.recommendation):
            continue
        if not anchor_vid:
            anchor_vid = scored.job.vacancy_id or ""
        await _send_scored_card(
            bot,
            chat_id,
            reply_to_message_id=item.message_id if reply_to_forwards else None,
            job=scored.job,
            score=scored.score,
            header=item.header,
            refresh_menu=False,
        )

    from bot_app.services.menu_manager import after_score, show_menu

    stats = count_batch_stats(rows, errors=errors)
    await show_menu(bot, chat_id, after_score(anchor_vid, batch_stats=stats))


async def _dispatch_vacancy_batch(
    items: list[VacancyForwardItem],
    *,
    bot: Bot,
    chat_id: int,
    account_id: int,
) -> None:
    """Одиночный форвард → прежняя карточка; ≥2 → batch-путь."""
    if not items:
        return
    if len(items) == 1:
        await _process_vacancy_forward_item(
            items[0], bot=bot, chat_id=chat_id, account_id=account_id
        )
        return
    await _process_vacancy_forward_batch(items, bot=bot, chat_id=chat_id, account_id=account_id)


async def _enqueue_vacancy_forward(
    message: Message,
    bot: Bot,
    *,
    source: str,
    vacancy_id_prefix: str,
    fallback_company: str,
    header: str,
    account_id: int,
) -> None:
    """Валидация → push в vacancy-батчер.

    `account_id` резолвится ОДИН раз у вызывающего хендлера (на месте есть `message.from_user`)
    и замыкается в `on_batch` — батчер группирует по `chat_id`, а в личке `chat_id` уже
    однозначно определяет аккаунт (Этап 5: не только владелец), доверезолвить его внутри
    батча нечем — там уже нет исходного `Message`.
    """
    text = (message.text or message.caption or "").strip()
    if len(text) < 50:
        await safe_reply(message, "Пост слишком короткий для скоринга (нужно от 50 символов).")
        return

    item = VacancyForwardItem(
        message_id=message.message_id,
        text=text,
        source=source,
        origin=_forwarded_post_vacancy_id(message, vacancy_id_prefix),
        vacancy_id_prefix=vacancy_id_prefix,
        fallback_company=fallback_company,
        header=header,
    )
    chat_id = message.chat.id

    async def on_batch(items: list[VacancyForwardItem]) -> None:
        await _dispatch_vacancy_batch(items, bot=bot, chat_id=chat_id, account_id=account_id)

    await _vacancy_batcher.push(chat_id, item, on_batch)


@router.message(
    IsAccount(),
    IsVacancyUrl(),
    F.chat.type == ChatType.PRIVATE,
    F.text | F.caption,
)
async def handle_vacancy_url(message: Message, bot: Bot) -> None:
    """Прямая ссылка hh/getmatch → карточка из БД или фетч+скоринг.

    hh: официальный `api.hh.ru` (не HTML страницы). Отказ API → «откройте в браузере
    с расширением», без скрейпинга с VM.
    """
    text = (message.text or message.caption or "").strip()
    ref = _vacancy_ref_from_url_text(text)
    if ref is None:
        return
    vacancy_id, source_name, header = ref

    await send_typing(message)

    account = await resolve_account(user_id=message.from_user.id) if message.from_user else None
    if account is None:
        await safe_reply(message, "Сначала получи токен — «Токен авторизации» в /start.")
        return
    account_id = account.id

    job = None
    try:
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — PG down → пробуем фетч
        logger.warning("vacancy url: DB lookup failed for %s: %s", vacancy_id, exc)

    if job is not None and job.score:
        try:
            score = ScoreResult.model_validate(job.score)
        except Exception as exc:  # noqa: BLE001 — битый jsonb → перескорим
            logger.warning("vacancy url: score jsonb invalid for %s: %s", vacancy_id, exc)
        else:
            await _send_scored_card(
                bot,
                message.chat.id,
                reply_to_message_id=message.message_id,
                job=job,
                score=score,
                header=header,
            )
            return

    try:
        raws = await ports.vacancy_source(source_name).fetch(text)
    except Exception as exc:  # noqa: BLE001 — антибот/сеть → честный фолбэк
        logger.warning("vacancy url: fetch failed (%s %s): %s", source_name, vacancy_id, exc)
        await safe_reply(message, _url_fetch_fallback(source_name))
        return

    raw = raws[0] if raws else None
    if raw is None or len((raw.text or "").strip()) < 50:
        await safe_reply(message, _url_fetch_fallback(source_name))
        return

    vac = VacancyInput(
        text=raw.text,
        url=raw.url or None,
        vacancy_id=raw.vacancy_id or vacancy_id,
        title=raw.title or None,
        company=raw.company or None,
        salary_text=raw.salary_text or None,
        area=raw.area or None,
        work_format=raw.work_format or None,
        source=_VACANCY_SOURCE_BY_NAME.get(source_name, SOURCE_VACANCY_PAGE),
    )
    try:
        scored = await score_and_persist(vac, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("vacancy url: score/persist failed (%s)", vacancy_id)
        await safe_reply(message, f"Не удалось оценить вакансию: {esc(str(exc))}")
        return

    await _send_scored_card(
        bot,
        message.chat.id,
        reply_to_message_id=message.message_id,
        job=scored.job,
        score=scored.score,
        header=header,
    )


@router.message(
    IsAccount(),
    IsVacancyChannelPost(),
    F.chat.type == ChatType.PRIVATE,
    F.text | F.caption,
)
async def handle_channel_vacancy_post(message: Message, bot: Bot) -> None:
    """Пост из вакансийного Telegram-канала: извлечение полей + скоринг как обычной
    вакансии. Регистрируется раньше `handle_hr_message` в этом же роутере — форварды из канала
    (`IsVacancyChannelPost`) перехватываются здесь, остальные форварды идут в HR-пайплайн ниже.
    """
    if message.from_user is None:
        return
    account = await resolve_account(user_id=message.from_user.id)
    if account is None:
        return

    origin = getattr(message, "forward_origin", None)
    chat = getattr(origin, "chat", None)
    channel_title = str(getattr(chat, "title", "") or "") if chat is not None else ""
    header = (
        f"📰 Пост из канала «{esc(channel_title)}»"
        if channel_title
        else "📰 Пост из вакансийного канала"
    )
    await _enqueue_vacancy_forward(
        message,
        bot,
        source=SOURCE_TELEGRAM_CHANNEL,
        vacancy_id_prefix="tg",
        fallback_company=channel_title,
        header=header,
        account_id=account.id,
    )


@router.message(
    IsAccount(),
    IsGetmatchPost(),
    F.chat.type == ChatType.PRIVATE,
    F.text | F.caption,
)
async def handle_getmatch_vacancy_post(message: Message, bot: Bot) -> None:
    """Пост/подборка, пересланная из Telegram-бота getmatch.ru: второй источник вакансий
    рядом с hh, тот же общий экстрактор+скоринг, что и `handle_channel_vacancy_post` — отличается
    только фильтром входа (`IsGetmatchPost`) и `source=getmatch` вместо `telegram_channel`.
    Регистрируется раньше `handle_hr_message` по той же причине, что и канал-хэндлер выше.
    """
    if message.from_user is None:
        return
    account = await resolve_account(user_id=message.from_user.id)
    if account is None:
        return

    await _enqueue_vacancy_forward(
        message,
        bot,
        source=SOURCE_GETMATCH,
        vacancy_id_prefix="gm",
        fallback_company="",
        header="🟣 Вакансия с getmatch.ru",
        account_id=account.id,
    )


@router.message(
    IsAccount(),
    IsHrInput(),
    F.chat.type == ChatType.PRIVATE,
    F.text | F.caption,
)
async def handle_hr_message(message: Message, bot: Bot) -> None:
    if message.from_user is None:
        return
    account = await resolve_account(user_id=message.from_user.id)
    if account is None:
        return
    account_id = account.id

    text = _prepend_hr_forward_hint(message, message.text or message.caption or "")
    if not text.strip():
        await safe_reply(message, "Не смог прочитать текст.")
        return

    await send_typing(message)

    async def on_batch(items: list[tuple[str, int]]) -> None:
        # Не используем «---»: сегментатор воспринимает его как границу смысловых блоков
        # и дробит каждое пересланное сообщение в отдельный сегмент → лишние LLM-вызовы.
        combined = "\n\n".join(t for t, _ in items if t)
        if not combined:
            return
        anchor_msg_id = items[-1][1]
        await _process_hr_text(combined, message.chat.id, anchor_msg_id, bot, account_id=account_id)

    await _hr_batcher.push(message.chat.id, (text.strip(), message.message_id), on_batch)
