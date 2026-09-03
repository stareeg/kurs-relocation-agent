"""A-10: доменные LLM-вызовы работают через порт (`FakeLlm`), без сети."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.opportunities.models import RemoteFeasibility, RemoteSignal
from core.domains.opportunities.remote_feasibility import (
    _MAX_SIGNALS,
    assess_remote_feasibility,
    assess_remote_feasibility_safe,
)
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.text.untrusted import CLOSE_MARKER, OPEN_MARKER
from tests.fakes import FakeLlm


# --------------------------------------------------------------- opportunities/remote


async def test_remote_feasibility_uses_port_and_spotlights_vacancy_text():
    fake = FakeLlm(result=RemoteFeasibility(score=70, verdict="real"))

    result = await assess_remote_feasibility("Полная удалёнка по РФ", llm=fake)

    assert result.score == 70
    call = fake.calls[0]
    assert call["feature"] == "remote_feasibility"
    assert call["schema"] is RemoteFeasibility
    # Текст вакансии — недоверенные данные: уходит в промпт только между маркерами.
    assert OPEN_MARKER in call["user"] and CLOSE_MARKER in call["user"]
    # Правило спотлайтинга подставляется в {{SPOTLIGHT}} промпта фичи, а не в код домена.
    assert "SPOTLIGHT" in call["prompt_vars"]


async def test_remote_feasibility_clamps_signals():
    signals = [
        RemoteSignal(text=f"сигнал {i}", polarity="contra") for i in range(_MAX_SIGNALS + 3)
    ]
    fake = FakeLlm(result=RemoteFeasibility(score=20, verdict="unlikely", signals=signals))

    result = await assess_remote_feasibility("текст", llm=fake)
    assert len(result.signals) == _MAX_SIGNALS


async def test_remote_feasibility_safe_swallows_llm_error():
    fake = FakeLlm(error=LlmError("провайдер недоступен"))
    assert await assess_remote_feasibility_safe("текст", llm=fake) is None


async def test_remote_feasibility_takes_bound_port_when_not_passed():
    fake = FakeLlm(result=RemoteFeasibility(score=55, verdict="conditional"))
    with ports.use_ports(llm=fake):
        result = await assess_remote_feasibility("текст")
    assert result.score == 55


# --------------------------------------------------------------- opportunities/scorer


def _score_stub() -> Any:
    from core.domains.opportunities.models import (
        BurnoutRisk,
        GradeMatch,
        RemoteAbroadCompat,
        RoleContentMatch,
        SalaryInfo,
        ScoreResult,
    )

    return ScoreResult(
        overall_score=70,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="500 000 ₽", note=""),
        role_content_match=RoleContentMatch(score=70, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["ок"],
        cons=["нет вилки в тексте"],
        red_flags=[],
        one_line_verdict="ок",
    )


async def test_scorer_hot_path_runs_on_fake_port_with_prompt_cache_split():
    """Горячий путь скоринга тоже на порту: статический system + `dynamic_tail` под prompt cache."""
    from core.domains.opportunities.scorer import _score_with_llm
    from core.domains.profile.model import ResumeData

    fake = FakeLlm(result=_score_stub())
    result = await _score_with_llm(
        "Senior Python, полная удалёнка, 500к",
        data=ResumeData(),
        preferences="ПРЕДПОЧТЕНИЯ: не берёт финтех",
        llm=fake,
    )

    assert result.overall_score == 70
    call = fake.calls[0]
    assert call["feature"] == "job_search"
    # Статический префикс (резюме + инструкции) отделён от меняющегося блока предпочтений:
    # кэшируется первый, а не склейка — иначе prompt cache промахивается на каждом вызове.
    assert "ПРЕДПОЧТЕНИЯ" not in call["system"]
    assert call["dynamic_tail"] == "ПРЕДПОЧТЕНИЯ: не берёт финтех"
    assert OPEN_MARKER in call["user"]  # текст вакансии — данные, а не инструкции
    assert set(call["metadata"]) == {"preferences_digest", "preferences_block"}


# --------------------------------------------------------------- profile/weak_bullets


async def test_weak_bullets_resolver_uses_port():
    from core.domains.profile.weak_bullets_llm import resolve_weak_bullets_llm

    fake = FakeLlm(text='{"verdicts": [{"i": 1, "weak": true, "reason": "общие слова"}]}')
    bullets = [("experience", "Acme", 0, "отвечал за качество")]

    resolved = await resolve_weak_bullets_llm(bullets, llm=fake)

    assert resolved is not None
    assert [w.text for w in resolved] == ["отвечал за качество"]
    assert fake.calls[0]["feature"] == "weak_bullets"


async def test_weak_bullets_resolver_falls_back_on_llm_error():
    from core.domains.profile.weak_bullets_llm import resolve_weak_bullets_llm

    fake = FakeLlm(error=LlmError("таймаут бюджета"))
    resolved = await resolve_weak_bullets_llm(
        [("experience", "Acme", 0, "отвечал за качество")], llm=fake
    )
    assert resolved is None  # None = «падай на regex», а не «слабых буллетов нет»


# --------------------------------------------------------------- pipeline/hr_direction


async def test_hr_direction_uses_port(monkeypatch: pytest.MonkeyPatch):
    from core.domains.pipeline import hr_direction_llm
    from core.domains.pipeline.hr_direction_llm import ThreadMessageIn, classify_hr_directions_llm

    monkeypatch.setattr(
        hr_direction_llm,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )

    class _Fake(FakeLlm):
        async def structured(self, feature: str, *, schema, **kwargs):
            self.calls.append({"feature": feature, **kwargs})
            return schema.model_validate({"items": [{"index": 1, "kind": "hr_out"}]})

    fake = _Fake()
    messages = [
        ThreadMessageIn(index=0, kind="hr_in", body="Добрый день"),
        ThreadMessageIn(index=1, kind=None, body="Готов ответить"),
    ]
    assert await classify_hr_directions_llm(messages, account_id=1, llm=fake) == {1: "hr_out"}
    assert fake.calls[0]["feature"] == "hr_direction"
