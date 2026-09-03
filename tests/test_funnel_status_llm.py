"""§15 плана local_context_blind_spots_2026_08_12.md: reasoning классификатора
`resolve_funnel_status_llm` раньше жил только в памяти функции/`llm_result_cache` — до
support-бандла (`GET /api/logs/bundle`, читает `copilot_logs`) не долетал вовсе. Теперь и
успешный, и fallback-путь оставляют `event(logger, "LLM", ...)` с reasoning."""

from __future__ import annotations

import logging

import pytest

from core.domains.pipeline import funnel_status_llm
from core.kernel import ports
from tests.fakes import FakeLlm


def _with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = type("S", (), {"openrouter_api_key": "test-key"})()
    monkeypatch.setattr(funnel_status_llm, "get_settings", lambda: settings)


async def test_success_logs_reasoning(caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    _with_api_key(monkeypatch)
    llm = FakeLlm(text='{"funnel_status": "Скрининг", "reasoning": "HR подтвердил звонок"}')

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.funnel_status_llm"):
        with ports.use_ports(llm=llm):
            status, reasoning = await funnel_status_llm.resolve_funnel_status_llm(
                hh_status_raw="response",
                vacancy_id="v-317",
            )

    assert reasoning == "HR подтвердил звонок"
    records = [r for r in caplog.records if r.getMessage().startswith("LLM funnel_status:")]
    assert len(records) == 1
    assert "HR подтвердил звонок" in records[0].getMessage()
    assert "v-317" in records[0].getMessage()
    assert records[0].fallback is False


async def test_unrecognized_status_logs_fallback_with_reasoning(
    caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    _with_api_key(monkeypatch)
    llm = FakeLlm(text='{"funnel_status": "не по списку", "reasoning": "модель ошиблась в имени"}')

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.funnel_status_llm"):
        with ports.use_ports(llm=llm):
            status, reasoning = await funnel_status_llm.resolve_funnel_status_llm(
                hh_status_raw="response",
                vacancy_id="v-42",
            )

    records = [r for r in caplog.records if r.getMessage().startswith("LLM funnel_status:")]
    assert len(records) == 1
    assert "модель ошиблась в имени" in records[0].getMessage()
    assert records[0].fallback is True


async def test_llm_failure_logs_reasoning_in_fallback_branch(
    caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    _with_api_key(monkeypatch)
    llm = FakeLlm(text="не json совсем")

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.funnel_status_llm"):
        with ports.use_ports(llm=llm):
            status, reasoning = await funnel_status_llm.resolve_funnel_status_llm(
                hh_status_raw="response",
                current_status="Скрининг",
                vacancy_id="v-9",
            )

    assert status == "Скрининг"
    records = [r for r in caplog.records if r.getMessage().startswith("LLM funnel_status: сбой")]
    assert len(records) == 1
    assert "v-9" in records[0].getMessage()
    assert records[0].fallback is True
