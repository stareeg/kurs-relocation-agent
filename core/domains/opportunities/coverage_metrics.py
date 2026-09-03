"""Суточная метрика покрытия входных данных скоринга.

Этап 9 §9.3, plans/scoring_precision_2026_08_17.md.

D11: `total_responses`/`letter_required`/`published_at` собираются расширением, но на проде
дырка была 342 из 342 (0% покрытия) и не всплывала нигде, кроме ручного SQL-аудита — «если
фича сломается, покажет ли лог-зип, что произошло?» (CLAUDE.md) отвечала «нет». Раз в сутки
кладём долю заполненности в лог, тем же приёмом, что `market.snapshot_refresh._refresh_situation`
использует для своего суточного `CronSpec`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from core.platform.observability import event
from core.platform.tasks import CronSpec, add_cron, register_handler

logger = logging.getLogger(__name__)

COVERAGE_METRICS_KIND = "opportunities_coverage_metrics"
COVERAGE_METRICS_SCHEDULE_ID = "opportunities_coverage_metrics"
_COVERAGE_METRICS_HOUR = 7
_COVERAGE_METRICS_MINUTE = 15
_DAILY_MISFIRE_GRACE_SEC = 3600


def _pct(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


async def _log_input_coverage(_payload: Mapping[str, Any]) -> None:
    """Доля вакансий аккаунта-владельца с заполненными total_responses/letter_required/
    published_at/salary.source=explicit — среди реально проскоренных (не stub) строк."""
    from core.domains.opportunities.jobs import input_coverage_stats
    from core.platform.repo.accounts import resolve_default_account_id

    account_id = await resolve_default_account_id()
    if account_id is None:
        event(
            logger,
            "ЗАДАЧА",
            "метрика покрытия входных данных: пропуск — нет аккаунта-владельца",
        )
        return

    stats = await input_coverage_stats(account_id=account_id)
    total = stats["total"]
    event(
        logger,
        "ЗАДАЧА",
        "покрытие входных данных: total_responses %s%%, letter_required=true %s%%, "
        "published_at %s%%, зарплата explicit %s%% (из %d вакансий)",
        _pct(stats["total_responses_filled"], total),
        _pct(stats["letter_required_true"], total),
        _pct(stats["published_at_filled"], total),
        _pct(stats["salary_explicit"], total),
        total,
        total=total,
        total_responses_filled=stats["total_responses_filled"],
        letter_required_true=stats["letter_required_true"],
        published_at_filled=stats["published_at_filled"],
        salary_explicit=stats["salary_explicit"],
    )


async def register_coverage_metrics_schedule() -> None:
    """Handler + суточный `CronSpec` (Этап 9 §9.3). Вызывается из `core.app.background`."""
    register_handler(COVERAGE_METRICS_KIND, _log_input_coverage)
    add_cron(
        CronSpec(
            schedule_id=COVERAGE_METRICS_SCHEDULE_ID,
            hour=_COVERAGE_METRICS_HOUR,
            minute=_COVERAGE_METRICS_MINUTE,
            kind=COVERAGE_METRICS_KIND,
            priority=110,
            misfire_grace_sec=_DAILY_MISFIRE_GRACE_SEC,
        )
    )
    event(
        logger,
        "ЗАПУСК",
        "шедулер метрики покрытия входных данных: раз в сутки в %02d:%02d",
        _COVERAGE_METRICS_HOUR,
        _COVERAGE_METRICS_MINUTE,
    )


__all__ = [
    "COVERAGE_METRICS_KIND",
    "COVERAGE_METRICS_SCHEDULE_ID",
    "register_coverage_metrics_schedule",
]
