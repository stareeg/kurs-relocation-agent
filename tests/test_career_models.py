"""R-32: модели домена career валидируются (без БД)."""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from core.domains.career import PortfolioItem, TimelineEvent
from core.domains.career.models import TimelineKind


def test_portfolio_item_defaults() -> None:
    p = PortfolioItem(project="Multi-agent RAG", role="Lead", outcome="p95 < 2s")
    assert p.artifact_url == ""
    assert p.source_ref == ""


def test_timeline_event_kinds() -> None:
    e = TimelineEvent(kind="offer", title="Оффер от X", source_ref="vac-1")
    assert e.kind == "offer"
    assert e.payload == {}


def test_career_literal_unions_cover_migration_checks() -> None:
    """Literals моделей ↔ CHECK в 0150_drop_career_goals_relocation (синхро-якорь)."""
    assert set(get_args(TimelineKind)) == {
        "application",
        "stage",
        "offer",
        "job_start",
        "promotion",
        "project",
        "certificate",
        "relocation",
        "other",
        "search_mode",
        "search_track",
    }


def test_empty_title_rejected() -> None:
    with pytest.raises(ValidationError):
        TimelineEvent(kind="other", title="")
