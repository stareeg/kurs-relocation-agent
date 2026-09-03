"""Ключ OpenRouter со страницы «Аккаунт» (in-process holder из БД) реально доходит до LLM.

Путь друга: он вставляет ключ на фронте (сохраняется в account_settings, при PATCH —
в per-account кэш). .env не трогает. Привязанный к account_id запрос НЕ падает на ключ
владельца/`.env` — иначе расширение до BYOK жгло бы счёт оператора.
Фон/скрипт без личности по-прежнему: process holder → .env.
"""

from __future__ import annotations

import pytest

from core.config import (
    CoreSettings,
    cache_account_openrouter_key,
    reset_current_account_id,
    set_current_account_id,
    set_runtime_openrouter_key,
)
from core.platform.config.runtime import reset_runtime_for_tests
from core.platform.llm.openrouter_chat import get_chat_model


def _settings(env_key: str = "") -> CoreSettings:
    # _env_file=None — не подмешиваем .env машины разработчика; тир задаём явно, чтобы фабрика
    # не упала на «не задана модель для тира».
    return CoreSettings(
        _env_file=None,
        model_tier_basic="openai/gpt-5.6-luna",
        openrouter_api_key=env_key,
    )


@pytest.fixture(autouse=True)
def _reset_runtime_key():
    reset_runtime_for_tests()
    yield
    reset_runtime_for_tests()


def test_db_key_takes_priority_over_env():
    set_runtime_openrouter_key("sk-or-db-123")
    model = get_chat_model("basic", settings=_settings(env_key="sk-or-env-999"))
    assert model.api_key == "sk-or-db-123"


def test_falls_back_to_env_key_when_no_account_context():
    model = get_chat_model("basic", settings=_settings(env_key="sk-or-env-999"))
    assert model.api_key == "sk-or-env-999"


def test_blank_db_key_resets_to_env_fallback():
    set_runtime_openrouter_key("   ")  # пустой/пробельный ключ = не задан
    model = get_chat_model("basic", settings=_settings(env_key="sk-or-env-999"))
    assert model.api_key == "sk-or-env-999"


def test_account_context_without_own_key_does_not_use_owner_env():
    """Member без BYOK не должен жечь OPENROUTER_API_KEY / runtime владельца."""
    set_runtime_openrouter_key("sk-or-owner-runtime")
    token = set_current_account_id(5)
    try:
        cache_account_openrouter_key(5, None)
        model = get_chat_model("basic", settings=_settings(env_key="sk-or-env-999"))
        assert model.api_key == ""
    finally:
        reset_current_account_id(token)


def test_account_context_uses_own_cached_key():
    token = set_current_account_id(5)
    try:
        cache_account_openrouter_key(5, "sk-or-member-own")
        model = get_chat_model("basic", settings=_settings(env_key="sk-or-env-999"))
        assert model.api_key == "sk-or-member-own"
    finally:
        reset_current_account_id(token)
