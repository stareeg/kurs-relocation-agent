"""Собранный CoreSettings: Db + Llm + App + Integration.

Слои правды:
1. дефолты в коде (поля секций ниже) — рядом с смыслом;
2. `.env` — секреты и инфраструктура (перекрывает дефолты);
3. `app_settings` (Postgres) — пользовательские ручки UI (веса, ключ OpenRouter);
   накладываются через `runtime.set_runtime_openrouter_key` / `core.platform.repo.settings`.

`*_prompt_path` сюда не входят — пути промптов в `domains/*/llm.py`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings

from core.platform.config.app import AppSettings
from core.platform.config.base import SETTINGS_CONFIG, strip_blank_numeric_env
from core.platform.config.db import DbSettings
from core.platform.config.integrations import IntegrationSettings
from core.platform.config.llm import LlmSettings
from core.platform.config.runtime import apply_runtime_to
from core.platform.config.secrets import format_validation_error


class CoreSettings(
    BaseSettings,
    DbSettings,
    LlmSettings,
    AppSettings,
    IntegrationSettings,
):
    """Единый объект настроек процесса. Секции — для документации и точечных ошибок."""

    model_config = SETTINGS_CONFIG

    @model_validator(mode="before")
    @classmethod
    def _strip_blank_numeric(cls, data: object) -> object:
        return strip_blank_numeric_env(cls, data)


def load_settings() -> CoreSettings:
    """Загрузить настройки; ValidationError → ConfigError с именами полей."""
    try:
        settings = CoreSettings()
    except ValidationError as exc:
        raise format_validation_error(exc) from exc
    return apply_runtime_to(settings)


@lru_cache
def get_settings() -> CoreSettings:
    """Кэшированный singleton настроек процесса."""
    return load_settings()


def clear_settings_cache() -> None:
    """Сбросить кэш (тесты, после подмены env)."""
    get_settings.cache_clear()


__all__ = [
    "CoreSettings",
    "clear_settings_cache",
    "get_settings",
    "load_settings",
]
