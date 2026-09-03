"""Тесты: классификация архива диалога и нормализация легаси «Архив» → «Отказ»."""

from __future__ import annotations

import logging

import pytest

from core.domains.pipeline import archive_disposition as archive_disposition_mod
from core.domains.pipeline.archive_disposition import (
    ArchiveDispositionResult,
    _format_transcript,
    classify_archive_disposition,
)
from core.kernel import ports
from core.kernel.schemas.funnel import FunnelStatus, resolve_funnel_status
from tests.fakes import FakeLlm


class _Msg:
    def __init__(self, kind: str, body: str) -> None:
        self.kind = kind
        self.body = body


def test_resolve_archive_maps_to_rejected() -> None:
    assert resolve_funnel_status("Архив") == FunnelStatus.REJECTED.value
    assert resolve_funnel_status("архив") == FunnelStatus.REJECTED.value
    assert resolve_funnel_status("в архиве") == FunnelStatus.REJECTED.value


def test_format_transcript_hr_only() -> None:
    text = _format_transcript(
        [
            _Msg("llm_user", "ignore"),
            _Msg("hr_in", "К сожалению, отказали"),
            _Msg("hr_out", "Понял, спасибо"),
        ]
    )
    assert "HR: К сожалению, отказали" in text
    assert "Я: Понял, спасибо" in text
    assert "ignore" not in text


def test_format_transcript_empty() -> None:
    assert _format_transcript([]) == "(переписки с HR нет)"
    assert _format_transcript([_Msg("llm_assistant", "hi")]) == "(переписки с HR нет)"


def test_archive_disposition_result_defaults() -> None:
    r = ArchiveDispositionResult()
    assert r.disposition == "skipped"


# §15 плана local_context_blind_spots_2026_08_12.md: reasoning раньше жил только в
# llm_result_cache, ни строчки в copilot_logs/бандле поддержки.
async def test_classify_logs_reasoning_on_success(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = type("S", (), {"openrouter_api_key": "test-key"})()
    monkeypatch.setattr(archive_disposition_mod, "get_settings", lambda: settings)
    llm = FakeLlm(text='{"disposition":"rejected","reasoning":"HR прямо написал про вилку"}')
    messages = [_Msg("hr_in", "К сожалению, вилка не подошла")]

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.archive_disposition"):
        with ports.use_ports(llm=llm):
            result = await classify_archive_disposition(
                company="IT_One",
                title="Backend",
                messages=messages,
                vacancy_id="v-74",
            )

    assert result.disposition == "rejected"
    records = [r for r in caplog.records if r.getMessage().startswith("LLM archive_disposition:")]
    assert len(records) == 1
    assert "HR прямо написал про вилку" in records[0].getMessage()
    assert "v-74" in records[0].getMessage()
    assert records[0].fallback is False


async def test_classify_logs_reasoning_on_llm_failure(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = type("S", (), {"openrouter_api_key": "test-key"})()
    monkeypatch.setattr(archive_disposition_mod, "get_settings", lambda: settings)
    llm = FakeLlm(text="совсем не json")
    messages = [_Msg("hr_in", "К сожалению, вилка не подошла")]

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.archive_disposition"):
        with ports.use_ports(llm=llm):
            result = await classify_archive_disposition(
                company="IT_One",
                title="Backend",
                messages=messages,
                vacancy_id="v-75",
            )

    assert result.disposition == "skipped"
    records = [
        r for r in caplog.records if r.getMessage().startswith("LLM archive_disposition: сбой")
    ]
    assert len(records) == 1
    assert "v-75" in records[0].getMessage()
    assert records[0].fallback is True
