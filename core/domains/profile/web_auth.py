"""Долгоживущий токен входа в веб, выдаваемый Telegram-ботом.

Токен — не колонка `accounts`, а строка отдельной таблицы `account_sessions`
(`core/platform/db/migrations/0108_account_sessions.sql`, Part C): у одного аккаунта может быть
НЕСКОЛЬКО одновременно активных сессий — по одной на устройство/браузер. Перевыпуск токена
(повторное нажатие «Токен авторизации» в боте) добавляет НОВУЮ сессию, не гасит старые — токен
нужен в первую очередь на случай поломки, а не как единственный способ входа с нового
устройства. Каждая сессия отзывается независимо (`revoke_session`/`revoke_session_by_token`) —
блок «Устройства» в Параметрах читает список через `list_sessions`, «Выйти на всех устройствах»
зовёт `revoke_all_sessions`.

В PG — только sha256, сырой токен уходит пользователю в Telegram. Отзыв (логаут из веба) не
удаляет запись, а ставит `revoked_at`: периметр остаётся закрытым, войти можно только новым
токеном из бота.

Переносимый токен («наш бот» один на всех): центральный бот не видит БД чужой
установки, поэтому гостю выдаётся самодостаточный токен `cc.<base64url(аккаунт)>.<секрет>`.
Свежая установка принимает его при логине и заводит/привязывает СВОЙ аккаунт (`role='owner'`
на этой установке) из токена; подписи нет — общего секрета между ботом и чужой установкой
не существует, предъявление токена = владение, что не слабее bootstrap-порога «свежая
установка открыта до первого токена». В отличие от обычных токенов, повторная адопция —
не «ещё одно устройство», а «то же самое браузер/install синхронизируется заново»: гасит
предыдущие сессии аккаунта, а не добавляется к ним (см. `adopt_portable_token`).

Модуль живёт в `profile` рядом с `telegram_link`: тем же кодом пользуются API и бот.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from core.platform.db.pool import Executor, get_pool, row_to_dict
from core.platform.repo.accounts import AccountRecord, get_account_by_id, upsert_account

logger = logging.getLogger(__name__)

# 24 байта → ~32 символа urlsafe: удобно копировать из Telegram одним тапом.
_TOKEN_NBYTES = 24

_SESSION_COLUMNS = (
    "id, account_id, token_sha256, issued_at, revoked_at, "
    "issued_via_telegram_user_id, login_user_agent, login_ip"
)
_SESSION_COLUMNS_S = (
    "s.id, s.account_id, s.token_sha256, s.issued_at, s.revoked_at, "
    "s.issued_via_telegram_user_id, s.login_user_agent, s.login_ip"
)
_ACCOUNT_COLUMNS_A = (
    "a.id as a_id, a.telegram_user_id as a_telegram_user_id, "
    "a.telegram_username as a_telegram_username, a.telegram_chat_id as a_telegram_chat_id, "
    "a.role as a_role, a.status as a_status"
)


class IssuedWebAuthToken(BaseModel):
    """Свежевыпущенный токен: сырое значение уходит только в сообщение бота, не в PG."""

    token: str
    account_id: int
    telegram_user_id: int
    issued_at: datetime


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Строка `account_sessions` — одно устройство/браузер (блок «Устройства», Part C)."""

    id: int
    account_id: int
    token_sha256: str
    issued_at: datetime
    revoked_at: datetime | None
    issued_via_telegram_user_id: int | None
    login_user_agent: str | None
    login_ip: str | None = None


def _session_from_row(row: object) -> SessionRecord | None:
    if row is None:
        return None
    return SessionRecord(**row_to_dict(row))  # type: ignore[arg-type]


def hash_token(raw_token: str) -> str:
    """sha256 сырого токена → hex (что храним в `account_sessions.token_sha256`)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_raw_token() -> str:
    """Сырой токен: `secrets.token_urlsafe` → только [A-Za-z0-9_-]."""
    return secrets.token_urlsafe(_TOKEN_NBYTES)


async def any_web_auth_token_issued(*, db: Executor | None = None) -> bool:
    """True, если хоть один токен хоть раз выпускался — глобальный флаг bootstrap.

    Не «активный», а «когда-либо выпущенный»: отозванная сессия не открывает периметр заново.
    Недоступный PG → False (аккаунты «не видны» → периметр открыт, как на свежей установке).
    """
    try:
        executor = db or get_pool()
        row = await executor.fetchrow("select 1 from account_sessions limit 1")
    except Exception as exc:
        logger.debug("web_auth: any_web_auth_token_issued недоступен: %s", exc)
        return False
    return row is not None


async def list_active_sessions_with_accounts(
    *, db: Executor | None = None
) -> list[tuple[SessionRecord, AccountRecord]]:
    """Все активные (не отозванные) сессии живых аккаунтов, с самим аккаунтом — то, что
    `api.security` кэширует на 15 с (hot path каждого запроса) и сверяет по хэшу токена.

    Аккаунтов/сессий мало (друзья, не публичная толпа) — линейный перебор с константным
    сравнением на запись безопаснее и проще, чем городить индекс по хэшу под одно сравнение.
    Недоступный PG → [] (см. `any_web_auth_token_issued`).
    """
    try:
        executor = db or get_pool()
        rows = await executor.fetch(
            f"select {_SESSION_COLUMNS_S}, {_ACCOUNT_COLUMNS_A} "
            "from account_sessions s join accounts a on a.id = s.account_id "
            "where s.revoked_at is null and a.status = 'active'"
        )
    except Exception as exc:
        logger.debug("web_auth: list_active_sessions_with_accounts недоступен: %s", exc)
        return []
    result: list[tuple[SessionRecord, AccountRecord]] = []
    for row in rows:
        data = row_to_dict(row)
        session = SessionRecord(
            id=data["id"],
            account_id=data["account_id"],
            token_sha256=data["token_sha256"],
            issued_at=data["issued_at"],
            revoked_at=data["revoked_at"],
            issued_via_telegram_user_id=data["issued_via_telegram_user_id"],
            login_user_agent=data["login_user_agent"],
            login_ip=data["login_ip"],
        )
        account = AccountRecord(
            id=data["a_id"],
            telegram_user_id=data["a_telegram_user_id"],
            telegram_username=data["a_telegram_username"],
            telegram_chat_id=data["a_telegram_chat_id"],
            role=data["a_role"],
            status=data["a_status"],
        )
        result.append((session, account))
    return result


async def find_account_by_raw_token(
    raw_token: str | None, *, db: Executor | None = None
) -> AccountRecord | None:
    """Свежая (мимо любого кэша) сверка токена — используется на логине, где токен из бота
    должен приниматься немедленно, а не через 15-секундное окно кэша `api.security`."""
    token = (raw_token or "").strip()
    if not token:
        return None
    needle = hash_token(token)
    for session, account in await list_active_sessions_with_accounts(db=db):
        if secrets.compare_digest(session.token_sha256, needle):
            return account
    return None


async def issue_web_auth_token(
    account_id: int,
    *,
    issued_via_telegram_user_id: int | None = None,
    db: Executor | None = None,
    now: datetime | None = None,
) -> IssuedWebAuthToken:
    """Выпустить токен входа для аккаунта — НОВАЯ сессия, прежние остаются активными (Part C:
    несколько устройств одновременно, перевыпуск не выкидывает другие браузеры)."""
    now = now or datetime.now(UTC)
    raw = generate_raw_token()
    db = db or get_pool()
    account_row = await db.fetchrow(
        "select telegram_user_id from accounts where id = $1", account_id
    )
    if account_row is None:
        raise ValueError(f"web_auth: аккаунт account_id={account_id} не найден")
    await db.execute(
        "insert into account_sessions "
        "(account_id, token_sha256, issued_at, issued_via_telegram_user_id) "
        "values ($1, $2, $3, $4)",
        account_id,
        hash_token(raw),
        now,
        issued_via_telegram_user_id,
    )
    logger.info("web_auth: выпущена сессия для account_id=%s", account_id)
    return IssuedWebAuthToken(
        token=raw,
        account_id=account_id,
        telegram_user_id=row_to_dict(account_row)["telegram_user_id"],
        issued_at=now,
    )


async def revoke_session_by_token(
    raw_token: str | None,
    *,
    db: Executor | None = None,
    now: datetime | None = None,
) -> bool:
    """Отозвать ОДНУ сессию — ту, что предъявлена cookie (логаут «с этого устройства»).
    True, если было что отзывать. Запись не удаляем — см. модульный докстринг."""
    token = (raw_token or "").strip()
    if not token:
        return False
    now = now or datetime.now(UTC)
    db = db or get_pool()
    row = await db.fetchrow(
        "update account_sessions set revoked_at = $2 "
        "where token_sha256 = $1 and revoked_at is null returning id",
        hash_token(token),
        now,
    )
    if row is not None:
        logger.info("web_auth: сессия id=%s отозвана (логаут)", row_to_dict(row)["id"])
    return row is not None


async def revoke_session(
    session_id: int,
    *,
    account_id: int,
    db: Executor | None = None,
    now: datetime | None = None,
) -> bool:
    """Отозвать ОДНУ сессию по id, только если она принадлежит `account_id` (владелец не может
    погасить чужую сессию, подставив произвольный id) — `POST /auth/sessions/{id}/revoke`."""
    now = now or datetime.now(UTC)
    db = db or get_pool()
    row = await db.fetchrow(
        "update account_sessions set revoked_at = $3 "
        "where id = $1 and account_id = $2 and revoked_at is null returning id",
        session_id,
        account_id,
        now,
    )
    return row is not None


async def revoke_all_sessions(
    account_id: int,
    *,
    db: Executor | None = None,
    now: datetime | None = None,
) -> int:
    """Отозвать ВСЕ активные сессии аккаунта — «Выйти на всех устройствах» и адопция
    переносимого токена (`adopt_portable_token`). Возвращает число отозванных сессий."""
    now = now or datetime.now(UTC)
    db = db or get_pool()
    rows = await db.fetch(
        "update account_sessions set revoked_at = $2 "
        "where account_id = $1 and revoked_at is null returning id",
        account_id,
        now,
    )
    if rows:
        logger.info("web_auth: %d сессий(и) account_id=%s отозваны разом", len(rows), account_id)
    return len(rows)


async def list_sessions(account_id: int, *, db: Executor | None = None) -> list[SessionRecord]:
    """Активные сессии аккаунта, новые сверху — блок «Устройства» в Параметрах."""
    try:
        executor = db or get_pool()
        rows = await executor.fetch(
            f"select {_SESSION_COLUMNS} from account_sessions "
            "where account_id = $1 and revoked_at is null order by issued_at desc",
            account_id,
        )
    except Exception as exc:
        logger.debug("web_auth: list_sessions недоступен: %s", exc)
        return []
    return [s for row in rows if (s := _session_from_row(row)) is not None]


async def token_ever_issued(raw_token: str | None, *, db: Executor | None = None) -> bool:
    """Существует ли (когда-либо) сессия с этим токеном — активная или отозванная. Различает
    «токен отозван» vs «токен вообще никогда не существовал» в сообщении об ошибке логина
    (`api.routers.meta.auth.perform_token_login`)."""
    token = (raw_token or "").strip()
    if not token:
        return False
    try:
        executor = db or get_pool()
        row = await executor.fetchrow(
            "select 1 from account_sessions where token_sha256 = $1 limit 1", hash_token(token)
        )
    except Exception as exc:
        logger.debug("web_auth: token_ever_issued недоступен: %s", exc)
        return False
    return row is not None


async def get_last_issued_at(account_id: int, *, db: Executor | None = None) -> datetime | None:
    """Дата последнего выпуска токена (любая сессия, активная или нет) — источник cooldown
    в `bot_app.services.auth_token` (перевыпуск не чаще раза в час)."""
    try:
        executor = db or get_pool()
        row = await executor.fetchrow(
            "select max(issued_at) as last_issued_at from account_sessions where account_id = $1",
            account_id,
        )
    except Exception as exc:
        logger.debug("web_auth: get_last_issued_at недоступен: %s", exc)
        return None
    return row_to_dict(row)["last_issued_at"] if row is not None else None


async def has_completed_web_login(account_id: int, *, db: Executor | None = None) -> bool:
    """True, если хотя бы одна сессия уже обменивалась на cookie (есть login_user_agent/ip).

    Нужен cooldown токена в боте: пока человек ни разу не вошёл в веб, повторное нажатие
    «Токен» скорее «потерял сообщение», чем «плодит устройства» — перевыпускаем.
    """
    try:
        executor = db or get_pool()
        row = await executor.fetchrow(
            "select 1 from account_sessions "
            "where account_id = $1 and (login_user_agent is not null or login_ip is not null) "
            "limit 1",
            account_id,
        )
    except Exception as exc:
        logger.debug("web_auth: has_completed_web_login недоступен: %s", exc)
        return False
    return row is not None


async def record_login_metadata(
    raw_token: str, *, user_agent: str | None, ip: str | None, db: Executor | None = None
) -> None:
    """Best-effort: записать User-Agent и IP браузера в сессию при первом обмене токена на
    cookie (`perform_token_login`) — не выдумываем название устройства/гео, показываем то, что
    реально пришло в запросе. Не перезаписывает уже сохранённые значения (сессия — одно
    устройство, ни UA, ни IP не должны «мигрировать» между вкладками одного браузера)."""
    agent = (user_agent or "").strip()[:512] or None
    ip_value = (ip or "").strip() or None
    if agent is None and ip_value is None:
        return
    try:
        executor = db or get_pool()
        await executor.execute(
            "update account_sessions set "
            "login_user_agent = coalesce(login_user_agent, $2), "
            "login_ip = coalesce(login_ip, $3) "
            "where token_sha256 = $1",
            hash_token(raw_token),
            agent,
            ip_value,
        )
    except Exception as exc:  # noqa: BLE001 — декоративная подпись, не критичный путь
        logger.debug("web_auth: record_login_metadata недоступен: %s", exc)


# --- Переносимый токен ---

PORTABLE_PREFIX = "cc."

# Секрет короче обычного (24 байта → ~32 симв.) не делаем: 18 байт → 24 симв. urlsafe,
# полный токен с payload'ом всё равно длиннее — копируется из Telegram одним тапом.
_PORTABLE_SECRET_NBYTES = 18


class PortableTokenIdentity(BaseModel):
    """Аккаунт Telegram, зашитый в переносимый токен."""

    model_config = ConfigDict(extra="ignore")

    user_id: int
    username: str | None = None


def build_portable_token(*, user_id: int, username: str | None = None) -> str:
    """Собрать переносимый токен для гостя: `cc.<base64url({u,n})>.<секрет>`."""
    payload = {"u": user_id, "n": (username.lstrip("@") if username else None) or None}
    blob = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    return f"{PORTABLE_PREFIX}{blob}.{secrets.token_urlsafe(_PORTABLE_SECRET_NBYTES)}"


def parse_portable_token(raw: str | None) -> PortableTokenIdentity | None:
    """Разобрать переносимый токен; обычный токен бота / мусор → None."""
    token = (raw or "").strip()
    if not token.startswith(PORTABLE_PREFIX):
        return None
    parts = token.split(".")
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    blob = parts[1]
    try:
        data = json.loads(base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4)))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("u")
    if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
        return None
    name = data.get("n")
    username = name.strip().lstrip("@") if isinstance(name, str) and name.strip() else None
    return PortableTokenIdentity(user_id=uid, username=username or None)


async def adopt_portable_token(
    raw_token: str,
    identity: PortableTokenIdentity,
    *,
    db: Executor | None = None,
    now: datetime | None = None,
) -> AccountRecord:
    """Привязать установку к переносимому токену (bootstrap или ротация того же аккаунта).

    Заводит (или переиспользует) аккаунт этой установки под identity гостя — `role='owner'`,
    как и любая другая привязка до Этапа 5 (self-serve `/start` в боте, где `role='member'`
    станет реальным сценарием). В отличие от `issue_web_auth_token` (генерирует свой секрет и
    ДОБАВЛЯЕТ сессию), здесь в PG кладётся хэш САМОГО переносимого токена, а предыдущие сессии
    этого аккаунта гасятся: повторная адопция — не «ещё одно устройство», а то же самое
    браузер/install синхронизируется заново (см. модульный докстринг).
    """
    now = now or datetime.now(UTC)
    account = await upsert_account(
        telegram_user_id=identity.user_id,
        telegram_username=identity.username,
        db=db,
    )
    executor = db or get_pool()
    await revoke_all_sessions(account.id, db=executor, now=now)
    await executor.execute(
        "insert into account_sessions "
        "(account_id, token_sha256, issued_at, issued_via_telegram_user_id) "
        "values ($1, $2, $3, $4)",
        account.id,
        hash_token(raw_token.strip()),
        now,
        identity.user_id,
    )
    refreshed = await get_account_by_id(account.id, db=db)
    logger.info("web_auth: установка привязана к переносимому токену account_id=%s", account.id)
    assert refreshed is not None
    return refreshed


__all__ = [
    "PORTABLE_PREFIX",
    "IssuedWebAuthToken",
    "PortableTokenIdentity",
    "SessionRecord",
    "adopt_portable_token",
    "any_web_auth_token_issued",
    "build_portable_token",
    "find_account_by_raw_token",
    "generate_raw_token",
    "get_last_issued_at",
    "has_completed_web_login",
    "hash_token",
    "issue_web_auth_token",
    "list_active_sessions_with_accounts",
    "list_sessions",
    "parse_portable_token",
    "record_login_metadata",
    "revoke_all_sessions",
    "revoke_session",
    "revoke_session_by_token",
    "token_ever_issued",
]
