"""События домена multiplayer: пока пусто (нет шинных публикаций/подписок).

Форма обязательна: `app/subscriptions.py` импортирует `events.py` у каждого домена.
"""

from __future__ import annotations

PUBLISHES: tuple[type, ...] = ()
SUBSCRIPTIONS: tuple[tuple[type, object], ...] = ()

__all__ = ["PUBLISHES", "SUBSCRIPTIONS"]
