"""Понятные ошибки конфигурации: имена секретов, не dump 95-полевой модели."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

# Секреты/инфраструктура, без которых «пустой» старт бессмысленен для друга.
# OPENROUTER_API_KEY сюда не входит: путь друга — ключ на вкладке «Параметры».
_ENV_BOOTSTRAP_HINTS: tuple[str, ...] = (
    "POSTGRES_HOST / POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB",
    "OPENROUTER_API_KEY (или ключ на вкладке «Параметры»)",
    "TELEGRAM_BOT_TOKEN (вход в веб — токен из бота) и API_KEY (расширение, опционально)",
)


class ConfigError(Exception):
    """Ошибка загрузки настроек: короткий текст + список полей/секретов."""

    def __init__(self, message: str, *, missing: Sequence[str] = ()) -> None:
        self.missing = [str(m) for m in missing]
        super().__init__(message)


def format_validation_error(exc: ValidationError) -> ConfigError:
    """Свернуть pydantic ValidationError в ConfigError с именами полей."""
    fields: list[str] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        if loc:
            fields.append(".".join(str(p) for p in loc))
        else:
            fields.append(err.get("type", "unknown"))
    # Уникальные, в стабильном порядке
    uniq = sorted(set(fields))
    listed = ", ".join(uniq) if uniq else "(неизвестно)"
    return ConfigError(
        f"Не удалось загрузить настройки из .env: битые поля {listed}. "
        "Проверьте типы и пустые числовые значения (образец — deploy/.env.example).",
        missing=uniq,
    )


def ensure_env_file(*, root: Path | None = None) -> None:
    """Нет `.env` в корне → ConfigError со списком, что заполнить.

    Не зовётся из `get_settings()` (тесты/CI могут жить на одних env-переменных).
    Зовётся из lifespan API, когда ожидаем файл .env.
    """
    base = root if root is not None else Path.cwd()
    env_path = base / ".env"
    if env_path.is_file():
        return
    hints = "; ".join(_ENV_BOOTSTRAP_HINTS)
    raise ConfigError(
        f"Нет файла .env в {base.resolve()}. "
        "Скопируйте deploy/.env.example → .env и задайте: "
        f"{hints}.",
        missing=[".env", *_ENV_BOOTSTRAP_HINTS],
    )


__all__ = ["ConfigError", "ensure_env_file", "format_validation_error"]
