"""Structured аудит writing/role_fit: конвертеры fixes и PG-снимок."""

from __future__ import annotations

from core.domains.profile.gap import ScoreFixItem
from core.domains.profile.model import ResumeData
from core.domains.profile.resume_score import (
    ResumeScoreSnapshot,
    audit_fixes_from_snapshot,
    audit_json_from_score,
)
from core.domains.profile.score_audit import (
    ResumeScoreAuditLlm,
    RoleFitFixOut,
    WritingFixOut,
    role_fit_notes_from_fixes,
    weak_bullets_from_fixes,
)


def _sample_audit() -> ResumeScoreAuditLlm:
    return ResumeScoreAuditLlm(
        writing_score=72,
        role_fit_score=68,
        writing_fixes=[
            WritingFixOut(
                label="Acme",
                current="Отвечал за качество кода",
                suggested="Сократил дефекты в проде на 40% через code review и CI",
                why="Нет метрики и действия",
                points_lost=6,
                section="experience",
                experience_index=0,
                apply_action="replace_bullet",
            )
        ],
        role_fit_fixes=[
            RoleFitFixOut(
                label="Навыки",
                current="",
                suggested="FastAPI",
                why="Часто в целевых вакансиях",
                points_lost=4,
                section="skills",
                apply_action="add_skill",
            )
        ],
    )


def test_audit_json_roundtrip() -> None:
    from core.domains.profile.gap import ResumeScoreBreakdown

    fixes = [
        ScoreFixItem(
            axis="writing",
            points_lost=5,
            label="Acme",
            current="Слабый буллет",
            suggested="Сильный буллет с метрикой",
            why="Нет результата",
            section="experience",
            experience_index=0,
            apply_action="replace_bullet",
        )
    ]
    score = ResumeScoreBreakdown(
        total=80,
        structure=85,
        market_coverage=None,
        writing=75,
        role_fit=80,
        score_fixes=fixes,
    )
    payload = audit_json_from_score(score)
    assert payload is not None
    snap = ResumeScoreSnapshot(
        total=80,
        structure=85,
        market_coverage=None,
        writing=75,
        role_fit=80,
        audit_json=payload,
    )
    loaded = audit_fixes_from_snapshot(snap)
    assert len(loaded) == 1
    assert loaded[0].label == "Acme"
    assert loaded[0].points_lost == 5


def test_weak_bullets_and_notes_from_fixes() -> None:
    data = ResumeData(
        experience=[
            {
                "company": "Acme",
                "position": "Dev",
                "description": "- Отвечал за качество кода",
            }
        ]
    )
    raw = _sample_audit()
    fixes = [
        ScoreFixItem(
            axis="writing",
            points_lost=w.points_lost,
            label=w.label,
            current=w.current,
            suggested=w.suggested,
            why=w.why,
            section=w.section,
            experience_index=w.experience_index,
            apply_action=w.apply_action,
        )
        for w in raw.writing_fixes
    ] + [
        ScoreFixItem(
            axis="role_fit",
            points_lost=r.points_lost,
            label=r.label,
            current=r.current,
            suggested=r.suggested,
            why=r.why,
            section=r.section,
            experience_index=r.experience_index,
            apply_action=r.apply_action,
        )
        for r in raw.role_fit_fixes
    ]
    weak = weak_bullets_from_fixes(fixes, data)
    assert len(weak) == 1
    assert weak[0].ref == "Acme"
    assert "метрик" in (weak[0].reason or "")

    notes = role_fit_notes_from_fixes(fixes)
    assert notes
    assert "FastAPI" in notes[0]
