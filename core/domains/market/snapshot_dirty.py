"""Дирти-трекер снапшотов «Рынка»: что из источников поменялось с последнего пересчёта.

Плановый пересчёт каждые `MARKET_SNAPSHOT_INTERVAL_SEC` тянет весь `jobs`/
`application_stages`/`offers`/`resume_stats` и пересобирает срезы (`grid`/`pulse`/`search`), даже
если между тиками ничего не произошло — типичный случай для одиночного пользователя вне
активных часов поиска. Домены-источники дёргают `mark_dirty(...)` из своих подписок на шину
(см. `events.py`) при событиях, которые реально меняют вход агрегатов; `snapshot_refresh.py`
перед тиком спрашивает `kinds_to_recompute()` и считает только их.

In-memory, не переживает рестарт процесса — это осознанно: рестарт форсит один полный пересчёт
«с нуля» (стартовое состояние — «всё грязное»), это безопаснее, чем гадать, что случилось, пока
процесс не работал.

Предохранитель: подписками на шину покрыты не все мутации входа (например, `skipped_vacancies`
или резюме-снимки hh/getmatch с расширения — у них нет доменных событий). Чтобы такие срезы не
протухали тихо под чистым дирти-флагом, `kinds_to_recompute()` форсирует пересчёт `kind`, если с
последнего успешного пересчёта прошло больше `safety_net_sec` — вызывающий (`snapshot_refresh.py`)
передаёт туда `MARKET_SNAPSHOT_STALE_AFTER_SEC`, так что пользователь физически не может увидеть
«протухший» бейдж по вине непокрытой подпиской мутации.
"""

from __future__ import annotations

from datetime import UTC, datetime

GRID = "grid"
PULSE = "pulse"
SEARCH = "search"

ALL_KINDS: tuple[str, ...] = (GRID, PULSE, SEARCH)

# Старт «всё грязное» — первый тик после старта процесса всегда считает всё, как до L-26.
_dirty: set[str] = set(ALL_KINDS)
_last_computed_at: dict[str, datetime] = {}


def mark_dirty(*kinds: str) -> None:
    """Позвать из подписки на событие, влияющее на вход `kind`-среза."""
    _dirty.update(kinds)


def kinds_to_recompute(*, safety_net_sec: float) -> frozenset[str]:
    """Что реально пересчитывать в этом тике: грязное + просроченное по предохранителю."""
    now = datetime.now(UTC)
    result = set(_dirty)
    for kind in ALL_KINDS:
        last = _last_computed_at.get(kind)
        if last is None or (now - last).total_seconds() > safety_net_sec:
            result.add(kind)
    return frozenset(result)


def mark_computed(*kinds: str) -> None:
    """Позвать после успешного пересчёта `kind` — снимает грязь, двигает предохранитель."""
    now = datetime.now(UTC)
    for kind in kinds:
        _dirty.discard(kind)
        _last_computed_at[kind] = now


def reset() -> None:
    """Тестовый хук: вернуть трекер в стартовое состояние («всё грязное»)."""
    _dirty.clear()
    _dirty.update(ALL_KINDS)
    _last_computed_at.clear()


__all__ = [
    "ALL_KINDS",
    "GRID",
    "PULSE",
    "SEARCH",
    "kinds_to_recompute",
    "mark_computed",
    "mark_dirty",
    "reset",
]
