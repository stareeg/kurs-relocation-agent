"""Персист канонического пакета скрининга."""

from __future__ import annotations

from core.domains.preparation.screening.pack import VacancySelfPres
from core.domains.preparation.screening_questions import (
    SavedScreeningQuestions,
    save_screening_questions,
)


async def save_self_pres_pack(
    vacancy_id: str, pack: VacancySelfPres, *, account_id: int
) -> SavedScreeningQuestions:
    """Upsert полного пакета скрининга."""
    groups = [g.model_dump(mode="json") for g in pack.groups]
    hr_questions = [q.model_dump(mode="json") for q in pack.hr_questions]
    return await save_screening_questions(
        vacancy_id,
        groups,
        account_id=account_id,
        hr_questions=hr_questions,
        why_company=pack.why_company,
        oral_pitch=pack.oral_pitch,
        pitch_blocks=[b.model_dump(mode="json") for b in pack.pitch_blocks],
        jd_brief=pack.jd_brief.model_dump(mode="json"),
        input_hash=pack.input_hash,
    )


__all__ = ["save_self_pres_pack"]
