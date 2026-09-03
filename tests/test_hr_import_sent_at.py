"""Клампинг sent_at при разборе HR-дампа (баг «новое сообщение агента появляется в середине
переписки», см. core/domains/pipeline/hr_import.py::_parse_sent_at)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.domains.pipeline import hr_import


def test_parse_sent_at_keeps_past_date():
    dt = hr_import._parse_sent_at("2026-07-15T14:32:00+03:00")
    assert dt is not None
    assert dt.isoformat() == "2026-07-15T14:32:00+03:00"


def test_parse_sent_at_clamps_future_date_to_now():
    """LLM ошиблась с годом (см. системный промпт) и отдала дату в будущем — не доверяем."""
    future = datetime.now(UTC) + timedelta(days=400)
    dt = hr_import._parse_sent_at(future.isoformat())
    assert dt is not None
    assert dt <= datetime.now(UTC)


def test_parse_sent_at_none_stays_none():
    assert hr_import._parse_sent_at(None) is None
    assert hr_import._parse_sent_at("") is None
    assert hr_import._parse_sent_at("не дата") is None
