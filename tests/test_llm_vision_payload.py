"""Картинки в LLM-вызове (Этап 1, `plans/chat_image_attachments_2026_08_03.md`).

Э1-3 (`core/platform/llm/call.py`): контентные блоки текущей реплики + различение по sha256
в ключе кэша/single-flight. Ловушки 1.1/1.2 (`_render_content`/`_preflight_guards`,
`openrouter_chat.py`) — Э1-4, покрыты ниже отдельным классом.
"""

from __future__ import annotations

import base64

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.platform.llm.call import ImageInput, _attach_images, _cache_key, run
from core.platform.llm.openrouter_chat import (
    OpenRouterError,
    OpenRouterChatModel,
    _render_content,
)
from core.platform.llm.registry import LlmFeature, register, unregister_for_tests


@pytest.fixture
def temp_feature():
    created: list[str] = []

    def _make(**kwargs) -> LlmFeature:
        feature = register(LlmFeature(**kwargs))
        created.append(feature.name)
        return feature

    yield _make
    for name in created:
        unregister_for_tests(name)


def _img(sha: str, data: bytes = b"\x89PNG") -> ImageInput:
    return ImageInput(sha256=sha, mime="image/webp", data=data)


def test_attach_images_puts_content_blocks_on_last_human_message():
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="что на скрине?"),
    ]
    out = _attach_images(messages, [_img("aaa"), _img("bbb")])
    last = out[-1]
    assert isinstance(last, HumanMessage)
    assert isinstance(last.content, list)
    assert last.content[0] == {"type": "text", "text": "что на скрине?"}
    assert last.content[1]["type"] == "image_url"
    assert last.content[1]["image_url"]["url"].startswith("data:image/webp;base64,")
    assert len(last.content) == 3


def test_attach_images_targets_last_human_message_not_earlier_ones():
    messages = [
        HumanMessage(content="первый вопрос"),
        AIMessage(content="ответ"),
        HumanMessage(content="второй вопрос"),
    ]
    out = _attach_images(messages, [_img("ccc")])
    assert out[0].content == "первый вопрос"
    assert isinstance(out[2].content, list)
    assert out[2].content[0]["text"] == "второй вопрос"


def test_attach_images_without_images_is_noop():
    messages = [HumanMessage(content="привет")]
    out = _attach_images(messages, [])
    assert out is messages


def test_attach_images_without_human_message_raises():
    with pytest.raises(ValueError):
        _attach_images([SystemMessage(content="sys")], [_img("ddd")])


def test_cache_key_differs_for_different_images_same_text(temp_feature):
    """Ловушка 1.3: два разных скрина с одинаковой подписью не должны схлопнуться в один ключ."""
    feat = temp_feature(
        name="_test_vision_cache_key",
        tier="basic",
        max_tokens=1024,
        budget_ms=5_000,
        prompt_in_code=True,
    )
    common = dict(
        feature=feat,
        system_text="sys",
        user_text="что тут?",
        schema=None,
        temperature=0.0,
        max_tokens=1024,
        ctx=None,
    )
    key_a = _cache_key(**common, images=[_img("aaa")])
    key_b = _cache_key(**common, images=[_img("bbb")])
    key_none = _cache_key(**common, images=[])
    assert len({key_a, key_b, key_none}) == 3


def test_cache_key_stable_for_same_images(temp_feature):
    feat = temp_feature(
        name="_test_vision_cache_key_stable",
        tier="basic",
        max_tokens=1024,
        budget_ms=5_000,
        prompt_in_code=True,
    )
    common = dict(
        feature=feat,
        system_text="sys",
        user_text="что тут?",
        schema=None,
        temperature=0.0,
        max_tokens=1024,
        ctx=None,
    )
    assert _cache_key(**common, images=[_img("aaa")]) == _cache_key(**common, images=[_img("aaa")])


@pytest.mark.asyncio
async def test_run_complete_with_images_sends_content_blocks(temp_feature):
    captured: dict = {}

    class _FakeChat:
        async def ainvoke(self, messages, config=None):
            captured["messages"] = messages

            class _Msg:
                content = "вижу код ABC123"

            return _Msg()

    feat = temp_feature(
        name="_test_vision_complete",
        tier="basic",
        max_tokens=1024,
        budget_ms=5_000,
        prompt_in_code=True,
    )
    text = await run(
        feat,
        user="что на скрине?",
        model=_FakeChat(),  # type: ignore[arg-type]
        images=[_img("eee", data=b"pngbytes")],
    )
    assert text == "вижу код ABC123"
    last = captured["messages"][-1]
    assert isinstance(last, HumanMessage)
    assert isinstance(last.content, list)
    kinds = [b["type"] for b in last.content]
    assert kinds == ["text", "image_url"]


@pytest.mark.asyncio
async def test_run_stream_with_images_attaches_before_streaming(temp_feature):
    captured: dict = {}

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeChat:
        async def astream(self, messages, config=None):
            captured["messages"] = messages
            for piece in ("о", "к"):
                yield _Chunk(piece)

    feat = temp_feature(
        name="_test_vision_stream",
        tier="basic",
        max_tokens=1024,
        budget_ms=5_000,
        prompt_in_code=True,
    )
    stream = await run(
        feat,
        user="разбери схему",
        stream=True,
        model=_FakeChat(),  # type: ignore[arg-type]
        images=[_img("fff")],
    )
    parts = [p async for p in stream]
    assert "".join(parts) == "ок"
    last = captured["messages"][-1]
    assert isinstance(last.content, list)
    assert last.content[-1]["type"] == "image_url"


def _data_url(n_bytes: int) -> str:
    payload = base64.b64encode(b"\x00" * n_bytes).decode("ascii")
    return f"data:image/webp;base64,{payload}"


def _model(**overrides) -> OpenRouterChatModel:
    kwargs = {"primary_model": "google/gemini-3.7-flash", "api_key": "test-key"}
    kwargs.update(overrides)
    return OpenRouterChatModel(**kwargs)


class TestRenderContentKeepsImages:
    """Ловушка 1.1: `_render_content` больше не роняет image_url для провайдеров без
    cache_control (раньше «схлопывание» оставляло только type == 'text')."""

    def test_no_cache_control_support_keeps_image_block(self):
        content = [
            {"type": "text", "text": "что на скрине?"},
            {"type": "image_url", "image_url": {"url": "data:image/webp;base64,AAAA"}},
        ]
        rendered = _render_content(content, allow_cache_control=False)
        types = [b["type"] for b in rendered]
        assert types == ["text", "image_url"]

    def test_no_cache_control_support_strips_only_cache_control_key(self):
        content = [
            {"type": "text", "text": "static", "cache_control": {"type": "ephemeral"}},
            {"type": "image_url", "image_url": {"url": "data:image/webp;base64,AAAA"}},
        ]
        rendered = _render_content(content, allow_cache_control=False)
        assert "cache_control" not in rendered[0]
        assert rendered[0]["text"] == "static"
        assert rendered[1]["image_url"]["url"] == "data:image/webp;base64,AAAA"

    def test_cache_control_support_keeps_key_as_is(self):
        content = [{"type": "text", "text": "static", "cache_control": {"type": "ephemeral"}}]
        rendered = _render_content(content, allow_cache_control=True)
        assert rendered[0]["cache_control"] == {"type": "ephemeral"}

    def test_fallback_model_family_actually_preserves_image(self):
        """Прогон через реальный код сборки сообщений, не только `_render_content` напрямую —
        `google/gemini-3.7-flash` (текущий OPENROUTER_MODEL_FALLBACK) не в списке
        `supports_cache_control`, это и есть та самая ветка «схлопнуть»."""
        llm = _model()
        messages = [
            HumanMessage(
                content=[
                    {"type": "text", "text": "прочитай код"},
                    {"type": "image_url", "image_url": {"url": _data_url(64)}},
                ]
            )
        ]
        payload = llm._build_payload(messages, llm.primary_model, None, {})
        rendered = payload["messages"][0]["content"]
        assert any(b.get("type") == "image_url" for b in rendered)


class TestPreflightGuardsSeparatesImages:
    """Ловушка 1.2: `_preflight_guards` больше не считает base64 картинки текстовыми
    символами — раньше один скриншот сам по себе пробивал `llm_max_input_chars`."""

    def test_large_image_does_not_trip_text_char_limit(self):
        llm = _model()
        # ~600 КБ картинки → ≈820000 base64-символов (пример из §1.5 плана), но текста мало.
        messages = [
            HumanMessage(
                content=[
                    {"type": "text", "text": "что тут?"},
                    {"type": "image_url", "image_url": {"url": _data_url(600_000)}},
                ]
            )
        ]
        llm._preflight_guards(messages, agent="test")  # не должно бросить

    def test_text_only_still_trips_char_limit(self):
        llm = _model()
        messages = [HumanMessage(content="a" * 900_000)]
        with pytest.raises(OpenRouterError):
            llm._preflight_guards(messages, agent="test")

    def test_too_many_images_trips_count_limit(self):
        llm = _model()
        blocks = [
            {"type": "image_url", "image_url": {"url": _data_url(16)}} for _ in range(11)
        ]
        messages = [HumanMessage(content=blocks)]
        with pytest.raises(OpenRouterError):
            llm._preflight_guards(messages, agent="test")

    def test_huge_total_image_bytes_trips_byte_limit(self):
        llm = _model()
        messages = [
            HumanMessage(
                content=[{"type": "image_url", "image_url": {"url": _data_url(41 * 1024 * 1024)}}]
            )
        ]
        with pytest.raises(OpenRouterError):
            llm._preflight_guards(messages, agent="test")
