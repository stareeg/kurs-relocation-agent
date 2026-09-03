"""Structured LLM-аудит шкал writing / role_fit с пунктами и points_lost."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from core.config import get_settings
from core.domains.profile.bullet_format import parse_bullets
from core.domains.profile.gap import ResumeGapReport, ScoreFixItem, WeakBullet, count_bullets
from core.domains.profile.model import ResumeData
from core.domains.profile.role_fit_llm import load_top_scored_summaries
from core.domains.profile.score_criteria import format_search_axes_block
from core.kernel import ports
from core.kernel.errors import LlmError

logger = logging.getLogger(__name__)

ApplyAction = Literal["replace_bullet", "strengthen_block", "add_skill", "patch_about"]
FixSection = Literal["experience", "about", "skills", "title"]


class WritingFixOut(BaseModel):
    label: str
    current: str
    suggested: str
    why: str = Field(max_length=160)
    points_lost: int = Field(ge=1, le=20)
    section: FixSection = "experience"
    experience_index: int | None = None
    apply_action: ApplyAction = "replace_bullet"


class RoleFitFixOut(BaseModel):
    label: str
    current: str
    suggested: str
    why: str = Field(max_length=160)
    points_lost: int = Field(ge=1, le=20)
    section: FixSection = "skills"
    experience_index: int | None = None
    apply_action: ApplyAction = "add_skill"


class ResumeScoreAuditLlm(BaseModel):
    writing_score: int = Field(ge=0, le=100)
    role_fit_score: int = Field(ge=0, le=100)
    writing_fixes: list[WritingFixOut] = Field(default_factory=list, max_length=5)
    role_fit_fixes: list[RoleFitFixOut] = Field(default_factory=list, max_length=4)


@lru_cache(maxsize=4)
def _load_prompt(path_str: str) -> str:
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.read_text(encoding="utf-8")


def _bullet_catalog(data: ResumeData) -> str:
    lines: list[str] = []
    n = 0
    for i, exp in enumerate(data.experience):
        company = (exp.company or "?").strip()
        for _line in parse_bullets(exp.description or ""):
            n += 1
            lines.append(f"{n}. [{company} idx={i}] {_line[:200]}")
    for _line in parse_bullets(data.about or ""):
        n += 1
        lines.append(f"{n}. [Обо мне] {_line[:200]}")
    return "\n".join(lines) if lines else "(буллетов нет)"


def _user_payload(
    data: ResumeData,
    report: ResumeGapReport,
    top_summaries: list[tuple[str, str]],
) -> str:
    pos = data.position
    skills = ", ".join(s for s in data.key_skills if s.strip()) or "(пусто)"
    about = (data.about or "").strip()
    if len(about) > 1000:
        about = about[:1000] + "…"
    exp_lines = [
        f"{i}. {e.company or '?'} — {e.position or '?'} ({e.start or '?'}–{e.end or 'н.в.'})"
        for i, e in enumerate(data.experience[:8])
        if e.company or e.position
    ]
    top_lines = [f"- {t or '?'} / {c or '?'}" for t, c in top_summaries[:5]]
    missing = ", ".join(c.name for c in report.missing[:10]) if report.missing else "(нет)"
    axes = format_search_axes_block(data)
    return (
        f"Желаемая должность: {pos.title or '(не указана)'}\n"
        f"Грейд: {', '.join(pos.grade) if pos.grade else '(не указан)'}\n\n"
        f"## Критерии поиска\n{axes}\n\n"
        f"Ключевые навыки: {skills}\n\n"
        f"Обо мне:\n{about or '(пусто)'}\n\n"
        "Опыт (индекс → компания):\n" + ("\n".join(exp_lines) if exp_lines else "(пусто)") + "\n\n"
        f"Буллеты (номер → компания, idx=индекс опыта):\n{_bullet_catalog(data)}\n\n"
        "Топ оценённых вакансий:\n" + ("\n".join(top_lines) if top_lines else "(нет)") + "\n\n"
        f"Недостающие рыночные концепты: {missing}\n"
    )


def _to_fix_items(raw: ResumeScoreAuditLlm) -> list[ScoreFixItem]:
    out: list[ScoreFixItem] = []
    for w in raw.writing_fixes[:5]:
        out.append(
            ScoreFixItem(
                axis="writing",
                points_lost=int(w.points_lost),
                label=w.label.strip(),
                current=w.current.strip(),
                suggested=w.suggested.strip(),
                why=w.why.strip(),
                section=w.section,
                experience_index=w.experience_index,
                apply_action=w.apply_action,
            )
        )
    for r in raw.role_fit_fixes[:4]:
        out.append(
            ScoreFixItem(
                axis="role_fit",
                points_lost=int(r.points_lost),
                label=r.label.strip(),
                current=r.current.strip(),
                suggested=r.suggested.strip(),
                why=r.why.strip(),
                section=r.section,
                experience_index=r.experience_index,
                apply_action=r.apply_action,
            )
        )
    return out


def fixes_for_axis(fixes: list[ScoreFixItem], axis: str) -> list[ScoreFixItem]:
    return [f for f in fixes if f.axis == axis]


def weak_bullets_from_fixes(fixes: list[ScoreFixItem], data: ResumeData) -> list[WeakBullet]:
    """Совместимость со старым полем weak_bullets — только writing fixes."""
    weak: list[WeakBullet] = []
    for f in fixes_for_axis(fixes, "writing"):
        section = "about" if f.section == "about" else "experience"
        weak.append(
            WeakBullet(
                section=section,
                ref=f.label,
                index=f.experience_index,
                text=f.current,
                reason=f.why,
            )
        )
    if weak:
        return weak
    return []


def role_fit_notes_from_fixes(fixes: list[ScoreFixItem]) -> list[str]:
    notes: list[str] = []
    for f in fixes_for_axis(fixes, "role_fit"):
        line = f.suggested.strip()
        if f.why and f.why not in line:
            line = f"{line} — {f.why}"
        notes.append(line[:240])
    return notes[:4]


async def resolve_score_audit_llm(
    data: ResumeData,
    report: ResumeGapReport,
    *,
    account_id: int,
    db: object | None = None,
) -> tuple[int, int, list[ScoreFixItem]] | None:
    """`(writing_score, role_fit_primary, fixes)` или None при сбое."""
    if not get_settings().openrouter_api_key:
        return None
    if count_bullets(data) == 0 and not (data.about or "").strip():
        return None

    try:
        summaries = await load_top_scored_summaries(5, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("score_audit: топ-вакансии недоступны: %s", exc)
        summaries = []

    try:
        from core.domains.profile.llm import SCORE_AUDIT

        system = _load_prompt(SCORE_AUDIT)
        raw = await ports.llm().structured(
            "resume_score_audit",
            system=system,
            user=_user_payload(data, report, summaries),
            schema=ResumeScoreAuditLlm,
            temperature=0.25,
        )
        if not isinstance(raw, ResumeScoreAuditLlm):  # pragma: no cover
            raise LlmError(f"score_audit вернул неожиданный тип: {type(raw).__name__}")
        fixes = _to_fix_items(raw)
        return int(raw.writing_score), int(raw.role_fit_score), fixes
    except Exception as exc:  # noqa: BLE001
        logger.warning("score_audit: LLM упал, fallback: %s", exc)
        return None


__all__ = [
    "ResumeScoreAuditLlm",
    "fixes_for_axis",
    "resolve_score_audit_llm",
    "role_fit_notes_from_fixes",
    "weak_bullets_from_fixes",
]
