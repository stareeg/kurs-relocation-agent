"""Тесты resolve_job_source_group с habr — бывшая точка «создать test_job_source_group.py» (Шаг 6)."""

from __future__ import annotations

from core.domains.opportunities.jobs import (
    SOURCE_GROUP_HABR,
    SOURCE_GROUPS_ORDER,
    resolve_job_source_group,
)


def test_resolve_source_habr():
    """source='habr' прямо → SOURCE_GROUP_HABR."""
    assert resolve_job_source_group("habr") == SOURCE_GROUP_HABR


def test_resolve_vacancy_id_habr():
    """vacancy_id с префиксом habr_ → SOURCE_GROUP_HABR."""
    assert resolve_job_source_group(None, "habr_1000164602") == SOURCE_GROUP_HABR
    assert resolve_job_source_group("", "habr_1000164602") == SOURCE_GROUP_HABR


def test_resolve_habr_before_hh_fallback():
    """habr_ не попадает в hh-фолбэк по digits — префикс имеет приоритет."""
    assert resolve_job_source_group(None, "habr_1000164602") == SOURCE_GROUP_HABR


def test_source_groups_order_contains_habr():
    """SOURCE_GROUPS_ORDER включает habr в детерминированном порядке."""
    assert SOURCE_GROUP_HABR in SOURCE_GROUPS_ORDER
    # Порядок: hh < getmatch < habr < telegram
    idx_hh = SOURCE_GROUPS_ORDER.index("hh")
    idx_gm = SOURCE_GROUPS_ORDER.index("getmatch")
    idx_habr = SOURCE_GROUPS_ORDER.index("habr")
    idx_tg = SOURCE_GROUPS_ORDER.index("tg")
    assert idx_hh < idx_gm < idx_habr < idx_tg