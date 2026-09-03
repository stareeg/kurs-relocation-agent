"""In-memory двойник identity-слоя (Этап 2/Part C): `core.platform.repo.accounts` +
`core.domains.profile.web_auth`.

`accounts` — корневая identity-таблица (RLS-фундамент §1 плана хостинга): её публичные
функции идут напрямую в SQL, не через `get_setting`/`set_setting`, поэтому старый приём
«подменить `get_setting`/`set_setting` словарём» для владельца/токена входа больше не
работает. `FakeAccountsStore` подменяет собой ПУБЛИЧНУЮ поверхность этих модулей
(`issue_web_auth_token`, `get_owner_account`, `upsert_account`, …) — тесты остаются plain
unit-тестами (CLAUDE.md: «~70 test files, no DB fixtures»), а не живым Postgres.

Part C: токен входа больше не колонка `accounts`, а строка отдельной `account_sessions` —
у аккаунта может быть несколько одновременно активных сессий. `self._sessions` — тот же
in-memory аналог, `SessionRecord`/`IssuedWebAuthToken` берутся из настоящего `web_auth`
(чистые dataclass/Pydantic-модели, без побочных эффектов — переиспользовать безопасно).

Поведенческие тесты самого SQL (RLS, реальные колонки/таблицы) — `tests/test_rls_accounts.py`
и `@pytest.mark.db`-тесты в `tests/test_web_auth.py`, не здесь.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from core.platform.repo.accounts import AccountRecord


class FakeAccountsStore:
    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._next_id = 1
        # account_telegram_links: telegram_user_id -> account_id (Part B, «Добавить аккаунт»).
        self._links: dict[int, int] = {}
        # account_has_content: account_id -> bool, управляется тестом напрямую (по умолчанию
        # «пусто» — большинство тестов не заводят контентные таблицы).
        self._content: dict[int, bool] = {}
        # account_sessions (Part C): session_id -> row.
        self._sessions: dict[int, dict[str, Any]] = {}
        self._next_session_id = 1

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _record(self, row: dict[str, Any]) -> AccountRecord:
        # Только поля личности: заметка оператора и причина отключения живут в ряду,
        # но в AccountRecord не входят — иначе утекут в /auth/status и бот.
        return AccountRecord(
            id=row["id"],
            telegram_user_id=row["telegram_user_id"],
            telegram_username=row.get("telegram_username"),
            telegram_chat_id=row.get("telegram_chat_id"),
            role=row["role"],
            status=row["status"],
        )

    def _session_record(self, row: dict[str, Any]) -> Any:
        from core.domains.profile.web_auth import SessionRecord

        return SessionRecord(**row)

    # --- core.platform.repo.accounts surface ---

    async def get_account_by_id(self, account_id: int, *, db: Any = None) -> AccountRecord | None:
        _ = db
        row = self._rows.get(account_id)
        return self._record(row) if row else None

    async def get_account_by_telegram_user_id(
        self, telegram_user_id: int, *, db: Any = None
    ) -> AccountRecord | None:
        _ = db
        linked_account_id = self._links.get(telegram_user_id)
        if linked_account_id is not None:
            row = self._rows.get(linked_account_id)
            if row is not None:
                return self._record(row)
        for row in self._rows.values():
            if row["telegram_user_id"] == telegram_user_id:
                return self._record(row)
        return None

    async def link_telegram_identity(
        self,
        *,
        account_id: int,
        telegram_user_id: int,
        telegram_username: str | None = None,
        telegram_chat_id: int | None = None,
        db: Any = None,
    ) -> None:
        _ = db, telegram_username, telegram_chat_id
        self._links[telegram_user_id] = account_id

    def set_content(self, account_id: int, has_content: bool) -> None:
        """Тестовый рычаг для `account_has_content` — по умолчанию аккаунт «пуст»."""
        self._content[account_id] = has_content

    async def account_has_content(self, account_id: int, *, db: Any = None) -> bool:
        _ = db
        return self._content.get(account_id, False)

    async def get_owner_account(self, *, db: Any = None) -> AccountRecord | None:
        _ = db
        for row in self._rows.values():
            if row["role"] == "owner" and row["status"] == "active":
                return self._record(row)
        return None

    async def resolve_default_account_id(self, *, db: Any = None) -> int | None:
        owner = await self.get_owner_account(db=db)
        return owner.id if owner else None

    async def list_active_accounts(self, *, db: Any = None) -> list[AccountRecord]:
        _ = db
        rows = sorted(self._rows.values(), key=lambda r: r["id"])
        return [self._record(row) for row in rows if row["status"] == "active"]

    async def upsert_account(
        self,
        *,
        telegram_user_id: int,
        telegram_username: str | None = None,
        telegram_chat_id: int | None = None,
        role: str = "owner",
        db: Any = None,
    ) -> AccountRecord:
        _ = db
        for row in self._rows.values():
            if row["telegram_user_id"] == telegram_user_id:
                row["telegram_username"] = telegram_username
                if telegram_chat_id is not None:
                    row["telegram_chat_id"] = telegram_chat_id
                row["status"] = "active"
                return self._record(row)
        account_id = self._next_id
        self._next_id += 1
        row = {
            "id": account_id,
            "telegram_user_id": telegram_user_id,
            "telegram_username": telegram_username,
            "telegram_chat_id": telegram_chat_id,
            "role": role,
            "status": "active",
        }
        self._rows[account_id] = row
        return self._record(row)

    async def telegram_username_map(
        self, account: AccountRecord, *, db: Any = None
    ) -> dict[int, str | None]:
        _ = db
        mapping: dict[int, str | None] = {account.telegram_user_id: account.telegram_username}
        for telegram_user_id, linked_account_id in self._links.items():
            if linked_account_id == account.id:
                row = self._rows.get(linked_account_id)
                mapping[telegram_user_id] = row.get("telegram_username") if row else None
        return mapping

    async def disable_account(
        self, account_id: int, *, reason: str | None = None, db: Any = None
    ) -> None:
        _ = db
        if account_id in self._rows:
            self._rows[account_id]["status"] = "disabled"
            self._rows[account_id]["disabled_at"] = datetime.now(UTC)
            self._rows[account_id]["disabled_reason"] = (reason or "").strip() or None

    async def enable_account(self, account_id: int, *, db: Any = None) -> None:
        _ = db
        if account_id in self._rows:
            self._rows[account_id]["status"] = "active"
            self._rows[account_id]["disabled_at"] = None
            self._rows[account_id]["disabled_reason"] = None

    async def set_account_role(self, account_id: int, role: str, *, db: Any = None) -> None:
        _ = db
        if account_id in self._rows:
            self._rows[account_id]["role"] = role

    async def set_account_note(self, account_id: int, note: str, *, db: Any = None) -> None:
        _ = db
        if account_id in self._rows:
            self._rows[account_id]["note"] = note.strip() or None

    # --- core.domains.profile.web_auth surface (Part C: account_sessions) ---

    async def issue_web_auth_token(
        self,
        account_id: int,
        *,
        issued_via_telegram_user_id: int | None = None,
        db: Any = None,
        now: datetime | None = None,
    ) -> Any:
        from core.domains.profile.web_auth import IssuedWebAuthToken, generate_raw_token

        _ = db
        row = self._rows.get(account_id)
        if row is None:
            raise ValueError(f"web_auth: аккаунт account_id={account_id} не найден")
        now = now or datetime.now(UTC)
        raw = generate_raw_token()
        session_id = self._next_session_id
        self._next_session_id += 1
        self._sessions[session_id] = {
            "id": session_id,
            "account_id": account_id,
            "token_sha256": self._hash(raw),
            "issued_at": now,
            "revoked_at": None,
            "issued_via_telegram_user_id": issued_via_telegram_user_id,
            "login_user_agent": None,
            "login_ip": None,
        }
        return IssuedWebAuthToken(
            token=raw,
            account_id=account_id,
            telegram_user_id=row["telegram_user_id"],
            issued_at=now,
        )

    async def revoke_session_by_token(
        self, raw_token: str | None, *, db: Any = None, now: datetime | None = None
    ) -> bool:
        _ = db
        token = (raw_token or "").strip()
        if not token:
            return False
        needle = self._hash(token)
        for session in self._sessions.values():
            if session["revoked_at"] is None and secrets.compare_digest(
                session["token_sha256"], needle
            ):
                session["revoked_at"] = now or datetime.now(UTC)
                return True
        return False

    async def revoke_session(
        self, session_id: int, *, account_id: int, db: Any = None, now: datetime | None = None
    ) -> bool:
        _ = db
        session = self._sessions.get(session_id)
        if session is None or session["account_id"] != account_id or session["revoked_at"] is not None:
            return False
        session["revoked_at"] = now or datetime.now(UTC)
        return True

    async def revoke_all_sessions(
        self, account_id: int, *, db: Any = None, now: datetime | None = None
    ) -> int:
        _ = db
        when = now or datetime.now(UTC)
        count = 0
        for session in self._sessions.values():
            if session["account_id"] == account_id and session["revoked_at"] is None:
                session["revoked_at"] = when
                count += 1
        return count

    async def list_sessions(self, account_id: int, *, db: Any = None) -> list[Any]:
        _ = db
        sessions = [
            s
            for s in self._sessions.values()
            if s["account_id"] == account_id and s["revoked_at"] is None
        ]
        sessions.sort(key=lambda s: s["issued_at"], reverse=True)
        return [self._session_record(s) for s in sessions]

    async def get_last_issued_at(self, account_id: int, *, db: Any = None) -> datetime | None:
        _ = db
        issued_ats = [s["issued_at"] for s in self._sessions.values() if s["account_id"] == account_id]
        return max(issued_ats) if issued_ats else None

    async def record_login_metadata(
        self, raw_token: str, *, user_agent: str | None, ip: str | None, db: Any = None
    ) -> None:
        _ = db
        agent = (user_agent or "").strip() or None
        ip_value = (ip or "").strip() or None
        if agent is None and ip_value is None:
            return
        needle = self._hash(raw_token)
        for session in self._sessions.values():
            if session["token_sha256"] == needle:
                if session["login_user_agent"] is None:
                    session["login_user_agent"] = agent
                if session["login_ip"] is None:
                    session["login_ip"] = ip_value
                return

    async def any_web_auth_token_issued(self, *, db: Any = None) -> bool:
        _ = db
        return bool(self._sessions)

    async def token_ever_issued(self, raw_token: str | None, *, db: Any = None) -> bool:
        _ = db
        token = (raw_token or "").strip()
        if not token:
            return False
        needle = self._hash(token)
        return any(s["token_sha256"] == needle for s in self._sessions.values())

    async def list_active_sessions_with_accounts(self, *, db: Any = None) -> list[tuple[Any, AccountRecord]]:
        _ = db
        result: list[tuple[Any, AccountRecord]] = []
        for session in self._sessions.values():
            if session["revoked_at"] is not None:
                continue
            row = self._rows.get(session["account_id"])
            if row is None or row["status"] != "active":
                continue
            result.append((self._session_record(session), self._record(row)))
        return result

    async def find_account_by_raw_token(
        self, raw_token: str | None, *, db: Any = None
    ) -> AccountRecord | None:
        token = (raw_token or "").strip()
        if not token:
            return None
        needle = self._hash(token)
        for session, account in await self.list_active_sessions_with_accounts(db=db):
            if secrets.compare_digest(session.token_sha256, needle):
                return account
        return None

    async def adopt_portable_token(
        self, raw_token: str, identity: Any, *, db: Any = None, now: datetime | None = None
    ) -> AccountRecord:
        account = await self.upsert_account(
            telegram_user_id=identity.user_id, telegram_username=identity.username, db=db
        )
        now = now or datetime.now(UTC)
        await self.revoke_all_sessions(account.id, db=db, now=now)
        session_id = self._next_session_id
        self._next_session_id += 1
        self._sessions[session_id] = {
            "id": session_id,
            "account_id": account.id,
            "token_sha256": self._hash(raw_token.strip()),
            "issued_at": now,
            "revoked_at": None,
            "issued_via_telegram_user_id": identity.user_id,
            "login_user_agent": None,
            "login_ip": None,
        }
        refreshed = await self.get_account_by_id(account.id, db=db)
        assert refreshed is not None
        return refreshed

    # --- core.domains.profile.telegram_link owner surface ---

    async def get_owner(self, *, db: Any = None) -> AccountRecord | None:
        return await self.get_owner_account(db=db)

    async def set_owner(
        self, *, user_id: int, chat_id: int, username: str | None = None, db: Any = None
    ) -> AccountRecord:
        return await self.upsert_account(
            telegram_user_id=user_id,
            telegram_username=username,
            telegram_chat_id=chat_id,
            role="owner",
            db=db,
        )

    async def unlink(self, *, db: Any = None) -> None:
        _ = db
        owner = await self.get_owner_account()
        if owner is not None:
            await self.disable_account(owner.id)

    # --- helpers для сборки фикстур ---

    def patch_accounts_module(self, monkeypatch: Any, module: Any) -> None:
        """`core.platform.repo.accounts` — там, где импортирован как модуль (`api.security` и т.п.).

        `raising=False`: разные модули импортируют разное подмножество имён (например,
        `api.security` берёт только `get_owner_account`) — недостающие тихо пропускаем.
        """
        for name, fn in (
            ("get_account_by_id", self.get_account_by_id),
            ("get_account_by_telegram_user_id", self.get_account_by_telegram_user_id),
            ("get_owner_account", self.get_owner_account),
            ("upsert_account", self.upsert_account),
            ("resolve_default_account_id", self.resolve_default_account_id),
            ("list_active_accounts", self.list_active_accounts),
            ("link_telegram_identity", self.link_telegram_identity),
            ("account_has_content", self.account_has_content),
            ("disable_account", self.disable_account),
            ("enable_account", self.enable_account),
            ("set_account_role", self.set_account_role),
            ("set_account_note", self.set_account_note),
            ("telegram_username_map", self.telegram_username_map),
        ):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, fn)

    def patch_web_auth_module(self, monkeypatch: Any, module: Any) -> None:
        """`core.domains.profile.web_auth` — функции, определённые прямо в модуле."""
        monkeypatch.setattr(module, "issue_web_auth_token", self.issue_web_auth_token)
        monkeypatch.setattr(module, "revoke_session_by_token", self.revoke_session_by_token)
        monkeypatch.setattr(module, "revoke_session", self.revoke_session)
        monkeypatch.setattr(module, "revoke_all_sessions", self.revoke_all_sessions)
        monkeypatch.setattr(module, "list_sessions", self.list_sessions)
        monkeypatch.setattr(module, "get_last_issued_at", self.get_last_issued_at)
        monkeypatch.setattr(module, "record_login_metadata", self.record_login_metadata)
        monkeypatch.setattr(module, "any_web_auth_token_issued", self.any_web_auth_token_issued)
        monkeypatch.setattr(module, "token_ever_issued", self.token_ever_issued)
        monkeypatch.setattr(
            module, "list_active_sessions_with_accounts", self.list_active_sessions_with_accounts
        )
        monkeypatch.setattr(module, "find_account_by_raw_token", self.find_account_by_raw_token)
        monkeypatch.setattr(module, "adopt_portable_token", self.adopt_portable_token)

    def patch_telegram_link_module(self, monkeypatch: Any, module: Any) -> None:
        """`core.domains.profile.telegram_link` — часть про владельца (`get_owner`/`set_owner`)."""
        monkeypatch.setattr(module, "get_owner_account", self.get_owner_account)
        monkeypatch.setattr(module, "upsert_account", self.upsert_account)
        monkeypatch.setattr(module, "disable_account", self.disable_account)

    def patch_account_link_module(self, monkeypatch: Any, module: Any) -> None:
        """`bot_app.services.account_link` — импортирует функции напрямую (`from ... import
        X`), поэтому патчить надо ИМЕННО этот модуль, не `core.platform.repo.accounts`/`web_auth`
        (иначе патч не долетит — имя уже связано со старым объектом на момент импорта)."""
        monkeypatch.setattr(module, "find_account_by_raw_token", self.find_account_by_raw_token)
        monkeypatch.setattr(module, "account_has_content", self.account_has_content)
        monkeypatch.setattr(module, "disable_account", self.disable_account)
        monkeypatch.setattr(module, "link_telegram_identity", self.link_telegram_identity)


__all__ = ["FakeAccountsStore"]
