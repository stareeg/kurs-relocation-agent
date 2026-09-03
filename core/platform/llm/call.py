"""Единая точка вызова LLM: `run(feature, …)`.

Домены не зовут `ainvoke` / `with_structured_output` / `astream` напрямую — только `run`
(или тонкие `complete_*`, которые делегируют сюда).

Внутри: сборка system из `LlmFeature.prompt` + `system_vars`/`prompt_vars` (`{{TOKEN}}`),
prompt caching (`cache_prefix`),
structured output, таймаут `budget_ms`, ретраи модели, метрики, single-flight,
кэш результатов.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from contextvars import Token
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast, overload

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from core.platform.cache.result_cache import DEFAULT_TTL_S, get_result_cache
from core.platform.cache.single_flight import get_single_flight
from core.platform.llm.prompt_cache import build_cached_system_prompt
from core.platform.llm.registry import LlmFeature, chat_model_for, require_feature
from core.platform.llm.usage import (
    UsageFact,
    begin_usage_capture,
    default_usage_sink,
    end_usage_capture,
    flush_usage_capture,
)
from core.platform.observability import event
from core.platform.observability.request_timing import record_llm_ms

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[3]

_ROLE_TO_MESSAGE = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}


@dataclass(slots=True)
class CallContext:
    """Опциональный контекст вызова: ключ кэша/single-flight и метаданные метрик."""

    cache_key: str | None = None
    skip_cache: bool = False
    skip_single_flight: bool = False
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImageInput:
    """Картинка мультимодального вызова — платформенный двойник `core.kernel.ports.ImageInput`.

    `platform` не имеет права импортировать `kernel`, поэтому тип дублируется здесь;
    конвертацию между ними делает `core.app.wiring.PlatformLlm` (единственное место, которое
    знает про оба слоя).
    """

    sha256: str
    mime: str
    data: bytes


def _attach_images(messages: list[BaseMessage], images: Sequence[ImageInput]) -> list[BaseMessage]:
    """Картинки текущей реплики уходят в последний `HumanMessage` как content-блоки.

    Только последний — потому что `user=`/хвост `messages=` это всегда текущий ход диалога;
    картинки прежних реплик приходят текстом через `analysis.title/text` (см. план вложений,
    §3), не пикселями — иначе каждый следующий вопрос переотправлял бы весь альбом.
    """
    if not images:
        return messages
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if not isinstance(msg, HumanMessage):
            continue
        text = _text_of(msg)
        blocks: list[str | dict[Any, Any]] = []
        if text:
            blocks.append({"type": "text", "text": text})
        for img in images:
            b64 = base64.b64encode(img.data).decode("ascii")
            blocks.append(
                {"type": "image_url", "image_url": {"url": f"data:{img.mime};base64,{b64}"}}
            )
        messages[i] = HumanMessage(content=blocks)
        return messages
    raise ValueError("run(): images переданы, но в messages нет ни одного user-сообщения")


def _text_of(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content or "")


def _to_messages(
    messages: Sequence[BaseMessage | dict[str, str]] | None,
) -> list[BaseMessage]:
    if not messages:
        return []
    out: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, BaseMessage):
            out.append(msg)
            continue
        cls = _ROLE_TO_MESSAGE.get(msg.get("role", "user"), HumanMessage)
        out.append(cls(content=msg.get("content", "")))
    return out


# Включение общего куска промпта: строка вида `{{include: prompts/<домен>/<файл>.md}}`
# целиком заменяется содержимым файла. Заведено под Э19: у трёх фич multiplayer общий канон
# (мир игры, тон, бан-лист, few-shot), и до этого он лежал отдельным файлом с пометкой
# «копируется в line/judge/ticker вручную» — то есть по факту не применялся нигде.
# Путь — от корня репозитория, как и `LlmFeature.prompt`.
_INCLUDE_RE = re.compile(r"(?m)^[ \t]*\{\{\s*include:\s*(?P<path>[^}\s]+)\s*\}\}[ \t]*$")
_MAX_INCLUDE_DEPTH = 3


def _read_prompt_file(path: str, *, depth: int) -> str:
    full = Path(path) if Path(path).is_absolute() else _ROOT / path
    if not full.is_file():
        raise FileNotFoundError(f"Промпт фичи не найден: {path}")
    text = full.read_text(encoding="utf-8")
    if "{{include:" not in text:
        return text
    if depth >= _MAX_INCLUDE_DEPTH:
        raise RecursionError(
            f"Промпт {path}: вложенность include глубже {_MAX_INCLUDE_DEPTH} — вероятно, цикл"
        )
    # repl-функция: возвращаемый текст подставляется буквально, escape-последовательности
    # внутри промпта (например, \n в примере JSON) не интерпретируются.
    return _INCLUDE_RE.sub(
        lambda m: _read_prompt_file(m.group("path"), depth=depth + 1).strip(), text
    )


@lru_cache(maxsize=64)
def _load_prompt_template(path: str) -> str:
    """Текст промпта с раскрытыми include.

    Кэш на раскрытом тексте важен для `_prompt_version`: хэш идёт по итоговому промпту,
    поэтому правка общего канона инвалидирует кэш результатов всех фич, которые его
    включают, а не только той, чей файл изменился.
    """
    return _read_prompt_file(path, depth=0)


def _format_prompt(template: str, system_vars: dict[str, Any] | None) -> str:
    if not system_vars:
        return template
    try:
        return template.format(**system_vars)
    except KeyError:
        # Частичный format — не роняем вызов, оставляем шаблон как есть для caller'а.
        return template


def _apply_prompt_vars(text: str, prompt_vars: Mapping[str, str] | None) -> str:
    """Подстановка `{{TOKEN}}` — соглашение файлов `prompts/` (не `str.format`: в промптах
    встречаются фигурные скобки JSON-примеров)."""
    if not prompt_vars:
        return text
    for key, value in prompt_vars.items():
        token = key if key.startswith("{{") else f"{{{{{key}}}}}"
        text = text.replace(token, value)
    return text


def _build_system_message(
    feature: LlmFeature,
    *,
    system: str | None,
    system_vars: dict[str, Any] | None,
    prompt_vars: Mapping[str, str] | None,
    dynamic_tail: str,
) -> SystemMessage | None:
    text = system
    if text is None and feature.prompt:
        text = _format_prompt(_load_prompt_template(feature.prompt), system_vars)
    elif text is None:
        return None
    text = _apply_prompt_vars(text, prompt_vars)

    use_cache = bool(feature.cache_prefix)
    if use_cache:
        return build_cached_system_prompt(text, dynamic_tail, cache=True)
    if dynamic_tail.strip():
        text = f"{text.rstrip()}\n\n{dynamic_tail.strip()}"
    return SystemMessage(content=text)


def _prompt_version(feature: LlmFeature) -> str:
    """Версия промпта для ключа кэша: хэш файла или маркер prompt_in_code."""
    if feature.prompt:
        body = _load_prompt_template(feature.prompt)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return "in_code"


def _cache_key(
    feature: LlmFeature,
    *,
    system_text: str,
    user_text: str,
    schema: type | None,
    temperature: float | None,
    max_tokens: int | None,
    ctx: CallContext | None,
    images: Sequence[ImageInput] = (),
) -> str:
    """Ключ L-17/L-18: feature : prompt_version : input_hash (или явный ctx.cache_key).

    `images` подмешивается отдельно от `user_text`: `_text_of` берёт только текстовые блоки
    content, значит два разных скрина с одинаковой подписью иначе схлопнулись бы в один ключ.
    """
    prompt_ver = _prompt_version(feature)
    if ctx and ctx.cache_key:
        return f"{feature.name}:{prompt_ver}:{ctx.cache_key}"
    schema_name = schema.__name__ if isinstance(schema, type) else ""
    images_digest = "|".join(img.sha256 for img in images)
    digest = hashlib.sha256(
        f"{schema_name}\0{temperature}\0{max_tokens}\0{system_text}\0{user_text}"
        f"\0{images_digest}".encode()
    ).hexdigest()[:32]
    return f"{feature.name}:{prompt_ver}:{digest}"


def _resolve_feature(feature: str | LlmFeature) -> LlmFeature:
    if isinstance(feature, LlmFeature):
        return feature
    return require_feature(feature)


@overload
async def run(
    feature: str | LlmFeature,
    *,
    system: str | None = None,
    system_vars: dict[str, Any] | None = None,
    prompt_vars: Mapping[str, str] | None = None,
    user: str | BaseMessage | None = None,
    messages: Sequence[BaseMessage | dict[str, str]] | None = None,
    dynamic_tail: str = "",
    schema: type[BaseModel],
    stream: Literal[False] = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tier_override: str | None = None,
    model_override: str | None = None,
    model: BaseChatModel | None = None,
    config: RunnableConfig | None = None,
    ctx: CallContext | None = None,
    max_retries: int | None = None,
    images: Sequence[ImageInput] = (),
) -> BaseModel: ...


@overload
async def run(
    feature: str | LlmFeature,
    *,
    system: str | None = None,
    system_vars: dict[str, Any] | None = None,
    prompt_vars: Mapping[str, str] | None = None,
    user: str | BaseMessage | None = None,
    messages: Sequence[BaseMessage | dict[str, str]] | None = None,
    dynamic_tail: str = "",
    schema: None = None,
    stream: Literal[False] = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tier_override: str | None = None,
    model_override: str | None = None,
    model: BaseChatModel | None = None,
    config: RunnableConfig | None = None,
    ctx: CallContext | None = None,
    max_retries: int | None = None,
    images: Sequence[ImageInput] = (),
) -> str: ...


@overload
async def run(
    feature: str | LlmFeature,
    *,
    system: str | None = None,
    system_vars: dict[str, Any] | None = None,
    prompt_vars: Mapping[str, str] | None = None,
    user: str | BaseMessage | None = None,
    messages: Sequence[BaseMessage | dict[str, str]] | None = None,
    dynamic_tail: str = "",
    schema: type[BaseModel] | None = None,
    stream: Literal[True],
    temperature: float | None = None,
    max_tokens: int | None = None,
    tier_override: str | None = None,
    model_override: str | None = None,
    model: BaseChatModel | None = None,
    config: RunnableConfig | None = None,
    ctx: CallContext | None = None,
    max_retries: int | None = None,
    images: Sequence[ImageInput] = (),
) -> AsyncIterator[str]: ...


async def run(
    feature: str | LlmFeature,
    *,
    system: str | None = None,
    system_vars: dict[str, Any] | None = None,
    prompt_vars: Mapping[str, str] | None = None,
    user: str | BaseMessage | None = None,
    messages: Sequence[BaseMessage | dict[str, str]] | None = None,
    dynamic_tail: str = "",
    schema: type[BaseModel] | None = None,
    stream: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tier_override: str | None = None,
    model_override: str | None = None,
    model: BaseChatModel | None = None,
    config: RunnableConfig | None = None,
    ctx: CallContext | None = None,
    max_retries: int | None = None,
    images: Sequence[ImageInput] = (),
) -> Any:
    """Вызов LLM-фичи. Возвращает str / Pydantic-модель / AsyncIterator[str] при stream=True."""
    feat = _resolve_feature(feature)
    effective_schema = schema if schema is not None else feat.schema
    if stream and effective_schema is not None:
        raise ValueError("run(..., stream=True) несовместим со structured schema")

    # L-11: история чата (messages без system) + system=/dynamic_tail → prefix уходит в
    # prompt cache. Если caller уже положил SystemMessage (со своим cache_control) — не трогаем.
    lc_messages = _to_messages(messages)
    has_system = any(isinstance(m, SystemMessage) for m in lc_messages)
    if not has_system:
        system_msg = _build_system_message(
            feat,
            system=system,
            system_vars=system_vars,
            prompt_vars=prompt_vars,
            dynamic_tail=dynamic_tail,
        )
        if system_msg is not None:
            lc_messages = [system_msg, *lc_messages]
    if user is not None:
        lc_messages = [
            *lc_messages,
            user if isinstance(user, BaseMessage) else HumanMessage(content=user),
        ]

    if not lc_messages:
        raise ValueError("run(): пустые messages — передай user= или messages=")

    lc_messages = _attach_images(lc_messages, images)

    system_text = ""
    user_text = ""
    for msg in lc_messages:
        if isinstance(msg, SystemMessage):
            system_text += _text_of(msg)
        elif isinstance(msg, HumanMessage):
            user_text += _text_of(msg)

    # L-02: факты usage копятся из openrouter и пишутся в sink здесь.
    facts, capture_token = begin_usage_capture()
    streaming = False
    try:
        if stream:
            streaming = True
            return _stream_with_usage_flush(
                facts,
                capture_token,
                feat,
                lc_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tier_override=tier_override,
                model_override=model_override,
                model=model,
                config=config,
                ctx=ctx,
            )

        flight = _cache_key(
            feat,
            system_text=system_text,
            user_text=user_text,
            schema=effective_schema if isinstance(effective_schema, type) else None,
            temperature=temperature if temperature is not None else feat.temperature,
            max_tokens=max_tokens if max_tokens is not None else feat.max_tokens,
            ctx=ctx,
            images=images,
        )

        # Инъекция model= (тесты) — без кэша и single-flight, чтобы моки не «слипались».
        skip_cache = bool(model) or bool(ctx and ctx.skip_cache)
        skip_flight = bool(model) or bool(ctx and ctx.skip_single_flight)

        cache = get_result_cache()
        if not skip_cache:
            cached = await cache.get(flight)
            if cached is not None:
                event(logger, "LLM", "cache hit: %s", feat.name, feature=feat.name)
                # Тайминги у попадания в кэш — NULL, а не 0: LLM-вызова не было, замерять
                # нечего. Нули втекали в percentile_cont по `llm_usage.total_ms` и роняли
                # медиану в админке до «0 мс» в дни с высокой долей кэша (69% 24 августа) —
                # мгновенный ответ провайдера, которого не случалось. Фильтр
                # `where total_ms is not null` в разрезе расхода теперь честно считает
                # латентность только по настоящим вызовам.
                default_usage_sink().record(
                    feat.name,
                    "cache",
                    0,
                    0,
                    0.0,
                    tier=feat.tier,
                    ttfb_ms=None,
                    total_ms=None,
                    queue_ms=None,
                    attempt=0,
                    cache_hit=True,
                )
                return cached

        # L-18: писать в кэш ВНУТРИ factory — до снятия inflight-ключа, иначе параллельный
        # запрос между «flight done» и cache.set уйдёт во второй LLM-вызов.
        async def _execute() -> Any:
            result = await _invoke_once(
                feat,
                lc_messages,
                schema=effective_schema if isinstance(effective_schema, type) else None,
                temperature=temperature,
                max_tokens=max_tokens,
                tier_override=tier_override,
                model_override=model_override,
                model=model,
                config=config,
                ctx=ctx,
                max_retries=max_retries,
                flight_key=flight,
            )
            if not skip_cache:
                await cache.set(flight, result, ttl_s=DEFAULT_TTL_S)
            return result

        if skip_flight:
            return await _execute()
        return await get_single_flight().do(flight, _execute)
    finally:
        if not streaming:
            if facts:
                flush_usage_capture(facts)
            end_usage_capture(capture_token)


async def _stream_with_usage_flush(
    facts: list[UsageFact],
    capture_token: Token[list[UsageFact] | None],
    feat: LlmFeature,
    messages: list[BaseMessage],
    *,
    temperature: float | None,
    max_tokens: int | None,
    tier_override: str | None,
    model_override: str | None,
    model: BaseChatModel | None,
    config: RunnableConfig | None,
    ctx: CallContext | None,
) -> AsyncIterator[str]:
    """Стрим + flush llm_usage по завершении генератора."""
    try:
        async for piece in _stream(
            feat,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tier_override=tier_override,
            model_override=model_override,
            model=model,
            config=config,
            ctx=ctx,
        ):
            yield piece
    finally:
        if facts:
            flush_usage_capture(facts)
        end_usage_capture(capture_token)


def _watch_for_stall(feat: LlmFeature) -> asyncio.Task[None] | None:
    """Фоновый таймер §13: WARNING на полпути `budget_ms`, если ответа ещё нет.

    Отличает зависший сетевой запрос (провайдер/сеть не отвечают вовсе) от честно долгого
    ответа — до этого лога было видно только «упало по budget_ms» постфактум, без сигнала,
    висел ли запрос всё время или ответил под конец. Отменяется вызывающим кодом сразу по
    завершении `_call()` — не пишет ничего, если ответ пришёл раньше половины бюджета.
    """
    budget_ms = feat.budget_ms
    if not budget_ms or budget_ms <= 0:
        return None

    async def _timer() -> None:
        try:
            await asyncio.sleep(budget_ms / 2000.0)
        except asyncio.CancelledError:
            return
        event(
            logger,
            "LLM",
            "%s: затянувшийся запрос — нет ответа за %.0fms (budget=%s)",
            feat.name,
            budget_ms / 2,
            budget_ms,
            level=logging.WARNING,
            feature=feat.name,
            tier=feat.tier,
        )

    return asyncio.create_task(_timer())


async def _invoke_once(
    feat: LlmFeature,
    messages: list[BaseMessage],
    *,
    schema: type[BaseModel] | None,
    temperature: float | None,
    max_tokens: int | None,
    tier_override: str | None,
    model_override: str | None,
    model: BaseChatModel | None,
    config: RunnableConfig | None,
    ctx: CallContext | None,
    max_retries: int | None,
    flight_key: str,
) -> Any:
    chat = model or chat_model_for(
        feat.name,
        temperature=temperature,
        max_tokens=max_tokens,
        tier_override=tier_override,
        model_override=model_override,
    )

    run_config = cast(RunnableConfig, dict(config or {}))
    tags = list(run_config.get("tags") or [])
    tags.extend([f"feature:{feat.name}", f"tier:{feat.tier}"])
    if ctx:
        tags.extend(ctx.tags)
    run_config["tags"] = tags
    meta = dict(run_config.get("metadata") or {})
    meta.update({"feature": feat.name, "tier": feat.tier, "flight_key": flight_key})
    if ctx:
        meta.update(ctx.metadata)
    run_config["metadata"] = meta

    # L-13: качество/схема — максимум 1 ремонтный вызов (итого ≤2 LLM-запроса на сценарий).
    retries = (
        max_retries
        if max_retries is not None
        else (feat.retries if feat.retries is not None else 1)
    )
    started = time.perf_counter()
    ttfb_ms: float | None = None

    async def _call() -> Any:
        nonlocal ttfb_ms
        if schema is not None:
            if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
                raise TypeError("schema must be a Pydantic BaseModel subclass")
            structured = chat.with_structured_output(schema, max_retries=retries)
            result = await structured.ainvoke(messages, config=run_config)
            ttfb_ms = (time.perf_counter() - started) * 1000
            return result
        result = await chat.ainvoke(messages, config=run_config)
        ttfb_ms = (time.perf_counter() - started) * 1000
        return _text_of(result)

    stall_task = _watch_for_stall(feat)
    try:
        if feat.budget_ms and feat.budget_ms > 0:
            result = await asyncio.wait_for(_call(), timeout=feat.budget_ms / 1000.0)
        else:
            result = await _call()
    except TimeoutError as exc:
        total_ms = (time.perf_counter() - started) * 1000
        record_llm_ms(total_ms)
        event(
            logger,
            "ОШИБКА",
            "LLM timeout %s за %.0fms (budget=%s)",
            feat.name,
            total_ms,
            feat.budget_ms,
            level=logging.ERROR,
            feature=feat.name,
            tier=feat.tier,
        )
        raise TimeoutError(f"LLM-фича {feat.name!r} превысила budget_ms={feat.budget_ms}") from exc
    except Exception as exc:
        # Наверху (роутер → конверт ошибки) видно только «LLM недоступен»: имя фичи и тир
        # теряются, а без них непонятно, что именно у пользователя не сработало.
        total_ms = (time.perf_counter() - started) * 1000
        record_llm_ms(total_ms)
        event(
            logger,
            "ОШИБКА",
            "LLM %s упал за %.0fms: %s",
            feat.name,
            total_ms,
            exc,
            level=logging.ERROR,
            feature=feat.name,
            tier=feat.tier,
            error_type=type(exc).__name__,
        )
        raise
    finally:
        if stall_task is not None:
            stall_task.cancel()

    total_ms = (time.perf_counter() - started) * 1000
    record_llm_ms(total_ms)
    event(
        logger,
        "LLM",
        "%s tier=%s ttfb=%.0fms total=%.0fms schema=%s",
        feat.name,
        feat.tier,
        ttfb_ms or total_ms,
        total_ms,
        schema.__name__ if schema else "-",
        feature=feat.name,
        tier=feat.tier,
        ttfb_ms=round(ttfb_ms or total_ms),
        total_ms=round(total_ms),
    )
    return result


async def _stream(
    feat: LlmFeature,
    messages: list[BaseMessage],
    *,
    temperature: float | None,
    max_tokens: int | None,
    tier_override: str | None,
    model_override: str | None,
    model: BaseChatModel | None,
    config: RunnableConfig | None,
    ctx: CallContext | None,
) -> AsyncIterator[str]:
    chat = model or chat_model_for(
        feat.name,
        temperature=temperature,
        max_tokens=max_tokens,
        tier_override=tier_override,
        model_override=model_override,
    )
    run_config = cast(RunnableConfig, dict(config or {}))
    tags = list(run_config.get("tags") or [])
    tags.extend([f"feature:{feat.name}", f"tier:{feat.tier}", "stream"])
    if ctx:
        tags.extend(ctx.tags)
    run_config["tags"] = tags

    started = time.perf_counter()
    first = True
    chars = 0
    try:
        async for chunk in chat.astream(messages, config=run_config):
            piece = getattr(chunk, "content", "")
            if not isinstance(piece, str) or not piece:
                continue
            if first:
                event(
                    logger,
                    "LLM",
                    "%s stream ttfb=%.0fms",
                    feat.name,
                    (time.perf_counter() - started) * 1000,
                    feature=feat.name,
                    tier=feat.tier,
                )
                first = False
            chars += len(piece)
            yield piece
    finally:
        total_ms = (time.perf_counter() - started) * 1000
        record_llm_ms(total_ms)
        event(
            logger,
            "LLM",
            "%s stream done chars=%d total=%.0fms",
            feat.name,
            chars,
            total_ms,
            feature=feat.name,
            tier=feat.tier,
        )


__all__ = ["CallContext", "ImageInput", "run"]
