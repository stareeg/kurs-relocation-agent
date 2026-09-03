"""Композиционный корень: реализации портов `kernel/ports.py` поверх `core.platform`.

Единственное место, где домен и инфраструктура встречаются. `api` и `bot_app` зовут
`wire_default_ports()` на старте; для CLI/скриптов есть ленивая страховка в
`core.kernel.ports._autowire`.

Правило слоёв: `app` знает и про `platform`, и про `kernel` — домены не знают ни про то,
ни про другое (кроме своих чистых моделей).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from core.app.subscriptions import register_domain_subscriptions
from core.app.uow import PostgresUnitOfWork
from core.kernel import ports
from core.kernel.errors import DomainError, LlmError, RateLimited
from core.kernel.events import DomainEvent
from core.platform.cache.result_cache import get_result_cache
from core.platform.events import log_domain_event
from core.platform.events.live import broadcaster as live_events
from core.platform.llm import OpenRouterError, OpenRouterRateLimitError
from core.platform.llm.call import CallContext, ImageInput, run


def _llm_failure(feature: str, exc: BaseException) -> DomainError:
    """Провайдерный сбой → доменная ошибка (лимит отдельно, чтобы api отдал 429).

    `message` — то, что увидит пользователь в тосте расширения/веба: короткий, без модели/HTTP-
    кодов/трейса (это не помогает пользователю и раньше выглядело как «непонятная ошибка»), но
    с кодом и именем фичи — есть что передать админу. Полная техническая цепочка (модели,
    статусы, `_response_diag` из `openrouter_chat.py`) — уже в `copilot_logs` через `event(...)`
    в `_run_with_retry`; дублировать её сюда не нужно, `details.cause` — на случай, если админ
    получит скриншот тоста, а не полезет в логи сам.
    """
    if isinstance(exc, OpenRouterRateLimitError):
        return RateLimited(
            f"ИИ-провайдер сейчас перегружен (лимит запросов). Попробуйте через пару минут — "
            f"если повторяется, сообщите админу код rate_limited, фича «{feature}».",
            details={"feature": feature, "cause": str(exc)},
        )
    return LlmError(
        f"ИИ-провайдер временно недоступен. Попробуйте ещё раз через пару минут — "
        f"если повторяется, сообщите админу код llm_error, фича «{feature}».",
        details={"feature": feature, "cause": str(exc)},
    )


logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _ctx(
    tags: Sequence[str],
    cache_key: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> CallContext | None:
    if not tags and cache_key is None and not metadata:
        return None
    return CallContext(cache_key=cache_key, tags=list(tags), metadata=dict(metadata or {}))


def _messages(messages: Sequence[Mapping[str, str]] | None) -> list[dict[str, str]] | None:
    """Порт отдаёт диалог чистыми dict'ами — в langchain-сообщения его переводит `run`."""
    if messages is None:
        return None
    return [dict(m) for m in messages]


def _images(images: Sequence[ports.ImageInput]) -> list[ImageInput]:
    """`kernel.ports.ImageInput` → платформенный двойник (`platform` не импортирует `kernel`).

    Сборка content-блоков для модели остаётся в `call.run` — адаптер только переносит байты.
    """
    return [ImageInput(sha256=i.sha256, mime=i.mime, data=i.data) for i in images]


class PlatformLlm:
    """`LlmPort` поверх `platform.llm.call.run`: реестр фич, бюджеты, кэш, метрики, usage.

    Ошибки провайдера и превышение `budget_ms` → `LlmError`; HTTP 429 провайдера →
    `RateLimited` (api отдаст 429). Домен не ловит `OpenRouterError`.
    """

    async def complete(
        self,
        feature: str,
        *,
        user: str | None = None,
        system: str | None = None,
        messages: Sequence[Mapping[str, str]] | None = None,
        prompt_vars: Mapping[str, str] | None = None,
        dynamic_tail: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_retries: int | None = None,
        tier_override: str | None = None,
        model_override: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        cache_key: str | None = None,
        images: Sequence[ports.ImageInput] = (),
    ) -> str:
        try:
            return await run(
                feature,
                system=system,
                prompt_vars=prompt_vars,
                dynamic_tail=dynamic_tail,
                user=user,
                messages=_messages(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                max_retries=max_retries,
                tier_override=tier_override,
                model_override=model_override,
                ctx=_ctx(tags, cache_key, metadata),
                images=_images(images),
            )
        except (OpenRouterError, TimeoutError) as exc:
            raise _llm_failure(feature, exc) from exc

    async def structured(
        self,
        feature: str,
        *,
        schema: type[ModelT],
        user: str | None = None,
        system: str | None = None,
        messages: Sequence[Mapping[str, str]] | None = None,
        prompt_vars: Mapping[str, str] | None = None,
        dynamic_tail: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_retries: int | None = None,
        tier_override: str | None = None,
        model_override: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        cache_key: str | None = None,
        images: Sequence[ports.ImageInput] = (),
    ) -> ModelT:
        try:
            result = await run(
                feature,
                system=system,
                prompt_vars=prompt_vars,
                dynamic_tail=dynamic_tail,
                user=user,
                messages=_messages(messages),
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                max_retries=max_retries,
                tier_override=tier_override,
                model_override=model_override,
                ctx=_ctx(tags, cache_key, metadata),
                images=_images(images),
            )
        except (OpenRouterError, TimeoutError) as exc:
            raise _llm_failure(feature, exc) from exc
        if not isinstance(result, schema):  # структурный контракт провайдера
            raise LlmError(
                f"фича {feature!r}: ожидался {schema.__name__}, получено {type(result).__name__}"
            )
        return result

    def stream(
        self,
        feature: str,
        *,
        user: str | None = None,
        system: str | None = None,
        messages: Sequence[Mapping[str, str]] | None = None,
        prompt_vars: Mapping[str, str] | None = None,
        dynamic_tail: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        tier_override: str | None = None,
        model_override: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        images: Sequence[ports.ImageInput] = (),
    ) -> AsyncIterator[str]:
        return self._stream(
            feature,
            user=user,
            system=system,
            messages=messages,
            prompt_vars=prompt_vars,
            dynamic_tail=dynamic_tail,
            temperature=temperature,
            max_tokens=max_tokens,
            tier_override=tier_override,
            model_override=model_override,
            tags=tags,
            metadata=metadata,
            images=images,
        )

    async def _stream(
        self,
        feature: str,
        *,
        user: str | None,
        system: str | None,
        messages: Sequence[Mapping[str, str]] | None,
        prompt_vars: Mapping[str, str] | None,
        dynamic_tail: str,
        temperature: float | None,
        max_tokens: int | None,
        tier_override: str | None,
        model_override: str | None,
        tags: Sequence[str],
        metadata: Mapping[str, Any] | None,
        images: Sequence[ports.ImageInput],
    ) -> AsyncIterator[str]:
        try:
            chunks = await run(
                feature,
                system=system,
                prompt_vars=prompt_vars,
                dynamic_tail=dynamic_tail,
                user=user,
                messages=_messages(messages),
                stream=True,
                temperature=temperature,
                max_tokens=max_tokens,
                tier_override=tier_override,
                model_override=model_override,
                ctx=_ctx(tags, None, metadata),
                images=_images(images),
            )
            async for chunk in chunks:
                yield chunk
        except (OpenRouterError, TimeoutError) as exc:
            raise _llm_failure(feature, exc) from exc


class PlatformCache:
    """`CachePort` поверх кэша результатов LLM (память + `llm_result_cache`)."""

    async def get(self, key: str) -> Any | None:
        return await get_result_cache().get(key)

    async def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        await get_result_cache().set(key, value, ttl_s=ttl_s)

    async def delete(self, key: str) -> None:
        await get_result_cache().delete(key)


def wire_default_ports(*, force: bool = False) -> None:
    """Связать порты с реализациями `platform`. Идемпотентно; `force` перетирает связанное.

    Не трогает то, что уже связано (например, фейк из теста или `Notifier` от бота).
    """
    from core.app.channels import register_builtin_channels
    from core.domains.opportunities.sources import register_builtin_sources

    ports.bind(
        llm=PlatformLlm(),
        cache=PlatformCache(),
        clock=ports.SystemClock(),
        # A-11: шина живёт в kernel (диспетчер без I/O), журнал витрины приходит из platform.
        events=ports.InProcessEventBus(journal=log_domain_event),
        # A-17: фабрика UoW — новый экземпляр на каждый `async with ports.uow()`.
        uow_factory=PostgresUnitOfWork,
        overwrite=force,
    )
    # A-26: hh / getmatch / habr — реализации VacancySource (новый источник = файл + регистрация).
    register_builtin_sources(overwrite=force)
    # A-27: web / telegram / extension — идентичности каналов (логика только в доменах).
    register_builtin_channels(overwrite=force)
    # Порядок важен: сначала связать шину, потом подписывать — иначе `ports.events()` создаст
    # дефолтную шину без журнала, и `bind(overwrite=False)` уже не заменит её.
    bus = ports.events()
    register_domain_subscriptions(bus)
    # L-45: фронт заменяет поллинг на SSE — один подписчик на всё (`DomainEvent`) рассылает
    # событие во все живые соединения `/api/events/stream`, фронт сам решает, что инвалидировать.
    bus.subscribe(DomainEvent, live_events.broadcast)


__all__ = ["PlatformCache", "PlatformLlm", "PostgresUnitOfWork", "wire_default_ports"]
