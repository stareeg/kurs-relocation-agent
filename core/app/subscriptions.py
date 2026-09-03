"""Подписки доменов на шину событий: единственное место, где домены встречаются.

Каждый домен объявляет свои подписки в `domains/<name>/events.py` кортежем `SUBSCRIPTIONS`
(тип события → обработчик). Здесь они собираются в шину — домен-издатель не знает
подписчиков, домен-подписчик не правит чужой код, чтобы его позвали.

Импортируются модули `events.py`, а не сами домены: их зависимости — kernel и (лениво, внутри
обработчика) собственный репозиторий, поэтому регистрация на старте ничего тяжёлого не тянет.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Домены, чьи `events.py` опрашиваются на старте. Новый домен добавляется сюда.
DOMAINS: tuple[str, ...] = (
    "assistant",
    "career",
    "market",
    "multiplayer",
    "offers",
    "opportunities",
    "pipeline",
    "preparation",
    "profile",
)


def register_domain_subscriptions(bus: Any) -> int:
    """Подписать обработчики всех доменов; вернуть их число.

    Идемпотентно: `subscribe` шины не задваивает пару (тип, обработчик), а `api` и `bot` в одном
    процессе зовут `wire_default_ports()` каждый по разу.
    """
    total = 0
    for domain in DOMAINS:
        module_name = f"core.domains.{domain}.events"
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:  # pragma: no cover — домен без events.py считаем ошибкой формы
            logger.warning("подписки домена %s не загружены: %s", domain, exc)
            continue
        for event_type, handler in getattr(module, "SUBSCRIPTIONS", ()):
            bus.subscribe(event_type, handler)
            total += 1
    return total


__all__ = ["DOMAINS", "register_domain_subscriptions"]
