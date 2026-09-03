"""Пустые числовые/булевы переменные из .env не должны ронять загрузку настроек.

Инцидент 2026-07-22 (путь друга): .env создаётся из deploy/.env.example, где `ADMIN_USER_ID=`
пусто. Pydantic v2 не приводит '' к int и валил ВЕСЬ main.py (BotSettings) до старта API —
сервер уходил в бесконечную автопочинку с кодом 1. Здесь фиксируем, что пустая строка для
числового/булева поля даёт дефолт, а не ValidationError, и что реальные значения не пострадали.
"""

from __future__ import annotations

from bot_app.config import BotSettings
from core.config import CoreSettings


def test_bot_settings_blank_admin_user_id_falls_back_to_default():
    # _env_file=None + явный пустой allowlist: изолируемся от реального .env/окружения владельца
    # (там могут быть заданы ADMIN_USER_IDS) — проверяем именно поведение пустого числового поля.
    settings = BotSettings(_env_file=None, admin_user_id="", admin_user_ids="")
    assert settings.admin_user_id == 0
    assert settings.admin_chat_id() is None


def test_bot_settings_blank_numeric_and_bool_fields_use_defaults():
    settings = BotSettings(
        _env_file=None,
        admin_user_id="",
        telegram_request_timeout="",
        salary_calib_min_pending="",
        bot_private_only="",
    )
    assert settings.telegram_request_timeout == 120.0
    assert settings.salary_calib_min_pending == 1
    assert settings.bot_private_only is True


def test_bot_settings_real_values_still_parse():
    settings = BotSettings(_env_file=None, admin_user_id="12345", bot_private_only="false")
    assert settings.admin_user_id == 12345
    assert isinstance(settings.admin_user_id, int)
    assert settings.bot_private_only is False
    assert settings.admin_chat_id() == 12345


def test_core_settings_blank_numeric_fields_use_defaults():
    settings = CoreSettings(
        _env_file=None,
        llm_timeout_s="",
        llm_max_input_chars="",
        postgres_port="",
    )
    assert settings.llm_timeout_s == 120.0
    assert settings.llm_max_input_chars == 800_000
    assert settings.postgres_port == 5432


def test_core_settings_string_field_keeps_blank():
    # Пустая строка для строкового поля легитимна (напр. ключ не задан) — не трогаем её.
    settings = CoreSettings(_env_file=None, openrouter_api_key="")
    assert settings.openrouter_api_key == ""
