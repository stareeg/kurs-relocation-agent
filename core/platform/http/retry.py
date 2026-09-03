"""Политика HTTP-ретраев.

Ретраим только сеть / 5xx / 429. Схемные 4xx — сразу наружу (фолбэк модели, не sleep).
Пауза — экспоненциальный backoff с full jitter. Лимит — `budget_ms` фичи, не счётчик попыток
(счётчик остаётся только safety-потолком от бесконечного цикла).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# Запас на следующий HTTP-запрос после sleep (connect + минимальный TTFB).
_DEFAULT_RESERVE_MS = 1_000.0


def is_retryable_http_status(status: int) -> bool:
    """429 и 5xx — да; прочие 4xx (схема/валидация) — нет."""
    return status == 429 or status >= 500


def backoff_with_jitter(
    attempt: int,
    *,
    base_s: float = 1.0,
    cap_s: float = 30.0,
    rng: random.Random | None = None,
) -> float:
    """Full jitter: uniform(0, min(cap, base * 2^attempt)).

    `attempt` — 0-based номер уже выполненной (неудачной) попытки перед sleep.
    """
    if attempt < 0:
        attempt = 0
    ceiling = min(cap_s, base_s * (2**attempt))
    if ceiling <= 0:
        return 0.0
    pick = rng.uniform if rng is not None else random.uniform
    return float(pick(0.0, ceiling))


def can_retry_within_budget(
    elapsed_ms: float,
    budget_ms: float | None,
    wait_s: float,
    *,
    reserve_ms: float = _DEFAULT_RESERVE_MS,
) -> bool:
    """Хватит ли бюджета на sleep + ещё одну попытку.

    `budget_ms is None` — бюджет не задан (прямой get_chat_model), ограничиваем только
    safety-потолком попыток снаружи.
    """
    if budget_ms is None or budget_ms <= 0:
        return True
    need_ms = wait_s * 1000.0 + reserve_ms
    return (elapsed_ms + need_ms) <= float(budget_ms)


@dataclass(frozen=True, slots=True)
class RetryPlan:
    """Решение: спать `wait_s` и повторять, или сдаться."""

    retry: bool
    wait_s: float = 0.0
    reason: str = ""


def plan_retry(
    *,
    status: int | None = None,
    network_error: bool = False,
    attempt: int,
    elapsed_ms: float,
    budget_ms: float | None,
    safety_max: int,
    rng: random.Random | None = None,
) -> RetryPlan:
    """Единая точка решения для OpenRouter `_run_with_retry`."""
    if attempt + 1 >= safety_max:
        return RetryPlan(False, reason="safety_max")

    if network_error:
        retryable = True
        base_s, cap_s = 1.0, 30.0
        kind = "network"
    elif status is not None and is_retryable_http_status(status):
        retryable = True
        if status == 429:
            base_s, cap_s = 2.0, 60.0
            kind = "429"
        else:
            base_s, cap_s = 1.0, 30.0
            kind = f"http_{status}"
    else:
        return RetryPlan(False, reason=f"not_retryable_status_{status}")

    if not retryable:
        return RetryPlan(False, reason="not_retryable")

    wait_s = backoff_with_jitter(attempt, base_s=base_s, cap_s=cap_s, rng=rng)
    if not can_retry_within_budget(elapsed_ms, budget_ms, wait_s):
        return RetryPlan(False, reason="budget_exhausted", wait_s=wait_s)
    return RetryPlan(True, wait_s=wait_s, reason=kind)
