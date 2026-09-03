"""SM-2 (plans/heuristics_to_llm.md): infer_stage_type — regex-фолбэк путает «техническое
собеседование» с live_coding. Проверяем, что новый LLM-путь решает конфликтный кейс корректнее
и что оба уровня fallback (LLM insufficient → regex, LLM unavailable → regex) работают.
"""

from __future__ import annotations

import logging

import pytest

from core.domains.pipeline.hr_enrichment import infer_stage_type
from core.domains.pipeline.hr_message_parser import _resolve_stage_type
from core.domains.pipeline import stage_type_llm
from core.kernel import ports
from tests.fakes import FakeLlm

# Конфликтный кейс из SM-2: "технич"/"инженер" триггерят regex-путь на line 47
# (`re.search(r"технич|technical|инженер"`) раньше, чем текст успевает сказать что-то более точное —
# HR-скрининг это или architecture-собес, regex не знает, но уверенно (и неверно) ставит live_coding.
CONFLICT_TEXT = "Приглашаем на техническое собеседование в пятницу, обсудим ваш опыт как инженер"


def test_regex_fallback_still_mislabels_conflict_case():
    """Документирует баг, который чинит SM-2: сырой regex-путь (без LLM) валит текст в live_coding."""
    assert infer_stage_type(CONFLICT_TEXT, {}) == "live_coding"


async def test_resolve_stage_type_uses_llm_over_regex_on_conflict(monkeypatch):
    async def fake_resolve(text: str):
        assert text == CONFLICT_TEXT
        return "system_design", "HR упомянул архитектурный контекст, не алгоритмы"

    monkeypatch.setattr(stage_type_llm, "resolve_stage_type_llm", fake_resolve)

    stage_type = await _resolve_stage_type(CONFLICT_TEXT, {})
    assert stage_type == "system_design"


async def test_resolve_stage_type_falls_back_to_regex_when_llm_unavailable(monkeypatch):
    async def fake_resolve_none(text: str):
        return None

    monkeypatch.setattr(stage_type_llm, "resolve_stage_type_llm", fake_resolve_none)

    stage_type = await _resolve_stage_type(CONFLICT_TEXT, {})
    assert stage_type == "live_coding"


async def test_resolve_stage_type_skips_llm_when_primary_parse_already_valid(monkeypatch):
    async def fail_if_called(text: str):
        raise AssertionError("resolve_stage_type_llm must not be called when parsed stage_type is valid")

    monkeypatch.setattr(stage_type_llm, "resolve_stage_type_llm", fail_if_called)

    stage_type = await _resolve_stage_type(CONFLICT_TEXT, {"stage_type": "hr_screening"})
    assert stage_type == "hr_screening"


async def test_resolve_stage_type_llm_parses_valid_json(monkeypatch):
    llm = FakeLlm(text='{"stage_type": "manager", "reasoning": "директор задаёт вопросы"}')
    monkeypatch.setattr(
        stage_type_llm,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )

    with ports.use_ports(llm=llm):
        result = await stage_type_llm.resolve_stage_type_llm("Собеседование с директором департамента")
    assert result == ("manager", "директор задаёт вопросы")


async def test_resolve_stage_type_llm_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(
        stage_type_llm,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": ""})(),
    )
    result = await stage_type_llm.resolve_stage_type_llm("любой текст")
    assert result is None


async def test_resolve_stage_type_llm_returns_none_on_invalid_value(monkeypatch):
    llm = FakeLlm(text='{"stage_type": "not_a_real_stage", "reasoning": "..."}')
    monkeypatch.setattr(
        stage_type_llm,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )

    with ports.use_ports(llm=llm):
        result = await stage_type_llm.resolve_stage_type_llm("непонятный текст")
    assert result is None


# FS-4: regex-фолбэк должен узнавать «финал» и не путать его с manager/live_coding.
def test_regex_fallback_detects_final_round():
    text = "Приглашаем на финальное собеседование с CTO по итогам техэтапов"
    assert infer_stage_type(text, {}) == "final"


def test_regex_fallback_final_takes_priority_over_technical_keyword():
    text = "Финальный раунд: обсудим ваш технический опыт как инженер с руководителем"
    assert infer_stage_type(text, {}) == "final"


async def test_resolve_stage_type_llm_parses_final(monkeypatch):
    llm = FakeLlm(text='{"stage_type": "final", "reasoning": "финальный раунд с CEO"}')
    monkeypatch.setattr(
        stage_type_llm,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )

    with ports.use_ports(llm=llm):
        result = await stage_type_llm.resolve_stage_type_llm("Финальное собеседование с CEO")
    assert result == ("final", "финальный раунд с CEO")


# §15 плана local_context_blind_spots_2026_08_12.md: reasoning раньше не долетал до
# copilot_logs/бандла поддержки — только до вызывающего кода в памяти.
async def test_resolve_stage_type_llm_logs_reasoning_on_success(caplog, monkeypatch):
    llm = FakeLlm(text='{"stage_type": "manager", "reasoning": "директор задаёт вопросы"}')
    monkeypatch.setattr(
        stage_type_llm,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.stage_type_llm"):
        with ports.use_ports(llm=llm):
            result = await stage_type_llm.resolve_stage_type_llm(
                "Собеседование с директором департамента", vacancy_id="v-1"
            )

    assert result == ("manager", "директор задаёт вопросы")
    records = [r for r in caplog.records if r.getMessage().startswith("LLM stage_type:")]
    assert len(records) == 1
    assert "директор задаёт вопросы" in records[0].getMessage()
    assert "v-1" in records[0].getMessage()
    assert records[0].fallback is False


async def test_resolve_stage_type_llm_logs_failure_in_fallback_branch(caplog, monkeypatch):
    llm = FakeLlm(text="совсем не json")
    monkeypatch.setattr(
        stage_type_llm,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.stage_type_llm"):
        with ports.use_ports(llm=llm):
            result = await stage_type_llm.resolve_stage_type_llm(
                "непонятный текст", vacancy_id="v-2"
            )

    assert result is None
    records = [r for r in caplog.records if r.getMessage().startswith("LLM stage_type: сбой")]
    assert len(records) == 1
    assert "v-2" in records[0].getMessage()
    assert records[0].fallback is True
