"""Резолвинг identity аккаунта.

Запросы здесь идут МИМО `account_scope()` — чтобы узнать, какой account_id ставить в
`app.account_id`, сначала нужно найти сам аккаунт, а RLS-политика без выставленного GUC
не отдаст ни строки (fail-closed, см. `core.platform.db.account_scope`). Соединение из
`get_pool()` работает под владельцем таблиц (`copilot`) и по умолчанию обходит RLS — этого
здесь достаточно и корректно: это тот же класс операций, что и системные подключения
`app_admin` (см. `core/platform/db/migrations/0095_accounts.sql`).

До появления self-serve `/start` в боте новый аккаунт создаётся только через привязку
Telegram-владельца — `upsert_account` поэтому по умолчанию заводит `role='owner'`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from core.platform.db.pool import Executor, get_pool, row_to_dict

Role = Literal["owner", "member"]

_COLUMNS = "id, telegram_user_id, telegram_username, telegram_chat_id, role, status"
_COLUMNS_A = "a.id, a.telegram_user_id, a.telegram_username, a.telegram_chat_id, a.role, a.status"

# Представительный (не исчерпывающий) набор «контентных» таблиц для account_has_content —
# используется только чтобы не молча стереть чужие данные при отвязке дубля («Добавить
# аккаунт», bot_app.services.account_link). Не все ~50 account_id-таблиц системы, осознанный
# компромисс: остальные — низкосигнальные (кэши/статистика), не то, что жалко потерять.
_CONTENT_TABLES = (
    "jobs",
    "hr_threads",
    "notes",
    "offers",
    "resumes",
    "interview_stages",
    "prep_sessions",
    "openrouter_key_requests",
    "career_facts",
)


@dataclass(frozen=True, slots=True)
class AccountRecord:
    """Строка `accounts` — личность инсталляции/пользователя (Этап 2).

    Токен входа больше не колонка этой строки (Part C, 0108_account_sessions.sql) — у аккаунта
    может быть несколько одновременно активных сессий, см. `core.domains.profile.web_auth`.
    """

    id: int
    telegram_user_id: int
    telegram_username: str | None
    telegram_chat_id: int | None
    role: Role
    status: str


def _record_from_row(row: object) -> AccountRecord | None:
    if row is None:
        return None
    return AccountRecord(**row_to_dict(row))  # type: ignore[arg-type]


async def get_account_by_id(account_id: int, *, db: Executor | None = None) -> AccountRecord | None:
    """Недоступный PG → None (как раньше `get_setting` тихо отдавал `default`, не 500)."""
    try:
        executor = db or get_pool()
        row = await executor.fetchrow(f"select {_COLUMNS} from accounts where id = $1", account_id)
    except Exception:
        return None
    return _record_from_row(row)


async def get_account_by_telegram_user_id(
    telegram_user_id: int, *, db: Executor | None = None
) -> AccountRecord | None:
    """Секондари-линк (`account_telegram_links`, «Добавить аккаунт») приоритетнее primary —
    это даёт свежепривязанному Telegram-id обойти собственный протухший (disabled) ряд
    `accounts` с тем же telegram_user_id, если он у него был раньше (bot_app.services.
    account_link). Недоступный PG → None (см. `get_account_by_id`)."""
    try:
        executor = db or get_pool()
        row = await executor.fetchrow(
            f"select {_COLUMNS_A} from account_telegram_links l "
            "join accounts a on a.id = l.account_id where l.telegram_user_id = $1",
            telegram_user_id,
        )
        if row is None:
            row = await executor.fetchrow(
                f"select {_COLUMNS} from accounts where telegram_user_id = $1", telegram_user_id
            )
    except Exception:
        return None
    return _record_from_row(row)


async def get_account_by_telegram_chat_id(
    telegram_chat_id: int, *, db: Executor | None = None
) -> AccountRecord | None:
    """M5 (plans/multitenancy_gaps_2026_08_06.md §6): резолв аккаунта по чату бота — для путей,
    где под рукой есть только `chat_id`, не `telegram_user_id` (де-факто изолированные по чату
    таблицы: tg_ui_messages, salary_calibration_*). Секондари-линк приоритетнее primary — см.
    `get_account_by_telegram_user_id`. Недоступный PG → None (см. `get_account_by_id`)."""
    try:
        executor = db or get_pool()
        row = await executor.fetchrow(
            f"select {_COLUMNS_A} from account_telegram_links l "
            "join accounts a on a.id = l.account_id where l.telegram_chat_id = $1",
            telegram_chat_id,
        )
        if row is None:
            row = await executor.fetchrow(
                f"select {_COLUMNS} from accounts where telegram_chat_id = $1", telegram_chat_id
            )
    except Exception:
        return None
    return _record_from_row(row)


async def get_owner_account(*, db: Executor | None = None) -> AccountRecord | None:
    """Единственный (пока) активный `role='owner'` — до Этапа 5 других способов стать
    аккаунтом нет. `status='disabled'` (после `telegram_link.unlink`) не считается: тот же
    telegram_user_id при повторной привязке реактивируется через `upsert_account`, а не
    остаётся невидимым мёртвым владельцем. Недоступный PG → None (см. `get_account_by_id`)."""
    try:
        executor = db or get_pool()
        row = await executor.fetchrow(
            f"select {_COLUMNS} from accounts where role = 'owner' and status = 'active' "
            "order by id limit 1"
        )
    except Exception:
        return None
    return _record_from_row(row)


async def list_active_accounts(*, db: Executor | None = None) -> list[AccountRecord]:
    """Все активные аккаунты (owner + member) — источник получателей для рассылок «всем»
    (M8, plans/multitenancy_gaps_2026_08_06.md §5.5/§3.13: `notify_account`/
    `broadcast_to_active_accounts`). Обычный select по `accounts`, не `account_telegram_links`
    — secondary-identity не заводят отдельных строк `accounts`, список активных аккаунтов от
    этого не меняется (см. M8 в плане). Недоступный PG → `[]` (см. `get_account_by_id`)."""
    try:
        executor = db or get_pool()
        rows = await executor.fetch(
            f"select {_COLUMNS} from accounts where status = 'active' order by id"
        )
    except Exception:
        return []
    records = [_record_from_row(row) for row in rows]
    return [r for r in records if r is not None]


async def resolve_default_account_id(*, db: Executor | None = None) -> int | None:
    """Аккаунт-по-умолчанию для путей без HTTP-контекста (бот/скрипты/фон).

    Этап 2 не ретрофитит доменные вызовы (scorer/rules/skill_suggest/…) на явный
    per-request account_id — это Этап 3, домен за доменом. До тех пор эти вызовы
    резолвят «текущий единственный аккаунт» (владелец) сами, здесь. `None`, если
    владельца ещё нет вообще (bootstrap) — вызывающая сторона тогда падает на
    app_settings (см. core.platform.repo.settings: account_id=None).
    """
    owner = await get_owner_account(db=db)
    return owner.id if owner is not None else None


async def upsert_account(
    *,
    telegram_user_id: int,
    telegram_username: str | None = None,
    telegram_chat_id: int | None = None,
    role: Role = "owner",
    db: Executor | None = None,
) -> AccountRecord:
    """Создать аккаунт, обновить username/chat_id уже существующего, или реактивировать
    отвязанный (`status='disabled'` после `telegram_link.unlink`) — повторная привязка того
    же telegram_user_id снова делает его видимым `get_owner_account()`.

    `role` не понижается/не повышается на update — `role='owner'` в проде ставится только
    один раз (первая привязка); повторный вызов для того же telegram_user_id (например,
    перевыпуск токена) не должен молча превратить владельца в member.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        f"""
        insert into accounts (telegram_user_id, telegram_username, telegram_chat_id, role)
        values ($1, $2, $3, $4)
        on conflict (telegram_user_id) do update set
            telegram_username = excluded.telegram_username,
            telegram_chat_id = coalesce(excluded.telegram_chat_id, accounts.telegram_chat_id),
            status = 'active'
        returning {_COLUMNS}
        """,
        telegram_user_id,
        telegram_username,
        telegram_chat_id,
        role,
    )
    record = _record_from_row(row)
    assert record is not None  # insert ... returning всегда отдаёт строку
    return record


async def disable_account(
    account_id: int, *, reason: str | None = None, db: Executor | None = None
) -> None:
    """Отвязка (`telegram_link.unlink`) и админ-консоль: `status='disabled'`.

    `reason` — почему оператор отключил (Этап 4.6). Отвязка Telegram причину не пишет.
    """
    db = db or get_pool()
    cleaned = (reason or "").strip() or None
    await db.execute(
        "update accounts set status = 'disabled', disabled_at = now(), "
        "disabled_reason = $2 where id = $1",
        account_id,
        cleaned,
    )


async def enable_account(account_id: int, *, db: Executor | None = None) -> None:
    """Вернуть `status='active'` без повторной привязки Telegram (админ-консоль).
    Сессии при отключении уже отозваны — нужен новый токен из бота. Причину гасим:
    иначе через полгода висит объяснение, которое больше не действует.
    """
    db = db or get_pool()
    await db.execute(
        "update accounts set status = 'active', disabled_at = null, "
        "disabled_reason = null where id = $1",
        account_id,
    )


async def set_account_role(account_id: int, role: Role, *, db: Executor | None = None) -> None:
    """Смена роли. Защита «последний owner» — в админ-сервисе, не здесь."""
    db = db or get_pool()
    await db.execute("update accounts set role = $2 where id = $1", account_id, role)


async def set_account_note(account_id: int, note: str, *, db: Executor | None = None) -> None:
    """Заметка оператора. Пустая строка стирает, не пишет пробелы."""
    db = db or get_pool()
    cleaned = note.strip() or None
    await db.execute("update accounts set note = $2 where id = $1", account_id, cleaned)


async def link_telegram_identity(
    *,
    account_id: int,
    telegram_user_id: int,
    telegram_username: str | None = None,
    telegram_chat_id: int | None = None,
    db: Executor | None = None,
) -> None:
    """«Добавить аккаунт» (bot_app.services.account_link): привязать ЕЩЁ один Telegram-id к
    уже существующему аккаунту (`account_telegram_links`), не заводя новый ряд `accounts`.
    `telegram_user_id unique` — переносит линк, если этот Telegram-id раньше был линком
    другого аккаунта (перепривязка при повторном «Добавить аккаунт» с новым токеном)."""
    db = db or get_pool()
    await db.execute(
        """
        insert into account_telegram_links
            (account_id, telegram_user_id, telegram_username, telegram_chat_id)
        values ($1, $2, $3, $4)
        on conflict (telegram_user_id) do update set
            account_id = excluded.account_id,
            telegram_username = excluded.telegram_username,
            telegram_chat_id = coalesce(
                excluded.telegram_chat_id, account_telegram_links.telegram_chat_id
            ),
            linked_at = now()
        """,
        account_id,
        telegram_user_id,
        telegram_username,
        telegram_chat_id,
    )


async def touch_last_seen(
    account_id: int,
    *,
    ip: str | None = None,
    db: Executor | None = None,
    now: datetime | None = None,
) -> None:
    """Отметить активность аккаунта — вызывается (throttled) на каждый аутентифицированный
    запрос из `api.security.touch_account_last_seen`. Заготовка под будущий admin-обзор «кто
    реально пользуется» и capacity planning, не бизнес-логика — недоступный PG тихо пропускаем,
    как и остальные функции этого модуля."""
    now = now or datetime.now(UTC)
    try:
        executor = db or get_pool()
        await executor.execute(
            "update accounts set last_seen_at = $2, "
            "last_seen_ip = coalesce($3, last_seen_ip) where id = $1",
            account_id,
            now,
            ip,
        )
    except Exception:
        pass


async def telegram_username_map(
    account: AccountRecord, *, db: Executor | None = None
) -> dict[int, str | None]:
    """{telegram_user_id: telegram_username} для ВСЕХ Telegram-identity аккаунта — primary
    (`accounts`) + secondary (`account_telegram_links`). Для честной подписи строки в списке
    устройств (блок «Устройства», Part C): `account_sessions.issued_via_telegram_user_id` может
    быть любой из них, не только primary."""
    mapping: dict[int, str | None] = {account.telegram_user_id: account.telegram_username}
    try:
        executor = db or get_pool()
        rows = await executor.fetch(
            "select telegram_user_id, telegram_username from account_telegram_links "
            "where account_id = $1",
            account.id,
        )
    except Exception:
        return mapping
    for row in rows:
        data = row_to_dict(row)
        mapping[data["telegram_user_id"]] = data["telegram_username"]
    return mapping


async def account_has_content(account_id: int, *, db: Executor | None = None) -> bool:
    """Есть ли у аккаунта хоть что-то в представительном наборе «контентных» таблиц
    (`_CONTENT_TABLES`) — гейт перед тихой отвязкой дубля в «Добавить аккаунт»
    (bot_app.services.account_link): пустой дубль гасим молча, непустой — не трогаем.
    Недоступный PG → True (fail-safe: лучше отказать в слиянии, чем молча погасить дубль,
    в котором на самом деле были данные, но мы их не увидели)."""
    checks = " or ".join(
        f"exists (select 1 from {table} where account_id = $1)" for table in _CONTENT_TABLES
    )
    try:
        executor = db or get_pool()
        row = await executor.fetchrow(f"select ({checks}) as has_content", account_id)
    except Exception:
        return True
    return bool(row_to_dict(row)["has_content"]) if row is not None else True


__all__ = [
    "AccountRecord",
    "Role",
    "account_has_content",
    "disable_account",
    "enable_account",
    "get_account_by_id",
    "get_account_by_telegram_chat_id",
    "get_account_by_telegram_user_id",
    "get_owner_account",
    "link_telegram_identity",
    "list_active_accounts",
    "set_account_note",
    "set_account_role",
    "telegram_username_map",
    "touch_last_seen",
    "upsert_account",
]
