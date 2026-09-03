"""L-14: reasoning_effort берётся из LlmFeature, не из MODEL_TIER_EFFORT на весь тир."""

from __future__ import annotations

import pytest

from core.platform.llm.registry import (
    LlmFeature,
    REASONING_EFFORTS,
    chat_model_for,
    register,
    unregister_for_tests,
)


def _settings(*, tier_effort_map: dict[str, str] | None = None):
    efforts = tier_effort_map if tier_effort_map is not None else {"advanced": "high"}

    class _S:
        def tier_model(self, t: str) -> str:
            return "openai/gpt-5.6-luna"

        def tier_fallback(self, t: str) -> str:
            return ""

        def tier_effort(self, t: str) -> str | None:
            return efforts.get(t) or None

        openrouter_model_fallback = ""
        llm_timeout_s = 90.0
        llm_max_retries = 3
        openrouter_base_url = "https://openrouter.ai/api/v1"
        openrouter_api_key = "k"
        openrouter_proxy = None
        agent_tier_overrides: dict = {}

    return _S()


def test_chat_model_for_uses_feature_effort_not_tier_map():
    name = "_l14_effort_medium"
    unregister_for_tests(name)
    register(
        LlmFeature(
            name=name,
            tier="advanced",
            prompt_in_code=True,
            max_tokens=1024,
            budget_ms=10_000,
            reasoning_effort="medium",
        )
    )
    try:
        # Тир в .env говорит high — фича должна победить.
        model = chat_model_for(name, settings=_settings(tier_effort_map={"advanced": "high"}))
        assert model.reasoning_effort == "medium"
    finally:
        unregister_for_tests(name)


def test_chat_model_for_none_effort_skips_tier_fallback():
    """Явный None на фиче — не слать reasoning, даже если MODEL_TIER_EFFORT заполнен."""
    name = "_l14_effort_none"
    unregister_for_tests(name)
    register(
        LlmFeature(
            name=name,
            tier="advanced",
            prompt_in_code=True,
            max_tokens=1024,
            budget_ms=10_000,
            reasoning_effort=None,
        )
    )
    try:
        model = chat_model_for(name, settings=_settings(tier_effort_map={"advanced": "medium"}))
        assert model.reasoning_effort is None
    finally:
        unregister_for_tests(name)


def test_factory_by_raw_tier_still_reads_model_tier_effort():
    """Фабрика по сырому тиру (без фичи) — легаси MODEL_TIER_EFFORT."""
    from core.platform.llm import openrouter_chat as or_mod

    model = or_mod.get_chat_model(
        "advanced", settings=_settings(tier_effort_map={"advanced": "low"})
    )
    assert model.reasoning_effort == "low"


def test_invalid_effort_rejected_at_declaration():
    with pytest.raises(ValueError, match="reasoning_effort"):
        LlmFeature(
            name="_l14_bad_effort",
            tier="basic",
            prompt_in_code=True,
            max_tokens=1024,
            budget_ms=10_000,
            reasoning_effort="ultra",  # type: ignore[arg-type]
        )


def test_heavy_features_declare_medium_light_ones_skip():
    from core.platform.llm.registry import all_features, ensure_features_loaded

    ensure_features_loaded()
    by_name = {f.name: f for f in all_features()}

    for name in (
        "situation",
        "prep",
        "prep_pack",
        "debrief",
        "screening_pitch",
        "screening_questions",
        "salary_estimate",
        "offer_negotiation",
    ):
        assert by_name[name].reasoning_effort == "medium", name

    # Резюме-фичи — на reserve-тире (Gemini 3.7 Flash); reasoning_effort не задан,
    # т.к. усиление/критик — extraction/редактирование без рассуждения.
    assert by_name["resume_strengthen"].reasoning_effort is None
    assert by_name["resume_strengthen"].tier == "reserve"
    assert by_name["resume_skill_suggest"].reasoning_effort is None
    assert by_name["resume_skill_suggest"].tier == "reserve"

    # basic / лёгкий advanced — без effort (быстрее; L-14 пример screening_brief).
    assert by_name["screening_brief"].reasoning_effort is None
    assert by_name["qa"].reasoning_effort is None
    assert by_name["chat"].reasoning_effort is None

    for feat in by_name.values():
        if feat.reasoning_effort is not None:
            assert feat.reasoning_effort in REASONING_EFFORTS
