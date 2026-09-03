"""Режим сбора вилок: память + Postgres (переживает рестарт бота) — порт S11.

Порт `bot.storage.salary_calib_sessions` на `core.domains.market.salary_calib`
(async). In-memory set `_active` — быстрый синхронный фильтр (`is_active` зовут
aiogram-фильтры на каждое сообщение); persist в PG — через async
`enable`/`disable`/`load_from_db`.
"""

from __future__ import annotations

from core.domains.market.salary_calib import list_active_sessions, set_session_active

_active: set[int] = set()


async def load_from_db() -> None:
    for chat_id in await list_active_sessions():
        _active.add(chat_id)


def list_active() -> list[int]:
    return sorted(_active)


async def enable(chat_id: int, *, account_id: int) -> None:
    _active.add(chat_id)
    await set_session_active(chat_id, active=True, account_id=account_id)


async def disable(chat_id: int) -> None:
    _active.discard(chat_id)
    await set_session_active(chat_id, active=False)


def is_active(chat_id: int) -> bool:
    return chat_id in _active
