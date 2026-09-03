"""Регресс-тест на фикс `_supports_sampling` (DR-7, docs/problems.md).

2026-07-08: Claude 5 Sonnet/Opus (через OpenRouter/Bedrock) отвечали 400, когда payload
одновременно содержал `temperature` и `reasoning.effort` (extended thinking несовместим
с sampling-параметрами у этого семейства). Фикс — `_supports_sampling()` / `_build_payload`
не шлют `temperature`/`top_p`/`top_k` для моделей из `_NO_SAMPLING_MODEL_PREFIXES`.

Без этого теста следующий рефакторинг модуля мог бы тихо вернуть `payload["temperature"]`
безусловно — сценарий проверен вручную (см. DoD в plans/deep_refactor.md, DR-7): тест ниже
падает, если убрать условие `if _supports_sampling(model)` в `_build_payload`.
"""

from __future__ import annotations

import json

import httpx
import pytest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

import core.domains.market.situation as situation
from core.domains.market.market_grid import MarketGrid
from core.domains.market.situation import SituationFacts
from core.platform.llm.openrouter_chat import (
    OpenRouterChatModel,
    _extract_json_object,
    _StructuredOutputRunnable,
    _supports_sampling,
)


def _model(**overrides) -> OpenRouterChatModel:
    kwargs = {
        "primary_model": "anthropic/claude-sonnet-5",
        "api_key": "test-key",
        "temperature": 0.3,
    }
    kwargs.update(overrides)
    return OpenRouterChatModel(**kwargs)


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-sonnet-5",
        "anthropic/claude-opus-4-8",
        "anthropic/claude-opus-4-7",
        "anthropic/claude-fable-5",
        "anthropic/claude-mythos-5",
    ],
)
def test_no_sampling_models_omit_temperature(model: str) -> None:
    assert _supports_sampling(model) is False
    llm = _model(primary_model=model, reasoning_effort="medium")
    payload = llm._build_payload([HumanMessage(content="hi")], model, None, {})
    assert "temperature" not in payload
    assert payload["reasoning"] == {"effort": "medium"}


@pytest.mark.parametrize(
    "model",
    ["openai/gpt-5.6-luna", "google/gemini-3.7-flash"],
)
def test_sampling_capable_models_keep_temperature(model: str) -> None:
    assert _supports_sampling(model) is True
    llm = _model(primary_model=model, temperature=0.42)
    payload = llm._build_payload([HumanMessage(content="hi")], model, None, {})
    assert payload["temperature"] == 0.42


def test_reasoning_effort_omitted_when_not_configured() -> None:
    llm = _model(reasoning_effort=None)
    payload = llm._build_payload(
        [HumanMessage(content="hi")], "anthropic/claude-sonnet-5", None, {}
    )
    assert "reasoning" not in payload


@pytest.mark.asyncio
async def test_reasoning_disable_is_best_effort_not_fatal() -> None:
    """Э19: 400 «reasoning нельзя выключить» — не повод ронять вызов.

    Отключение thinking это оптимизация. Часть эндпоинтов её запрещает, и раньше такой
    провайдер намертво рвал цепочку деградации: игра падала в статическую заглушку каждый
    раз, когда основную модель придерживал rate-limit.
    """
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        if "reasoning" in payload:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Reasoning is mandatory for this endpoint "
                        "and cannot be disabled.",
                        "code": 400,
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            },
        )

    llm = _model(reasoning_effort="none")
    llm._transport = httpx.MockTransport(handler)
    result = await llm.ainvoke([HumanMessage(content="hi")])

    assert result.content == "ok"
    assert len(seen) == 2, "должен быть ровно один повтор — без флага reasoning"
    assert seen[0]["reasoning"] == {"enabled": False}
    assert "reasoning" not in seen[1]


def test_reasoning_none_disables_thinking_not_sets_effort_none() -> None:
    """`effort: "none"` — несуществующее значение у OpenRouter: модель продолжает думать.

    Фичи, которым думать не надо (раздел «Мультиплеер»), объявляют `reasoning_effort="none"`.
    В запрос это обязано уходить как `reasoning.enabled = false` — единственная форма, которую
    OpenRouter транслирует в родной флаг провайдера (Qwen `enable_thinking`, DeepSeek — свой).
    Иначе скрытый reasoning съедает max_tokens и при json_schema возвращается пустой content,
    а фича молча падает в fallback-строку.
    """
    llm = _model(reasoning_effort="none")
    payload = llm._build_payload([HumanMessage(content="hi")], "qwen/qwen3.8-flash", None, {})
    assert payload["reasoning"] == {"enabled": False}
    assert payload["reasoning"] != {"effort": "none"}


@pytest.mark.asyncio
async def test_stream_drops_reasoning_flag_instead_of_dying() -> None:
    """Э19.8: тот же best-effort, что и в обычном вызове, но для стрима.

    Найдено живым прогоном: `wolves_line` стримится, основную модель придержал upstream 429,
    запасная ответила `400 Reasoning is mandatory…` — и стрим обрывал всю цепочку деградации,
    хотя достаточно было снять флаг. Отдельная ловушка: у `client.stream(...)` тело ошибки не
    прочитано, `resp.text` бросает `ResponseNotRead`, и без явного `aread()` причину 400
    вообще не видно — в логах стояло «<тело недоступно>».
    """
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        if "reasoning" in payload:
            return httpx.Response(
                400,
                json={"error": {"message": "Reasoning is mandatory for this endpoint", "code": 400}},
            )
        body = (
            'data: {"choices":[{"delta":{"content":"Уронил прод"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":" в пятницу."}}]}\n\n'
            'data: {"usage":{"prompt_tokens":9,"completion_tokens":4}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    llm = _model(primary_model="qwen/qwen3.8-flash", reasoning_effort="none")
    llm._transport = httpx.MockTransport(handler)

    chunks = [c.message.content async for c in llm._astream([HumanMessage(content="hi")])]

    assert "".join(chunks) == "Уронил прод в пятницу."
    assert len(seen) == 2, "должен быть ровно один повтор — без флага reasoning"
    assert seen[0]["reasoning"] == {"enabled": False}
    assert "reasoning" not in seen[1]
    assert seen[1]["model"] == "qwen/qwen3.8-flash", "повтор идёт в ту же модель, не в запасную"


@pytest.mark.asyncio
async def test_stream_falls_through_to_the_next_model() -> None:
    """Если та же модель не спаслась и без флага — цепочка деградации идёт дальше."""
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        attempts.append(payload["model"])
        if payload["model"] == "qwen/qwen3.8-flash":
            return httpx.Response(429, json={"error": {"message": "rate-limited", "code": 429}})
        body = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    llm = _model(
        primary_model="qwen/qwen3.8-flash",
        fallback_model="tencent/hy3",
        reasoning_effort="none",
    )
    llm._transport = httpx.MockTransport(handler)

    chunks = [c.message.content async for c in llm._astream([HumanMessage(content="hi")])]

    assert "".join(chunks) == "ok"
    assert attempts[-1] == "tencent/hy3"


def test_models_to_try_builds_tier_aware_chain() -> None:
    """LLM-1: primary → тир-фолбэк → глобальный фолбэк, без дублей."""
    llm = _model(
        primary_model="anthropic/claude-sonnet-5",
        tier_fallback_model="openai/gpt-5.6-luna",
        fallback_model="google/gemini-3.7-flash",
    )
    assert llm._models_to_try() == [
        "anthropic/claude-sonnet-5",
        "openai/gpt-5.6-luna",
        "google/gemini-3.7-flash",
    ]


def test_models_to_try_dedupes_when_tier_fallback_matches_global() -> None:
    llm = _model(
        primary_model="anthropic/claude-sonnet-5",
        tier_fallback_model="google/gemini-3.7-flash",
        fallback_model="google/gemini-3.7-flash",
    )
    assert llm._models_to_try() == [
        "anthropic/claude-sonnet-5",
        "google/gemini-3.7-flash",
    ]


def test_models_to_try_without_tier_fallback_matches_old_behavior() -> None:
    llm = _model(primary_model="anthropic/claude-sonnet-5", fallback_model="google/gemini-3.7-flash")
    assert llm._models_to_try() == ["anthropic/claude-sonnet-5", "google/gemini-3.7-flash"]


@pytest.mark.asyncio
async def test_agenerate_falls_through_tier_fallback_to_global_fallback() -> None:
    """Primary отдаёт `400 Schema is too complex` (живой инцидент 2026-07-16), тир-фолбэк тоже
    падает — `_agenerate` обязан дойти до третьей модели (глобальный фолбэк), а не сдаться после
    второй попытки."""
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        model = payload["model"]
        attempts.append(model)
        if model in ("anthropic/claude-sonnet-5", "openai/gpt-5.6-luna"):
            return httpx.Response(
                400, json={"error": {"message": "Schema is too complex.", "code": 400}}
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    llm = _model(
        primary_model="anthropic/claude-sonnet-5",
        tier_fallback_model="openai/gpt-5.6-luna",
        fallback_model="google/gemini-3.7-flash",
        max_retries=1,
    )
    llm._transport = httpx.MockTransport(handler)

    result = await llm.ainvoke([HumanMessage(content="hi")])

    assert result.content == "ok"
    assert attempts == [
        "anthropic/claude-sonnet-5",
        "openai/gpt-5.6-luna",
        "google/gemini-3.7-flash",
    ]


@pytest.mark.asyncio
async def test_agenerate_sends_payload_without_temperature_over_wire() -> None:
    """Полный путь `_agenerate` через мок httpx-транспорта (без реальной сети) —
    ловит регрессии не только в `_build_payload`, но и в сборке запроса вокруг него."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    llm = _model(reasoning_effort="medium")
    llm._transport = httpx.MockTransport(handler)

    result = await llm.ainvoke([HumanMessage(content="hi")])

    assert result.content == "ok"
    assert "temperature" not in captured["payload"]
    assert captured["payload"]["reasoning"] == {"effort": "medium"}
    assert captured["payload"]["model"] == "anthropic/claude-sonnet-5"


# --- LLM-2: устойчивый парсинг JSON от слабых/неточных моделей ---


class _Point(BaseModel):
    x: int
    y: int


@pytest.mark.parametrize(
    "raw",
    [
        '{"x": 1, "y": 2}',
        '```json\n{"x": 1, "y": 2}\n```',
        '```\n{"x": 1, "y": 2}\n```',
        'Вот JSON:\n```json\n{"x": 1, "y": 2}\n```\nНадеюсь, помогло!',
        'Конечно! {"x": 1, "y": 2} — это ответ.',
    ],
)
def test_extract_json_object_recovers_wrapped_json(raw: str) -> None:
    extracted = _extract_json_object(raw)
    assert json.loads(extracted) == {"x": 1, "y": 2}


def test_extract_json_object_leaves_broken_text_untouched() -> None:
    """Пустой/битый текст без парного JSON внутри — не проглатывать молча, вернуть как есть,
    чтобы вызывающий код бросил исходную ошибку и ушёл в retry-цикл."""
    assert _extract_json_object("") == ""
    broken = "Извините, не могу выполнить запрос."
    assert _extract_json_object(broken) == broken


@pytest.mark.asyncio
async def test_structured_output_parses_markdown_wrapped_json() -> None:
    """Живой инцидент 2026-07-16: `Expecting value: line 157 column 1` — фолбэк-модель обернула
    валидный JSON в ```json-фенс с преамбулой/послесловием. Раньше `_parse` падал сразу; теперь
    `_extract_json_object` должен вычленить объект до Pydantic-валидации."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": 'Вот JSON:\n```json\n{"x": 1, "y": 2}\n```\nНадеюсь, помогло!'
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    llm = _model()
    llm._transport = httpx.MockTransport(handler)
    runnable = _StructuredOutputRunnable(llm, _Point)

    result = await runnable.ainvoke([HumanMessage(content="hi")])

    assert result == _Point(x=1, y=2)


# --- LLM-4: регресс-тест на класс ошибки «Schema is too complex» через полный путь
# generate_situation_narrative (тир-фолбэк + LLM-2 устойчивый парсинг). Живой инцидент
# 2026-07-16, docs/problems.md. D-08: схема сводки урезана до 2 полей, split diagnosis/actions
# снят — теперь один structured-вызов на попытку.


_FAKE_SETTINGS = type("_FakeSettings", (), {"openrouter_api_key": "test-key"})()

_NARRATIVE_JSON = {
    "conclusion": "тест сводки",
    "steps": [
        {
            "text": "поменять поведение",
            "target": {"section": "jobs", "params": {}},
        }
    ],
}


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def _situation_llm() -> OpenRouterChatModel:
    return _model(
        primary_model="anthropic/claude-sonnet-5",
        tier_fallback_model="openai/gpt-5.6-luna",
        fallback_model="google/gemini-3.7-flash",
        temperature=0.4,
        max_retries=1,
    )


async def _run_narrative(monkeypatch: pytest.MonkeyPatch, llm: OpenRouterChatModel):
    monkeypatch.setattr(
        situation,
        "gather_situation_facts",
        lambda **_kw: _facts(),
    )
    monkeypatch.setattr(situation, "_load_prompt", lambda _cfg, **_kw: "SYSTEM PROMPT")
    # A-07: situation зовёт run(); подменяем фабрику модели внутри call.
    import core.platform.llm.call as llm_call

    monkeypatch.setattr(llm_call, "chat_model_for", lambda *_a, **_kw: llm)
    return await situation.generate_situation_narrative(account_id=1, settings=_FAKE_SETTINGS)


async def _facts() -> SituationFacts:
    return SituationFacts(grid=MarketGrid(available=True))


@pytest.mark.asyncio
async def test_situation_narrative_survives_schema_too_complex_on_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Живой инцидент 2026-07-16: primary (`claude-sonnet-5`) отдаёт ровно тот payload из лога
    (`400 Schema is too complex`). Тир-фолбэк (`gpt-5.6-luna`) отвечает валидным JSON —
    сводка обязана долететь до результата, а не упасть, как это было до LLM-1."""
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        model = payload["model"]
        attempts.append(model)
        if model == "anthropic/claude-sonnet-5":
            return httpx.Response(
                400, json={"error": {"message": "Schema is too complex.", "code": 400}}
            )
        return _chat_response(json.dumps(_NARRATIVE_JSON, ensure_ascii=False))

    llm = _situation_llm()
    llm._transport = httpx.MockTransport(handler)

    narrative = await _run_narrative(monkeypatch, llm)

    assert narrative.conclusion == "тест сводки"
    assert narrative.steps[0].text == "поменять поведение"
    assert narrative.steps[0].target.section == "jobs"
    assert set(attempts) == {"anthropic/claude-sonnet-5", "openai/gpt-5.6-luna"}


@pytest.mark.asyncio
async def test_situation_narrative_survives_markdown_wrapped_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Второй живой инцидент того же дня: `Expecting value: line 157 column 1` — модель (что
    primary, что тир-фолбэк) обернула валидный JSON в ```json-фенс с преамбулой/послесловием.
    `_extract_json_object` обязан вычленить объект вне зависимости от того, какая именно
    модель в цепочке ответила."""

    def handler(request: httpx.Request) -> httpx.Response:
        wrapped = (
            "Вот результат:\n```json\n"
            + json.dumps(_NARRATIVE_JSON, ensure_ascii=False)
            + "\n```\nНадеюсь, помогло!"
        )
        return _chat_response(wrapped)

    llm = _situation_llm()
    llm._transport = httpx.MockTransport(handler)

    narrative = await _run_narrative(monkeypatch, llm)

    assert narrative.conclusion == "тест сводки"
    assert narrative.steps[0].text == "поменять поведение"
