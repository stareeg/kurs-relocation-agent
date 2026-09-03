"""RLS-контекст запроса.

`app.account_id` — session-level GUC, который читают RLS-политики account-скоуп таблиц
(`account_id = current_setting('app.account_id', true)::bigint`, fail-closed: не выставлен →
NULL → ни одна строка не проходит сравнение). `SET ROLE app_rls` обязателен рядом: без него
RLS ничего не значит — соединение по умолчанию работает под владельцем таблиц (`copilot`), а
владелец обходит RLS независимо от GUC (стандартное поведение Postgres, если не включён
`FORCE ROW LEVEL SECURITY`). `app_rls` — обычная роль без BYPASSRLS, заведена миграцией
0095_accounts.sql вместе с GRANT на account-скоуп таблицы.

Пока (Этап 1) ни один роутер и ни одна фоновая задача не зовут этот хелпер — только
`tests/test_rls_accounts.py`. Реальное подключение к `require_account`/роутерам — Этап 2/3.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from core.platform.db.pool import Executor, TimingPool, get_pool


@contextlib.asynccontextmanager
async def account_scope(
    account_id: int, *, pool: TimingPool | None = None
) -> AsyncIterator[Executor]:
    """Дать соединение, ограниченное аккаунтом `account_id`, на время блока `async with`.

    Соединение возвращается в пул в `finally` — если не сбросить роль и GUC до `release`,
    следующий не связанный с аккаунтом запрос на этом же pooled-соединении унаследует чужую
    личность (риск, явно отмеченный в плане).
    """
    pool = pool if pool is not None else get_pool()
    conn = await pool.acquire()
    try:
        await conn.execute("select set_config('app.account_id', $1, false)", str(account_id))
        await conn.execute("set role app_rls")
        yield conn
    finally:
        await conn.execute("reset role")
        await conn.execute("select set_config('app.account_id', '', false)")
        await pool.release(conn)


__all__ = ["account_scope"]
