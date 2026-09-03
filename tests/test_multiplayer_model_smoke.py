"""Smoke обеих моделей раздела через живой OpenRouter (Э19.8).

Раздел ходит в две модели — «режиссёр» (`MODEL_MULTIPLAYER`: сцена слота, газета) и «актёр»
(`MODEL_MULTIPLAYER_ACTOR`: реплики, судья, реакции). Slug тест не называет: берёт то, что
настроено, и проверяет, годится ли кандидат на роль — отвечает по-русски, укладывается в
лимит слов и не заворачивает фразу в JSON.

Это первое, что стоит прогнать на новой модели перед тем, как ставить её на прод.

Запуск: `uv run pytest -m llm tests/test_multiplayer_model_smoke.py`
(нужны `OPENROUTER_API_KEY` и непустой `MODEL_MULTIPLAYER`).
"""

from __future__ import annotations

import uuid

import pytest

from core.config import get_settings
from core.domains.multiplayer import wolves_llm
from core.domains.multiplayer.models import Phase
from core.domains.multiplayer.rules import start_match
from core.platform.llm.call import CallContext, run

pytestmark = pytest.mark.llm


def _scene() -> tuple[object, str]:
    state = start_match(4242)
    state.phase = Phase.LINES
    state.question_chip = "q_incident"
    seat = next(s for s in state.seats.values() if s.kind.value == "candidate")
    seat.played = list(seat.hand[:1])
    return state, seat.id


async def _say(feature: str, tail: str, model: str) -> str:
    return await run(
        feature,
        dynamic_tail=tail,
        user="Говори:",
        model_override=model,
        ctx=CallContext(skip_cache=True, cache_key=str(uuid.uuid4())),
    )


async def test_actor_model_plays_a_candidate_line() -> None:
    settings = get_settings()
    if not settings.openrouter_api_key.strip():
        pytest.skip("нет OPENROUTER_API_KEY")
    model = settings.multiplayer_actor_model()
    if not model:
        pytest.skip("нет MODEL_MULTIPLAYER/MODEL_MULTIPLAYER_ACTOR")

    state, seat_id = _scene()
    raw = await _say("wolves_line", wolves_llm.build_line_context(state, seat_id), model)
    line = wolves_llm.sanitize_utterance(
        raw, max_words=wolves_llm.LINE_MAX_WORDS, fallback=wolves_llm.FALLBACK_BOT_LINE
    )
    assert line != wolves_llm.FALLBACK_BOT_LINE, f"модель не дала живой реплики: {raw!r}"
    assert not raw.strip().startswith("{"), f"{model} отвечает JSON, промпт просит строку: {raw!r}"
    assert wolves_llm.word_count(line) <= wolves_llm.LINE_MAX_WORDS


async def test_director_model_announces_the_slot() -> None:
    settings = get_settings()
    if not settings.openrouter_api_key.strip():
        pytest.skip("нет OPENROUTER_API_KEY")
    model = settings.multiplayer_model()
    if not model:
        pytest.skip("нет MODEL_MULTIPLAYER")

    state, _ = _scene()
    raw = await _say("wolves_brief", wolves_llm.build_brief_context(state), model)
    brief = wolves_llm.sanitize_utterance(
        raw, max_words=wolves_llm.BRIEF_MAX_WORDS, fallback=wolves_llm.FALLBACK_BRIEF
    )
    assert brief != wolves_llm.FALLBACK_BRIEF, f"режиссёр не объявил день: {raw!r}"
    assert wolves_llm.word_count(brief) <= wolves_llm.BRIEF_MAX_WORDS
