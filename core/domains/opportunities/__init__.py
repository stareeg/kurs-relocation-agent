"""Домен opportunities: скоринг вакансий, доска, скипы, discovery.

Публичный API — ленивый (`__getattr__`), как в `pipeline`: иначе импорт любой чистой части
домена (`models`, `remote_feasibility`) тянет за собой scorer/persist → `core.platform` →
langchain и пул Postgres. Ленивость делает правило A-10 «домен зависит от портов, а не от
инфраструктуры» проверяемым (`tests/test_domain_ports.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pyright/IDE видят символы статически, рантайм грузит лениво
    from core.domains.opportunities.competition import compute_competition_insight
    from core.domains.opportunities.models import (
        BurnoutRisk,
        CompetitionInsight,
        GradeMatch,
        RemoteAbroadCompat,
        RemoteFeasibility,
        RemoteSignal,
        RoleContentMatch,
        SalaryInfo,
        ScoreResult,
        VacancyInput,
    )
    from core.domains.opportunities.persist import ScoredJob, persist_scored, score_and_persist
    from core.domains.opportunities.remote_feasibility import (
        assess_remote_feasibility,
        assess_remote_feasibility_safe,
    )
    from core.domains.opportunities.scorer import score_vacancy
    from core.domains.opportunities.skip_reasons import (
        SELF_SKIP_REASONS,
        SKIP_REASON_GRID_KEYS,
        aggregate_skip_reason_counts,
        canonical_skip_reason,
        is_manual_skip_reason,
    )
    from core.domains.opportunities.sources.getmatch import extract_getmatch_numeric_id_from_text
    from core.domains.opportunities.sources.habr import (
        HabrVacancySource,
        extract_habr_numeric_id_from_text,
    )

_MODELS = "core.domains.opportunities.models"
_PERSIST = "core.domains.opportunities.persist"
_REMOTE = "core.domains.opportunities.remote_feasibility"
_COMPETITION = "core.domains.opportunities.competition"
_SKIPS = "core.domains.opportunities.skip_reasons"

_LAZY: dict[str, tuple[str, str]] = {
    "BurnoutRisk": (_MODELS, "BurnoutRisk"),
    "CompetitionInsight": (_MODELS, "CompetitionInsight"),
    "compute_competition_insight": (_COMPETITION, "compute_competition_insight"),
    "GradeMatch": (_MODELS, "GradeMatch"),
    "RemoteAbroadCompat": (_MODELS, "RemoteAbroadCompat"),
    "RemoteFeasibility": (_MODELS, "RemoteFeasibility"),
    "RemoteSignal": (_MODELS, "RemoteSignal"),
    "RoleContentMatch": (_MODELS, "RoleContentMatch"),
    "SalaryInfo": (_MODELS, "SalaryInfo"),
    "ScoreResult": (_MODELS, "ScoreResult"),
    "VacancyInput": (_MODELS, "VacancyInput"),
    "ScoredJob": (_PERSIST, "ScoredJob"),
    "persist_scored": (_PERSIST, "persist_scored"),
    "score_and_persist": (_PERSIST, "score_and_persist"),
    "assess_remote_feasibility": (_REMOTE, "assess_remote_feasibility"),
    "assess_remote_feasibility_safe": (_REMOTE, "assess_remote_feasibility_safe"),
    "score_vacancy": ("core.domains.opportunities.scorer", "score_vacancy"),
    "SELF_SKIP_REASONS": (_SKIPS, "SELF_SKIP_REASONS"),
    "SKIP_REASON_GRID_KEYS": (_SKIPS, "SKIP_REASON_GRID_KEYS"),
    "aggregate_skip_reason_counts": (_SKIPS, "aggregate_skip_reason_counts"),
    "canonical_skip_reason": (_SKIPS, "canonical_skip_reason"),
    "is_manual_skip_reason": (_SKIPS, "is_manual_skip_reason"),
    "extract_getmatch_numeric_id_from_text": (
        "core.domains.opportunities.sources.getmatch",
        "extract_getmatch_numeric_id_from_text",
    ),
    "extract_habr_numeric_id_from_text": (
        "core.domains.opportunities.sources.habr",
        "extract_habr_numeric_id_from_text",
    ),
    "HabrVacancySource": (
        "core.domains.opportunities.sources.habr",
        "HabrVacancySource",
    ),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(target[0]), target[1])
    globals()[name] = value
    return value


__all__ = [
    "BurnoutRisk",
    "CompetitionInsight",
    "GradeMatch",
    "HabrVacancySource",
    "RemoteAbroadCompat",
    "RemoteFeasibility",
    "RemoteSignal",
    "RoleContentMatch",
    "SELF_SKIP_REASONS",
    "SKIP_REASON_GRID_KEYS",
    "SalaryInfo",
    "ScoreResult",
    "ScoredJob",
    "VacancyInput",
    "aggregate_skip_reason_counts",
    "assess_remote_feasibility",
    "assess_remote_feasibility_safe",
    "canonical_skip_reason",
    "compute_competition_insight",
    "extract_getmatch_numeric_id_from_text",
    "extract_habr_numeric_id_from_text",
    "is_manual_skip_reason",
    "persist_scored",
    "score_and_persist",
    "score_vacancy",
]
