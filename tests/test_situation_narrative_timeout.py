"""UX2-10.2 (plans/ui_polish_2.md): «Разобрать ситуацию» крутилась бесконечно.

Два независимых фикса:
1. `api/routers/market/narrative.py` — `except RuntimeError` стоял ПОСЛЕ `except Exception`,
   поэтому был недостижим (порядок веток исправлен).
2. `core.domains.market.situation` — `gather_situation_facts` (4 последовательных сырых
   DB-запроса) теперь обёрнут в `asyncio.wait_for`, зависший сбор фактов падает с понятной
   ошибкой вместо бесконечного висения.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.routers.market.narrative as narrative_router
import core.domains.market.situation as situation
from api.security import AccountContext


def _plain_request() -> SimpleNamespace:
    """Заглушка `Request` без `Accept: text/event-stream` — плоский JSON-путь роутера."""
    return SimpleNamespace(headers={})


_FAKE_ACCOUNT = AccountContext(
    account_id=1, telegram_user_id=1, telegram_username=None, role="owner"
)


async def test_runtime_error_maps_to_pg_unavailable_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(**_kw) -> None:
        raise RuntimeError("Postgres pool не инициализирован")

    monkeypatch.setattr(narrative_router, "generate_situation_narrative", boom)

    with pytest.raises(HTTPException) as exc_info:
        await narrative_router.make_situation(_plain_request(), account=_FAKE_ACCOUNT)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Postgres недоступен для сводки"


class _UnrelatedError(Exception):
    pass


async def test_generic_exception_still_falls_through_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(**_kw) -> None:
        raise _UnrelatedError("что-то незапланированное")

    monkeypatch.setattr(narrative_router, "generate_situation_narrative", boom)

    with pytest.raises(HTTPException) as exc_info:
        await narrative_router.make_situation(_plain_request(), account=_FAKE_ACCOUNT)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Не удалось сгенерировать сводку"


async def test_timeout_error_maps_to_clear_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(**_kw) -> None:
        raise TimeoutError("Сбор данных для сводки завис дольше 45с (БД?)")

    monkeypatch.setattr(narrative_router, "generate_situation_narrative", boom)

    with pytest.raises(HTTPException) as exc_info:
        await narrative_router.make_situation(_plain_request(), account=_FAKE_ACCOUNT)

    assert exc_info.value.status_code == 503
    assert "завис" in exc_info.value.detail


async def test_gather_facts_hang_raises_timeout_with_clear_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hangs_forever(*, account_id=None, db=None, settings=None):  # noqa: ANN001
        await asyncio.sleep(3600)

    monkeypatch.setattr(situation, "gather_situation_facts", hangs_forever)
    monkeypatch.setattr(situation, "_FACTS_TIMEOUT_S", 0.05)
    monkeypatch.setattr(
        situation, "get_settings", lambda: type("S", (), {"openrouter_api_key": "x"})()
    )

    with pytest.raises(TimeoutError, match="завис"):
        await situation.generate_situation_narrative(account_id=1)
