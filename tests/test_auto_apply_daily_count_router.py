"""GET /api/pipeline/auto-apply/daily-count (2.7 + 8.2): счётчик обычно из application_stages,
но если площадка сегодня уже сигналила о СВОЁМ дневном лимите (platform_limit) — бюджет
считается исчерпанным тем же путём (count подтянут до cap), не заводя отдельную ручку у раннера.

2026-08-28: `cap` — жёсткий потолок площадки (`auto_apply_daily_hard_cap`), не ручка
пользователя (hh 150 / getmatch 30 / habr 30).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from api.routers.pipeline import auto_apply as router_mod
from api.security import AccountContext
from core.domains.pipeline.auto_apply.config import auto_apply_daily_hard_cap

_HH_CAP = auto_apply_daily_hard_cap("hh")


def _account() -> AccountContext:
    return AccountContext(account_id=1, telegram_user_id=1, telegram_username=None, role="owner")


@pytest.fixture(autouse=True)
def _no_db_real_apply_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """`daily_count` теперь отдаёт `last_real_apply_at` (серверный клок троттлинга) — в этих
    юнит-тестах БД нет, отдаём None."""
    monkeypatch.setattr(router_mod, "last_real_apply_at", AsyncMock(return_value=None))


async def test_normal_count_is_unaffected_when_not_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router_mod, "count_today", AsyncMock(return_value=2))
    monkeypatch.setattr(router_mod, "is_platform_limited_today", AsyncMock(return_value=False))

    result = await router_mod.daily_count("hh", account=_account())

    assert result.count == 2
    assert result.cap == _HH_CAP == 150
    assert result.remaining == _HH_CAP - 2


async def test_platform_limited_today_exhausts_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router_mod, "count_today", AsyncMock(return_value=2))
    monkeypatch.setattr(router_mod, "is_platform_limited_today", AsyncMock(return_value=True))

    result = await router_mod.daily_count("hh", account=_account())

    assert result.count == _HH_CAP
    assert result.remaining == 0


async def test_already_at_cap_does_not_call_platform_limit_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(router_mod, "count_today", AsyncMock(return_value=_HH_CAP))
    limited_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(router_mod, "is_platform_limited_today", limited_mock)

    result = await router_mod.daily_count("hh", account=_account())

    assert result.remaining == 0
    limited_mock.assert_not_called()
