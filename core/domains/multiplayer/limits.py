"""Э14: лимиты нагрузки — комнаты на хоста + rate-limit create/join.

In-process sliding window (один API-процесс на VM). Без Redis: достаточно,
чтобы не заспамить Postgres и WS-хаб с одного аккаунта.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

# Сколько живых (open|playing) столов может держать один хост.
MAX_ACTIVE_ROOMS_PER_HOST = 3

# Sliding window: (max_calls, window_sec)
CREATE_RATE = (5, 60.0)
JOIN_RATE = (30, 60.0)

# Бюджет ассетов public/multiplayer (Э14 chunk size).
ASSET_MAX_BYTES_PER_FILE = 8 * 1024
ASSET_MAX_TOTAL_BYTES = 48 * 1024

_lock = threading.Lock()
_windows: dict[tuple[str, int], deque[float]] = defaultdict(deque)


def reset_rate_limits_for_tests() -> None:
    """Сброс окон между тестами."""
    with _lock:
        _windows.clear()


def _prune(q: deque[float], *, now: float, window_sec: float) -> None:
    cutoff = now - window_sec
    while q and q[0] < cutoff:
        q.popleft()


def check_rate_limit(
    *,
    action: str,
    account_id: int,
    limit: tuple[int, float],
    now: float | None = None,
) -> bool:
    """True = можно; False = лимит исчерпан. Успешный вызов записывает тик."""
    max_calls, window_sec = limit
    ts = time.monotonic() if now is None else now
    key = (action, account_id)
    with _lock:
        q = _windows[key]
        _prune(q, now=ts, window_sec=window_sec)
        if len(q) >= max_calls:
            return False
        q.append(ts)
        return True


def allow_create(account_id: int) -> bool:
    return check_rate_limit(action="create", account_id=account_id, limit=CREATE_RATE)


def allow_join(account_id: int) -> bool:
    return check_rate_limit(action="join", account_id=account_id, limit=JOIN_RATE)


__all__ = [
    "ASSET_MAX_BYTES_PER_FILE",
    "ASSET_MAX_TOTAL_BYTES",
    "CREATE_RATE",
    "JOIN_RATE",
    "MAX_ACTIVE_ROOMS_PER_HOST",
    "allow_create",
    "allow_join",
    "check_rate_limit",
    "reset_rate_limits_for_tests",
]
