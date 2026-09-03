"""Инфраструктурная половина шины событий: журнал в витрину логов.

Сам диспетчер (`InProcessEventBus`) живёт в `core/kernel/ports.py` — правило слоёв запрещает
`platform` импортировать `kernel`, а шина обязана быть доступна домену без инфраструктуры.
Здесь остаётся то, что без I/O не сделать: запись события в `copilot_logs`.
"""

from core.platform.events.journal import log_domain_event
from core.platform.events.live import broadcaster

__all__ = ["broadcaster", "log_domain_event"]
