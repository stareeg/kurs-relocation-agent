"""aiogram-фильтры бота: allowlist владельца и режимы ввода (задача 2.6)."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from bot_app.access import is_allowed_admin, resolve_account


class IsAdmin(BaseFilter):
    """Пропускает ОПЕРАТОРА: DB-owner (`accounts.role='owner'`) ∪ env-allowlist."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if user is None:
            return False
        return await is_allowed_admin(user_id=user.id, username=user.username)


class IsAccount(BaseFilter):
    """Пропускает любой активный АККАУНТ (owner ∪ member) — Этап 5, план §5: функции,
    доступные «любому активному аккаунту», не только оператору (например, карточки вакансий
    или пауза автооткликов). Не гейт для большинства хендлеров — те остаются на `IsAdmin` до
    отдельного ретрофита каждой доменной операции под произвольный account_id (план §9)."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if user is None:
            return False
        return await resolve_account(user_id=user.id) is not None


class IsForwarded(BaseFilter):
    """Пересланное сообщение (любой тип forward в Telegram)."""

    async def __call__(self, message: Message) -> bool:
        return bool(
            message.forward_origin
            or message.forward_from
            or message.forward_from_chat
            or message.forward_sender_name
        )


class IsHrText(BaseFilter):
    """Длинный текст от владельца — переписка, вставленная вручную (не команда)."""

    async def __call__(self, message: Message) -> bool:
        text = (message.text or message.caption or "").strip()
        if not text or text.startswith("/"):
            return False
        return len(text) >= 40


class IsSalaryCalibActive(BaseFilter):
    """Режим сбора вилок для калибровки (/calib on)."""

    async def __call__(self, message: Message) -> bool:
        from bot_app.storage import salary_calib_sessions

        return message.chat is not None and salary_calib_sessions.is_active(message.chat.id)


class IsVacancyChannelPost(BaseFilter):
    """Пересланный пост из Telegram-канала (не личка/группа) — вакансийный поток.

    Происхождение форварда — надёжный, бесплатный сигнал «пост из канала-агрегатора вакансий»,
    в отличие от текстовых эвристик: канал (не личный чат HR, не группа) значит, что это не ответ
    живого человека кандидату, а публикация в поток. `salary_calibration`/`IsSalaryCalibActive`
    регистрируется раньше `forwarded` — во время `/calib on` форварды уходят туда, сюда не попадают.

    Читает **только `forward_origin`** (Bot API 7.0+, декабрь 2023) — `forward_from_chat` полностью
    выведен из протокола и Telegram больше никогда его не заполняет (грабли GM-2: JS-17 изначально
    проверял именно `forward_from_chat`, из-за чего фильтр не срабатывал ни на одном живом форварде,
    хотя host-тесты были зелёными — они конструировали `Message` вручную с этим мёртвым полем).
    """

    async def __call__(self, message: Message) -> bool:
        origin = getattr(message, "forward_origin", None)
        return bool(origin is not None and getattr(origin, "type", None) == "channel")


# Официальный кандидатский бот getmatch.ru (t.me/g_jobbot, подтверждено на живых форвардах
# 2026-07-03 — GM-2 подшаг 2): посты не содержат домен "getmatch.ru" в тексте вовсе (карточка
# вакансии — чистый текст без ссылок, CTA-кнопки бота при форварде не переезжают), поэтому
# изначальная идея текстовой эвристики по домену (bottleneck_research_plan.md) не сработала на
# практике — распознаём по имени пользователя-отправителя форварда.
# Список username'ов берётся из .env (GETMATCH_BOT_USERNAMES) через BotSettings (H2).
def _getmatch_bot_usernames() -> set[str]:
    from bot_app.config import get_bot_settings

    return get_bot_settings().getmatch_bot_username_set()


def _forward_sender_username(message: Message) -> str | None:
    """Username отправителя форварда (сам бот-источник, не автор оригинала).

    Проверяет и новый `forward_origin.sender_user` (Bot API 7.0+), и легаси `forward_from` —
    на живых данных GM-2 оба поля были заполнены для форварда из личного чата с ботом (в отличие
    от `forward_from_chat` для каналов, который Telegram больше не заполняет никогда).
    """
    origin = getattr(message, "forward_origin", None)
    if origin is not None and getattr(origin, "type", None) == "user":
        sender_user = getattr(origin, "sender_user", None)
        username = getattr(sender_user, "username", None)
        if username:
            return username
    user = getattr(message, "forward_from", None)
    return getattr(user, "username", None)


class IsGetmatchPost(BaseFilter):
    """Пересланный пост из Telegram-бота getmatch.ru — второй источник вакансий.

    getmatch раздаёт подборки через СВОЙ Telegram-бот в личке, а не через канал — origin такого
    форварда `type == "user"` (sender_user = сам бот), не `"channel"`, поэтому фильтр канала
    его не ловит (и не должен — это разные потоки). Основной сигнал — username бота-отправителя
    форварда (из `.env` через `BotSettings.getmatch_bot_username_set()`, H2); упоминание домена
    `getmatch.ru` в тексте — запасной сигнал на случай другого формата поста (сама ссылка на сайт).
    """

    async def __call__(self, message: Message) -> bool:
        if not await IsForwarded()(message):
            return False
        username = _forward_sender_username(message)
        if username and username.lower() in _getmatch_bot_usernames():
            return True
        text = (message.text or message.caption or "").strip()
        return "getmatch.ru" in text.lower()


class IsVacancyUrl(BaseFilter):
    """Прямая ссылка на вакансию hh/getmatch в тексте (не форвард) — TB-0.6 / B1.

    Короткий URL (`hh.ru/vacancy/123`) не проходит `IsHrText` (≥40 символов) и раньше
    падал в banter/fallback. Форварды не трогаем: канал / getmatch-бот / HR — свои фильтры.
    """

    async def __call__(self, message: Message) -> bool:
        if await IsForwarded()(message):
            return False
        text = (message.text or message.caption or "").strip()
        if not text or text.startswith("/"):
            return False
        from core.domains.opportunities.jobs import extract_getmatch_numeric_id_from_text
        from core.domains.opportunities.sources.habr import extract_habr_numeric_id_from_text
        from core.domains.pipeline.vacancy_links import extract_primary_vacancy_id

        if extract_primary_vacancy_id(text):
            return True
        if extract_habr_numeric_id_from_text(text):
            return True
        return extract_getmatch_numeric_id_from_text(text) is not None


class IsHrInput(BaseFilter):
    """Пересланное HR-сообщение или вставленная переписка (вход HR-пайплайна S11).

    Не перехватываем, когда активна калибровка зарплат — у её роутера приоритет.
    Self-debrief отсекает сам обработчик до HR-парсера.
    """

    async def __call__(self, message: Message) -> bool:
        if message.chat is None:
            return False
        from bot_app.storage import salary_calib_sessions

        if salary_calib_sessions.is_active(message.chat.id):
            return False
        if await IsForwarded()(message):
            return True
        return await IsHrText()(message)
