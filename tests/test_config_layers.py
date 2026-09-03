"""A-18: слоистый конфиг — секции, понятные ошибки, без *_prompt_path."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import (
    AppSettings,
    ConfigError,
    CoreSettings,
    DbSettings,
    IntegrationSettings,
    LlmSettings,
    clear_settings_cache,
    ensure_env_file,
    get_settings,
    load_settings,
)
from core.platform.config.secrets import format_validation_error


@pytest.fixture(autouse=True)
def _clear_settings():
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_core_settings_is_composed_of_four_sections():
    assert issubclass(CoreSettings, DbSettings)
    assert issubclass(CoreSettings, LlmSettings)
    assert issubclass(CoreSettings, AppSettings)
    assert issubclass(CoreSettings, IntegrationSettings)


def test_no_prompt_path_fields_left():
    """A-06/R-40: пути промптов не в CoreSettings (реестр LlmFeature)."""
    prompt_fields = [n for n in CoreSettings.model_fields if n.endswith("prompt_path")]
    assert prompt_fields == []
    assert "instructions_path" not in CoreSettings.model_fields


def test_migrations_dir_points_to_platform():
    assert get_settings().migrations_dir == "core/platform/db/migrations"
    assert Path(get_settings().migrations_dir).is_dir()


def test_missing_env_file_lists_concrete_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Старт без .env → понятная ошибка про секреты, не простыня модели."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as ei:
        ensure_env_file(root=tmp_path)
    msg = str(ei.value)
    assert ".env" in msg
    assert "deploy/.env.example" in msg
    assert "OPENROUTER_API_KEY" in msg
    assert "POSTGRES" in msg
    # Не dump 95 полей pydantic
    assert len(msg) < 600
    assert "model_fields" not in msg


def test_ensure_env_file_ok_when_present(tmp_path: Path):
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=\n", encoding="utf-8")
    ensure_env_file(root=tmp_path)  # не бросает


def test_validation_error_names_specific_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Битое поле → ConfigError с именем поля, не ValidationError на всю модель."""
    import os

    env = tmp_path / ".env"
    env.write_text("POSTGRES_PORT=not-a-number\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # Убрать унаследованные из окружения процесса POSTGRES_* — иначе перекроют файл.
    for key in list(os.environ):
        if key.startswith(("POSTGRES_", "OPENROUTER_")):
            monkeypatch.delenv(key, raising=False)
    clear_settings_cache()
    with pytest.raises(ConfigError) as ei:
        load_settings()
    msg = str(ei.value).lower()
    assert "postgres_port" in msg
    assert len(str(ei.value)) < 500


def test_format_validation_error_is_short():
    try:
        CoreSettings.model_validate({"postgres_port": "x", "llm_max_retries": "y"})
    except ValidationError as exc:
        err = format_validation_error(exc)
    else:
        pytest.fail("ожидали ValidationError")
    assert isinstance(err, ConfigError)
    assert "postgres_port" in err.missing or "llm_max_retries" in err.missing
    assert len(str(err)) < 500


def test_section_field_counts_are_focused():
    """Секции заметно меньше монолита: ошибка по секции не тянет 95 полей."""
    assert len(DbSettings.model_fields) <= 12
    assert len(LlmSettings.model_fields) <= 25
    assert len(AppSettings.model_fields) <= 20
    total = len(CoreSettings.model_fields)
    # Монолит был ~95 с prompt_path; после A-06/A-18 — заметно меньше.
    assert total < 90
