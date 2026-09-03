"""Конфиг бота (bot_app): pydantic-settings, источник — .env в корне репо (задача 2.6).

Бот — отдельный HTTP-клиент к новому api (на том же .env). Telegram-ключи переехали
Имена переменных .env: TELEGRAM_*, ADMIN_*.
Путь к API и X-API-Key — общий с api (BACKEND_URL указывает на новый API; API_KEY — тот же).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.config import strip_blank_numeric_env


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Пустой ADMIN_USER_ID= (и прочие числовые опции) из .env друга → дефолт, а не краш запуска
    # (инцидент 2026-07-22, docs/problems.md): '' не парсится в int и роняет весь main.py.
    @model_validator(mode="before")
    @classmethod
    def _strip_blank_numeric(cls, data: object) -> object:
        return strip_blank_numeric_env(cls, data)

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_proxy: str = ""
    # РКН режет TCP до api.telegram.org с рос. хостинга (docs/problems.md, 2026-08-05) — ICMP и
    # обычный интернет при этом живы, значит SOCKS-прокси тут не помогает так же просто, как раньше
    # (нужен внешний узел). TELEGRAM_API_BASE подменяет хост Bot API на прокси-воркер (напр.
    # Cloudflare Workers, deploy/cloudflare/proxy_worker.js), который сам не заблокирован —
    # см. bot_app/session.py: TelegramAPIServer.from_base(...).
    telegram_api_base: str = ""
    telegram_request_timeout: float = 120.0
    # Доступ владельца с нескольких аккаунтов (allowlist, логика из bot/admin_access.py).
    admin_user_id: int = 0
    admin_user_ids: str = ""
    admin_usernames: str = ""
    # true = отвечаем только в личке.
    bot_private_only: bool = True

    # --- Новый API (api) ---
    # BACKEND_URL теперь указывает на новый API (по умолчанию тот же :8000).
    backend_url: str = "http://localhost:8000"
    # Тот же ключ, что API_KEY в api — путь расширения и бота (X-API-Key).
    api_key: str = ""
    api_timeout_s: float = 90.0

    # --- getmatch-бот (GM-2/H2): username(s) отправителя форвардов getmatch-бота.
    # Comma-separated, как admin_user_ids (pydantic-settings v2 парсит list как JSON — неудобно для .env).
    getmatch_bot_usernames: str = "g_jobbot"

    def getmatch_bot_username_set(self) -> set[str]:
        """Lowercase-множество username'ов getmatch-бота для фильтра IsGetmatchPost."""
        return {
            raw.strip().lower().lstrip("@")
            for raw in (self.getmatch_bot_usernames or "").replace(";", ",").split(",")
            if raw.strip()
        }

    # --- Веб-дэшборд (JS-D.1: «для глаз» уехало в веб, бот линкует на него) ---
    # В dev фронт на Vite :5173. Inline-URL-кнопка рисуется только для https (Telegram
    # отвергает localhost/http у inline-кнопок и ломает отправку) — в dev URL даём текстом.
    # На проде выставить публичный https-URL дэшборда.
    web_url: str = "http://localhost:5173"

    # --- Калибровка зарплат ---
    salary_calib_auto: bool = False
    salary_calib_debounce_sec: float = 25.0
    salary_calib_min_pending: int = 1
    salary_calib_analyze_every: int = 12
    # Артефакт прогона бота — в logs/, не в plans/.
    salary_calib_export_path: str = "logs/salary_calibration_latest.md"

    def admin_chat_id(self) -> int | None:
        """Env-only chat id владельца (ADMIN_USER_ID / первый из ADMIN_USER_IDS).

        Для пушей зови ``await push_chat_id()`` — там DB-owner приоритетнее env.
        """
        if self.admin_user_id:
            return int(self.admin_user_id)
        for raw in (self.admin_user_ids or "").replace(";", ",").split(","):
            raw = raw.strip()
            if raw.isdigit():
                return int(raw)
        return None


async def push_chat_id(settings: BotSettings | None = None) -> int | None:
    """Чат для пуш-нотификаций: ``accounts.telegram_chat_id`` владельца приоритетнее env.

    Нет привязки в PG / нет chat_id на аккаунте → фолбэк на ``BotSettings.admin_chat_id()``.
    Нет ни того, ни другого → None (пуш пропускаем).
    """
    from bot_app.access import resolve_owner

    owner = await resolve_owner()
    if owner is not None and owner.telegram_chat_id is not None:
        return int(owner.telegram_chat_id)
    settings = settings or get_bot_settings()
    return settings.admin_chat_id()


@lru_cache
def get_bot_settings() -> BotSettings:
    return BotSettings()
