"""Э0.2: подсказки городов — пустой агрегат не падает."""

from __future__ import annotations

from api.routers.meta.meta import _city_item, _own_city_names
from core.domains.opportunities.jobs import list_seen_work_cities


class _EmptyDb:
    async def fetch(self, sql: str, *args: object):  # noqa: ARG002
        return []


async def test_list_seen_work_cities_empty_aggregate() -> None:
    assert await list_seen_work_cities(account_id=1, db=_EmptyDb()) == []


async def test_own_city_names_without_account() -> None:
    assert await _own_city_names(None) == []


def test_city_item_known_and_unknown() -> None:
    moscow = _city_item("Москва", "jobs")
    assert moscow.city == "Москва"
    assert moscow.country == "Россия"
    assert moscow.timezone == "Europe/Moscow"
    assert moscow.utc_offset == "UTC+3"
    assert moscow.overlap_emea is not None

    unknown = _city_item("Хогвартс", "resume")
    assert unknown.city == "Хогвартс"
    assert unknown.country == ""
    assert unknown.timezone == ""
    assert unknown.source == "resume"
