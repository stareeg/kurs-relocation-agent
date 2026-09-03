"""Троттл пре-генерации сопроводительного (`schedule_cover_letter_pregen`).

`preview_with_pregen` зовётся на КАЖДЫЙ GET /api/pipeline/auto-apply/preview, а фронт
«Расширения» опрашивает превью раз в 5 секунд. Без троттла FAILED-письмо (которое не
сохранилось в jobs.cover_letter_text) перезапускало бы платный LLM-вызов на каждый опрос.
"""

from __future__ import annotations

import pytest

from core.app.scenarios import cover_letter as scenario


@pytest.fixture(autouse=True)
def _clear_throttle_state() -> None:
    scenario._recent_pregen.clear()
    yield
    scenario._recent_pregen.clear()


def test_repeat_calls_for_same_job_enqueue_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(scenario, "enqueue_soon", lambda *a, **kw: calls.append(kw))

    for _ in range(5):
        scenario.schedule_cover_letter_pregen(720, "x" * 80, account_id=9)

    assert len(calls) == 1, "5 опросов превью подряд — одна постановка в очередь"


def test_different_jobs_and_accounts_not_throttled_against_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(scenario, "enqueue_soon", lambda *a, **kw: calls.append(kw))

    scenario.schedule_cover_letter_pregen(1, "x" * 80, account_id=9)
    scenario.schedule_cover_letter_pregen(2, "x" * 80, account_id=9)
    scenario.schedule_cover_letter_pregen(1, "x" * 80, account_id=42)

    assert len(calls) == 3, "троттл — per (account_id, job_id), не глобальный"


def test_throttle_window_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(scenario, "enqueue_soon", lambda *a, **kw: calls.append(kw))
    clock = [1000.0]
    monkeypatch.setattr(scenario.time, "monotonic", lambda: clock[0])

    scenario.schedule_cover_letter_pregen(720, "x" * 80, account_id=9)
    clock[0] += scenario._PREGEN_THROTTLE_SEC + 1
    scenario.schedule_cover_letter_pregen(720, "x" * 80, account_id=9)

    assert len(calls) == 2, "по истечении окна — можно ставить снова"


def test_short_vacancy_text_still_skipped_before_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(scenario, "enqueue_soon", lambda *a, **kw: calls.append(kw))

    scenario.schedule_cover_letter_pregen(720, "коротко", account_id=9)
    # Пустой текст не должен «съедать» окно троттла: настоящий текст следом — ставится.
    scenario.schedule_cover_letter_pregen(720, "x" * 80, account_id=9)

    assert len(calls) == 1
