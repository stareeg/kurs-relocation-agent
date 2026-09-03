"""Кастомный `BaseChatModel` поверх OpenRouter.

Один путь для всех LLM-вызовов системы: tier-роутинг, fallback primary→fallback,
retry/backoff, cost-учёт через UsageSink, structured output (response_format: json_schema +
Pydantic-валидация с retry), bind_tools и prompt caching. Async-first; sync `invoke` работает
только вне запущенного event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ConfigDict, PrivateAttr, ValidationError

from core.config import (
    CoreSettings,
    current_account_id,
    current_account_openrouter_key,
    get_settings,
    normalize_openrouter_model,
    runtime_openrouter_key,
)
from core.platform.llm.prompt_cache import supports_cache_control
from core.platform.llm.usage import (
    UsageSink,
    compute_cost,
    default_usage_sink,
    emit_usage,
)
from core.platform.observability import event
from core.platform.observability.langsmith import configure_langsmith

logger = logging.getLogger(__name__)

TIERS = ("advanced", "basic", "reserve")


def _is_reasoning_rejection(exc: Exception) -> bool:
    """Провайдер ответил 400 «reasoning отключать нельзя» (текст у всех свой, слово одно)."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    if exc.response.status_code != 400:
        return False
    return "reasoning" in _response_diag(exc.response).casefold()


async def _read_error_body(resp: httpx.Response) -> None:
    """Дочитать тело не-2xx ответа стрима.

    У `client.stream(...)` тело не прочитано, и `resp.text` бросает `ResponseNotRead` —
    `_response_diag` отдаёт «<тело недоступно>», а по нему не отличить «модель не разрешает
    выключать reasoning» от любой другой 400. Именно из-за этого стрим не умел снимать флаг
    reasoning и вся цепочка деградации обрывалась на первом же запасном варианте (Э19.8).
    """
    if not resp.is_error:
        return
    with contextlib.suppress(Exception):
        await resp.aread()


def _response_diag(resp: httpx.Response) -> str:
    """content-type + короткий сниппет тела не-2xx ответа.

    Различает на глаз, где именно отвалилось: HTML-страница инфры (релей на Render/CDN
    упал/не задеплоен — `text/html`, «no-deploy»/502-заглушка) vs настоящая JSON-ошибка от
    самого OpenRouter (`application/json`, `{"error": {...}}`) — без этого оба случая в логах
    выглядели одинаково как «HTTP 502 на <модель>».
    """
    content_type = resp.headers.get("content-type", "?")
    try:
        snippet = " ".join(resp.text.split())[:200]
    except Exception:  # noqa: BLE001 — диагностика best-effort, не должна ронять обработку ошибки
        snippet = "<тело недоступно>"
    return f"{content_type}: {snippet}" if snippet else content_type


# --- Ошибки (перенос таксономии из backend/scoring/openrouter.py) ---
class OpenRouterError(Exception):
    pass


class OpenRouterRateLimitError(OpenRouterError):
    """HTTP 429 — лимиты исчерпаны после ретраев."""


class OpenRouterConnectionError(OpenRouterError):
    """Таймаут или ошибка соединения."""


class OpenRouterResponseError(OpenRouterError):
    """Невалидный, пустой ответ API или несошедшийся structured output."""


_ROLE_BY_TYPE = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}

# Runaway-защита для картинок в `_preflight_guards` (плана chat_image_attachments): не
# env-настройка (как `_MAX_SIDE_PX`/`_THUMB_PX` в assistant/attachments/service.py) — здесь
# это последний рубеж перед HTTP-вызовом, а не продуктовый лимит композера.
_ATTACHMENT_MAX_PER_MESSAGE = 10
_ATTACHMENT_MAX_TOTAL_BYTES = 40 * 1024 * 1024  # ~10 нормализованных скринов с запасом

# Ключи JSON-схемы, которые Anthropic (и Amazon Bedrock) structured output не поддерживают на
# integer: minimum/maximum → HTTP 400 "For 'integer' type, properties maximum, minimum are not
# supported" (грабли, docs/problems.md). Gemini их принимает. Срезаем для ВСЕХ провайдеров —
# схема и так strict=False (подсказка), а диапазоны гарантирует наша Pydantic-валидация ответа.
# Без этого primary/fallback на Anthropic-моделях падал бы на скоринге (ScoreResult: Field(ge/le)).
_UNSUPPORTED_SCHEMA_KEYS = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"})


# Модели, не принимающие sampling-параметры (temperature/top_p/top_k) — Claude 5 Sonnet и др.
# Sonnet 5 отвергает их 400-й (Claude 5 Sonnet Migration Guide, OpenRouter). Префикс-матч по slug.
_NO_SAMPLING_MODEL_PREFIXES = (
    "anthropic/claude-sonnet-5",
    "anthropic/claude-opus-4-8",
    "anthropic/claude-opus-4-7",
    "anthropic/claude-fable-5",
    "anthropic/claude-mythos-5",
)


def _supports_sampling(model: str) -> bool:
    """Принимает ли модель sampling-параметры (temperature/top_p/top_k)."""
    m = (model or "").strip().lower()
    return not m.startswith(_NO_SAMPLING_MODEL_PREFIXES)


def _strip_unsupported_schema_keys(node: Any) -> Any:
    """Рекурсивно убрать неподдерживаемые Anthropic ключи валидации из JSON-схемы."""
    if isinstance(node, dict):
        return {
            k: _strip_unsupported_schema_keys(v)
            for k, v in node.items()
            if k not in _UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(node, list):
        return [_strip_unsupported_schema_keys(x) for x in node]
    return node


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)


def _extract_balanced(text: str) -> str | None:
    """Найти первую `{`/`[` и вернуть сбалансированную подстроку до её парной закрывающей
    скобки (учитывая строки/экранирование), либо None, если баланс не сошёлся."""
    start = next((i for i, ch in enumerate(text) if ch in "{["), None)
    if start is None:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _extract_json_object(text: str) -> str:
    """Вычленить JSON из ответа модели, если он обёрнут в код-фенс или окружён пояснительным
    текстом. Слабые/фолбэк-модели иногда возвращают ```json ... ``` с преамбулой/
    послесловием вместо строгого JSON — раньше это сразу валило `json.JSONDecodeError`
    (`Expecting value: line N column 1`) без попытки достать сам объект. Если ничего не
    помогло — вернуть текст как есть, пусть исходная ошибка всплывёт и уйдёт в retry-цикл."""
    stripped = text.strip()
    if not stripped:
        return text
    try:
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        pass
    fence_match = _CODE_FENCE_RE.search(stripped)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            stripped = candidate
    extracted = _extract_balanced(stripped)
    return extracted if extracted is not None else text


def _render_content(content: Any, *, allow_cache_control: bool) -> Any:
    """LangChain-контент → формат OpenRouter.

    Для провайдеров без поддержки `cache_control` раньше весь список блоков схлопывался в
    плоский текст (только `type == "text"`), чтобы вычистить непринимаемый ключ — но это же
    молча выбрасывало `image_url`-блоки: фолбэк-модель отвечала «не вижу изображения» без
    единой ошибки в логе. Теперь
    блоки всегда сохраняются как список; при `allow_cache_control=False` из dict-блоков
    вычищается только сам ключ `cache_control`.
    """
    if not isinstance(content, list):
        return content or ""
    parts: list[dict] = []
    for block in content:
        if isinstance(block, str):
            parts.append({"type": "text", "text": block})
        elif isinstance(block, dict):
            parts.append(block if allow_cache_control else _without_cache_control(block))
    return parts


def _without_cache_control(block: dict) -> dict:
    if "cache_control" not in block:
        return block
    return {k: v for k, v in block.items() if k != "cache_control"}


def _content_stats(content: Any) -> tuple[int, int, int]:
    """(текстовые_символы, число_картинок, суммарные_байты_картинок) одного `content`.

    Считает по блокам, а не `len(str(content))` целиком — иначе base64 data-URI картинки
    (ловушка 1.2) раздувает текстовый счётчик на сотни тысяч «символов» одним скриншотом.
    Байты картинки — по длине base64-полезной нагрузки (`* 3 // 4`), без декодирования.
    """
    if isinstance(content, str):
        return len(content), 0, 0
    if not isinstance(content, list):
        return len(str(content or "")), 0, 0
    chars = 0
    n_images = 0
    image_bytes = 0
    for block in content:
        if isinstance(block, str):
            chars += len(block)
            continue
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            chars += len(str(block.get("text", "")))
        elif block_type == "image_url":
            n_images += 1
            url = str((block.get("image_url") or {}).get("url", ""))
            b64_payload = url.split(",", 1)[1] if "," in url else ""
            image_bytes += (len(b64_payload) * 3) // 4
    return chars, n_images, image_bytes


def _payload_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Форма запроса без содержимого сообщений — раньше в файловый DEBUG-лог уходил
    ПОЛНЫЙ payload (резюме/переписка с HR всех аккаунтов открытым текстом, без привязки к
    account_id — не то же самое, что account-scoped `copilot_logs`). Оставляем размер/форму,
    достаточную для дебага (обрезало ли по лимиту, сколько картинок), без самого текста."""
    messages = payload.get("messages") or []
    total_chars = total_images = total_image_bytes = 0
    for m in messages:
        chars, n_images, image_bytes = _content_stats(m.get("content"))
        total_chars += chars
        total_images += n_images
        total_image_bytes += image_bytes
    return {
        "n_messages": len(messages),
        "chars": total_chars,
        "images": total_images,
        "image_bytes": total_image_bytes,
        "max_tokens": payload.get("max_tokens"),
        "tools": bool(payload.get("tools")),
        "response_format": bool(payload.get("response_format")),
    }


def _to_openrouter_messages(messages: list[BaseMessage], *, model: str) -> list[dict]:
    allow_cache = supports_cache_control(model)
    out: list[dict] = []
    for msg in messages:
        role = _ROLE_BY_TYPE.get(msg.type, "user")
        entry: dict[str, Any] = {
            "role": role,
            "content": _render_content(msg.content, allow_cache_control=allow_cache),
        }
        if isinstance(msg, AIMessage) and msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.get("id") or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("args") or {}, ensure_ascii=False),
                    },
                }
                for i, tc in enumerate(msg.tool_calls)
            ]
            entry.setdefault("content", "")
        if isinstance(msg, ToolMessage):
            entry["tool_call_id"] = msg.tool_call_id
        out.append(entry)
    return out


class OpenRouterChatModel(BaseChatModel):
    """Чат-модель поверх OpenRouter с тирами, fallback, cost-учётом и structured output."""

    model_config = ConfigDict(protected_namespaces=(), arbitrary_types_allowed=True)

    primary_model: str
    fallback_model: str = ""
    # Тир-осознанный fallback между primary и глобальным fallback_model. Пусто →
    # цепочка как раньше, только primary → fallback_model.
    tier_fallback_model: str = ""
    # Модель тира при model_override: без неё override «сиротит» тир, и primary падает сразу
    # в глобальный fallback. У «Мультиплеера» это значит: перегруженный `MODEL_MULTIPLAYER`
    # → сразу gemini (обязательный reasoning, +400), минуя рабочую `MODEL_TIER_BASIC`. Пусто
    # = override не задан или совпал с моделью тира.
    override_base_model: str = ""
    # OpenRouter provider-routing (OPENROUTER_PROVIDER) — в поле `provider` запроса. Пусто = не шлём.
    provider_prefs: dict[str, Any] = {}
    tier: str = "basic"
    agent: str = "system"
    temperature: float = 0.3
    max_tokens: int | None = None
    request_timeout: float = 90.0
    # Safety-потолок попыток (основной лимит — budget_ms, не счётчик).
    max_retries: int = 3
    # Бюджет времени фичи (мс). None — только safety max_retries (прямой get_chat_model).
    budget_ms: int | None = None
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    proxy: str | None = None
    # OpenRouter reasoning-effort (low/medium/high). None → reasoning не шлём (по умолчанию).
    reasoning_effort: str | None = None

    _usage_sink: UsageSink | None = PrivateAttr(default=None)
    # Точка для httpx.MockTransport в тестах; в проде None → обычный клиент.
    _transport: Any = PrivateAttr(default=None)
    # Для детерминированных тестов L-09 (jitter).
    _retry_rng: Any = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "openrouter-chat"

    @property
    def usage_sink(self) -> UsageSink:
        return self._usage_sink or default_usage_sink()

    def _combine_llm_outputs(self, llm_outputs: list[dict | None]) -> dict:
        """Сохранить llm_output (cost/usage/model) в LLMResult — иначе on_llm_end (и
        трасса LangSmith) получают пустой dict (дефолт базового класса)."""
        for out in llm_outputs:
            if out:
                return out
        return {}

    def _should_stream(self, *, async_api: bool = True, **kwargs: Any) -> bool:
        """Как в базе (стримим, когда есть стрим-обработчик: явный .astream), НО structured
        output (response_format) и tool calls форсируем в _agenerate: SSE-парсер стрима не
        понимает JSON-ответ → «No generations found in stream»."""
        if kwargs.get("response_format") or kwargs.get("tools") or kwargs.get("tool_choice"):
            return False
        return super()._should_stream(async_api=async_api, **kwargs)

    # --- HTTP + retry (перенос из OpenRouterClient) ---
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://relocation-copilot.local",
            "X-Title": "Career & Relocation Copilot",
        }

    def _chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        # L-07: общий keep-alive клиент; MockTransport в тестах — ephemeral, без singleton.
        from core.platform.http import get_http_client, make_client, request_timeout

        url = self._chat_url()
        timeout = request_timeout(self.request_timeout)
        if self._transport is not None:
            async with make_client(transport=self._transport, timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
        resp = await get_http_client().post(
            url, json=payload, headers=self._headers(), timeout=timeout
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _validate_data(data: dict[str, Any]) -> dict[str, Any]:
        if "error" in data:
            raise OpenRouterResponseError(f"API вернул ошибку: {data['error']}")
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterResponseError("Некорректная структура ответа API") from exc
        has_content = bool(str(message.get("content") or "").strip())
        has_tools = bool(message.get("tool_calls"))
        if not has_content and not has_tools:
            raise OpenRouterResponseError("Пустой ответ от модели")
        return data

    async def _run_with_retry(
        self, payload: dict[str, Any], model: str
    ) -> tuple[dict[str, Any], int, float]:
        """L-09: ретраи сеть/5xx/429 с jitter; 4xx-схема — без ретрая; лимит — budget_ms.

        Возвращает (data, attempt_1based, queue_ms) — queue_ms = сумма пауз backoff.
        """
        from core.platform.http.retry import plan_retry

        last_error: Exception | None = None
        queue_ms = 0.0
        started = time.perf_counter()
        safety_max = max(int(self.max_retries), 1)
        attempt = 0
        reasoning_dropped = False

        while attempt < safety_max:
            try:
                data = await self._post(payload)
                return self._validate_data(data), attempt + 1, queue_ms
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                diag = _response_diag(exc.response)
                # Часть эндпоинтов не разрешает выключать reasoning вовсе и отвечает 400
                # («Reasoning is mandatory for this endpoint and cannot be disabled»).
                # Отключение thinking — оптимизация, а не требование, поэтому это не повод
                # ронять вызов: снимаем флаг и пробуем ту же модель ещё раз. Без этого
                # цепочка деградации рвётся на первом же таком запасном варианте — ровно
                # так «Хрюши и Волки» падали в статическую заглушку, когда основную модель
                # притормаживал rate-limit (Э19).
                if (
                    not reasoning_dropped
                    and _is_reasoning_rejection(exc)
                    and payload.pop("reasoning", None) is not None
                ):
                    reasoning_dropped = True
                    event(
                        logger,
                        "LLM",
                        "%s не разрешает отключать reasoning — повтор без флага",
                        model,
                        model=model,
                        level=logging.WARNING,
                    )
                    continue
                if status == 429:
                    last_error = OpenRouterRateLimitError(f"HTTP 429 на {model}: {exc}")
                else:
                    last_error = OpenRouterError(f"HTTP {status} на {model} ({diag})")
                elapsed_ms = (time.perf_counter() - started) * 1000
                plan = plan_retry(
                    status=status,
                    attempt=attempt,
                    elapsed_ms=elapsed_ms,
                    budget_ms=self.budget_ms,
                    safety_max=safety_max,
                    rng=self._retry_rng,
                )
                if not plan.retry:
                    event(
                        logger,
                        "LLM",
                        "HTTP %d на %s: без ретрая (%s) — %s",
                        status,
                        model,
                        plan.reason,
                        diag,
                        level=logging.WARNING if status == 429 else logging.ERROR,
                        model=model,
                        tier=self.tier,
                        agent=self.agent,
                        status_code=status,
                        retry_reason=plan.reason,
                        base_url=self.base_url,
                        response_diag=diag,
                    )
                    break
                event(
                    logger,
                    "LLM",
                    "HTTP %d на %s: попытка %d, пауза %.2fс (budget_ms=%s) — %s",
                    status,
                    model,
                    attempt + 1,
                    plan.wait_s,
                    self.budget_ms,
                    diag,
                    level=logging.WARNING,
                    model=model,
                    tier=self.tier,
                    agent=self.agent,
                    status_code=status,
                    base_url=self.base_url,
                    response_diag=diag,
                )
                await asyncio.sleep(plan.wait_s)
                queue_ms += plan.wait_s * 1000
                attempt += 1
                continue
            except httpx.TransportError as exc:
                # RemoteProtocolError («Server disconnected») и прочие обрывы — как сеть, с ретраем.
                last_error = OpenRouterConnectionError(str(exc))
                elapsed_ms = (time.perf_counter() - started) * 1000
                plan = plan_retry(
                    network_error=True,
                    attempt=attempt,
                    elapsed_ms=elapsed_ms,
                    budget_ms=self.budget_ms,
                    safety_max=safety_max,
                    rng=self._retry_rng,
                )
                if not plan.retry:
                    event(
                        logger,
                        "LLM",
                        "сеть %s (%s): без ретрая (%s): %s",
                        model,
                        self.base_url,
                        plan.reason,
                        exc,
                        level=logging.WARNING,
                        model=model,
                        tier=self.tier,
                        agent=self.agent,
                        retry_reason=plan.reason,
                        base_url=self.base_url,
                    )
                    break
                event(
                    logger,
                    "LLM",
                    "сеть %s (%s): попытка %d, пауза %.2fс: %s",
                    model,
                    self.base_url,
                    attempt + 1,
                    plan.wait_s,
                    exc,
                    level=logging.WARNING,
                    model=model,
                    tier=self.tier,
                    agent=self.agent,
                    base_url=self.base_url,
                )
                await asyncio.sleep(plan.wait_s)
                queue_ms += plan.wait_s * 1000
                attempt += 1
            except OpenRouterResponseError as exc:
                event(
                    logger,
                    "LLM",
                    "ответ API %s: %s",
                    model,
                    exc,
                    level=logging.ERROR,
                    model=model,
                    tier=self.tier,
                    agent=self.agent,
                )
                last_error = exc
                break
        if isinstance(last_error, (OpenRouterRateLimitError, OpenRouterConnectionError)):
            raise last_error
        raise OpenRouterError(f"модель {model}: попытки исчерпаны. Последняя ошибка: {last_error}")

    def _models_to_try(self) -> list[str]:
        """Цепочка деградации по приоритету: primary → модель тира (при override) → тир-фолбэк
        → глобальный фолбэк, без дублей (LLM-1: раньше был только primary → глобальный фолбэк,
        для reasoning_pro это сразу откат на 2 класса ниже, gemini-flash не держит сложный
        structured output)."""
        models = [self.primary_model]
        for candidate in (
            self.override_base_model,
            self.tier_fallback_model,
            self.fallback_model,
        ):
            if candidate and candidate not in models:
                models.append(candidate)
        return models

    def _build_payload(
        self, messages: list[BaseMessage], model: str, stop: list[str] | None, kwargs: dict
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": _to_openrouter_messages(messages, model=model),
            "usage": {"include": True},
        }
        # sampling-параметры поддерживает не каждая модель: Claude Sonnet 5 / Opus 4.8 и др.
        # отвергают temperature/top_p/top_k с 400. Шлём только если модель их принимает.
        if _supports_sampling(model):
            payload["temperature"] = kwargs.get("temperature", self.temperature)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stop:
            payload["stop"] = stop
        if self.provider_prefs:
            payload["provider"] = self.provider_prefs
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
            if kwargs.get("tool_choice"):
                payload["tool_choice"] = kwargs["tool_choice"]
        if kwargs.get("response_format"):
            payload["response_format"] = kwargs["response_format"]
        # Reasoning на тирах с effort (Sonnet 5 medium и т.п.); OpenRouter мапит effort в
        # extended thinking. Тиры без effort сюда не попадают — обычный запрос.
        #
        # "none" — не уровень усилия, а «выключить думание совсем»: у OpenRouter для этого
        # `reasoning.enabled = false`, который он транслирует в родной флаг провайдера
        # (Qwen — enable_thinking, DeepSeek — свой). Слать `{"effort": "none"}` нельзя:
        # такого значения в API нет, модель молча продолжает думать, жрёт бюджет токенов
        # на скрытый reasoning и возвращает пустой content при json_schema. Держим это
        # здесь, а не в декларации фичи, чтобы смена MODEL_MULTIPLAYER на другую модель не
        # требовала знать, как у неё называется выключение thinking.
        if self.reasoning_effort == "none":
            payload["reasoning"] = {"enabled": False}
        elif self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        return payload

    @staticmethod
    def _to_chat_result(data: dict[str, Any], model: str, agent: str, tier: str) -> ChatResult:
        message = data["choices"][0]["message"]
        content = str(message.get("content") or "")
        tool_calls = []
        for i, tc in enumerate(message.get("tool_calls") or []):
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                {
                    "name": fn.get("name", ""),
                    "args": args,
                    "id": tc.get("id") or f"call_{i}",
                    "type": "tool_call",
                }
            )
        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        cost = compute_cost(model, tokens_in, tokens_out, provider_cost=usage.get("cost"))
        info = {
            "model": model,
            "agent": agent,
            "tier": tier,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost,
            "finish_reason": data["choices"][0].get("finish_reason"),
        }
        ai = AIMessage(
            content=content,
            tool_calls=tool_calls,
            response_metadata=info,
            usage_metadata={
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        )
        return ChatResult(
            generations=[ChatGeneration(message=ai, generation_info=info)],
            llm_output={"model": model, "usage": usage, "cost_usd": cost},
        )

    def _preflight_guards(self, messages: list[BaseMessage], *, agent: str) -> None:
        """Стоп-кран ДО любого HTTP-вызова (общий для _agenerate и _astream).

        Дневных cost-лимитов (soft/hard) больше нет — их circuit breaker мешал бесшовной работе,
        лимит трат живёт на стороне OpenRouter. Остаётся только защита от аварийно гигантского
        одиночного запроса (раздутый task.input → промпт в сотни тысяч токенов и реальные деньги) —
        это не про дневной бюджет, а про явно сломанный вход.

        Текст и картинки считаются раздельно (ловушка 1.2, `plans/chat_image_attachments_
        2026_08_03.md`): раньше `len(str(content))` на list-контенте сериализовал весь
        base64 data-URI картинки — PNG в 600 КБ даёт ≈820к «символов» и один скриншот сам
        по себе пробивал `llm_max_input_chars`, хотя реального текста в запросе почти нет.
        """
        settings = get_settings()
        max_chars = settings.llm_max_input_chars
        total_chars = 0
        total_images = 0
        total_image_bytes = 0
        for m in messages:
            chars, n_images, image_bytes = _content_stats(getattr(m, "content", "") or "")
            total_chars += chars
            total_images += n_images
            total_image_bytes += image_bytes

        if max_chars > 0 and total_chars > max_chars:
            raise OpenRouterError(
                f"Запрос превышает лимит размера: {total_chars} символов > {max_chars} "
                f"(агент={agent}). Защита от runaway — урежьте вход."
            )
        if total_images > _ATTACHMENT_MAX_PER_MESSAGE:
            raise OpenRouterError(
                f"Запрос превышает лимит картинок: {total_images} > "
                f"{_ATTACHMENT_MAX_PER_MESSAGE} (агент={agent})."
            )
        if total_image_bytes > _ATTACHMENT_MAX_TOTAL_BYTES:
            raise OpenRouterError(
                f"Запрос превышает лимит суммарного размера картинок: {total_image_bytes} "
                f"байт > {_ATTACHMENT_MAX_TOTAL_BYTES} (агент={agent})."
            )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        agent = kwargs.get("agent", self.agent)
        self._preflight_guards(messages, agent=agent)

        last_error: Exception | None = None
        for model in self._models_to_try():
            payload = self._build_payload(messages, model, stop, kwargs)
            # Форма запроса, не содержимое — раньше сюда уходил полный payload (PII, см.
            # _payload_shape). Только в файл (DEBUG), терминал не засоряем.
            logger.debug("LLM запрос %s: %s", model, _payload_shape(payload))
            started = time.perf_counter()
            try:
                data, attempt, queue_ms = await self._run_with_retry(payload, model)
            except OpenRouterError as exc:
                last_error = exc
                event(
                    logger,
                    "LLM",
                    "модель %s не сработала: %s",
                    model,
                    exc,
                    level=logging.WARNING,
                    model=model,
                    tier=self.tier,
                    agent=agent,
                )
                continue
            latency_ms = (time.perf_counter() - started) * 1000
            result = self._to_chat_result(data, model, agent, self.tier)
            info = result.generations[0].generation_info or {}
            tokens_in = int(info.get("tokens_in", 0) or 0)
            tokens_out = int(info.get("tokens_out", 0) or 0)
            cost = float(info.get("cost_usd", 0.0) or 0.0)
            # Нестрим: TTFB ≈ total (JSON приходит целиком). Под call.run emit копит в capture.
            emit_usage(
                agent,
                model,
                tokens_in,
                tokens_out,
                cost,
                tier=self.tier,
                ttfb_ms=round(latency_ms),
                total_ms=round(latency_ms),
                queue_ms=round(queue_ms),
                attempt=attempt,
            )
            event(
                logger,
                "LLM",
                "ответ: %s, %d→%d ток, $%.4f, %.1fс",
                model,
                tokens_in,
                tokens_out,
                cost,
                latency_ms / 1000,
                agent=agent,
                tier=self.tier,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=round(latency_ms),
            )
            return result

        event(
            logger,
            "LLM",
            "все модели исчерпаны (%s): %s",
            ", ".join(self._models_to_try()),
            last_error,
            level=logging.ERROR,
            tier=self.tier,
            agent=agent,
        )
        raise OpenRouterError(f"Все модели исчерпаны ({self._models_to_try()}). {last_error}")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Sync-путь: гоняет async-реализацию. Внутри запущенного loop недоступен."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._agenerate(messages, stop, None, **kwargs))
        raise NotImplementedError(
            "OpenRouterChatModel — async-first; внутри event loop используй ainvoke"
        )

    # --- Стрим токенов (живой чат) ---
    @staticmethod
    async def _iter_sse_chunks(
        resp: httpx.Response,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Построчный разбор SSE OpenRouter → (кусок_текста, usage)."""
        async for raw in resp.aiter_lines():
            line = raw.strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            usage = obj.get("usage") or {}
            text = ""
            for choice in obj.get("choices") or []:
                piece = (choice.get("delta") or {}).get("content")
                if isinstance(piece, str):
                    text += piece
            if text or usage:
                yield text, usage

    async def _stream_post(
        self, payload: dict[str, Any], model: str
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """POST со stream=true → построчный разбор SSE OpenRouter. Отдаёт (кусок_текста, usage).

        usage приходит финальным кадром (часто с пустым choices) при `usage: {include: true}`.
        L-07: общий keep-alive клиент; MockTransport — ephemeral.
        """
        from core.platform.http import get_http_client, make_client, request_timeout

        url = self._chat_url()
        timeout = request_timeout(self.request_timeout)
        headers = self._headers()
        if self._transport is not None:
            async with (
                make_client(transport=self._transport, timeout=timeout) as client,
                client.stream("POST", url, json=payload, headers=headers) as resp,
            ):
                await _read_error_body(resp)
                resp.raise_for_status()
                async for item in self._iter_sse_chunks(resp):
                    yield item
            return

        async with get_http_client().stream(
            "POST", url, json=payload, headers=headers, timeout=timeout
        ) as resp:
            await _read_error_body(resp)
            resp.raise_for_status()
            async for item in self._iter_sse_chunks(resp):
                yield item

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Стрим токенов: реальный токен-за-токеном ответ для чата.
        Structured output сюда не ходит (он на _agenerate).

        Fallback primary→fallback срабатывает только ДО первого токена: если уже стримили и
        соединение оборвалось — отдаём что есть с ошибкой (не дублируем ответ другой моделью).
        """
        agent = kwargs.get("agent", self.agent)
        self._preflight_guards(messages, agent=agent)

        last_error: Exception | None = None
        for model in self._models_to_try():
            payload = self._build_payload(messages, model, stop, kwargs)
            payload["stream"] = True
            reasoning_dropped = False
            while True:
                started = time.perf_counter()
                yielded = False
                failed = False
                ttfb_ms: float | None = None
                usage: dict[str, Any] = {}
                try:
                    async for text, chunk_usage in self._stream_post(payload, model):
                        if chunk_usage:
                            usage = chunk_usage
                        if not text:
                            continue
                        if ttfb_ms is None:
                            ttfb_ms = (time.perf_counter() - started) * 1000
                        yielded = True
                        gen = ChatGenerationChunk(message=AIMessageChunk(content=text))
                        if run_manager is not None:
                            await run_manager.on_llm_new_token(text, chunk=gen)
                        yield gen
                except (httpx.HTTPError, OpenRouterError) as exc:
                    last_error = exc
                    if yielded:
                        event(
                            logger,
                            "LLM",
                            "стрим прерван на %s: %s",
                            model,
                            exc,
                            level=logging.ERROR,
                            model=model,
                            tier=self.tier,
                            agent=agent,
                        )
                        raise OpenRouterError(f"стрим прерван на {model}: {exc}") from exc
                    # Тот же best-effort, что и в `_run_with_retry`: отключение thinking —
                    # оптимизация, а не требование. Без этого повтора стрим ронял всю цепочку
                    # деградации на модели, которая не разрешает выключать reasoning (Э19.8).
                    if (
                        not reasoning_dropped
                        and _is_reasoning_rejection(exc)
                        and payload.pop("reasoning", None) is not None
                    ):
                        reasoning_dropped = True
                        event(
                            logger,
                            "LLM",
                            "%s не разрешает отключать reasoning в стриме — повтор без флага",
                            model,
                            model=model,
                            tier=self.tier,
                            agent=agent,
                            level=logging.WARNING,
                        )
                        continue
                    event(
                        logger,
                        "LLM",
                        "стрим %s не сработал: %s",
                        model,
                        exc,
                        level=logging.WARNING,
                        model=model,
                        tier=self.tier,
                        agent=agent,
                    )
                    failed = True
                break
            if failed:
                continue
            total_ms = (time.perf_counter() - started) * 1000
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
            cost = compute_cost(model, tokens_in, tokens_out, provider_cost=usage.get("cost"))
            emit_usage(
                agent,
                model,
                tokens_in,
                tokens_out,
                cost,
                tier=self.tier,
                ttfb_ms=round(ttfb_ms if ttfb_ms is not None else total_ms),
                total_ms=round(total_ms),
                queue_ms=0,
                attempt=1,
            )
            event(
                logger,
                "LLM",
                "стрим: %s, %d→%d ток, $%.4f, %.1fс",
                model,
                tokens_in,
                tokens_out,
                cost,
                total_ms / 1000,
                agent=agent,
                tier=self.tier,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=round(total_ms),
            )
            return
        event(
            logger,
            "LLM",
            "все модели исчерпаны (стрим, %s): %s",
            ", ".join(self._models_to_try()),
            last_error,
            level=logging.ERROR,
            tier=self.tier,
            agent=agent,
        )
        models = self._models_to_try()
        raise OpenRouterError(f"Все модели исчерпаны (стрим, {models}). {last_error}")

    # --- LangChain-интерфейс: tools и structured output ---
    def bind_tools(
        self, tools: list[Any], *, tool_choice: str | dict | None = None, **kwargs: Any
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        formatted = [convert_to_openai_tool(t) for t in tools]
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        return self.bind(tools=formatted, **kwargs)

    def with_structured_output(
        self,
        schema: type[BaseModel] | dict,
        *,
        include_raw: bool = False,
        max_retries: int = 1,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, Any]:
        """response_format: json_schema + Pydantic-валидация с retry (В8.4).

        По умолчанию max_retries=1: один ремонт схемы, не цикл из трёх+ вызовов.
        """
        return _StructuredOutputRunnable(
            self, schema, include_raw=include_raw, max_retries=max_retries
        )


class _StructuredOutputRunnable(Runnable[LanguageModelInput, Any]):
    """Биндит response_format=json_schema, валидирует ответ Pydantic-моделью, на провале
    подмешивает ошибку и переспрашивает (до max_retries раз)."""

    def __init__(
        self,
        llm: OpenRouterChatModel,
        schema: type[BaseModel] | dict,
        *,
        include_raw: bool = False,
        max_retries: int = 1,
    ) -> None:
        self._llm = llm
        self._schema = schema
        self._include_raw = include_raw
        self._max_retries = max_retries
        self._is_pydantic = isinstance(schema, type) and issubclass(schema, BaseModel)
        self._response_format = self._build_response_format(schema)

    @staticmethod
    def _build_response_format(schema: type[BaseModel] | dict) -> dict:
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            name, json_schema = schema.__name__, schema.model_json_schema()
        else:
            name = schema.get("title", "Output") if isinstance(schema, dict) else "Output"
            json_schema = schema
        # strict=False: схема как подсказка провайдеру, гарантия — наша Pydantic-валидация.
        # minimum/maximum срезаем: Anthropic structured output их не принимает (см. helper выше).
        return {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "schema": _strip_unsupported_schema_keys(json_schema),
                "strict": False,
            },
        }

    def _parse(self, text: str) -> Any:
        candidate = _extract_json_object(text)
        if self._is_pydantic:
            return self._schema.model_validate_json(candidate)  # type: ignore[union-attr]
        return json.loads(candidate)

    @staticmethod
    def _text_of(message: BaseMessage) -> str:
        if isinstance(message.content, str):
            return message.content
        return "\n".join(b.get("text", "") for b in message.content if isinstance(b, dict))

    def invoke(self, input: LanguageModelInput, config: RunnableConfig | None = None, **kw: Any):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.ainvoke(input, config, **kw))
        raise NotImplementedError("structured output — async-first; используй ainvoke")

    async def ainvoke(
        self, input: LanguageModelInput, config: RunnableConfig | None = None, **kw: Any
    ) -> Any:
        bound = self._llm.bind(response_format=self._response_format)
        messages = self._llm._convert_input(input).to_messages()
        last_error: Exception | None = None
        ai: BaseMessage | None = None
        for _ in range(self._max_retries + 1):
            ai = await bound.ainvoke(messages, config=config, **kw)
            try:
                parsed = self._parse(self._text_of(ai))
                if self._include_raw:
                    return {"raw": ai, "parsed": parsed, "parsing_error": None}
                return parsed
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                messages = [
                    *messages,
                    ai,
                    HumanMessage(
                        content=(
                            f"Ответ не прошёл валидацию схемы: {exc}. "
                            "Верни строго корректный JSON по схеме, без markdown и пояснений."
                        )
                    ),
                ]
        if self._include_raw:
            return {"raw": ai, "parsed": None, "parsing_error": last_error}
        raise OpenRouterResponseError(
            f"structured output не прошёл валидацию после {self._max_retries} ретраев: {last_error}"
        )


def get_chat_model(
    tier_or_agent: str,
    *,
    settings: CoreSettings | None = None,
    usage_sink: UsageSink | None = None,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    model_override: str | None = None,
    agent: str | None = None,
    **kwargs: Any,
) -> OpenRouterChatModel:
    """Фабрика по тиру (`advanced`/`basic`/`reserve`) или имени фичи из реестра.

    Имена моделей берутся только из конфига — в коде их нет (CLAUDE.md).

    Домены зовут `run(feature)` / `complete_*`, не эту функцию напрямую.
    `agent` — ярлык для usage/LangSmith, если `tier_or_agent` уже тир (из `chat_model_for`/`run`).
    `model_override` — явная модель поверх тира (редкие ensemble-шаги).
    """
    settings = settings or get_settings()
    # Идемпотентно поднять трассировку до первого вызова (задача 0.3).
    configure_langsmith()

    if tier_or_agent in TIERS:
        tier = tier_or_agent
        agent_name = agent or tier_or_agent
    else:
        from core.platform.llm.registry import resolve_tier

        agent_name = agent or tier_or_agent
        tier = resolve_tier(tier_or_agent, settings=settings)
        if tier not in TIERS:
            tier = "basic"

    primary = normalize_openrouter_model(model_override or settings.tier_model(tier))
    if not primary:
        raise OpenRouterError(
            f"Не задана модель для тира '{tier}' (MODEL_TIER_{tier.upper()} в .env)"
        )
    # При явном override модель тира не выпадает из цепочки деградации — иначе перегруженный
    # override падает сразу в глобальный fallback (см. `_models_to_try`).
    override_base = ""
    if model_override:
        tier_slug = normalize_openrouter_model(settings.tier_model(tier) or "")
        if tier_slug and tier_slug != primary:
            override_base = tier_slug

    # agent/tier → tags и metadata каждого рана LangSmith (cost попадает в on_llm_end
    # через llm_output/usage_metadata, подшаг 2).
    kwargs.setdefault("tags", [f"tier:{tier}", f"agent:{agent_name}"])
    kwargs.setdefault("metadata", {"agent": agent_name, "tier": tier})

    # L-13: HTTP-таймаут не короче budget_ms фичи — иначе wait_for ещё думает, а сокет уже мёртв.
    budget_ms = kwargs.get("budget_ms")
    base_timeout = float(settings.llm_timeout_s or 90.0)
    if isinstance(budget_ms, (int, float)) and budget_ms > 0:
        request_timeout = max(base_timeout, float(budget_ms) / 1000.0 + 5.0)
    else:
        request_timeout = base_timeout
    kwargs.setdefault("request_timeout", request_timeout)

    # L-14: chat_model_for передаёт effort фичи (в т.ч. None); прямой get_chat_model(tier) —
    # легаси MODEL_TIER_EFFORT.
    if "reasoning_effort" in kwargs:
        reasoning_effort = kwargs.pop("reasoning_effort")
    else:
        reasoning_effort = settings.tier_effort(tier)

    model = OpenRouterChatModel(
        primary_model=primary,
        fallback_model=normalize_openrouter_model(settings.openrouter_model_fallback or ""),
        tier_fallback_model=settings.tier_fallback(tier),
        override_base_model=override_base,
        # getattr: часть тестов подсовывает урезанный стаб настроек без нового поля.
        provider_prefs=dict(getattr(settings, "openrouter_provider", None) or {}),
        tier=tier,
        agent=agent_name,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=settings.llm_max_retries,
        base_url=settings.openrouter_base_url,
        # Ключ (Этап 5 + изоляция member'ов):
        # - если запрос/апдейт привязан к account_id — ТОЛЬКО ключ этого аккаунта
        #   (пустой = нет ключа; не падаем на runtime/.env владельца — иначе расширение
        #   до BYOK жжёт счёт оператора);
        # - фон/скрипт без личности — process holder → OPENROUTER_API_KEY из .env.
        api_key=(
            current_account_openrouter_key()
            if current_account_id() is not None
            else (runtime_openrouter_key() or settings.openrouter_api_key)
        ),
        proxy=settings.openrouter_proxy or None,
        reasoning_effort=reasoning_effort,
        **kwargs,
    )
    if usage_sink is not None:
        model._usage_sink = usage_sink
    return model
