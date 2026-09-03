"""S-04 (`plans/skills_2026_07_28.md`): снимок навыков — мои + разрывы в одной таблице."""

from __future__ import annotations

from typing import Any

from core.domains.opportunities.models import SkillRequirement
from core.domains.profile.ats_fit import HH_KEY_SKILLS_LIMIT
from core.domains.profile.model import ResumeData
from core.domains.profile.skill_suggest import (
    MAX_ACTIONS,
    SkillActionLlm,
    SkillDemand,
    SkillSnapshot,
    SkillSuggestionRow,
    SkillSuggestLlm,
    build_demand,
    build_snapshot,
    clamp_actions,
    load_latest_snapshot,
    save_snapshot,
)
from core.domains.profile.skills_corpus import SelectionVacancy
from tests.fakes import FakeLlm


def _vac(vacancy_id: str, company: str = "Ozon") -> SelectionVacancy:
    return SelectionVacancy(
        vacancy_id=vacancy_id, title="Backend", company=company, text="", score=60, status="Отклик"
    )


def _resume(key_skills: list[str]) -> ResumeData:
    data = ResumeData()
    data.key_skills = key_skills
    data.position.title = "Backend developer"
    return data


class FakeDb:
    """Двойник Executor: своя таблица `vacancy_skill_requirements` + снимки навыков в памяти."""

    def __init__(self, requirements: dict[str, list[SkillRequirement]] | None = None) -> None:
        self._requirements = requirements or {}
        self._snapshots: list[dict[str, Any]] = []
        self._rows: dict[int, list[dict[str, Any]]] = {}
        self._next_snapshot_id = 1
        self._next_row_id = 1

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "vacancy_skill_requirements" in query:
            ids = args[0]
            return [
                {"vacancy_id": vid, "skills": [s.model_dump(mode="json") for s in reqs]}
                for vid, reqs in self._requirements.items()
                if vid in ids
            ]
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
        if "from resume_skill_snapshots" in query:
            return self._snapshots[-1] if self._snapshots else None
        raise NotImplementedError(query)


# --- build_demand (агрегат спроса) --------------------------------------------------------


def test_build_demand_canonicalizes_writing_across_vacancies():
    # v1 пишет «k8s», v2 - «Kubernetes» (S-02 уже дедупит внутри одной вакансии; здесь спрос
    # должен схлопнуть разные написания одной вакансии в один навык на канон S-03).
    selection = [_vac("v1", "Ozon"), _vac("v2", "Avito")]
    reqs = {
        "v1": [SkillRequirement(skill="k8s", importance="preferred")],
        "v2": [SkillRequirement(skill="Kubernetes", importance="required")],
    }
    demand = build_demand(selection, reqs)
    assert len(demand) == 1
    d = demand[0]
    assert d.skill == "Kubernetes"
    assert d.demand_count == 2
    assert d.importance == "required"  # required хоть в одной вакансии - required агрегата
    assert d.companies == ["Ozon", "Avito"]


def test_build_demand_counts_vacancy_once_even_with_duplicate_canon_in_input():
    # Защитный случай: если апстрим всё же прислал канон-дубль внутри одной вакансии
    # (обычно уже дедупит сам), спрос не должен посчитать вакансию дважды.
    selection = [_vac("v1", "Ozon")]
    reqs = {
        "v1": [
            SkillRequirement(skill="k8s", importance="preferred"),
            SkillRequirement(skill="Kubernetes", importance="preferred"),
        ],
    }
    demand = build_demand(selection, reqs)
    assert len(demand) == 1
    assert demand[0].demand_count == 1


def test_build_demand_sorted_by_demand_desc():
    selection = [_vac("v1"), _vac("v2"), _vac("v3")]
    reqs = {
        "v1": [SkillRequirement(skill="Python", importance="required")],
        "v2": [SkillRequirement(skill="Python", importance="required")],
        "v3": [SkillRequirement(skill="Go", importance="required")],
    }
    demand = build_demand(selection, reqs)
    assert [d.skill for d in demand] == ["Python", "Go"]


# --- clamp_actions (постпроцессинг) ---------------------------------------------------------


def _demand(skill: str, count: int = 5) -> SkillDemand:
    return SkillDemand(skill=skill, demand_count=count, importance="required", companies=["Ozon"])


def test_clamp_actions_add_ignores_out_of_candidate_list():
    add_candidates = {"vllm": _demand("vLLM")}
    actions = [SkillActionLlm(skill="Something Else", action="add")]
    rows = clamp_actions(
        actions,
        add_candidates=add_candidates,
        drop_candidates={},
        demand_total=10,
        current_count=5,
    )
    assert rows == []


def test_clamp_actions_drop_is_zero_demand():
    drop_candidates = {
        "apache spark": SkillDemand(skill="Apache Spark", demand_count=0, importance="preferred")
    }
    actions = [SkillActionLlm(skill="Apache Spark", action="drop", rationale="не требует никто")]
    rows = clamp_actions(
        actions,
        add_candidates={},
        drop_candidates=drop_candidates,
        demand_total=10,
        current_count=30,
    )
    assert len(rows) == 1
    assert rows[0].state == "drop"
    assert rows[0].demand_count == 0


def test_clamp_actions_add_blocked_at_full_slots_without_drop():
    add_candidates = {"vllm": _demand("vLLM")}
    actions = [SkillActionLlm(skill="vLLM", action="add")]
    rows = clamp_actions(
        actions,
        add_candidates=add_candidates,
        drop_candidates={},
        demand_total=10,
        current_count=HH_KEY_SKILLS_LIMIT,
    )
    assert rows == []  # 30/30, drop нет -> add не показывается вовсе (Решение 7)


def test_clamp_actions_add_allowed_when_paired_with_drop():
    add_candidates = {"vllm": _demand("vLLM")}
    drop_candidates = {
        "apache spark": SkillDemand(skill="Apache Spark", demand_count=0, importance="preferred")
    }
    actions = [
        SkillActionLlm(skill="Apache Spark", action="drop"),
        SkillActionLlm(skill="vLLM", action="add"),
    ]
    rows = clamp_actions(
        actions,
        add_candidates=add_candidates,
        drop_candidates=drop_candidates,
        demand_total=10,
        current_count=HH_KEY_SKILLS_LIMIT,
    )
    states = {r.skill: r.state for r in rows}
    assert states == {"Apache Spark": "drop", "vLLM": "add"}


def test_clamp_actions_caps_total_at_max_actions():
    add_candidates = {f"skill{i}".casefold(): _demand(f"Skill{i}") for i in range(12)}
    actions = [SkillActionLlm(skill=f"Skill{i}", action="add") for i in range(12)]
    rows = clamp_actions(
        actions,
        add_candidates=add_candidates,
        drop_candidates={},
        demand_total=10,
        current_count=0,
    )
    assert len(rows) <= MAX_ACTIONS


def test_clamp_actions_rename_pairs_drop_candidate_with_add_candidate():
    add_candidates = {"vector database": _demand("Vector Database")}
    drop_candidates = {
        "векторная бд stub": SkillDemand(
            skill="Векторная бд stub", demand_count=0, importance="preferred"
        )
    }
    actions = [
        SkillActionLlm(skill="Векторная бд stub", action="rename", renames_to="Vector Database"),
    ]
    rows = clamp_actions(
        actions,
        add_candidates=add_candidates,
        drop_candidates=drop_candidates,
        demand_total=10,
        current_count=5,
    )
    assert len(rows) == 1
    assert rows[0].state == "rename"
    assert rows[0].renames_to == "Vector Database"


def test_clamp_actions_no_duplicate_add_of_existing_key_skill():
    # Кандидат на добавление никогда не пересекается с key_skills резюме - _add_candidates уже
    # исключил их по канону, здесь только страховка, что рендж-кейс не проходит незаметно.
    rows = clamp_actions(
        [SkillActionLlm(skill="Python", action="add")],
        add_candidates={},  # Python не в кандидатах — уже есть в резюме
        drop_candidates={},
        demand_total=10,
        current_count=5,
    )
    assert rows == []


# --- build_snapshot (сквозной прогон) ------------------------------------------------------


async def test_build_snapshot_have_rows_use_canon_and_actions_capped(monkeypatch):
    selection = [_vac(f"v{i}") for i in range(10)]
    requirements = {
        v.vacancy_id: [SkillRequirement(skill="Kubernetes", importance="required")]
        for v in selection
    }
    db = FakeDb(requirements)

    async def fake_selection_corpus(*, db=None, **_kw):
        return selection

    async def fake_describe_selection(*, db=None, **_kw):
        return "10 вакансий: скор >= 55 или в работе, без пропущенных"

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.describe_selection", fake_describe_selection
    )

    data = _resume(["k8s"])  # разное написание - должно схлопнуться в have по канону
    llm = FakeLlm(result=SkillSuggestLlm(actions=[]))
    snapshot = await build_snapshot(account_id=1, data=data, db=db, llm=llm)

    have = [r for r in snapshot.rows if r.state == "have"]
    assert len(have) == 1
    assert have[0].skill == "k8s"
    assert have[0].demand_count == 10
    actions = [r for r in snapshot.rows if r.state != "have"]
    assert len(actions) <= MAX_ACTIONS


async def test_build_snapshot_skips_llm_when_no_candidates(monkeypatch):
    async def fake_selection_corpus(*, db=None, **_kw):
        return []

    async def fake_describe_selection(*, db=None, **_kw):
        return "0 вакансий"

    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.load_selection_corpus", fake_selection_corpus
    )
    monkeypatch.setattr(
        "core.domains.profile.skill_suggest.describe_selection", fake_describe_selection
    )

    data = _resume([])
    db = FakeDb({})
    from tests.fakes import RaisingLlm

    snapshot = await build_snapshot(account_id=1, data=data, db=db, llm=RaisingLlm())

    assert snapshot.rows == []


# --- save_snapshot / load_latest_snapshot (персист + Решение 6) ---------------------------


async def test_save_and_load_snapshot_roundtrip():
    db = FakeDb()
    snapshot = SkillSnapshot(
        input_fp="fp1",
        corpus_size=5,
        selection_rule="5 вакансий",
        rows=[
            SkillSuggestionRow(skill="Python", state="have", demand_count=5, demand_total=5),
            SkillSuggestionRow(skill="vLLM", state="add", demand_count=3, demand_total=5),
        ],
    )
    saved = await save_snapshot(snapshot, account_id=1, db=db)
    assert saved.id == 1
    loaded = await load_latest_snapshot(account_id=1, db=db)
    assert loaded is not None
    assert {r.skill for r in loaded.rows} == {"Python", "vLLM"}


async def test_save_snapshot_carries_hidden_state_across_rebuild():
    db = FakeDb()
    first = SkillSnapshot(
        input_fp="fp1",
        corpus_size=5,
        selection_rule="rule",
        rows=[
            SkillSuggestionRow(
                skill="vLLM", state="add", demand_count=3, demand_total=5, user_state="hidden"
            )
        ],
    )
    await save_snapshot(first, account_id=1, db=db)

    second = SkillSnapshot(
        input_fp="fp2",
        corpus_size=6,
        selection_rule="rule",
        rows=[SkillSuggestionRow(skill="vLLM", state="add", demand_count=4, demand_total=6)],
    )
    saved = await save_snapshot(second, account_id=1, db=db)
    assert saved.rows[0].user_state == "hidden"
