"""Кэш результатов LLM: память + Postgres `llm_result_cache`.

Ключ формирует `call._cache_key` = feature : prompt_version : input_hash.
PG недоступен → только in-process (как NoopUsageSink: LLM-путь не падает).
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Дефолт TTL записи (повторное открытие карточки/пакета в пределах недели).
DEFAULT_TTL_S = 7 * 24 * 3600
_MEMORY_MAX_ENTRIES = 512


@runtime_checkable
class ResultCache(Protocol):
    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...


def _encode(value: Any) -> tuple[str, str, str | None, Any | None] | None:
    """→ (kind, schema_ref, value_text, value_json) или None если не кэшируем."""
    if isinstance(value, str):
        return ("text", "", value, None)
    if isinstance(value, BaseModel):
        cls = type(value)
        ref = f"{cls.__module__}:{cls.__qualname__}"
        return ("pydantic", ref, None, value.model_dump(mode="json"))
    if isinstance(value, (dict, list)):
        return ("json", "", None, value)
    return None


def _decode(kind: str, schema_ref: str, value_text: str | None, value_json: Any) -> Any | None:
    if kind == "text":
        return value_text if value_text is not None else ""
    if kind == "json":
        return value_json
    if kind == "pydantic":
        if not schema_ref or ":" not in schema_ref:
            return None
        mod_name, cls_name = schema_ref.rsplit(":", 1)
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
        except Exception as exc:  # noqa: BLE001 — устаревшая схема / рефакторинг
            logger.debug("llm_result_cache: не собрали %s: %s", schema_ref, exc)
            return None
        if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
            return None
        try:
            return cls.model_validate(value_json)
        except Exception as exc:  # noqa: BLE001
            logger.debug("llm_result_cache: validate %s: %s", schema_ref, exc)
            return None
    return None


class MemoryResultCache:
    """In-process LRU+TTL — всегда доступен, даже без Postgres."""

    def __init__(self, *, max_entries: int = _MEMORY_MAX_ENTRIES) -> None:
        self._items: OrderedDict[str, tuple[Any, float | None]] = OrderedDict()
        self._max = max(16, max_entries)

    async def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        value, expires_mono = item
        if expires_mono is not None and time.monotonic() >= expires_mono:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        if _encode(value) is None:
            return
        ttl = DEFAULT_TTL_S if ttl_s is None else ttl_s
        expires = time.monotonic() + ttl if ttl and ttl > 0 else None
        self._items[key] = (value, expires)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    async def delete(self, key: str) -> None:
        self._items.pop(key, None)


class PostgresResultCache:
    """Персистентный слой. Ошибки БД глотаются — кэш не должен ронять LLM."""

    def __init__(self, pool: Any | None = None) -> None:
        self._pool = pool

    def _resolve_pool(self) -> Any | None:
        if self._pool is not None:
            return self._pool
        try:
            from core.platform.db.pool import get_pool

            return get_pool()
        except Exception:  # noqa: BLE001 — пул не поднят / тесты
            return None

    async def get(self, key: str) -> Any | None:
        pool = self._resolve_pool()
        if pool is None:
            return None
        try:
            row = await pool.fetchrow(
                """
                select value_kind, schema_ref, value_text, value_json, expires_at
                from llm_result_cache
                where cache_key = $1
                """,
                key,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("llm_result_cache get: %s", exc)
            return None
        if row is None:
            return None
        expires_at = row["expires_at"]
        if expires_at is not None:
            now = datetime.now(UTC)
            exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
            if exp <= now:
                with contextlib.suppress(Exception):
                    await pool.execute("delete from llm_result_cache where cache_key = $1", key)
                return None
        value = _decode(
            row["value_kind"],
            row["schema_ref"] or "",
            row["value_text"],
            row["value_json"],
        )
        if value is None:
            return None
        with contextlib.suppress(Exception):
            await pool.execute(
                "update llm_result_cache set hits = hits + 1 where cache_key = $1",
                key,
            )
        return value

    async def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        encoded = _encode(value)
        if encoded is None:
            return
        pool = self._resolve_pool()
        if pool is None:
            return
        kind, schema_ref, value_text, value_json = encoded
        parts = key.split(":", 2)
        feature = parts[0] if parts else ""
        prompt_version = parts[1] if len(parts) > 1 else ""
        input_hash = parts[2] if len(parts) > 2 else key
        ttl = DEFAULT_TTL_S if ttl_s is None else ttl_s
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl) if ttl and ttl > 0 else None
        try:
            await pool.execute(
                """
                insert into llm_result_cache (
                    cache_key, feature, prompt_version, input_hash,
                    value_kind, schema_ref, value_text, value_json, expires_at
                ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                on conflict (cache_key) do update set
                    value_kind = excluded.value_kind,
                    schema_ref = excluded.schema_ref,
                    value_text = excluded.value_text,
                    value_json = excluded.value_json,
                    expires_at = excluded.expires_at,
                    created_at = now(),
                    hits = 0
                """,
                key,
                feature,
                prompt_version,
                input_hash,
                kind,
                schema_ref,
                value_text,
                value_json,
                expires_at,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("llm_result_cache set: %s", exc)

    async def delete(self, key: str) -> None:
        pool = self._resolve_pool()
        if pool is None:
            return
        try:
            await pool.execute("delete from llm_result_cache where cache_key = $1", key)
        except Exception as exc:  # noqa: BLE001
            logger.debug("llm_result_cache delete: %s", exc)


class LayeredResultCache:
    """Память → Postgres. Hit в PG прогревает память."""

    def __init__(
        self,
        memory: MemoryResultCache | None = None,
        postgres: PostgresResultCache | None = None,
    ) -> None:
        self._memory = memory or MemoryResultCache()
        self._postgres = postgres or PostgresResultCache()

    async def get(self, key: str) -> Any | None:
        hit = await self._memory.get(key)
        if hit is not None:
            return hit
        hit = await self._postgres.get(key)
        if hit is not None:
            await self._memory.set(key, hit)
        return hit

    async def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        await self._memory.set(key, value, ttl_s=ttl_s)
        await self._postgres.set(key, value, ttl_s=ttl_s)

    async def delete(self, key: str) -> None:
        await self._memory.delete(key)
        await self._postgres.delete(key)


_DEFAULT: ResultCache | None = None


def get_result_cache() -> ResultCache:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = LayeredResultCache()
    return _DEFAULT


def set_result_cache_for_tests(cache: ResultCache | None) -> None:
    """Подмена кэша в тестах (None → сброс к Layered по умолчанию при следующем get)."""
    global _DEFAULT
    _DEFAULT = cache


def reset_result_cache_for_tests() -> None:
    set_result_cache_for_tests(None)


__all__ = [
    "DEFAULT_TTL_S",
    "ResultCache",
    "MemoryResultCache",
    "PostgresResultCache",
    "LayeredResultCache",
    "get_result_cache",
    "set_result_cache_for_tests",
    "reset_result_cache_for_tests",
]
