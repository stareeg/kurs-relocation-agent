"""L-19: хэш входа рядом со скрининг-пакетом и prep-pack — совпадение хэша не зовёт LLM."""

from __future__ import annotations

import pytest

from core.domains.preparation import scenarios as prep_scenarios
from core.domains.preparation.prep_pack import PrepPackDocument
from core.domains.preparation.screening import scenarios as screening
from core.domains.preparation.screening_questions import SavedScreeningQuestions
from core.kernel.hashing import input_digest

VACANCY_TEXT = "python, fastapi, postgres, требуется опытный бэкенд-разработчик в команду"


def test_input_digest_is_deterministic_and_sensitive_to_input() -> None:
    a = input_digest("title", "company", "text", "summary")
    b = input_digest("title", "company", "text", "summary")
    c = input_digest("title", "company", "other text", "summary")
    assert a == b
    assert a != c


# --------------------------------------------------------------------------- скрининг-пакет


async def _no_record(vacancy_id: str, *, account_id=None):  # load_record fallback: тест не трогает PG
    return None


@pytest.mark.asyncio
async def test_generate_pack_skips_llm_when_input_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vacancy_id = "v1"
    title, company = "Backend", "Acme"
    digest = input_digest(title, company, VACANCY_TEXT, "")

    saved = SavedScreeningQuestions(
        vacancy_id=vacancy_id,
        groups=[{"title": "g", "hook": "h", "questions": []}],
        hr_questions=[{"question": "q?", "intent": "i", "draft_answer": "a"}],
        why_company="почему сюда",
        oral_pitch="рассказ",
        pitch_blocks=[],
        jd_brief={},
        input_hash=digest,
    )

    async def _fake_get(vid: str, *, account_id=None, db=None):
        assert vid == vacancy_id
        return saved

    async def _boom(**kwargs):
        raise AssertionError("generate_self_pres_pack не должен зваться при неизменном входе")

    monkeypatch.setattr(screening, "load_record", _no_record)
    monkeypatch.setattr(screening, "get_screening_questions", _fake_get)
    monkeypatch.setattr(screening, "generate_self_pres_pack", _boom)

    pack = await screening.generate_pack(
        vacancy_id, title=title, company=company, vacancy_text=VACANCY_TEXT, account_id=1
    )
    assert pack.oral_pitch == "рассказ"
    assert pack.why_company == "почему сюда"
    assert pack.input_hash == digest


@pytest.mark.asyncio
async def test_generate_pack_calls_llm_when_input_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    vacancy_id = "v1"
    title, company = "Backend", "Acme"
    stale_saved = SavedScreeningQuestions(
        vacancy_id=vacancy_id,
        groups=[{"title": "g", "hook": "h", "questions": []}],
        hr_questions=[],
        why_company="старое",
        oral_pitch="старый рассказ",
        pitch_blocks=[],
        jd_brief={},
        input_hash="совсем-другой-хэш",
    )

    async def _fake_get(vid: str, *, account_id=None, db=None):
        return stale_saved

    called = {}

    async def _fake_generate(**kwargs):
        called["yes"] = True
        from core.domains.preparation.screening.pack import VacancySelfPres

        return VacancySelfPres(vacancy_id=vacancy_id, oral_pitch="новый рассказ")

    monkeypatch.setattr(screening, "load_record", _no_record)
    monkeypatch.setattr(screening, "get_screening_questions", _fake_get)
    monkeypatch.setattr(screening, "generate_self_pres_pack", _fake_generate)

    pack = await screening.generate_pack(
        vacancy_id, title=title, company=company, vacancy_text=VACANCY_TEXT, account_id=1
    )
    assert called.get("yes") is True
    assert pack.oral_pitch == "новый рассказ"


@pytest.mark.asyncio
async def test_generate_pack_calls_llm_when_no_saved_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get(vid: str, *, account_id=None, db=None):
        return None

    called = {}

    async def _fake_generate(**kwargs):
        called["yes"] = True
        from core.domains.preparation.screening.pack import VacancySelfPres

        return VacancySelfPres(vacancy_id="v1", oral_pitch="первый рассказ")

    monkeypatch.setattr(screening, "load_record", _no_record)
    monkeypatch.setattr(screening, "get_screening_questions", _fake_get)
    monkeypatch.setattr(screening, "generate_self_pres_pack", _fake_generate)

    pack = await screening.generate_pack(
        "v1", title="Backend", company="Acme", vacancy_text=VACANCY_TEXT, account_id=1
    )
    assert called.get("yes") is True
    assert pack.oral_pitch == "первый рассказ"


# --------------------------------------------------------------------------- prep-pack


def _ref() -> prep_scenarios.VacancyRef:
    return prep_scenarios.VacancyRef(
        vacancy_id="v1",
        vacancy_text=VACANCY_TEXT,
        title="Backend",
        company="Acme",
    )


@pytest.mark.asyncio
async def test_regenerate_prep_pack_skips_llm_when_input_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref()
    stage = "tech"
    digest = prep_scenarios._prep_pack_input_hash(ref, stage)
    saved = PrepPackDocument(
        vacancy_id=ref.vacancy_id, stage=stage, content="старый бриф", input_hash=digest
    )

    async def _fake_get_prep_pack(vacancy_id: str, stage_: str, *, account_id=None, db=None):
        return saved

    async def _boom(record, stage_, profile=None, *, account_id=None):
        raise AssertionError("generate_prep_pack не должен зваться при неизменном входе")

    monkeypatch.setattr(prep_scenarios, "get_prep_pack", _fake_get_prep_pack)
    monkeypatch.setattr(prep_scenarios, "generate_prep_pack", _boom)

    text, returned_hash = await prep_scenarios.regenerate_prep_pack(ref, stage, account_id=1)
    assert text == "старый бриф"
    assert returned_hash == digest


@pytest.mark.asyncio
async def test_regenerate_prep_pack_calls_llm_when_input_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref()
    stage = "tech"
    saved = PrepPackDocument(
        vacancy_id=ref.vacancy_id, stage=stage, content="старый бриф", input_hash="stale-hash"
    )

    async def _fake_get_prep_pack(vacancy_id: str, stage_: str, *, account_id=None, db=None):
        return saved

    called = {}

    async def _fake_generate(record, stage_, profile=None, *, account_id=None):
        called["yes"] = True
        return "новый бриф"

    monkeypatch.setattr(prep_scenarios, "get_prep_pack", _fake_get_prep_pack)
    monkeypatch.setattr(prep_scenarios, "generate_prep_pack", _fake_generate)

    text, digest = await prep_scenarios.regenerate_prep_pack(ref, stage, account_id=1)
    assert called.get("yes") is True
    assert text == "новый бриф"
    assert digest == prep_scenarios._prep_pack_input_hash(ref, stage)


@pytest.mark.asyncio
async def test_regenerate_prep_pack_calls_llm_when_no_saved_pack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = _ref()
    stage = "tech"

    async def _fake_get_prep_pack(vacancy_id: str, stage_: str, *, account_id=None, db=None):
        return PrepPackDocument(vacancy_id=ref.vacancy_id, stage=stage)

    called = {}

    async def _fake_generate(record, stage_, profile=None, *, account_id=None):
        called["yes"] = True
        return "первый бриф"

    monkeypatch.setattr(prep_scenarios, "get_prep_pack", _fake_get_prep_pack)
    monkeypatch.setattr(prep_scenarios, "generate_prep_pack", _fake_generate)

    text, _digest = await prep_scenarios.regenerate_prep_pack(ref, stage, account_id=1)
    assert called.get("yes") is True
    assert text == "первый бриф"
