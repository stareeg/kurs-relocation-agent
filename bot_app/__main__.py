"""Точка входа бота: python -m bot_app (нужен запущенный api).

Этот модуль — только бот, против уже работающего API (BACKEND_URL в .env).
"""

from __future__ import annotations

import asyncio
import contextlib

from bot_app.run import run_bot
from core.platform.observability import setup_logging

if __name__ == "__main__":
    setup_logging()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_bot())
