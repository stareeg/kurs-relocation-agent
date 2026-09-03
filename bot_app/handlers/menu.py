"""Главное меню бота — hub-кнопки вместо команд (порт `bot/handlers/menu.py`, S12c).

Концепция: пользователь жмёт кнопки; единственная live-команда — `/start`, остальное —
inline-кнопки в сообщении меню. `/start` рисует живое inline-меню (`menu_manager`);
callback'и `menu:*` маршрутизируются здесь; pending-input flow («жду текст») держит
per-chat словарь.

Ссылки на веб в меню больше нет: при `/start` (и после выдачи токена) бот шлёт
отдельное сообщение с ссылкой на сайт и ЗАКРЕПЛЯЕТ его в чате (`_send_site_pin`) —
оно всегда под рукой в шапке диалога. Токен остаётся голой строкой; куда его вставлять
— следующим сообщением (`_send_token_next_steps`).
"""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandObject, CommandStart, Filter
from aiogram.types import (
    CallbackQuery,
    Message,
)

from bot_app.access import resolve_account, resolve_owner_account_id
from bot_app.config import get_bot_settings
from bot_app.filters import IsAccount, IsAdmin
from bot_app.services.auth_token import issue_auth_token_reply
from bot_app.services.avatar_sync import sync_owner_avatar_from_telegram
from bot_app.services.batch_cleanup import (
    CB_BATCH_CLEANUP,
    CB_BATCH_CLEANUP_DONT_ASK,
    execute_pending_cleanup,
    set_batch_cleanup_auto,
)
from bot_app.services.card_replace import send_or_replace_score_card
from bot_app.services.menu_manager import (
    CB_ADD_ACCOUNT,
    CB_AUTH_TOKEN,
    CB_CLEANUP_CHAT,
    CB_HR_CONTACTS,
    CB_TOP_TODAY,
    after_score,
    auth_token_kb,
    idle,
    member_home,
    show_menu,
    show_menu_for,
)
from bot_app.telegram_send import safe_send, send_typing
from bot_app.tg_util import editable_message
from bot_app.utils import esc
from bot_app.utils.keyboards import remove_reply_keyboard
from core.domains.opportunities.jobs import (
    get_job_by_vacancy_id,
    job_record_needs_vacancy_text,
)
from core.domains.opportunities.models import ScoreResult
from core.domains.profile.telegram_link import extract_link_token

logger = logging.getLogger(__name__)
router = Router(name="menu")


# Per-chat «жду текста» состояния. Минимальный stateful flow: бот запоминает chat_id и
# следующий текст распарсит как payload (контакт HR / токен второго аккаунта).
_pending_input: dict[int, dict] = {}

# In-memory отметка «pin для этого чата уже отправлен» в рамках процесса — чтобы /start
# не спамил закрепом при каждом вызове. Переживает рестарт лишь до следующего /start.
_pin_sent_chats: set[int] = set()


_LINK_EXPIRED = "Токен устарел, сгенерируй новый в разделе «Аккаунт»."


class IsLinkStartPayload(Filter):
    """`/start link_<token>` — привязка из веба. Без IsAdmin: токен = допуск."""

    async def __call__(self, message: Message) -> bool:
        text = (message.text or "").strip()
        if not text:
            return False
        parts = text.split(maxsplit=1)
        args = parts[1] if len(parts) > 1 else ""
        return extract_link_token(args) is not None


def set_pending(chat_id: int, kind: str, **payload) -> None:
    _pending_input[chat_id] = {"kind": kind, **payload}


def pop_pending(chat_id: int) -> dict | None:
    return _pending_input.pop(chat_id, None)


def has_pending(chat_id: int) -> bool:
    return chat_id in _pending_input


def consume_pending_if(chat_id: int, kind: str) -> dict | None:
    state = _pending_input.get(chat_id)
    if state and state.get("kind") == kind:
        return _pending_input.pop(chat_id)
    return None


class IsPendingInput(Filter):
    """True, если для этого чата меню ждёт текстовый payload (set_pending)."""

    async def __call__(self, message: Message) -> bool:
        return message.chat is not None and message.chat.id in _pending_input


# ---------- Закреп со ссылкой на сайт ----------


def _web_url() -> str:
    return (get_bot_settings().web_url or "").strip().rstrip("/")


async def _send_site_pin(bot: Bot, chat_id: int) -> None:
    """Отправить «Сайт — ссылка» и закрепить сообщение (best-effort, один раз на процесс).

    In-memory `_pin_sent_chats` не даёт спамить закрепом при повторных /start в жизни
    процесса. Ошибки pin (старое закреплённое, нет прав) глушим — это декоративная фича.
    """
    if chat_id in _pin_sent_chats:
        return
    web = _web_url()
    if not web:
        logger.warning("WEB_URL пуст — закреп со ссылкой на сайт не отправлен chat=%s", chat_id)
        return
    sent = await safe_send(bot, chat_id, f"Сайт — {web}", disable_web_page_preview=False)
    if sent is None:
        return
    _pin_sent_chats.add(chat_id)
    try:
        await bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
    except Exception as exc:  # noqa: BLE001 — уже закреплено / нет прав
        logger.debug("site pin failed chat=%s: %s", chat_id, exc)


_TOKEN_NEXT_STEPS = (
    "Это код входа на сайт. Открой ссылку ниже, зайди в раздел «Аккаунт» "
    "и вставь токен туда — не обратно в этот чат.\n\n"
    "Дальше на сайте: ключ OpenRouter → расширение → резюме."
)


async def _send_token_next_steps(bot: Bot, chat_id: int) -> None:
    """Куда вставлять токен — отдельным сообщением (токен сам остаётся голой строкой)."""
    web = _web_url()
    body = _TOKEN_NEXT_STEPS
    if web:
        body = f"{body}\n\n{web}"
    else:
        logger.warning("WEB_URL пуст — next-steps без ссылки chat=%s", chat_id)
    await safe_send(bot, chat_id, body, disable_web_page_preview=False)


# ---------- /start ----------


async def complete_telegram_link(message: Message, raw_token: str) -> bool:
    """Потребить link-токен → завести/перелинковать `accounts`-строку. True при успехе.

    M7 (plans/multitenancy_gaps_2026_08_06.md §3.11): роль решает ТОЛЬКО совпадение с
    env-allowlist (тот же принцип, что уже у кнопки «Токен авторизации»,
    `bot_app.services.auth_token`) — раньше эта ветка безусловно заводила владельца, и второй
    Telegram-пользователь, прошедший веб-привязку, мог перехватить роль owner.
    """
    from bot_app.access import invalidate, is_allowed_admin
    from core.domains.profile.telegram_link import consume_token
    from core.platform.repo.accounts import Role

    user = message.from_user
    chat = message.chat
    if user is None or chat is None:
        return False

    async def resolve_role() -> Role:
        return (
            "owner" if await is_allowed_admin(user_id=user.id, username=user.username) else "member"
        )

    account = await consume_token(
        raw_token,
        user_id=user.id,
        chat_id=chat.id,
        username=user.username,
        role=resolve_role,
    )
    if account is None:
        await message.answer(_LINK_EXPIRED)
        return False

    invalidate()
    if account.role == "member":
        from core.domains.career.friendships_repo import ensure_system_admin_friendships

        await ensure_system_admin_friendships(account.id)
    web = esc(get_bot_settings().web_url)
    who = (
        f"@{esc(account.telegram_username)}"
        if account.telegram_username
        else f"id {account.telegram_user_id}"
    )
    await message.answer(
        f"Привязано: <code>{web}</code> ↔ {who}",
        parse_mode="HTML",
        reply_markup=remove_reply_keyboard(),
    )
    bot = getattr(message, "bot", None)
    if bot is not None:
        await _send_site_pin(bot, chat.id)
    await show_menu_for(message, idle() if account.role == "owner" else member_home())
    return True


@router.message(CommandStart(), IsLinkStartPayload(), F.chat.type == ChatType.PRIVATE)
async def cmd_start_telegram_link(message: Message, command: CommandObject) -> None:
    """Deep-link из Параметров: t.me/<bot>?start=link_<token>."""
    token = extract_link_token((command.args or "").strip())
    if token is None:
        await message.answer(_LINK_EXPIRED)
        return
    await complete_telegram_link(message, token)


@router.message(CommandStart(), IsAdmin(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, command: CommandObject) -> None:
    # Deep-link из расширения: t.me/<bot>?start=vac_<vacancy_id> → сразу действия по вакансии.
    payload = (command.args or "").strip()
    if payload.startswith("vac_"):
        vacancy_id = payload[len("vac_") :].strip()
        if vacancy_id:
            await _open_vacancy_deeplink(message, vacancy_id)
            return

    if message.bot is not None:
        await _send_site_pin(message.bot, message.chat.id)
    await show_menu_for(message, idle())


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start_guest(message: Message) -> None:
    """Self-serve / возврат: ссылка на сайт + токен входа (Этап 5).

    Бот один на всю систему: незнакомцу заводится member-аккаунт при нажатии
    «Токен авторизации». Уже привязанному — то же меню, без копи «заведу аккаунт».
    """
    if message.bot is not None:
        await _send_site_pin(message.bot, message.chat.id)

    account = None
    if message.from_user is not None:
        account = await resolve_account(user_id=message.from_user.id)

    if account is not None:
        await message.answer(
            "Снова сюда — ок. Нужен код входа на сайт: нажми «Токен авторизации». "
            "Токен вставляй на сайте в «Аккаунт», не в этот чат.",
        )
        home = idle() if account.role == "owner" else member_home()
        await show_menu_for(message, home)
        return

    await message.answer(
        "Нажми «Токен авторизации» — заведу аккаунт и пришлю код входа.\n"
        "Потом открой сайт (ссылка выше) → «Аккаунт» → вставь токен туда.",
        reply_markup=auth_token_kb(),
    )


async def _open_vacancy_deeplink(message: Message, vacancy_id: str) -> None:
    """Карточка скоринга по deep-link из расширения (start=vac_<id>)."""
    await send_typing(message)
    try:
        account_id = await resolve_owner_account_id()
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id) if account_id else None
    except Exception as exc:  # noqa: BLE001 — недоступный PG не должен ронять /start
        logger.warning("deeplink job fetch failed: %s", exc)
        job = None

    if job is None:
        await message.answer(
            f"Вакансия <code>{esc(vacancy_id)}</code> ещё не в системе.\n"
            "Открой её на hh.ru и нажми «Оценить вакансию» в расширении.",
            parse_mode="HTML",
        )
        await show_menu_for(message, idle())
        return

    score: ScoreResult | None = None
    if job.score and not job_record_needs_vacancy_text(job):
        try:
            score = ScoreResult.model_validate(job.score)
        except Exception as exc:  # noqa: BLE001 — битый jsonb → текстовый фолбэк
            logger.warning("deeplink score jsonb invalid for %s: %s", vacancy_id, exc)

    if score is not None and message.bot is not None:
        await send_or_replace_score_card(
            message.bot,
            message.chat.id,
            job=job,
            score=score,
            header="Вакансия из расширения",
        )
        await show_menu_for(message, after_score(vacancy_id))
        return

    company = esc(job.company or "?")
    title = esc(job.title or "вакансия")
    raw_score = job.overall_score
    if raw_score is None:
        raw_score = (job.score or {}).get("overall_score")
    if job_record_needs_vacancy_text(job):
        score_line = (
            "\n❗ <b>Нет текста вакансии</b> — открой страницу на площадке "
            "(расширение спарсит) или вставь текст."
        )
    elif raw_score is not None:
        score_line = f"\nСкоринг: <b>{raw_score}/100</b>"
    else:
        score_line = ""
    web = get_bot_settings().web_url.rstrip("/")
    job_url = f"{web}/jobs/{vacancy_id}"
    chat_url = f"{web}/chat?vacancy={vacancy_id}"
    await message.answer(
        f"<b>{company} — {title}</b>{score_line}\n\n"
        f"Карточка: <code>{esc(job_url)}</code>\n"
        f"Диалог: <code>{esc(chat_url)}</code>",
        parse_mode="HTML",
    )
    await show_menu_for(message, after_score(vacancy_id))


# ---------- Токен авторизации ----------


def _cooldown_alert(remaining) -> str:
    minutes = max(1, int(remaining.total_seconds() // 60) + 1)
    return f"Токен уже выдан — новый можно через ~{minutes} мин."


async def _send_auth_token(bot: Bot, chat_id: int, token: str) -> None:
    """Токен — отдельным сообщением и ТОЛЬКО сырым значением (удобно копировать одним тапом)."""
    await safe_send(bot, chat_id, token)


@router.callback_query(F.data == CB_AUTH_TOKEN)
async def cb_auth_token(query: CallbackQuery, bot: Bot) -> None:
    """Выдать токен входа (Этап 5). Без IsAdmin: оператор и self-serve member."""
    user = query.from_user
    msg = query.message
    if user is None or msg is None:
        await query.answer()
        return
    chat_id = msg.chat.id
    try:
        reply = await issue_auth_token_reply(
            user_id=user.id, chat_id=chat_id, username=user.username
        )
    except Exception as exc:  # noqa: BLE001 — недоступный PG не должен ронять callback
        logger.warning("auth_token: выдача не удалась: %s", exc)
        await query.answer("База недоступна — попробуй позже", show_alert=True)
        return

    if reply.token is None:
        # cooldown: токен уже живой, новый не плодим — напомним, куда его вставлять.
        await query.answer(_cooldown_alert(reply.cooldown_remaining), show_alert=True)
        await _send_site_pin(bot, chat_id)
        await _send_token_next_steps(bot, chat_id)
        return

    # Выдача токена отменяет ожидание «пришли токен другого Telegram» — иначе новичок
    # после копирования собственного токена попадает в dead-end add-account flow.
    pop_pending(chat_id)

    await query.answer()
    await _send_auth_token(bot, chat_id, reply.token)
    await _send_site_pin(bot, chat_id)
    await _send_token_next_steps(bot, chat_id)
    if reply.role == "owner":
        await sync_owner_avatar_from_telegram(bot, user.id)
        await show_menu(bot, chat_id, idle())
    else:
        await show_menu(bot, chat_id, member_home())


# ---------- Привязать другой Telegram ----------

_ADD_ACCOUNT_PROMPT = (
    "Это только если у тебя уже есть аккаунт в другом Telegram.\n\n"
    "Там нажми «Токен авторизации», скопируй код и пришли его сюда — "
    "тогда этот чат откроет тот же аккаунт, а не новый.\n\n"
    "Если другого Telegram нет — не сюда: открой сайт, зайди в «Аккаунт» "
    "и вставь свой токен там."
)
_ADD_ACCOUNT_NOT_FOUND = "Такой токен не найден или устарел — проверь и пришли ещё раз."
_ADD_ACCOUNT_ALREADY_LINKED = (
    "Этот чат уже привязан к твоему аккаунту — привязывать нечего.\n"
    "Токен вставляй на сайте в «Аккаунт», не обратно в этот чат."
)
_ADD_ACCOUNT_CONFLICT = (
    "Этот Telegram уже привязан к другому аккаунту, в котором есть данные — "
    "автоматически объединить нельзя. Обратись к администратору."
)
_ADD_ACCOUNT_NEED_TOKEN_FIRST = (
    "Сначала заведи аккаунт: нажми «Токен авторизации». "
    "«Привязать другой Telegram» — только когда аккаунт уже есть в другом чате."
)


@router.callback_query(F.data == CB_ADD_ACCOUNT)
async def cb_add_account(query: CallbackQuery, bot: Bot) -> None:
    """Привязка второго Telegram к уже существующему аккаунту (account_link).

    Без IsAdmin. Гостю без аккаунта — отказ с подсказкой: иначе pending ждёт токен,
    а handle_pending_input под IsAccount его молча игнорирует.
    """
    await query.answer()
    msg = query.message
    if msg is None or query.from_user is None:
        return
    chat_id = msg.chat.id
    account = await resolve_account(user_id=query.from_user.id)
    if account is None:
        await safe_send(bot, chat_id, _ADD_ACCOUNT_NEED_TOKEN_FIRST)
        return
    set_pending(chat_id, "add_account_token")
    web = _web_url()
    body = _ADD_ACCOUNT_PROMPT
    if web:
        body = f"{body}\n\nСайт: {web}"
    await safe_send(bot, chat_id, body, disable_web_page_preview=False)


# ---------- Callback router: menu:* ----------


@router.callback_query(IsAdmin(), F.data == "menu:home")
async def cb_home(query: CallbackQuery, bot: Bot) -> None:
    await query.answer()
    if query.message:
        await show_menu(bot, query.message.chat.id, idle())


@router.callback_query(IsAccount(), F.data == CB_TOP_TODAY)
async def cb_top_today(query: CallbackQuery, bot: Bot) -> None:
    """Заглушка до TB-8.2."""
    await query.answer()
    if not query.message or query.from_user is None:
        return
    await safe_send(bot, query.message.chat.id, "Топ за сегодня — скоро.")
    account = await resolve_account(user_id=query.from_user.id)
    home = idle() if account is not None and account.role == "owner" else member_home()
    await show_menu(bot, query.message.chat.id, home)


async def _strip_summary_keyboard(query: CallbackQuery) -> None:
    """Убрать кнопки уборки со сводки после клика (best-effort)."""
    msg = editable_message(query.message)
    if msg is None:
        return
    with contextlib.suppress(Exception):
        await msg.edit_reply_markup(reply_markup=None)


@router.callback_query(IsAccount(), F.data == CB_CLEANUP_CHAT)
async def cb_cleanup_chat(query: CallbackQuery, bot: Bot) -> None:
    """Подчистить pending-форварды батча; без pending — коротко."""
    if not query.message or query.from_user is None:
        await query.answer()
        return
    chat_id = query.message.chat.id
    deleted = await execute_pending_cleanup(bot, chat_id)
    if deleted:
        await query.answer(f"Удалено: {deleted}")
    else:
        await query.answer("Нечего подчищать")
    account = await resolve_account(user_id=query.from_user.id)
    home = idle() if account is not None and account.role == "owner" else member_home()
    await show_menu(bot, chat_id, home)


@router.callback_query(IsAccount(), F.data == CB_BATCH_CLEANUP)
async def cb_batch_cleanup(query: CallbackQuery, bot: Bot) -> None:
    """Кнопка сводки: «Подчистить N пересланных»."""
    if not query.message:
        await query.answer()
        return
    chat_id = query.message.chat.id
    deleted = await execute_pending_cleanup(bot, chat_id)
    await _strip_summary_keyboard(query)
    if deleted:
        await query.answer(f"Удалено: {deleted}")
    else:
        await query.answer("Нечего подчищать")


@router.callback_query(IsAccount(), F.data == CB_BATCH_CLEANUP_DONT_ASK)
async def cb_batch_cleanup_dont_ask(query: CallbackQuery, bot: Bot) -> None:
    """«Больше не спрашивать» → prefs.batch_cleanup=auto + уборка этого батча."""
    if not query.message:
        await query.answer()
        return
    chat_id = query.message.chat.id
    try:
        await set_batch_cleanup_auto()
    except Exception as exc:  # noqa: BLE001 — уборку всё равно делаем
        logger.warning("batch_cleanup prefs→auto failed: %s", exc)
    deleted = await execute_pending_cleanup(bot, chat_id)
    await _strip_summary_keyboard(query)
    if deleted:
        await query.answer(f"Ок, дальше сам. Удалено: {deleted}")
    else:
        await query.answer("Ок, дальше подчищаю сам")


@router.callback_query(IsAccount(), F.data == CB_HR_CONTACTS)
async def cb_hr_contacts(query: CallbackQuery, bot: Bot) -> None:
    """TB-7.4: последние HR-контакты + deeplink на треды в вебе (любой активный аккаунт)."""
    from bot_app.services.hr_contacts import build_hr_contacts_screen

    await query.answer()
    if not query.message or query.from_user is None:
        return
    account = await resolve_account(user_id=query.from_user.id)
    if account is None:
        return
    chat_id = query.message.chat.id
    screen = await build_hr_contacts_screen(
        account_id=account.id, web_url=get_bot_settings().web_url
    )
    await safe_send(
        bot,
        chat_id,
        screen.text,
        parse_mode="HTML",
        reply_markup=screen.reply_markup,
        disable_web_page_preview=True,
    )
    home = idle() if account.role == "owner" else member_home()
    await show_menu(bot, chat_id, home)


# ---------- Pending-input handler ----------


@router.message(
    IsAccount(),
    IsPendingInput(),
    F.chat.type == ChatType.PRIVATE,
    F.text,
    ~F.text.startswith("/"),
)
async def handle_pending_input(message: Message) -> bool | None:
    """Принимает текст для активного pending-input (set_pending). Иначе пропускает."""
    chat_id = message.chat.id
    state = _pending_input.get(chat_id)
    if not state:
        return None

    kind = state.get("kind")
    text = (message.text or "").strip()

    if kind == "hr_contact":
        # TB-7.2: ответ на «Указать @HR» — сохранить контакт вручную.
        _pending_input.pop(chat_id, None)
        from bot_app.services.hr_card import hr_contact_display, save_manual_hr_contact
        from bot_app.services.menu_manager import after_hr
        from bot_app.storage import hr_pending

        account_id = None
        if message.from_user is not None:
            account = await resolve_account(user_id=message.from_user.id)
            account_id = account.id if account is not None else None
        if account_id is None:
            await message.answer("Сначала получи токен — «Токен авторизации».")
            return True

        key, err = await save_manual_hr_contact(
            text,
            vacancy_id=str(state.get("vacancy_id") or ""),
            company=str(state.get("company") or ""),
            position=str(state.get("position") or ""),
            account_id=account_id,
        )
        if key is None:
            # Ошибка ввода — снова ждём контакт, не теряем контекст.
            set_pending(chat_id, "hr_contact", **{k: v for k, v in state.items() if k != "kind"})
            await message.answer(esc(err or "Не понял контакт."), parse_mode="HTML")
            return True

        # Обновим analysis в hr_pending (если токен ещё жив) — на случай повторного resolve.
        token = str(state.get("token") or "")
        if token:
            ctx = await hr_pending.get(token, account_id=account_id)
            if ctx is not None:
                updated = hr_pending.PendingHrContext(
                    analysis=ctx.analysis.model_copy(update={"hr_link": key}),
                    pending_resolve_vacancy_id=ctx.pending_resolve_vacancy_id,
                    telegram_msg_id=ctx.telegram_msg_id,
                    chat_id=ctx.chat_id,
                    created_at=ctx.created_at,
                )
                await hr_pending.put(token, updated, account_id=account_id)

        vid = str(state.get("vacancy_id") or "")
        label = esc(hr_contact_display(key))
        if vid:
            body = f"Контакт сохранён: <b>{label}</b> → вакансия <code>{esc(vid)}</code>."
        else:
            body = (
                f"Контакт принят: <b>{label}</b>. "
                "Вакансия не привязана — укажи id в переписке или подтверди кнопкой."
            )
        await message.answer(body, parse_mode="HTML")
        await show_menu_for(message, after_hr(vid))
        return True

    if kind == "add_account_token":
        # «Привязать другой Telegram»: текст — токен уже существующего аккаунта.
        _pending_input.pop(chat_id, None)
        from bot_app.services.account_link import link_telegram_account

        if message.from_user is None:
            return True

        outcome = await link_telegram_account(
            raw_token=text,
            user_id=message.from_user.id,
            chat_id=chat_id,
            username=message.from_user.username,
        )
        if not outcome.ok:
            body = {
                "not_found": _ADD_ACCOUNT_NOT_FOUND,
                "already_linked": _ADD_ACCOUNT_ALREADY_LINKED,
                "conflict": _ADD_ACCOUNT_CONFLICT,
            }[outcome.reason or "not_found"]
            await message.answer(body)
            # Свой же токен / путаница «куда вставлять» — сразу ткнём на сайт.
            if outcome.reason == "already_linked" and message.bot is not None:
                await _send_site_pin(message.bot, chat_id)
                await _send_token_next_steps(message.bot, chat_id)
        else:
            await message.answer("Готово — этот Telegram теперь тоже открывает тот же аккаунт.")

        account = outcome.account or await resolve_account(user_id=message.from_user.id)
        home = idle() if account is not None and account.role == "owner" else member_home()
        await show_menu_for(message, home)
        return True

    return None


__all__ = ["router", "has_pending", "set_pending", "pop_pending", "consume_pending_if"]
