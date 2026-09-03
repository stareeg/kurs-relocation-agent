"""S13: `_negotiation_job_source` распознаёт площадочные префиксы откликов —
`habr_*` → SOURCE_HABR (аналог уже существующего `gm_*` → SOURCE_GETMATCH), иначе
hh_negotiations-фолбэк."""

from __future__ import annotations

from core.domains.opportunities.jobs import (
    SOURCE_GETMATCH,
    SOURCE_HABR,
    SOURCE_HH_NEGOTIATIONS,
)
from core.domains.pipeline.negotiations import _negotiation_job_source


def test_habr_prefix_maps_to_habr_source() -> None:
    assert _negotiation_job_source("habr_1000164602") == SOURCE_HABR
    assert _negotiation_job_source("habr_42") == SOURCE_HABR


def test_getmatch_prefix_maps_to_getmatch_source() -> None:
    assert _negotiation_job_source("gm_123") == SOURCE_GETMATCH


def test_plain_id_falls_back_to_hh_negotiations() -> None:
    assert _negotiation_job_source("135719770") == SOURCE_HH_NEGOTIATIONS
    assert _negotiation_job_source("") == SOURCE_HH_NEGOTIATIONS
