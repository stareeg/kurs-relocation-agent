"""A-0: серверный провайдер вместо ключа OpenRouter у каждого пользователя.

Три режима фабрики:
- у аккаунта есть свой ключ → OpenRouter, ключ и счёт аккаунта (как раньше);
- ключа нет, серверный провайдер задан → LiteLLM перед инференс-ВМ, ключ только в настройках;
- серверный провайдер не задан → прежнее поведение (process holder / .env).
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from core.platform.config import runtime as cfg_runtime
from core.platform.config.llm import LlmSettings, ServerLlmSettings
from core.platform.config.runtime import cache_account_use_personal_key, llm_available
from core.platform.llm.openrouter_chat import (
    OpenRouterChatModel,
    OpenRouterError,
    get_chat_model,
)

SERVER_BASE = "http://litellm:4000"
SERVER_KEY = "sk-server-master"
ACCOUNT_KEY = "sk-or-v1-account"


@pytest.fixture(autouse=True)
def _reset_runtime() -> None:
    cfg_runtime.reset_runtime_for_tests()
    yield
    cfg_runtime.reset_runtime_for_tests()


class _Settings(LlmSettings, ServerLlmSettings):
    """Секции LLM и серверного провайдера вместе — как в CoreSettings, без БД-полей."""


def _settings(**overrides: object) -> _Settings:
    values: dict[str, object] = {
        "model_tier_advanced": "openai/gpt-5.6-luna",
        "model_tier_basic": "openai/gpt-5.6-luna",
        "model_tier_reserve": "google/gemini-3.7-flash",
        "server_llm_base_url": SERVER_BASE,
        "server_llm_api_key": SERVER_KEY,
        "model_server_advanced": "glm-5.3-flash",
        "model_server_basic": "glm-5.3-flash",
        "model_server_reserve": "openrouter-reserve",
        "openrouter_base_url": "https://openrouter.ai/api/v1",
        "openrouter_api_key": "sk-or-v1-process",
        "openrouter_proxy": None,
    }
    values.update(overrides)
    return _Settings(**values)


def test_server_available_requires_both_address_and_key() -> None:
    assert _settings().server_llm_available() is True
    assert _settings(server_llm_api_key="").server_llm_available() is False
    assert _settings(server_llm_base_url="  ").server_llm_available() is False


def test_server_tier_model_empty_when_not_set() -> None:
    assert _settings().server_tier_model("advanced") == "glm-5.3-flash"
    assert _settings(model_server_advanced="").server_tier_model("advanced") == ""


def test_account_without_key_goes_to_server_provider() -> None:
    token = cfg_runtime.set_current_account_id(42)
    try:
        model = get_chat_model("advanced", settings=_settings())
    finally:
        cfg_runtime.reset_current_account_id(token)

    assert model.base_url == SERVER_BASE
    assert model.api_key == SERVER_KEY
    assert model.primary_model == "glm-5.3-flash"
    assert model.api_style == "openai"
    # Цепочку деградации держит LiteLLM, приложению запасные slug'и не нужны.
    assert model.fallback_model == ""
    assert model.tier_fallback_model == ""


def test_personal_key_with_toggle_wins_over_server_provider() -> None:
    cfg_runtime.cache_account_openrouter_key(42, ACCOUNT_KEY)
    cache_account_use_personal_key(42, True)
    token = cfg_runtime.set_current_account_id(42)
    try:
        model = get_chat_model("advanced", settings=_settings())
    finally:
        cfg_runtime.reset_current_account_id(token)

    assert model.base_url == "https://openrouter.ai/api/v1"
    assert model.api_key == ACCOUNT_KEY
    assert model.primary_model == "openai/gpt-5.6-luna"
    assert model.api_style == "openrouter"


def test_background_without_account_uses_server_when_configured() -> None:
    model = get_chat_model("basic", settings=_settings())
    assert model.base_url == SERVER_BASE
    assert model.api_key == SERVER_KEY
    assert model.api_style == "openai"


def test_server_provider_without_tier_model_fails_loudly() -> None:
    token = cfg_runtime.set_current_account_id(42)
    try:
        with pytest.raises(OpenRouterError, match="MODEL_SERVER_ADVANCED"):
            get_chat_model("advanced", settings=_settings(model_server_advanced=""))
    finally:
        cfg_runtime.reset_current_account_id(token)


def test_openai_style_payload_has_no_openrouter_fields() -> None:
    model = OpenRouterChatModel(
        primary_model="glm-5.3-flash",
        base_url=SERVER_BASE,
        api_key=SERVER_KEY,
        api_style="openai",
        reasoning_effort="low",
        provider_prefs={"sort": "throughput"},
    )
    payload = model._build_payload([HumanMessage(content="привет")], "glm-5.3-flash", None, {})

    assert payload["model"] == "glm-5.3-flash"
    assert payload["reasoning_effort"] == "low"
    assert "usage" not in payload
    assert "provider" not in payload
    assert "reasoning" not in payload


def test_openai_style_without_effort_defaults_to_low() -> None:
    model = OpenRouterChatModel(
        primary_model="glm-5.3-flash",
        base_url=SERVER_BASE,
        api_key=SERVER_KEY,
        api_style="openai",
    )
    payload = model._build_payload([HumanMessage(content="привет")], "glm-5.3-flash", None, {})
    assert payload["reasoning_effort"] == "low"


def test_openai_style_medium_effort_is_lowered_to_low() -> None:
    model = OpenRouterChatModel(
        primary_model="glm-5.3-flash",
        base_url=SERVER_BASE,
        api_key=SERVER_KEY,
        api_style="openai",
        reasoning_effort="medium",
    )
    payload = model._build_payload([HumanMessage(content="привет")], "glm-5.3-flash", None, {})
    assert payload["reasoning_effort"] == "low"


def test_openai_style_high_effort_stays_high() -> None:
    model = OpenRouterChatModel(
        primary_model="glm-5.3-flash",
        base_url=SERVER_BASE,
        api_key=SERVER_KEY,
        api_style="openai",
        reasoning_effort="high",
    )
    payload = model._build_payload([HumanMessage(content="привет")], "glm-5.3-flash", None, {})
    assert payload["reasoning_effort"] == "high"


def test_openai_style_none_effort_is_lowered_to_low() -> None:
    model = OpenRouterChatModel(
        primary_model="glm-5.3-flash",
        base_url=SERVER_BASE,
        api_key=SERVER_KEY,
        api_style="openai",
        reasoning_effort="none",
    )
    payload = model._build_payload([HumanMessage(content="привет")], "glm-5.3-flash", None, {})
    assert payload["reasoning_effort"] == "low"


def test_openrouter_style_payload_keeps_provider_and_reasoning_object() -> None:
    model = OpenRouterChatModel(
        primary_model="openai/gpt-5.6-luna",
        base_url="https://openrouter.ai/api/v1",
        api_key=ACCOUNT_KEY,
        reasoning_effort="high",
        provider_prefs={"sort": "throughput"},
    )
    payload = model._build_payload(
        [HumanMessage(content="привет")], "openai/gpt-5.6-luna", None, {}
    )

    assert payload["usage"] == {"include": True}
    assert payload["provider"] == {"sort": "throughput"}
    assert payload["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in payload


def test_llm_available_is_true_with_server_provider_and_no_keys() -> None:
    settings = _Settings(
        server_llm_base_url=SERVER_BASE,
        server_llm_api_key=SERVER_KEY,
        model_server_advanced="glm-5.3-flash",
    )
    assert llm_available(settings=settings) is True


def test_llm_available_false_without_any_path_to_a_model() -> None:
    assert llm_available(settings=_Settings()) is False


def test_llm_available_account_key_counts_without_server() -> None:
    cfg_runtime.cache_account_openrouter_key(7, ACCOUNT_KEY)
    token = cfg_runtime.set_current_account_id(7)
    try:
        assert llm_available(settings=_Settings()) is True
    finally:
        cfg_runtime.reset_current_account_id(token)


def test_llm_available_process_key_counts_for_background() -> None:
    assert llm_available(settings=_Settings(openrouter_api_key="sk-or-v1-process")) is True


def test_personal_key_needs_toggle_when_server_is_configured() -> None:
    cfg_runtime.cache_account_openrouter_key(42, ACCOUNT_KEY)
    token = cfg_runtime.set_current_account_id(42)
    try:
        model = get_chat_model("advanced", settings=_settings())
    finally:
        cfg_runtime.reset_current_account_id(token)
    # Тумблер выключен по умолчанию: даже со своим ключом человек на модели курса.
    assert model.base_url == SERVER_BASE
    assert model.api_key == SERVER_KEY


def test_personal_key_with_toggle_on_goes_to_openrouter() -> None:
    cfg_runtime.cache_account_openrouter_key(42, ACCOUNT_KEY)
    cache_account_use_personal_key(42, True)
    token = cfg_runtime.set_current_account_id(42)
    try:
        model = get_chat_model("advanced", settings=_settings())
    finally:
        cfg_runtime.reset_current_account_id(token)
    assert model.base_url == "https://openrouter.ai/api/v1"
    assert model.api_key == ACCOUNT_KEY
    assert model.api_style == "openrouter"


def test_personal_key_works_without_server_provider_even_with_toggle_off() -> None:
    cfg_runtime.cache_account_openrouter_key(42, ACCOUNT_KEY)
    token = cfg_runtime.set_current_account_id(42)
    try:
        model = get_chat_model(
            "advanced",
            settings=_settings(server_llm_base_url="", server_llm_api_key=""),
        )
    finally:
        cfg_runtime.reset_current_account_id(token)
    # Friend-install: серверного провайдера нет, свой ключ — единственный путь.
    assert model.base_url == "https://openrouter.ai/api/v1"
    assert model.api_key == ACCOUNT_KEY
