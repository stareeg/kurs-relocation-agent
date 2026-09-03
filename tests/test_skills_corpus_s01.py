"""S-01 (`plans/skills_2026_07_28.md`): корпус выборки навыков — правило Решения 3."""

from __future__ import annotations

from core.domains.profile.model import ResumeData
from core.domains.profile.skills_corpus import (
    DEFAULT_MIN_SCORE,
    SelectionVacancy,
    build_selection_sql,
    describe_selection,
    load_min_score,
    load_selection_corpus,
)


class _FakeDb:
    """Двойник пула: возвращает заготовленные строки, запоминает SQL и параметры."""

    def __init__(self, rows: list[dict] | None = None, setting_value: object = None):
        self.rows = rows or []
        self.setting_value = setting_value
        self.queries: list[tuple[str, tuple]] = []

    async def fetch(self, query: str, *params):
        self.queries.append((query, params))
        return self.rows

    async def fetchrow(self, query: str, *params):
        if self.setting_value is None:
            return None
        return {"value": self.setting_value}


def _row(vacancy_id: str, score: int | None, status: str | None) -> dict:
    return {
        "vacancy_id": vacancy_id,
        "t": "Title",
        "c": "Company",
        "x": "текст вакансии" * 20,
        "overall_score": score,
        "status": status,
    }


def test_build_selection_sql_without_target_companies():
    sql, params = build_selection_sql(55, [], account_id=1)
    assert "company_canonical = any" not in sql
    assert params == [1, 55]
    assert "account_id = $1" in sql
    assert "overall_score >= $2" in sql
    assert "'Отклик'" in sql or "Отклик" in sql
    assert "not exists (select 1 from skipped_vacancies" in sql


def test_build_selection_sql_with_target_companies():
    sql, params = build_selection_sql(55, ["Сбербанк"], account_id=1)
    assert "company_canonical = any($3::text[])" in sql
    assert params == [1, 55, ["Сбербанк"]]


async def test_load_min_score_defaults_when_setting_missing():
    db = _FakeDb(setting_value=None)
    assert await load_min_score(account_id=1, db=db) == DEFAULT_MIN_SCORE


async def test_load_min_score_reads_app_settings_override():
    db = _FakeDb(setting_value=70)
    assert await load_min_score(account_id=1, db=db) == 70


async def test_load_selection_corpus_maps_rows():
    db = _FakeDb(rows=[_row("v1", 60, "Отклик")], setting_value=None)
    corpus = await load_selection_corpus(account_id=1, data=ResumeData(), db=db)
    assert corpus == [
        SelectionVacancy(
            vacancy_id="v1", title="Title", company="Company",
            text="текст вакансии" * 20, score=60, status="Отклик",
        )
    ]


async def test_describe_selection_reports_count_and_rule():
    db = _FakeDb(rows=[_row("v1", 60, "Отклик"), _row("v2", 40, "Отказ")], setting_value=55)
    text = await describe_selection(account_id=1, data=ResumeData(), db=db)
    assert text == "2 вакансии: скор ≥ 55 или в работе, без пропущенных"


async def test_describe_selection_plural_forms():
    db = _FakeDb(rows=[_row(str(i), 60, "Отклик") for i in range(11)], setting_value=55)
    text = await describe_selection(account_id=1, data=ResumeData(), db=db)
    assert text.startswith("11 вакансий:")
