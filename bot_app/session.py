"""Telegram-сессия с настройками под нестабильную сеть/Windows (порт bot/telegram_session.py)."""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.utils.backoff import BackoffConfig

from bot_app.config import BotSettings, get_bot_settings

# Длинный backoff для нестабильного VPN / сбросов сокета на Windows во время long-polling.
NETWORK_BACKOFF = BackoffConfig(min_delay=2.0, max_delay=60.0, factor=1.5, jitter=0.2)


class ResilientAiohttpSession(AiohttpSession):
    """aiohttp-сессия под флапающее соединение к api.telegram.org."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._connector_init.update({"enable_cleanup_closed": True})


def create_bot(settings: BotSettings | None = None) -> Bot:
    settings = settings or get_bot_settings()
    proxy = (settings.telegram_proxy or "").strip() or None
    session_kwargs: dict = {
        "proxy": proxy,
        "limit": 30,
        "timeout": settings.telegram_request_timeout,
    }
    api_base = (settings.telegram_api_base or "").strip()
    if api_base:
        # api= по умолчанию у AiohttpSession — не None, а сам TelegramAPIServer(production);
        # передавать его явным None здесь нельзя, поэтому кладём ключ только когда база задана.
        session_kwargs["api"] = TelegramAPIServer.from_base(api_base)
    session = ResilientAiohttpSession(**session_kwargs)
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
