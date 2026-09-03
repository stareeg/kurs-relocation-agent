"""`GET /api/debrief/stage-index` — по каким вакансиям/этапам расшифровка уже разобрана.

Рельс Скринингов/Техничек рисует по нему отметку на карточке вакансии. Раньше такой отметки не
было вовсе, и «вставлял я сюда расшифровку или нет» узнавалось только заходом в вакансию.
"""

from __future__ import annotations

import pytest

import api.routers.preparation.debrief as debrief_router
from api.security import AccountContext

_ACCOUNT = AccountContext(account_id=1, telegram_user_id=1, telegram_username=None, role="owner")


@pytest.fixture
def _pairs(monkeypatch):
    """Подменяет источник пар (vacancy_id, stage) — БД в юнит-тестах не поднимаем."""

    def _set(pairs: list[tuple[str, str]]) -> None:
        async def fake(*, account_id: int) -> list[tuple[str, str]]:
            assert account_id == _ACCOUNT.account_id
            return pairs

        monkeypatch.setattr(debrief_router.prep, "debrief_stage_index", fake)

    return _set


async def test_groups_stages_by_vacancy(_pairs) -> None:
    _pairs([("v-1", "theory"), ("v-1", "screening"), ("v-2", "screening")])
    result = await debrief_router.stage_index(account=_ACCOUNT)
    by_vacancy = {it.vacancy_id: it.stages for it in result.items}
    # Этапы отсортированы — порядок ответа не зависит от порядка строк в БД.
    assert by_vacancy == {"v-1": ["screening", "theory"], "v-2": ["screening"]}


async def test_empty_index_is_not_an_error(_pairs) -> None:
    _pairs([])
    assert (await debrief_router.stage_index(account=_ACCOUNT)).items == []


async def test_route_is_declared_before_vacancy_id_catch_all() -> None:
    """Иначе FastAPI матчит «stage-index» как vacancy_id и отдаёт пустую историю разборов."""
    paths = [getattr(r, "path", "") for r in debrief_router.router.routes]
    assert paths.index("/api/debrief/stage-index") < paths.index("/api/debrief/{vacancy_id}")
