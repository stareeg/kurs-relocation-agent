"""Дешёвый extract-вызов «релевантность роли» для балла резюме."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from core.config import get_settings
from core.domains.profile.gap import ResumeGapReport, load_top_scored_summaries
from core.domains.profile.model import ResumeData
from core.domains.profile.score_criteria import format_search_axes_block
from core.domains.profile.score_tips import format_role_fit_note
from core.kernel import ports
from core.kernel.errors import LlmError

logger = logging.getLogger(__name__)


class RoleFitLlm(BaseModel):
    score: int = Field(ge=0, le=100)
    notes: list[str] = Field(default_factory=list)


@lru_cache(maxsize=4)
def _load_prompt(path_str: str) -> str:
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.read_text(encoding="utf-8")


def _user_payload(
    data: ResumeData,
    report: ResumeGapReport,
    top_summaries: list[tuple[str, str]],
) -> str:
    sc = data.search_criteria
    pos = data.position
    niches = ", ".join(sc.niches) if sc.niches else "(не указаны)"
    skills = ", ".join(s for s in data.key_skills if s.strip()) or "(пусто)"
    about = (data.about or "").strip()
    if len(about) > 800:
        about = about[:800] + "…"
    exp_lines = [
        f"- {e.position or '?'} @ {e.company or '?'} ({e.industry or 'отрасль не указана'})"
        for e in data.experience[:6]
        if e.company or e.position
    ]
    top_lines = [f"- {t or '?'} / {c or '?'}" for t, c in top_summaries[:5]]
    missing = ", ".join(c.name for c in report.missing[:8]) if report.missing else "(нет)"
    axes = format_search_axes_block(data)
    return (
        f"Желаемая должность: {pos.title or '(не указана)'}\n"
        f"Грейд: {', '.join(pos.grade) if pos.grade else '(не указан)'}\n"
        f"Ниши поиска: {niches}\n\n"
        f"## Критерии поиска (левая панель)\n{axes}\n\n"
        f"Ключевые навыки ({len(data.key_skills)}): {skills}\n"
        f"Обо мне:\n{about or '(пусто)'}\n"
        "Опыт (заголовки):\n" + ("\n".join(exp_lines) if exp_lines else "(пусто)") + "\n"
        "Топ оценённых вакансий:\n" + ("\n".join(top_lines) if top_lines else "(нет)") + "\n"
        f"Недостающие рыночные концепты: {missing}\n"
    )


async def resolve_role_fit_llm(
    data: ResumeData,
    report: ResumeGapReport,
    top_jobs_texts: list[str] | None = None,
    *,
    account_id: int,
    db: object | None = None,
) -> tuple[int, list[str]] | None:
    """`(score, notes)` или `None` при отсутствии ключа / сбое (caller → эвристика)."""
    settings = get_settings()
    if not settings.openrouter_api_key:
        return None

    try:
        summaries = await load_top_scored_summaries(5, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("role_fit: топ-вакансии недоступны: %s", exc)
        summaries = []
        if top_jobs_texts:
            summaries = [("(вакансия)", "")] * min(5, len(top_jobs_texts))

    try:
        from core.domains.profile.llm import ROLE_FIT

        system = _load_prompt(ROLE_FIT)
        raw = await ports.llm().structured(
            "resume_role_fit",
            system=system,
            user=_user_payload(data, report, summaries),
            schema=RoleFitLlm,
            temperature=0.2,
        )
        if not isinstance(raw, RoleFitLlm):  # pragma: no cover
            raise LlmError(f"role_fit вернул неожиданный тип: {type(raw).__name__}")
        notes = [format_role_fit_note(n) for n in raw.notes if n and n.strip()]
        notes = [n for n in notes if n][:3]
        return int(raw.score), notes
    except Exception as exc:  # noqa: BLE001
        logger.warning("role_fit: LLM упал, эвристика: %s", exc)
        return None


__all__ = ["RoleFitLlm", "resolve_role_fit_llm"]
