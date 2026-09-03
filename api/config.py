"""Конфиг API: pydantic-settings, источник — .env в корне репо.

Секреты и ключи — только через .env и secrets/ (см. CLAUDE.md).
extra="ignore" — в одном .env живут переменные API, ядра и бота.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.config import strip_blank_numeric_env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Пустые числовые/булевы переменные из .env друга → дефолт, а не краш запуска API
    # (инцидент 2026-07-22, docs/problems.md): '' не парсится в int/bool.
    @model_validator(mode="before")
    @classmethod
    def _strip_blank_numeric(cls, data: object) -> object:
        return strip_blank_numeric_env(cls, data)

    app_name: str = "Career Copilot API"

    # Postgres (compose: сервис postgres)
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "copilot"
    postgres_password: str = "copilot"
    postgres_db: str = "copilot"

    # --- Auth ---
    # Статический X-API-Key из .env — запасной путь расширения/скриптов. Основная учётка —
    # web-токен из Telegram-бота (api/security.py); логин по паролю удалён (2026-07-31).
    api_key: str = ""
    # Этап 2 (плана хостинга): `Secure` на cookie `copilot_auth`. False по умолчанию —
    # локальная разработка на http://localhost сломалась бы иначе
    # (браузер тихо не ставит Secure-cookie без https). На хостинге за Caddy/TLS — true в .env.
    web_cookie_secure: bool = False

    # --- CORS (задача 2.5, подшаг 5) ---
    # Origin фронта (Vite dev по умолчанию) — для /api/* с cookie-сессией.
    frontend_origin: str = "http://localhost:5173"
    # chrome-extension://<id> матчится регуляркой (id расширения меняется) — для /score.
    extension_origin_regex: str = r"^chrome-extension://.*$"

    # --- Telegram: тот же TELEGRAM_BOT_TOKEN, что у бота; api не импортирует bot_app ---
    telegram_bot_token: str = ""
    # Username официального бота продукта (без @). Пользователи не создают своих ботов:
    # фронт всегда показывает ссылку t.me/<username>, даже пока кэш getMe пуст.
    telegram_bot_username: str = "BBX_fan_bot"


@lru_cache
def get_settings() -> Settings:
    return Settings()
