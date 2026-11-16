"""U-0: видимость разделов интерфейса — умолчание режима курса и перекрытие из app_settings."""

from __future__ import annotations

from typing import Any

import pytest

from core.platform.repo.settings import COURSE_HIDDEN_SECTIONS, UI_SECTIONS, get_ui_features


class _FakeDb:
    def __init__(self, value: Any) -> None:
        self._value = value

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        assert "app_settings" in query
        assert args == ("ui_features",)
        return None if self._value is None else {"value": self._value}


@pytest.mark.asyncio
async def test_course_mode_by_default() -> None:
    features = await get_ui_features(db=_FakeDb(None))  # type: ignore[arg-type]
    assert set(features) == set(UI_SECTIONS)
    assert {k for k, v in features.items() if not v} == COURSE_HIDDEN_SECTIONS
    assert features["agent"] and features["jobs"] and features["resume"]


@pytest.mark.asyncio
async def test_override_from_app_settings() -> None:
    db = _FakeDb({"market": True, "agent": False, "unknown": True, "tech": "yes"})
    features = await get_ui_features(db=db)  # type: ignore[arg-type]
    assert features["market"] is True
    assert features["agent"] is False
    assert "unknown" not in features
    assert features["tech"] is False  # не bool — умолчание


@pytest.mark.asyncio
async def test_override_as_json_string() -> None:
    features = await get_ui_features(db=_FakeDb('{"career": true}'))  # type: ignore[arg-type]
    assert features["career"] is True
