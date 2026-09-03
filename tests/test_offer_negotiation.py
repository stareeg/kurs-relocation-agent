"""RD-17 (plans/frontend_ux_redesign.md): аргументы для торга по офферу. Проверяем чистую
логику без LLM/БД — сборку промпта (факты не выдумываются при отсутствии данных) и парсинг
ответа модели (JSON → NegotiationBrief, мусор в аргументах отфильтровывается).
"""

from __future__ import annotations

import pytest

from core.domains.offers.models import OfferRecord
from core.domains.offers import offer_negotiation
from core.domains.offers.offer_negotiation import (
    _build_system_parts,
    _parse_arguments,
    _parse_response,
    negotiate_offer,
)
from core.kernel import ports
from tests.fakes import FakeLlm


def _offer(**kwargs) -> OfferRecord:
    base = {"vacancy_id": "v1", "company": "Acme", "position": "Lead LLM Engineer"}
    base.update(kwargs)
    return OfferRecord(**base)


def _stub_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_read(account_id: int, db=None):
        return None

    monkeypatch.setattr(
        "core.domains.profile.structured_store.read_resume_data_for_account", fake_read
    )
    monkeypatch.setattr(
        "core.domains.opportunities.prompt.load_candidate_identity",
        lambda **_: "Кандидат",
    )
    monkeypatch.setattr(
        "core.domains.opportunities.prompt.load_candidate_min_salary",
        lambda **_: 400_000,
    )


async def test_prompt_does_not_invent_benchmark_or_others(monkeypatch: pytest.MonkeyPatch):
    _stub_resume(monkeypatch)
    _static, dynamic = await _build_system_parts(
        account_id=1,
        offer=_offer(base_salary=500_000),
        others=[],
        benchmark=None,
        leverage={},
        salary_line="450 000 - 550 000 ₽",
    )
    assert "не выдумывать цифры рынка" in dynamic
    assert "других активных офферов сейчас нет" in dynamic
    assert "450 000 - 550 000" in dynamic


async def test_prompt_includes_other_offers_and_leverage(monkeypatch: pytest.MonkeyPatch):
    _stub_resume(monkeypatch)
    _static, dynamic = await _build_system_parts(
        account_id=1,
        offer=_offer(),
        others=[_offer(vacancy_id="v2", company="OtherCo", base_salary=600_000)],
        benchmark=None,
        leverage={"Техничка": 3, "Оффер": 1},
        salary_line="",
    )
    assert "OtherCo" in dynamic
    assert "На Техничке сейчас: 3" in dynamic
    assert "Активных офферов кроме этого: 1" in dynamic


def test_parse_arguments_filters_incomplete_and_caps_at_five():
    items = [
        {"fact": "База выше медианы рынка на 15%", "wording": "У вас база ниже рыночной"},
        {"fact": "", "wording": "пустой факт - отсеять"},
        {"fact": "нет формулировки"},
        *[{"fact": f"f{i}", "wording": f"w{i}"} for i in range(10)],
    ]
    parsed = _parse_arguments(items)
    assert len(parsed) == 5
    assert parsed[0].fact == "База выше медианы рынка на 15%"


def test_parse_response_strips_code_fences():
    raw = '```json\n{"arguments": [], "draft_message": "текст"}\n```'
    data = _parse_response(raw)
    assert data["draft_message"] == "текст"


async def test_negotiate_offer_requires_api_key(monkeypatch):
    monkeypatch.setattr(
        offer_negotiation, "get_settings", lambda: type("S", (), {"openrouter_api_key": ""})()
    )
    try:
        await negotiate_offer(_offer(), account_id=1)
    except Exception as exc:  # noqa: BLE001 - LlmError без ключа
        assert "OPENROUTER_API_KEY" in str(exc)
    else:
        raise AssertionError("negotiate_offer must raise without an API key")


async def test_negotiate_offer_parses_llm_response(monkeypatch):
    monkeypatch.setattr(
        offer_negotiation, "get_settings", lambda: type("S", (), {"openrouter_api_key": "test"})()
    )
    _stub_resume(monkeypatch)

    llm = FakeLlm(
        text=(
            '{"arguments": [{"fact": "Оффер OtherCo выше на 100k", '
            '"wording": "У меня есть оффер с базой выше"}], '
            '"draft_message": "Прошу пересмотреть базу."}'
        )
    )

    with ports.use_ports(llm=llm):
        brief = await negotiate_offer(
            _offer(), account_id=1, other_offers=[], benchmark=None, leverage={}
        )
    assert llm.features == ["offer_negotiation"]
    assert len(brief.arguments) == 1
    assert brief.draft_message == "Прошу пересмотреть базу."
