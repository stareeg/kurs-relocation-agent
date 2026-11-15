"""Слоистый конфиг: defaults в коде → .env → app_settings (БД).

Публичный вход для остального кода по-прежнему `core.config` (тонкий фасад).
Прямой импорт из `core.platform.config` допустим в platform/app.
"""

from core.platform.config.app import AppSettings
from core.platform.config.base import normalize_openrouter_model, strip_blank_numeric_env
from core.platform.config.db import DbSettings
from core.platform.config.integrations import IntegrationSettings
from core.platform.config.llm import LlmSettings, ServerLlmSettings
from core.platform.config.runtime import (
    account_openrouter_key_cache_stale,
    cache_account_openrouter_key,
    cache_account_use_personal_key,
    current_account_id,
    current_account_openrouter_key,
    current_account_use_personal_key,
    llm_available,
    reset_current_account_id,
    runtime_openrouter_key,
    set_current_account_id,
    set_runtime_openrouter_key,
)
from core.platform.config.secrets import ConfigError, ensure_env_file
from core.platform.config.settings import (
    CoreSettings,
    clear_settings_cache,
    get_settings,
    load_settings,
)

__all__ = [
    "AppSettings",
    "ConfigError",
    "CoreSettings",
    "DbSettings",
    "IntegrationSettings",
    "LlmSettings",
    "ServerLlmSettings",
    "account_openrouter_key_cache_stale",
    "cache_account_openrouter_key",
    "cache_account_use_personal_key",
    "clear_settings_cache",
    "current_account_id",
    "current_account_openrouter_key",
    "current_account_use_personal_key",
    "ensure_env_file",
    "get_settings",
    "llm_available",
    "load_settings",
    "normalize_openrouter_model",
    "reset_current_account_id",
    "runtime_openrouter_key",
    "set_current_account_id",
    "set_runtime_openrouter_key",
    "strip_blank_numeric_env",
]
