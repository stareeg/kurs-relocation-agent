"""Общая инфраструктура для кросс-аккаунтных RLS-тестов (plan §6 M0, §7,
plans/multitenancy_gaps_2026_08_06.md): фикстура «два аккаунта» + `assert_isolated` — так, чтобы
ретрофит очередной таблицы в M1..M9 добавлял три строки в свой тестовый файл, а не копировал
весь boilerplate (`_make_account`/`db`-фикстуру/teardown), как до сих пор делали пять
tests/test_rls_*.py по отдельности.

Использование в новом M-этапе::

    import pytest
    from tests.rls_isolation import assert_isolated, two_accounts

    pytestmark = pytest.mark.db

    async def test_offers_isolated(two_accounts):
        account_a, account_b = two_accounts
        await assert_isolated(
            account_a=account_a,
            account_b=account_b,
            insert_as_a=lambda c: c.execute(
                "insert into offers (account_id, vacancy_id, ...) values ($1, $2, ...)",
                account_a, "vac-1",
            ),
            visible_to_b=lambda c: c.fetch("select account_id from offers"),
        )

Существующие tests/test_rls_*.py не переписаны на этот хелпер этим этапом — они уже работают
и не блокируют M0 («полдня, ничего не ломает», план §6); новые M-этапы используют хелпер сразу.
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import Executor, TimingPool, close_pool, get_pool, init_pool

# tests/test_rls_*.py уже заняли 999_000_0xx..999_000_4xx под свои ручные фикстуры (см. их
# файлы) — этот общий хелпер живёт в отдельном диапазоне, чтобы параллельные прогоны разных
# файлов не путали sentinel-аккаунты друг друга по telegram_user_id.
_TG_ID_COUNTER = itertools.count(999_000_501)


async def _make_account(pool: TimingPool, telegram_user_id: int) -> int:
    return await pool.fetchval(
        "insert into accounts (telegram_user_id, role) values ($1, 'member') returning id",
        telegram_user_id,
    )


@pytest.fixture
async def two_accounts() -> AsyncIterator[tuple[int, int]]:
    """`(account_a_id, account_b_id)` — свежие sentinel-аккаунты, удаляются после теста.

    Требует живой Postgres — файл теста должен сам выставить `pytestmark = pytest.mark.db`
    (см. `tests/test_rls_accounts.py` про запуск: `uv run pytest -m db ...`).
    """
    pool = await init_pool()
    tg_a, tg_b = next(_TG_ID_COUNTER), next(_TG_ID_COUNTER)
    account_a = await _make_account(pool, tg_a)
    account_b = await _make_account(pool, tg_b)
    try:
        yield account_a, account_b
    finally:
        await pool.execute(
            "delete from accounts where telegram_user_id = any($1::bigint[])", [tg_a, tg_b]
        )
        await close_pool()


async def assert_isolated(
    *,
    account_a: int,
    account_b: int,
    insert_as_a: Callable[[Executor], Awaitable[Any]],
    visible_to_b: Callable[[Executor], Awaitable[list[Any]]],
) -> None:
    """Вставить строку под аккаунтом A через `account_scope`, убедиться, что B её не видит.

    `visible_to_b` обычно `lambda c: c.fetch("select * from <table>")` БЕЗ ручного WHERE —
    именно отсутствие фильтра в тесте и проверяет, что защищает сама RLS-политика, а не тест.
    """
    async with account_scope(account_a) as scoped:
        await insert_as_a(scoped)

    async with account_scope(account_b) as scoped:
        rows = await visible_to_b(scoped)
        assert rows == [], (
            f"account B видит {len(rows)} чужих строк — RLS-политика не режет или не включена"
        )


async def assert_app_admin_bypasses(
    *, visible: Callable[[Executor], Awaitable[list[Any]]], expected_min_rows: int = 1
) -> None:
    """`app_admin` (BYPASSRLS, план §1) обязан видеть строки всех аккаунтов — фоновые системные
    задачи (GC вложений, маркет-агрегация, миграции) идут под ним, а не под `account_scope`."""
    conn = await get_pool().acquire()
    try:
        await conn.execute("set role app_admin")
        rows = await visible(conn)
        assert len(rows) >= expected_min_rows, (
            f"app_admin увидел {len(rows)} строк, ожидали ≥{expected_min_rows} — BYPASSRLS не работает?"
        )
    finally:
        await conn.execute("reset role")
        await get_pool().release(conn)


__all__ = ["assert_app_admin_bypasses", "assert_isolated", "two_accounts"]
