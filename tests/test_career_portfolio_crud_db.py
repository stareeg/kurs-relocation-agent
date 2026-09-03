"""`delete_portfolio_item` (Этап 5.0 редизайна «Карьеры», plans/career_redesign_2026_08_26.md).

Требует живой Postgres.
"""

from __future__ import annotations

import pytest

from core.domains.career.models import PortfolioItem
from core.domains.career.repo import delete_portfolio_item, insert_portfolio_item
from tests.rls_isolation import two_accounts

pytestmark = pytest.mark.db


async def test_delete_portfolio_item_removes_row_and_reports_true(two_accounts) -> None:
    account_a, _account_b = two_accounts
    item = await insert_portfolio_item(
        PortfolioItem(project="Удалить меня"), account_id=account_a
    )
    assert await delete_portfolio_item(item.id, account_id=account_a) is True
    assert await delete_portfolio_item(item.id, account_id=account_a) is False  # уже удалён


async def test_delete_portfolio_item_wrong_account_returns_false(two_accounts) -> None:
    account_a, account_b = two_accounts
    item = await insert_portfolio_item(PortfolioItem(project="Чужой элемент"), account_id=account_a)

    assert await delete_portfolio_item(item.id, account_id=account_b) is False
