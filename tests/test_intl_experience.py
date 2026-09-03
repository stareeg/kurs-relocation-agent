"""Э1.2 слой 2: пост-обработка цитат снимка международного опыта."""

from __future__ import annotations

from core.domains.profile.international import (
    apply_experience_snapshot,
    derive_international_readiness,
)
from core.domains.profile.intl_experience import (
    IntlExperienceSnapshot,
    filter_quoted_fields,
)
from core.domains.profile.model import ResumeData


def test_invented_quotes_are_dropped() -> None:
    source = "Работал с заказчиками из EU, вёл документацию на английском."
    snap = IntlExperienceSnapshot(
        english_artifacts=["вёл документацию на английском", "выступал на QCon London"],
        timezone_experience=["overlap 4h EST", "с заказчиками из EU"],
    )
    cleaned = filter_quoted_fields(snap, source)
    assert cleaned.english_artifacts == ["вёл документацию на английском"]
    assert cleaned.timezone_experience == ["с заказчиками из EU"]


def test_snapshot_fills_only_empty_fields() -> None:
    base = derive_international_readiness(ResumeData())
    filled = apply_experience_snapshot(
        base,
        {
            "distributed_experience": True,
            "client_facing": True,
            "english_artifacts": ["docs in English"],
            "suggested_english_level": "B2",
        },
    )
    assert filled.distributed_experience is True
    assert filled.client_facing is True
    assert filled.english_artifacts == ["docs in English"]
    assert filled.suggested_english_level == "B2"
    assert filled.english_level == ""  # предложение, не запись

    already = base.model_copy(update={"english_artifacts": ["своё"]})
    kept = apply_experience_snapshot(already, {"english_artifacts": ["чужое"]})
    assert kept.english_artifacts == ["своё"]
