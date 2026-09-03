"""Доменные ошибки → единый HTTP-конверт.

Домен не должен ловить `OpenRouterError` или asyncpg-исключения: инфраструктурные сбои
приходят через порты (`kernel/ports.py`) уже как ошибки этого модуля.

Машинный ``code`` стабилен для транспорта/фронта; ``message`` — человекочитаемый текст.
Маппинг в HTTP — только в ``api/errors.py`` (пустой вход → 400, лимит → 429, нет ключа → 503).
"""

from __future__ import annotations


class DomainError(Exception):
    """Ошибка домена с машинным кодом для транспорта."""

    code = "domain_error"

    def __init__(self, message: str = "", *, code: str | None = None, details: dict | None = None):
        if code:
            self.code = code
        self.message = message or self.code
        self.details = details or {}
        super().__init__(self.message)


class PortNotBoundError(DomainError):
    """Порт запрошен раньше, чем композиционный корень его связал (см. `core/app/wiring.py`)."""

    code = "port_unbound"


class InvalidInput(DomainError):
    """Вход не проходит проверку сценария (пустой текст, неизвестный статус воронки)."""

    code = "invalid_input"


class Unprocessable(DomainError):
    """Вход синтаксически корректен, но сценарий не может из него ничего сделать."""

    code = "unprocessable"


class NotFound(DomainError):
    """Сущность, на которой держится сценарий, не найдена."""

    code = "not_found"


class RateLimited(DomainError):
    """Лимит провайдера/бюджета исчерпан — повтор позже или смена ключа."""

    code = "rate_limited"


class StorageUnavailable(DomainError):
    """Postgres недоступен там, где деградация недопустима (иначе UI соврёт про сохранение)."""

    code = "storage_unavailable"


class UpstreamError(DomainError):
    """Внешний источник ответил ошибкой — сценарий не виноват, повтор может помочь."""

    code = "upstream_error"


class InternalError(DomainError):
    """Инвариант домена нарушен (битый jsonb, повреждённые настройки) — чинится руками."""

    code = "internal_error"


class LlmError(DomainError):
    """Сбой LLM-порта: провайдер, сеть, таймаут бюджета, невалидный структурный ответ.

    Нет ключа OpenRouter — тоже сюда (транспорт → 503). Лимит 429 — ``RateLimited``.
    Домены ловят её там, где деградация лучше падения (fallback на эвристику/regex).
    """

    code = "llm_error"


__all__ = [
    "DomainError",
    "InternalError",
    "InvalidInput",
    "LlmError",
    "NotFound",
    "PortNotBoundError",
    "RateLimited",
    "StorageUnavailable",
    "Unprocessable",
    "UpstreamError",
]
