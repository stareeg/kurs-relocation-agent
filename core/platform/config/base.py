"""Общие примитивы слоистого конфига."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# Устаревшие/ошибочные slug из .env → канон OpenRouter. Пусто в норме — заполняется, когда
# в проде всплывает конкретный битый alias.
# `deepseek/deepseek-v4-flash-latest` без `~` — частая опечатка; канон OpenRouter always-latest
# для семейства Flash — с тильдой (`~deepseek/...`).
_OPENROUTER_MODEL_ALIASES: dict[str, str] = {
    "deepseek/deepseek-v4-flash-latest": "~deepseek/deepseek-v4-flash-latest",
}

SETTINGS_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    # Поля `model_*` (MODEL_TIER_*, MODEL_PRICES) — не конфликт с pydantic namespace.
    protected_namespaces=(),
)


def strip_blank_numeric_env(cls: type[BaseSettings], data: object) -> object:
    """Пустые строки из .env для числовых/булевых/JSON-полей → выкинуть, чтобы применился дефолт.

    Путь друга: .env создаётся из deploy/.env.example, где опции могут быть пустыми
    (напр. `ADMIN_USER_ID=`, `OPENROUTER_PROVIDER=`). Pydantic v2 не приводит '' к int/float/bool
    (и не парсит '' как JSON для dict/list) — роняет ВЕСЬ запуск сервера на этапе загрузки
    настроек (инцидент 2026-07-22, docs/problems.md).
    """
    if not isinstance(data, dict):
        return data
    for name, field in cls.model_fields.items():
        value = data.get(name)
        # bool — подкласс int: isinstance(default, (int, float)) ловит int/float/bool.
        if (
            isinstance(value, str)
            and not value.strip()
            and isinstance(field.default, (int, float, dict, list))
        ):
            data.pop(name)
    return data


def normalize_openrouter_model(model: str) -> str:
    """Привести slug модели к канону OpenRouter (алиасы из старых .env)."""
    m = (model or "").strip()
    return _OPENROUTER_MODEL_ALIASES.get(m, m)


__all__ = [
    "SETTINGS_CONFIG",
    "normalize_openrouter_model",
    "strip_blank_numeric_env",
]
