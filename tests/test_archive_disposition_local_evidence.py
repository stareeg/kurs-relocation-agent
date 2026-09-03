"""Регресс §2 плана local_context_blind_spots_2026_08_12.md: та же дыра, что уже чинили в
`negotiations.py` (инцидент «ТехВилл», 2026-08-12, commit `9675db7`), нашлась в ручной
классификации архива диалога (`classify_archive_disposition`) — LLM видел только переданную
переписку, не `interview_stages`. Если по вакансии уже стоит запланированный этап,
классификатор теперь не спрашивает LLM вовсе и возвращает `skipped`."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.pipeline import archive_disposition as archive_disposition_mod
from core.domains.pipeline.archive_disposition import classify_archive_disposition
from core.kernel import ports
from tests.fakes import FakeLlm, RaisingLlm


class _Msg:
    def __init__(self, kind: str, body: str) -> None:
        self.kind = kind
        self.body = body


def _with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM-ветка `classify_archive_disposition` требует настроенный ключ — тестовое окружение
    по умолчанию его не задаёт (`.env` локальный, gitignored)."""
    settings = type("S", (), {"openrouter_api_key": "test-key"})()
    monkeypatch.setattr(archive_disposition_mod, "get_settings", lambda: settings)


class _FakeStagesDb:
    """Мок `Executor` — обслуживает только `interview_stages` (то, что читает
    `has_scheduled_interview_stage`); любой другой запрос — ошибка теста."""

    def __init__(self, *, stage_rows: list[dict[str, Any]] | None = None) -> None:
        self._stage_rows = stage_rows or []

    async def fetch(self, sql: str, *_args: Any) -> list[dict[str, Any]]:
        if "from interview_stages" in sql.lower():
            return self._stage_rows
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchrow(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("classify_archive_disposition local-evidence check must not fetchrow")

    async def fetchval(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("classify_archive_disposition local-evidence check must not fetchval")

    async def execute(self, *_a: Any, **_k: Any) -> str:
        raise AssertionError("classify_archive_disposition local-evidence check must not write")

    async def executemany(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("classify_archive_disposition local-evidence check must not write")


def _stage_row(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 6,
        "vacancy_id": "135719770",
        "stage_type": "hr_screening",
        "scheduled_at": None,
        "format": "online",
        "status": "scheduled",
        "position": 0,
        "notes": "",
        "source_message_id": None,
        "created_at": None,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_scheduled_stage_blocks_llm_and_returns_skipped() -> None:
    """Переписка сама по себе звучит как отказ, но встреча уже назначена — LLM не спрашиваем."""
    db = _FakeStagesDb(stage_rows=[_stage_row(status="scheduled")])
    messages = [_Msg("hr_in", "К сожалению, мы вынуждены отказать")]

    with ports.use_ports(llm=RaisingLlm("classify_archive_disposition не должен звать LLM")):
        result = await classify_archive_disposition(
            company="ТехВилл",
            title="Техлид Дата Сайентист",
            messages=messages,
            vacancy_id="135719770",
            account_id=1,
            db=db,
        )

    assert result.disposition == "skipped"
    assert "запланированная встреча" in result.reasoning


@pytest.mark.asyncio
async def test_no_scheduled_stage_falls_through_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без запланированного этапа — прежнее поведение: классификатор доходит до LLM."""
    _with_api_key(monkeypatch)
    db = _FakeStagesDb(stage_rows=[])
    messages = [_Msg("hr_in", "К сожалению, мы вынуждены отказать")]
    llm = FakeLlm(text='{"disposition":"rejected","reasoning":"явный отказ HR"}')

    with ports.use_ports(llm=llm):
        result = await classify_archive_disposition(
            company="ТехВилл",
            title="Техлид Дата Сайентист",
            messages=messages,
            vacancy_id="135719770",
            account_id=1,
            db=db,
        )

    assert result.disposition == "rejected"
    assert llm.calls, "LLM должна была вызваться без локального факта встречи"


@pytest.mark.asyncio
async def test_cancelled_stage_does_not_block_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отменённый этап — не активная встреча, не должен блокировать классификацию."""
    _with_api_key(monkeypatch)
    db = _FakeStagesDb(stage_rows=[_stage_row(status="cancelled")])
    messages = [_Msg("hr_in", "К сожалению, мы вынуждены отказать")]
    llm = FakeLlm(text='{"disposition":"rejected","reasoning":"явный отказ HR"}')

    with ports.use_ports(llm=llm):
        result = await classify_archive_disposition(
            company="ТехВилл",
            title="Техлид Дата Сайентист",
            messages=messages,
            vacancy_id="135719770",
            account_id=1,
            db=db,
        )

    assert result.disposition == "rejected"
    assert llm.calls


@pytest.mark.asyncio
async def test_missing_vacancy_context_skips_local_evidence_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без vacancy_id/account_id (вызывающая сторона их не передала) — проверка тихо
    пропускается, поведение как до этой правки."""
    _with_api_key(monkeypatch)
    messages = [_Msg("hr_in", "К сожалению, мы вынуждены отказать")]
    llm = FakeLlm(text='{"disposition":"rejected","reasoning":"явный отказ HR"}')

    with ports.use_ports(llm=llm):
        result = await classify_archive_disposition(
            company="ТехВилл",
            title="Техлид Дата Сайентист",
            messages=messages,
        )

    assert result.disposition == "rejected"
    assert llm.calls
