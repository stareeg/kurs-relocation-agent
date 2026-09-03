"""Сетка метрик вкладки «Рынок».

Единый registry ячеек: порядок, метки, единицы. `build_market_grid` — чистая функция;
`get_market_grid` тянет Postgres best-effort. Источник правды для UI и LLM-сводки (MARKET_GRID).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from core.domains.market.market_grid_compute import (
    compute_market_grid_values,
    load_market_grid_inputs,
)
from core.domains.market.pulse import PULSE_WINDOW_DAYS, MarketPulse

logger = logging.getLogger(__name__)

GridUnit = Literal["count", "pct", "days", "score", "money", "minutes", "hours"]

# Hero-ячейка: шанс офферов (строка 2, позиция 1).
HERO_CELL_KEY = "offer_chance"

# (key, label, unit) — порядок строк сетки 7 колонок; LLM читает сверху вниз.
GRID_SPEC: tuple[tuple[str, str, GridUnit], ...] = (
    # Строка 1 — поток за 30д (hero-тайл «Шанс офферов» первым)
    ("offer_chance", "Шанс офферов", "pct"),
    ("scored_30d", "Заскорено за 30 дней", "count"),
    ("applied_30d", "Откликов за 30 дней", "count"),
    ("hr_responses_30d", "Ответов HR за 30 дней", "count"),
    ("avg_score_30d", "Средний скор", "score"),
    ("score_60_plus_30d", "Скор 60+", "count"),
    # Строка 2 — воронка
    ("active_pipeline", "Активных вакансий", "count"),
    ("screenings_30d", "Кол-во скринингов", "count"),
    ("screening_pct_30d", "% скринингов", "pct"),
    ("tech_30d", "Кол-во техничек", "count"),
    ("tech_pct_30d", "% техничек", "pct"),
    ("final_30d", "Кол-во финалов", "count"),
    ("offers_total", "Кол-во офферов", "count"),
    # Строка 3 — офферы + медианы времени (30д)
    ("offer_pct", "% офферов", "pct"),
    ("time_to_apply", "Время до отклика", "minutes"),
    ("time_to_screening", "Время до скрининга", "hours"),
    ("time_to_tech", "Время до технички", "hours"),
    ("time_to_offer", "Время до оффера", "hours"),
    # Строка 4 — резюме на площадках
    ("recommended_vacancies", "Рекомендовано вакансий", "count"),
    ("impressions", "Показы на hh", "count"),
    ("views", "Просмотры на hh", "count"),
    ("getmatch_views", "Просмотры на GM", "count"),
    # Строка 5 — итоги
    ("resume_quality", "Балл резюме", "score"),
    ("tg_vacancies", "Вакансий через TG", "count"),
    # Строка 6 — skip за 30д
    ("skipped_30d", "Пропущено за 30 дней", "count"),
    ("skip_low_salary", "Низкая зарплата", "count"),
    ("skip_low_grade", "Низкий грейд", "count"),
    ("skip_wrong_stack_domain", "Не та роль/домен", "count"),
    ("skip_wrong_format", "Не тот формат", "count"),
    ("skip_role_kind", "Не та роль (IC vs рук)", "count"),
    ("skip_bad_company", "Избегать компанию", "count"),
)

assert len(GRID_SPEC) == 31

# Пояснение формулы каждой метрики — в ответе сетки (`cell.how`) и в LLM-сводке.
# Человеческий русский без имён таблиц/полей и без латиницы.
GRID_METRIC_HOW: dict[str, str] = {
    "scored_30d": ("Вакансии, оценённые за последние 30 дней; отклонённые вручную не входят."),
    "applied_30d": (
        "Вакансии, впервые дошедшие до «Отклик» за последние 30 дней; "
        "отклонённые вручную не входят."
    ),
    "hr_responses_30d": (
        "Вакансии со скринингом за 30 дней, где был контакт с рекрутером; "
        "если контакта нет в данных — считаются все такие скрининги. "
        "Отклонённые вручную не входят."
    ),
    "avg_score_30d": (
        "Средний балл оценки по вакансиям за 30 дней; отклонённые вручную не входят."
    ),
    "score_60_plus_30d": (
        "Вакансии с баллом 60 и выше, оценённые за 30 дней; отклонённые вручную не входят."
    ),
    "offer_chance": (
        "Сводный показатель «шанс офферов» от 0 до 100 по воронке, резюме и активности; "
        "суточная дельта — изменение за сутки."
    ),
    "active_pipeline": (
        "Сейчас в работе: скрининг, техничка, финал или оффер; отклонённые вручную не входят."
    ),
    "screenings_30d": "Вакансии, впервые дошедшие до «Скрининг» за 30 дней.",
    "screening_pct_30d": (
        "Доля скринингов среди откликов за 30 дней "
        "(включая первый контакт рекрутера без отклика на площадке)."
    ),
    "tech_30d": "Вакансии, впервые дошедшие до «Техничка» за 30 дней.",
    "tech_pct_30d": "Доля техничек среди скринингов за 30 дней.",
    "final_30d": "Вакансии, впервые дошедшие до «Финал» за 30 дней.",
    "offers_total": "Вакансии, хотя бы раз бывшие на этапе «Оффер» за всё время.",
    "offer_pct": ("Доля офферов среди вакансий, где хотя бы раз была техничка; по всей истории."),
    "time_to_apply": "Типичное время от просмотра до отклика (медиана минут) за 30 дней.",
    "time_to_screening": (
        "Типичное время от отклика или первого сообщения рекрутера в Телеграме "
        "до скрининга за 30 дней."
    ),
    "time_to_tech": "Типичное время от скрининга до технички (медиана часов) за 30 дней.",
    "time_to_offer": "Типичное время от технички до оффера (медиана часов) за 30 дней.",
    "recommended_vacancies": (
        "Сколько вакансий площадка Хедхантер сейчас рекомендует под резюме; "
        "последний снимок из расширения."
    ),
    "impressions": "Показы резюме на Хедхантере за 7 дней; снимок из расширения.",
    "views": "Просмотры резюме на Хедхантере за 7 дней; снимок из расширения.",
    "getmatch_views": (
        "Просмотры профиля на Гетматче; снимок со страницы статистики через расширение."
    ),
    "resume_quality": (
        "Последний балл резюме из проверки готовности; суточная дельта — изменение за сутки."
    ),
    "tg_vacancies": ("Вакансии, где первый контакт был в Телеграме, без отклика на площадке."),
    "skipped_30d": ("Сколько вакансий вы явно отклонили за 30 дней. Это не этап воронки."),
    "skip_low_salary": "Пропуски за 30 дней с причиной «низкая зарплата».",
    "skip_low_grade": "Пропуски за 30 дней с причиной «низкий грейд».",
    "skip_wrong_stack_domain": "Пропуски за 30 дней с причиной «не та роль или домен».",
    "skip_wrong_format": "Пропуски за 30 дней с причиной «не тот формат работы».",
    "skip_role_kind": "Пропуски за 30 дней с причиной «не та роль — баланс самостоятельной и управленческой работы».",
    "skip_bad_company": "Пропуски за 30 дней с причиной «избегать компанию».",
}


class MarketGridCell(BaseModel):
    key: str
    label: str
    value: float | int | str | None = None
    unit: GridUnit
    delta: float | None = None
    empty_reason: str | None = None
    # B-06: человеческая формула метрики (из GRID_METRIC_HOW) — UI и LLM, один источник.
    how: str | None = None


class MarketGrid(BaseModel):
    available: bool = False
    cells: list[MarketGridCell] = Field(default_factory=list)
    generated_at: datetime | None = None
    funnel_note: str | None = None
    # L-25: снапшот из кэша посчитан по расписанию — `stale` включает индикатор «обновляется»
    # на фронте вместо повторного пересчёта на каждый заход.
    stale: bool = False


def _kpi_map(pulse: MarketPulse) -> dict[str, tuple[float, float | None]]:
    return {k.key: (k.value, k.delta) for k in pulse.kpis}


async def _load_resume_quality(*, account_id: int, db) -> tuple[int | None, float | None]:
    from core.domains.profile.resume_score import load_score_at

    snap_now = await load_score_at(None, account_id=account_id, db=db)
    if snap_now is None:
        return None, None
    total = int(snap_now.total)
    snap_ago = await load_score_at(
        datetime.now(UTC) - timedelta(days=PULSE_WINDOW_DAYS),
        account_id=account_id,
        db=db,
    )
    delta: float | None = None
    if snap_ago is not None:
        delta = round(float(total - int(snap_ago.total)), 1)
    return total, delta


def build_market_grid(
    *,
    pulse: MarketPulse,
    jobs,
    stages,
    skipped_rows,
    hr_first_inbound,
    resume_quality: int | None = None,
    resume_quality_delta: float | None = None,
    funnel_note: str | None = None,
) -> MarketGrid:
    """Собрать ячейки сетки. Вызывается только когда pulse.available."""
    kpis = _kpi_map(pulse)
    values = compute_market_grid_values(
        jobs=jobs,
        stages=stages,
        skipped_rows=skipped_rows,
        hr_first_inbound=hr_first_inbound,
        kpis=kpis,
        offer_chance_score=pulse.offer_chance.score,
        offer_chance_delta=float(pulse.offer_chance.delta)
        if pulse.offer_chance.delta is not None
        else None,
        resume_quality=resume_quality,
        resume_quality_delta=resume_quality_delta,
    )

    cells: list[MarketGridCell] = []
    for key, label, unit in GRID_SPEC:
        raw_val, delta, empty_reason = values.get(key, (None, None, "не задано"))
        if raw_val is None and empty_reason is None:
            empty_reason = "нет данных"
        cells.append(
            MarketGridCell(
                key=key,
                label=label,
                value=raw_val,
                unit=unit,
                delta=delta,
                empty_reason=empty_reason if raw_val is None else None,
                how=GRID_METRIC_HOW.get(key),
            )
        )
    return MarketGrid(available=True, cells=cells, funnel_note=funnel_note)


async def get_market_grid(*, account_id: int, db=None) -> MarketGrid:
    """Собрать сетку аккаунта из Postgres. Нет PG / нет заскоренных → available=false."""
    from core.domains.market.pulse import get_market_pulse
    from core.domains.market.search_metrics import get_search_metrics

    grid = MarketGrid()
    try:
        pulse = await get_market_pulse(account_id=account_id, db=db)
        search = await get_search_metrics(account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("market-grid недоступен: %s", exc)
        return grid

    if not pulse.available:
        return grid

    resume_quality: int | None = None
    resume_quality_delta: float | None = None
    jobs, stages, skipped_rows, hr_first = [], [], [], {}
    try:
        if db is not None:
            pool = db
        else:
            from core.platform.db.pool import get_pool

            pool = get_pool()
        jobs, stages, skipped_rows, hr_first = await load_market_grid_inputs(
            account_id=account_id, db=pool
        )
        resume_quality, resume_quality_delta = await _load_resume_quality(
            account_id=account_id, db=pool
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("market-grid inputs недоступны: %s", exc)

    built = build_market_grid(
        pulse=pulse,
        jobs=jobs,
        stages=stages,
        skipped_rows=skipped_rows,
        hr_first_inbound=hr_first,
        resume_quality=resume_quality,
        resume_quality_delta=resume_quality_delta,
        funnel_note=search.funnel.note,
    )
    return built.model_copy(update={"generated_at": datetime.now(UTC)})


def _fmt_cell_value(cell: MarketGridCell) -> str:
    if cell.value is None or cell.value == "":
        return "—"
    if cell.unit == "pct" and isinstance(cell.value, (int, float)):
        v = round(float(cell.value) * 10) / 10
        return f"{v:g}%"
    if cell.unit == "money":
        return f"{cell.value} ₽"
    if cell.unit == "minutes" and isinstance(cell.value, (int, float)):
        return f"{float(cell.value):g} мин"
    if cell.unit == "hours" and isinstance(cell.value, (int, float)):
        return f"{float(cell.value):g} ч"
    if cell.unit == "days" and isinstance(cell.value, (int, float)):
        return f"{float(cell.value):g} дн"
    if cell.unit == "score" and isinstance(cell.value, (int, float)):
        return f"{round(float(cell.value))} балл"
    return str(cell.value)


def format_market_grid_cell_line(cell: MarketGridCell) -> str:
    """Одна строка ячейки для LLM-сводки (MARKET_GRID)."""
    val = _fmt_cell_value(cell)
    parts = [f"{cell.label}: {val}"]
    if cell.delta is not None and cell.delta != 0:
        parts.append(f"Δ24ч {cell.delta:+g}")
    if cell.empty_reason and (cell.value is None or cell.value == ""):
        parts.append(f"({cell.empty_reason})")
    return " · ".join(parts)


def format_market_grid_json_for_llm(grid: MarketGrid) -> str:
    """JSON-дамп метрик grid с формулами — вход LLM-сводки (MARKET_GRID)."""
    if not grid.available or not grid.cells:
        return json.dumps(
            {"available": False, "note": "Сетка недоступна"}, ensure_ascii=False, indent=2
        )
    metrics = []
    for cell in grid.cells:
        metrics.append(
            {
                "label": cell.label,
                "value": cell.value,
                "unit": cell.unit,
                "delta_24h": cell.delta,
                "how": cell.how or "",
                "empty_reason": cell.empty_reason,
            }
        )
    payload = {
        "available": True,
        "generated_at": grid.generated_at.isoformat() if grid.generated_at else None,
        "window_days": 30,
        "metrics": metrics,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def format_market_grid_for_llm(grid: MarketGrid) -> str:
    """Дамп ячеек grid для LLM (legacy текст; предпочтительно JSON)."""
    return format_market_grid_json_for_llm(grid)


__all__ = [
    "GRID_SPEC",
    "HERO_CELL_KEY",
    "MarketGrid",
    "MarketGridCell",
    "build_market_grid",
    "format_market_grid_cell_line",
    "format_market_grid_for_llm",
    "format_market_grid_json_for_llm",
    "get_market_grid",
    "GRID_METRIC_HOW",
]
