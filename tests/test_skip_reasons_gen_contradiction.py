"""Регресс: чип skip_reasons_gen не должен противоречить сам себе (EX-11).

Реальный кейс: вакансия 132634764 «Алабуга. Менеджмент» — LLM выдала чип
{"text": "487,5 тыс. до налогов — зарплата подходит", "canonical": "Низкая зарплата"}.
Текст утверждает, что зарплата подходит, метка — что она низкая. Такой чип
скрывается из результата (не переписывается за LLM), остальные проходят как есть.
"""

from __future__ import annotations

import pytest

from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
    SkipReasonsPack,
    SkipReasonSuggestion,
)
from core.domains.opportunities.skip_reasons_gen import generate_skip_reasons
from tests.fakes import FakeLlm


def _score_result() -> ScoreResult:
    return ScoreResult(
        overall_score=9,
        recommendation="skip",  # type: ignore[arg-type]
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="487.5к", note=""),
        role_content_match=RoleContentMatch(score=20, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["p"],
        cons=["c"],
        red_flags=[],
        one_line_verdict="v",
    )


def _pack_with_contradiction() -> SkipReasonsPack:
    return SkipReasonsPack(
        reasons=[
            SkipReasonSuggestion(
                text="487,5 тыс. до налогов — зарплата подходит",
                canonical="Низкая зарплата",
            ),
            SkipReasonSuggestion(text="Грейд заметно выше твоего", canonical="Низкий грейд"),
            SkipReasonSuggestion(text="Стек далёкий от ML", canonical="Не тот стек/домен"),
            SkipReasonSuggestion(text="Только офис, без удалёнки", canonical="Не тот формат"),
            SkipReasonSuggestion(
                text="Роль почти целиком менеджерская",
                canonical="Не та роль (IC vs рук)",
            ),
            SkipReasonSuggestion(text="Enterprise-стиль, мало R&D", canonical="Не тот стек/домен"),
        ]
    )


@pytest.mark.asyncio
async def test_contradictory_chip_is_dropped():
    llm = FakeLlm(result=_pack_with_contradiction())

    pack = await generate_skip_reasons("вакансия текст", _score_result(), llm=llm)

    assert pack is not None
    texts = [r.text for r in pack.reasons]
    assert "487,5 тыс. до налогов — зарплата подходит" not in texts
    assert len(pack.reasons) == 5
    # остальные чипы, без противоречия, проходят как есть
    assert "Грейд заметно выше твоего" in texts


@pytest.mark.asyncio
async def test_clean_pack_keeps_all_chips():
    clean = _pack_with_contradiction().model_copy(
        update={
            "reasons": [
                r.model_copy(update={"text": "487,5 тыс. — ниже твоего минимума"})
                if r.canonical == "Низкая зарплата"
                else r
                for r in _pack_with_contradiction().reasons
            ]
        }
    )
    llm = FakeLlm(result=clean)

    pack = await generate_skip_reasons("вакансия текст", _score_result(), llm=llm)

    assert pack is not None
    assert len(pack.reasons) == 6
