"""Тесты авто-расчёта весов скоринга из резюме (F-?)."""

from __future__ import annotations

from core.domains.opportunities.auto_weights import (
    TUNABLE_KEYS,
    derive_auto_scoring_weights,
)
from core.domains.opportunities.score_breakdown import MANAGEMENT_WEIGHT, SALARY_WEIGHT
from core.domains.profile.model import DesiredPosition, ResumeData, SearchCriteria


def _weights(
    *, role_kind: str = "unknown", travel_is_dealbreaker: bool = False, **overrides
) -> dict:
    position = overrides.pop("position", None) or DesiredPosition()
    search = overrides.pop("search_criteria", None) or SearchCriteria()
    return derive_auto_scoring_weights(
        ResumeData(position=position, search_criteria=search),
        role_kind=role_kind,
        travel_is_dealbreaker=travel_is_dealbreaker,
    )


def test_auto_weights_sum_to_100_and_keep_salary_fixed():
    weights = _weights()
    assert sum(weights.values()) == 100
    assert weights["salary"] == SALARY_WEIGHT
    assert set(TUNABLE_KEYS) <= set(weights)


def test_management_weight_low_for_mixed_and_unknown_role_kind():
    """Этап 3 (§5 плана): mixed/unknown — ось «Управление» почти симметрична, база минимальная."""
    for role_kind in ("mixed", "unknown"):
        weights = _weights(role_kind=role_kind)
        assert sum(weights.values()) == 100
        assert weights["management"] < MANAGEMENT_WEIGHT


def test_management_weight_full_for_hands_on_and_management_role_kind():
    """Кандидат явно выбрал сторону — ось честно несёт полный вес."""
    for role_kind in ("hands_on", "management"):
        weights = _weights(role_kind=role_kind)
        assert sum(weights.values()) == 100
        assert weights["management"] == MANAGEMENT_WEIGHT


def test_management_base_frees_points_for_other_tunable_axes():
    """Освободившиеся баллы от низкой базы «Управления» уходят в остальной пул (Этап 4 их
    перераспределит явно в role_content; здесь — что они вообще не теряются впустую)."""
    mixed = _weights(role_kind="mixed")
    committed = _weights(role_kind="hands_on")
    other_keys = ("work_format", "grade_match", "role_content", "company")
    assert sum(mixed[k] for k in other_keys) > sum(committed[k] for k in other_keys)


def test_company_weight_rises_when_company_lists_present():
    empty = _weights()
    with_lists = _weights(search_criteria=SearchCriteria(target_companies=["Сбер"]))
    assert with_lists["company"] > empty["company"]


def test_work_format_weight_rises_when_schedule_set():
    plain = _weights()
    scheduled = _weights(position=DesiredPosition(schedule=["Удалённо"]))
    assert scheduled["work_format"] > plain["work_format"]


def test_role_weight_rises_with_categories_and_niches():
    plain = _weights()
    rich = _weights(
        position=DesiredPosition(categories=["Backend"]),
        search_criteria=SearchCriteria(niches=["LLM"]),
    )
    assert rich["role_content"] > plain["role_content"]


def test_empty_resume_reaches_defaults():
    weights = _weights()
    assert weights["work_format"] >= 0
    assert weights["grade_match"] >= 0
    assert weights["role_content"] >= 0
    assert weights["company"] >= 0


def test_role_content_weight_stays_in_target_range_regardless_of_role_kind():
    """Этап 4 §4.1: ориентир 25-30 из 100 (здесь: 22-30, диапазон базы+сигнала)."""
    for role_kind in ("hands_on", "management", "mixed", "unknown"):
        weights = _weights(role_kind=role_kind)
        assert 22 <= weights["role_content"] <= 30


def test_role_content_is_heaviest_axis_for_a_filled_resume():
    """§1.6 плана: единственная ось с доказанной предиктивной силой — должна стать тяжелее
    salary/work_format (20) при обычном, не крайне пустом резюме."""
    rich = dict(
        position=DesiredPosition(schedule=["Удалённо"], grade=["Senior"], categories=["Backend"]),
        search_criteria=SearchCriteria(niches=["LLM"], target_companies=["Сбер"]),
    )
    for role_kind in ("hands_on", "management", "mixed", "unknown"):
        weights = _weights(role_kind=role_kind, **rich)
        assert weights["role_content"] == max(weights.values())


def test_filled_resume_does_not_collapse_pool_weights_to_uniform():
    """Этап 5 §5.4, регресс на §1.5/D7: при полном резюме work_format/grade_match/company не
    должны стать одинаковыми — на проде так вырождалось в 17/16/16, «ось заполнена» переставало
    что-либо различать. Форма резюме близка к живому прод-снимку из §Живая проверка плана."""
    filled = _weights(
        role_kind="mixed",
        travel_is_dealbreaker=False,
        position=DesiredPosition(
            schedule=["Гибрид", "Удалённо"],
            grade=["Senior", "Lead"],
            employment="Полная занятость",
            categories=["Data & ML", "Analytics", "Top Management"],
        ),
        search_criteria=SearchCriteria(
            niches=["MLOps/LLMOps", "LLM & RAG", "Agentic AI"],
            target_companies=[f"Компания {i}" for i in range(10)],
            avoid_companies=[f"Изб. компания {i}" for i in range(5)],
        ),
    )
    pool = (filled["work_format"], filled["grade_match"], filled["company"])
    assert len(set(pool)) > 1
    assert sum(filled.values()) == 100


def test_schedule_specificity_beats_broad_schedule():
    """Этап 5 §5.4: одна отмеченная опция (строгое требование) весит больше, чем все три
    (кандидату всё равно) — раньше count-формула считала наоборот."""
    narrow = _weights(position=DesiredPosition(schedule=["Удалённо"]))
    broad = _weights(position=DesiredPosition(schedule=["Офис", "Гибрид", "Удалённо"]))
    assert narrow["work_format"] > broad["work_format"]


def test_travel_dealbreaker_raises_work_format_priority():
    """Этап 5 §5.4: явное стоп-условие по командировкам — конкретный dealbreaker-сигнал,
    поднимает приоритет формата отдельно от того, насколько узко выбран schedule."""
    plain = _weights(position=DesiredPosition(schedule=["Удалённо", "Гибрид"]))
    with_dealbreaker = _weights(
        position=DesiredPosition(schedule=["Удалённо", "Гибрид"]), travel_is_dealbreaker=True
    )
    assert with_dealbreaker["work_format"] >= plain["work_format"]


def test_role_content_weight_independent_of_role_kind():
    """Ось `role_content` растёт с сигналом резюме (категории/ниши), не с `role_kind` —
    это `management` меняется по стороне, у role_content другой источник насыщенности."""
    rich = dict(
        position=DesiredPosition(categories=["Backend"]),
        search_criteria=SearchCriteria(niches=["LLM"]),
    )
    mixed = _weights(role_kind="mixed", **rich)
    hands_on = _weights(role_kind="hands_on", **rich)
    assert mixed["role_content"] == hands_on["role_content"]
