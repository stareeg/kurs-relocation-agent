"""FR2-86: правила авто-предложения сдвига воронки из stage_type (без LLM/БД)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from core.domains.opportunities import jobs as jobs_mod
from core.domains.pipeline import funnel_suggest, hr_threads, stage_type_llm
from core.domains.pipeline.funnel_suggest import proposed_funnel_for_stage, should_offer_funnel_suggestion
from core.kernel.schemas.funnel import FunnelStatus


def test_live_coding_proposes_tech():
    assert proposed_funnel_for_stage("live_coding", text="будет лайвкодинг") == FunnelStatus.TECH


def test_final_proposes_final():
    assert proposed_funnel_for_stage("final", text="финальное собеседование") == FunnelStatus.FINAL


def test_hr_screening_without_hint_is_silent():
    # stage_type_llm часто отдаёт hr_screening как дефолт — не спамим «Скрининг?»
    assert proposed_funnel_for_stage("hr_screening", text="спасибо, жду ответ") is None


def test_hr_screening_with_hint_proposes_screening():
    assert (
        proposed_funnel_for_stage("hr_screening", text="приглашаем на скрининг в пятницу")
        == FunnelStatus.SCREENING
    )


def test_unknown_stage_type_is_none():
    assert proposed_funnel_for_stage("unknown_stage", text="техническое") is None


def test_should_offer_only_forward():
    assert should_offer_funnel_suggestion(FunnelStatus.SCREENING, FunnelStatus.TECH)
    assert not should_offer_funnel_suggestion(FunnelStatus.TECH, FunnelStatus.TECH)
    assert not should_offer_funnel_suggestion(FunnelStatus.TECH, FunnelStatus.SCREENING)
    assert should_offer_funnel_suggestion(FunnelStatus.APPLIED, FunnelStatus.SCREENING)
    assert should_offer_funnel_suggestion(None, FunnelStatus.TECH)
    assert not should_offer_funnel_suggestion(FunnelStatus.OFFER, FunnelStatus.TECH)
    assert not should_offer_funnel_suggestion(FunnelStatus.SCREENING, FunnelStatus.REJECTED)
    assert not should_offer_funnel_suggestion(FunnelStatus.APPLIED, None)


# §9 local_context_blind_spots_2026_08_12.md: функция ни разу не сработала на реальных данных —
# каждая развилка должна оставлять след в copilot_logs (не только True), иначе следующее молчание
# или срабатывание снова придётся разгадывать прямым SQL-запросом, а не по зипу логов.
@pytest.mark.parametrize(
    ("current", "proposed", "expected", "needle"),
    [
        (FunnelStatus.APPLIED, None, False, "proposed пуст"),
        (FunnelStatus.APPLIED, FunnelStatus.REJECTED, False, "не двигает воронку вперёд"),
        (FunnelStatus.TECH, FunnelStatus.SCREENING, False, "не выше"),
        (None, FunnelStatus.TECH, True, "cur пуст"),
        (FunnelStatus.SCREENING, FunnelStatus.TECH, True, "предложено —"),
    ],
)
def test_should_offer_logs_every_branch(
    caplog: pytest.LogCaptureFixture, current, proposed, expected, needle
) -> None:
    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.funnel_suggest"):
        result = should_offer_funnel_suggestion(current, proposed, vacancy_id="v-1")
    assert result is expected
    records = [r for r in caplog.records if r.getMessage().startswith("ЗАДАЧА funnel_suggest:")]
    assert len(records) == 1
    assert needle in records[0].getMessage()
    assert "v-1" in records[0].getMessage()


# §15 плана local_context_blind_spots_2026_08_12.md: suggest_funnel_from_dialog раньше
# распаковывал (stage_type, _reason) и выбрасывал reasoning — теперь он идёт дальше в
# итоговый event() вместо того, чтобы пропасть на приёме.
async def test_suggest_funnel_from_dialog_logs_stage_type_reasoning(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = hr_threads.HrThread(id=1, vacancy_id="v1")
    messages = [
        hr_threads.HrMessage(
            id=1,
            thread_id=1,
            kind="hr_in",
            body="Приглашаем на лайвкодинг в четверг",
            author_uncertain=False,
        ),
    ]
    monkeypatch.setattr(hr_threads, "get_primary_thread", AsyncMock(return_value=thread))
    monkeypatch.setattr(hr_threads, "list_messages", AsyncMock(return_value=messages))
    monkeypatch.setattr(hr_threads, "set_funnel_suggestion", AsyncMock())
    monkeypatch.setattr(jobs_mod, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    monkeypatch.setattr(
        stage_type_llm,
        "resolve_stage_type_llm",
        AsyncMock(return_value=("live_coding", "HR явно назвал формат — лайвкодинг")),
    )

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.funnel_suggest"):
        proposed = await funnel_suggest.suggest_funnel_from_dialog(
            "v1", account_id=7, db=AsyncMock()
        )

    assert proposed == FunnelStatus.TECH
    records = [
        r
        for r in caplog.records
        if r.getMessage().startswith("ЗАДАЧА funnel_suggest: vacancy_id=v1")
    ]
    assert len(records) == 1
    assert "HR явно назвал формат — лайвкодинг" in records[0].getMessage()
    assert records[0].reasoning == "HR явно назвал формат — лайвкодинг"
