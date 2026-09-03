"""S-05 (`plans/skills_2026_07_28.md`): ручки — GET/PATCH снимка, single-flight пересборки."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from core.domains.profile.model import ResumeData
from core.domains.profile.skill_suggest import (
    SkillSnapshot,
    SkillSuggestionRow,
    _input_fingerprint,
    load_skills_panel,
    refresh_snapshot,
    save_snapshot,
    set_user_state,
)
from core.domains.profile.skills_corpus import SelectionVacancy
from core.platform.cache.single_flight import SingleFlight, set_single_flight_for_tests


def _resume(key_skills: list[str]) -> ResumeData:
    data = ResumeData()
    data.key_skills = key_skills
    data.position.title = "Backend developer"
    return data


def _vac(vacancy_id: str) -> SelectionVacancy:
    return SelectionVacancy(
        vacancy_id=vacancy_id, title="Backend", company="Ozon", text="", score=60, status="Отклик"
    )


def _fake_read_resume_data(data: ResumeData):
    """Фейк `read_resume_data_for_account` (async, account-aware) с фиксированным ответом."""

    async def _fake(account_id, *, db=None):
        return data

    return _fake


class FakeDb:
    """Двойник Executor для снимков навыков: шапка + строки + обновление `user_state`."""

    def __init__(self) -> None:
        self._snapshots: list[dict[str, Any]] = []
        self._rows: dict[int, list[dict[str, Any]]] = {}
        self._next_snapshot_id = 1
        self._next_row_id = 1

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if query.startswith("select id, skill from resume_skill_suggestions"):
            snapshot_id = args[0]
            return [{"id": r["id"], "skill": r["skill"]} for r in self._rows.get(snapshot_id, [])]
        if "resume_skill_suggestions" in query:
            snapshot_id = args[0]
            return list(self._rows.get(snapshot_id, []))
        raise NotImplementedError(query)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "insert into resume_skill_snapshots" in query:
            _account_id, input_fp, resume_fp, corpus_size, selection_rule, vacancy_ids = args
            snapshot_id = self._next_snapshot_id
            self._next_snapshot_id += 1
            row = {
                "id": snapshot_id,
                "input_fp": input_fp,
                "resume_fp": resume_fp,
                "corpus_size": corpus_size,
                "selection_rule": selection_rule,
                "vacancy_ids": vacancy_ids,
                "created_at": None,
            }
            self._snapshots.append(row)
            self._rows[snapshot_id] = []
            return row
        if "insert into resume_skill_suggestions" in query:
            (
                _account_id,
                snapshot_id,
                skill,
                state,
                renames_to,
                importance,
                demand_count,
                demand_total,
                companies,
                rationale,
                user_state,
            ) = args
            row = {
                "id": self._next_row_id,
                "skill": skill,
                "state": state,
                "renames_to": renames_to,
                "importance": importance,
                "demand_count": demand_count,
                "demand_total": demand_total,
                "companies": companies,
                "rationale": rationale,
                "user_state": user_state,
                "state_at": None,
            }
            self._next_row_id += 1
            self._rows[snapshot_id].append(row)
            return row
        if query.startswith("select id from resume_skill_snapshots"):
            return {"id": self._snapshots[-1]["id"]} if self._snapshots else None
        if "from resume_skill_snapshots" in query:
            return self._snapshots[-1] if self._snapshots else None
        if query.startswith("update resume_skill_suggestions"):
            target_id, user_state = args
            for rows in self._rows.values():
                for row in rows:
                    if row["id"] == target_id:
                        row["user_state"] = user_state
                        row["state_at"] = datetime.now(UTC)
                        return dict(row)
            return None
        raise NotImplementedError(query)


# --- load_skills_panel: GET никогда не зовёт LLM, stale словами -----------------------------


async def test_load_skills_panel_cold_db_reports_no_selection(monkeypatch):
    async def fake_selection_corpus(*, db=None, **_kw):
        return []

    async def fake_describe_selection(*, db=None, **_kw):
        return "0 вакансий: скор >= 55 или в работе, без пропущенных"

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.describe_selection", fake_describe_selection
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.read_resume_data_for_account",
        _fake_read_resume_data(_resume([])),
    )

    panel = await load_skills_panel(account_id=1, db=FakeDb())

    assert panel.rows == []
    assert panel.stale is True
    assert panel.stale_reason == "нет вакансий выборки"
    assert panel.corpus_size == 0


async def test_load_skills_panel_no_snapshot_yet(monkeypatch):
    selection = [_vac("v1")]

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_describe_selection(*, db=None, **_kw):
        return "1 вакансия"

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.describe_selection", fake_describe_selection
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.read_resume_data_for_account",
        _fake_read_resume_data(_resume(["Python"])),
    )

    panel = await load_skills_panel(account_id=1, db=FakeDb())

    assert panel.stale is True
    assert "снимок ещё не собран" in panel.stale_reason
    assert panel.slots_used == 1


async def test_load_skills_panel_fresh_snapshot_matches_fingerprint(monkeypatch):
    selection = [_vac("v1")]
    key_skills = ["Python"]

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_describe_selection(*, db=None, **_kw):
        return "1 вакансия"

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.describe_selection", fake_describe_selection
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.read_resume_data_for_account",
        _fake_read_resume_data(_resume(key_skills)),
    )

    db = FakeDb()
    fp = _input_fingerprint(key_skills, selection)
    await save_snapshot(
        SkillSnapshot(input_fp=fp, corpus_size=1, selection_rule="1 вакансия", rows=[]),
        account_id=1,
        db=db,
    )

    panel = await load_skills_panel(account_id=1, db=db)

    assert panel.stale is False
    assert panel.stale_reason == ""


async def test_load_skills_panel_stale_names_new_vacancies_count(monkeypatch):
    # Снимок был по одной вакансии, выборка выросла до двух — причина называет число,
    # а не общую фразу «данные изменились».
    selection = [_vac("v1"), _vac("v2")]

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_describe_selection(*, db=None, **_kw):
        return "2 вакансии"

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.describe_selection", fake_describe_selection
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.read_resume_data_for_account",
        _fake_read_resume_data(_resume(["Python"])),
    )

    db = FakeDb()
    await save_snapshot(
        SkillSnapshot(
            input_fp="stale-fp",
            corpus_size=1,
            selection_rule="1 вакансия",
            vacancy_ids=["v1"],
            rows=[],
        ),
        account_id=1,
        db=db,
    )

    panel = await load_skills_panel(account_id=1, db=db)

    assert panel.stale is True
    assert panel.stale_reason == "+1 вакансия с последнего разбора — нажми «Пересобрать»"


async def test_load_skills_panel_stale_names_resume_change_when_no_new_vacancies(monkeypatch):
    # Тот же состав выборки, но `key_skills` резюме сдвинулся с последнего снимка — причина
    # должна называть резюме, а не выдумывать «+0 вакансий».
    selection = [_vac("v1")]

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_describe_selection(*, db=None, **_kw):
        return "1 вакансия"

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.describe_selection", fake_describe_selection
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.read_resume_data_for_account",
        _fake_read_resume_data(_resume(["Go"])),
    )

    db = FakeDb()
    await save_snapshot(
        SkillSnapshot(
            input_fp="stale-fp",
            corpus_size=1,
            selection_rule="1 вакансия",
            vacancy_ids=["v1"],
            rows=[],
        ),
        account_id=1,
        db=db,
    )

    panel = await load_skills_panel(account_id=1, db=db)

    assert panel.stale is True
    assert panel.stale_reason == "резюме изменилось с последнего разбора — нажми «Пересобрать»"


# --- refresh_snapshot: двойной клик - один прогон (single-flight) ----------------------


async def test_refresh_snapshot_double_call_runs_once(monkeypatch):
    set_single_flight_for_tests(SingleFlight())
    try:
        calls = {"n": 0}
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_build_snapshot(*, account_id=None, data=None, db=None, llm=None):
            calls["n"] += 1
            started.set()
            await release.wait()
            return SkillSnapshot(input_fp="fp", corpus_size=0, selection_rule="", rows=[])

        monkeypatch.setattr(
            "core.domains.profile.skill_suggest.build_snapshot", fake_build_snapshot
        )

        db = FakeDb()
        t1 = asyncio.create_task(refresh_snapshot(account_id=1, db=db))
        t2 = asyncio.create_task(refresh_snapshot(account_id=1, db=db))
        await started.wait()
        await asyncio.sleep(0.02)
        assert calls["n"] == 1
        release.set()
        results = await asyncio.gather(t1, t2)
        assert calls["n"] == 1
        assert results[0].id == results[1].id
    finally:
        set_single_flight_for_tests(None)


# --- set_user_state: «скрыть»/«вернуть» переживает перезагрузку (Решение 6) ------------------


async def test_set_user_state_hides_row_by_canon():
    db = FakeDb()
    await save_snapshot(
        SkillSnapshot(
            input_fp="fp",
            corpus_size=1,
            selection_rule="rule",
            rows=[SkillSuggestionRow(skill="vLLM", state="add", demand_count=3, demand_total=5)],
        ),
        account_id=1,
        db=db,
    )

    updated = await set_user_state("vllm", "hidden", account_id=1, db=db)

    assert updated is not None
    assert updated.skill == "vLLM"
    assert updated.user_state == "hidden"


async def test_set_user_state_unknown_skill_returns_none():
    db = FakeDb()
    await save_snapshot(
        SkillSnapshot(
            input_fp="fp",
            corpus_size=1,
            selection_rule="rule",
            rows=[SkillSuggestionRow(skill="vLLM", state="add", demand_count=3, demand_total=5)],
        ),
        account_id=1,
        db=db,
    )

    assert await set_user_state("Nonexistent Skill", "hidden", account_id=1, db=db) is None


async def test_set_user_state_no_snapshot_returns_none():
    assert await set_user_state("vLLM", "hidden", account_id=1, db=FakeDb()) is None
