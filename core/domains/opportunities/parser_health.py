"""Наблюдаемость парсера hh: доля structural за час (Шаг 6).

Счётчик в памяти процесса API — без крона и без запроса в `copilot_logs`.
После рестарта окно пустое: алерт приедет, как накопится новая выборка.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

HH_VACANCY_PARSE_METHODS = frozenset({"config", "default", "structural"})
STRUCTURAL_SHARE_THRESHOLD = 0.10
WINDOW_S = 3600.0
# Один странный разбор не должен кричать «селекторы мертвы».
MIN_SAMPLES = 5
ALERT_COOLDOWN_S = 3600.0


@dataclass(frozen=True, slots=True)
class StructuralShareAlert:
    """Доля structural пересекла порог — пора править `hh_selectors.json`."""

    total: int
    structural: int
    share: float


class HhVacancyParseWindow:
    """Скользящее окно методов разбора страницы вакансии hh."""

    def __init__(self) -> None:
        self._samples: deque[tuple[float, str]] = deque()
        self._last_alert_at: float | None = None

    def reset(self) -> None:
        self._samples.clear()
        self._last_alert_at = None

    def observe(self, method: str, *, now: float) -> StructuralShareAlert | None:
        if method not in HH_VACANCY_PARSE_METHODS:
            return None
        self._samples.append((now, method))
        cutoff = now - WINDOW_S
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        total = len(self._samples)
        if total < MIN_SAMPLES:
            return None
        structural = sum(1 for _, sample in self._samples if sample == "structural")
        share = structural / total
        if share <= STRUCTURAL_SHARE_THRESHOLD:
            return None
        if self._last_alert_at is not None and (now - self._last_alert_at) < ALERT_COOLDOWN_S:
            return None
        self._last_alert_at = now
        return StructuralShareAlert(total=total, structural=structural, share=share)


_window = HhVacancyParseWindow()


def note_hh_vacancy_parse(method: str, *, now: float | None = None) -> StructuralShareAlert | None:
    """Учесть разбор вакансии hh; вернуть алерт, если доля structural > 10% за час."""
    return _window.observe(method, now=time.monotonic() if now is None else now)


def reset_hh_vacancy_parse_window() -> None:
    """Сброс окна — только для тестов."""
    _window.reset()
