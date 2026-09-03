"""L-11: cache_prefix на фичах с большим статическим префиксом + сборка cache_control."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from core.platform.llm.call import _build_system_message, run
from core.platform.llm.registry import (
    LlmFeature,
    all_features,
    ensure_features_loaded,
    register,
    unregister_for_tests,
)


# Фичи из шага L-11 (скрининг / техничка / разбор / резюме / офферы / чат).
_L11_CACHE_FEATURES = frozenset(
    {
        "screening_brief",
        "screening_pitch",
        "screening_questions",
        "prep",
        "prep_pack",
        "debrief",
        "qa",
        "resume_parse_pdf",
        "resume_strengthen",
        "resume_strengthen_critic",
        "resume_role_fit",
        "offer_parse",
        "offer_compare",
        "offer_negotiation",
        "offer_bonus_estimate",
        "chat",
        "qa_vacancy",
        "resume_gap_chat",
        "hr_draft_chat",
    }
)


def test_l11_features_have_cache_prefix() -> None:
    ensure_features_loaded()
    by_name = {f.name: f for f in all_features()}
    missing = sorted(name for name in _L11_CACHE_FEATURES if not by_name.get(name))
    assert not missing, f"нет фич в реестре: {missing}"
    without = sorted(
        name for name in _L11_CACHE_FEATURES if not by_name[name].cache_prefix
    )
    assert not without, f"L-11: нет cache_prefix у {without}"


def test_build_system_message_marks_cache_control() -> None:
    feat = LlmFeature(
        name="_l11_cache_probe",
        tier="basic",
        prompt_in_code=True,
        cache_prefix=True,
        max_tokens=1024,
        budget_ms=10_000,
    )
    msg = _build_system_message(
        feat,
        system="STATIC PREFIX RULES",
        system_vars=None,
        prompt_vars=None,
        dynamic_tail="DYNAMIC VACANCY BLOCK",
    )
    assert isinstance(msg, SystemMessage)
    assert isinstance(msg.content, list)
    assert msg.content[0]["cache_control"] == {"type": "ephemeral"}
    assert msg.content[0]["text"] == "STATIC PREFIX RULES"
    assert msg.content[1]["text"] == "DYNAMIC VACANCY BLOCK"


def test_build_system_message_without_flag_is_plain_text() -> None:
    feat = LlmFeature(
        name="_l11_nocache_probe",
        tier="basic",
        prompt_in_code=True,
        cache_prefix=False,
        max_tokens=1024,
        budget_ms=10_000,
    )
    msg = _build_system_message(
        feat,
        system="STATIC",
        system_vars=None,
        prompt_vars=None,
        dynamic_tail="TAIL",
    )
    assert msg.content == "STATIC\n\nTAIL"


@pytest.mark.asyncio
async def test_run_prepends_cached_system_when_messages_have_no_system(
    monkeypatch,
) -> None:
    """История чата без system + system=/dynamic_tail → prefix с cache_control."""
    name = "_l11_run_chat_probe"
    unregister_for_tests(name)
    register(
        LlmFeature(
            name=name,
            tier="basic",
            prompt_in_code=True,
            cache_prefix=True,
            max_tokens=1024,
            budget_ms=10_000,
        )
    )

    captured: dict = {}

    class _FakeChat:
        async def ainvoke(self, messages, config=None):
            captured["messages"] = messages
            from langchain_core.messages import AIMessage

            return AIMessage(content="ok")

    monkeypatch.setattr(
        "core.platform.llm.call.chat_model_for",
        lambda *a, **k: _FakeChat(),
    )

    try:
        text = await run(
            name,
            system="STATIC CHAT RULES",
            dynamic_tail="note: foo",
            messages=[{"role": "user", "content": "prev"}],
            user="hello",
        )
        assert text == "ok"
        msgs = captured["messages"]
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[0].content, list)
        assert msgs[0].content[0]["cache_control"]["type"] == "ephemeral"
        assert any(isinstance(m, HumanMessage) and m.content == "prev" for m in msgs)
        assert any(isinstance(m, HumanMessage) and m.content == "hello" for m in msgs)
    finally:
        unregister_for_tests(name)
