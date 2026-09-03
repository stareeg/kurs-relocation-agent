"""Короткие подписи ленты действий вакансии — без rationale и прочих LLM-текстов."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from api.schemas.jobs import VacancyActivityEvent, VacancyActivityHistory
from core.domains.opportunities.activity import (
    debrief_items,
    funnel_items,
    hr_view_item,
    interview_items,
    merge_activity,
    offer_item,
    score_fallback,
    score_items,
    skip_item,
)


def _ts(hour: int) -> datetime:
    return datetime(2026, 8, 25, hour, 0, tzinfo=UTC)


def test_funnel_labels_are_transitions_not_essays() -> None:
    items = funnel_items(
        [
            (1, "Просмотр", "scoring", _ts(10)),
            (2, "Отклик", "api_kanban", _ts(11)),
            (3, "Отклик", "api_kanban", _ts(12)),  # повтор той же стадии — шум
            (4, "Скрининг", "hh_negotiations", _ts(13)),
        ]
    )
    assert [it.label for it in items] == [
        "Просмотр",
        "Просмотр → Отклик",
        "Отклик → Скрининг",
    ]


def test_auto_apply_label_is_short() -> None:
    items = funnel_items(
        [
            (1, "Просмотр", "scoring", _ts(10)),
            (2, "Отклик", "auto_apply_hh", _ts(11)),
        ]
    )
    assert items[-1].label == "Просмотр → автоотклик"


def test_score_labels_skip_rationale_and_zero_delta_dupes() -> None:
    items = score_items(
        [
            (3, 63, 6, "hr_confirmed", _ts(12)),
            (2, 57, 0, "hr_confirmed", _ts(11)),
            (1, 57, 0, "jd_only", _ts(10)),
        ]
    )
    labels = [it.label for it in items]
    assert labels == ["Скор 57", "Скор 57 → 63 · HR"]
    assert all("потому что" not in it.label for it in items)
    assert all(len(it.label) < 40 for it in items)


def test_score_fallback_when_no_revisions() -> None:
    items = score_fallback(68, _ts(9))
    assert [it.label for it in items] == ["Скор 68"]
    assert score_fallback(None, _ts(9)) == []


def test_skip_uses_canonical_not_long_reason() -> None:
    short = skip_item(
        reason="очень длинное объяснение модели почему не стоит подавать на эту роль",
        canonical="Низкая зарплата",
        at=_ts(14),
        row_id=9,
    )
    assert short is not None
    assert short.label == "Пропущено · Низкая зарплата"
    long_only = skip_item(
        reason="очень длинное объяснение модели почему не стоит подавать на эту роль",
        canonical=None,
        at=_ts(14),
    )
    assert long_only is not None
    assert long_only.label == "Пропущено"


def test_interview_debrief_offer_hr_view_are_terse() -> None:
    interview = interview_items([(1, "hr_screening", _ts(15))])
    debrief = debrief_items([(2, "tech", _ts(16))])
    offer = offer_item(_ts(17))
    viewed = hr_view_item(_ts(18))
    assert interview[0].label == "Этап: HR-скрининг"
    assert debrief[0].label == "Разбор: Техничка"
    assert offer is not None and offer.label == "Оффер"
    assert viewed is not None and viewed.label == "HR открыл резюме"


def test_activity_item_maps_to_transport_schema() -> None:
    """Регрессия 500: без from_attributes непустая лента валится на VacancyActivityEvent."""
    items = score_fallback(68, _ts(9))
    assert items, "нужен непустой список — пустой как раз маскировал 500"

    with pytest.raises(ValidationError):
        VacancyActivityEvent.model_validate(items[0])

    history = VacancyActivityHistory.from_items("vac-1", items)
    assert history.vacancy_id == "vac-1"
    assert history.items[0].id == "score:current"
    assert history.items[0].label == "Скор 68"
    assert history.items[0].at == _ts(9)


def test_merge_newest_first_and_drops_nones() -> None:
    items = merge_activity(
        funnel_items([(1, "Просмотр", "scoring", _ts(10))]),
        [hr_view_item(None), offer_item(_ts(12))],
        score_fallback(70, _ts(11)),
    )
    assert [it.kind for it in items] == ["offer", "score", "funnel"]
