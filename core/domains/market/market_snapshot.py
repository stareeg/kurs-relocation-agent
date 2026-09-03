"""Repository дневных снимков «Рынка» (все агрегаты pulse + search-metrics одним jsonb-блобом).

Зачем отдельно от `resume_stats`: там снимает расширение по своим счётчикам с hh, здесь — сам
бэкенд по своим же вычисленным агрегатам (KPI, шанс офферов, воронка, офферы, активность) —
чтобы дельта день-ко-дню считалась по ЗАСТЫВШЕМУ прошлому значению, а не реконструкцией по
мутабельным строкам `jobs`/`application_stages` (переоценка вакансии задним числом искажает
"сутки назад"). Один снимок на календарный день: `save_market_snapshot` — upsert (последний
заход за день обновляет значения), `get_previous_snapshot` — последний снимок СТРОГО ДО дня
`before` (по умолчанию — до сегодня, т.е. «вчера или последний известный»).
`list_snapshots` — окно для спарклайна шанса офферов: без интерполяции пропусков.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

# Окно спарклайна «Шанс офферов»: меньше 7 дней бессмысленно, больше полугода — шум.
_HISTORY_DAYS_MIN = 7
_HISTORY_DAYS_MAX = 180


class MarketSnapshot(BaseModel):
    """Один дневной снимок: день + момент последнего обновления + сырой payload агрегатов."""

    id: int | None = None
    day: date
    captured_at: datetime | None = None
    payload: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class OfferChancePoint(BaseModel):
    """Одна точка спарклайна: календарный день + score из снимка."""

    day: date
    score: float


class OfferChanceHistory(BaseModel):
    """Ответ `GET /api/analytics/offer-chance-history`.

    `available=false`, если точек меньше двух (одна точка — не тренд). Дни без снимка не
    заполняются — разрыв остаётся разрывом.
    """

    available: bool = False
    points: list[OfferChancePoint] = Field(default_factory=list)


class MetricPoint(BaseModel):
    """Одна точка истории произвольной величины: календарный день + значение из снимка."""

    day: date
    value: float


class MetricHistory(BaseModel):
    """Ответ `GET /api/market/history?metric=...`.

    `metric` — ключ headline-KPI (`hr_response`, `avg_fit`, ...) из `payload["metrics"]` снимка
    или агрегат верхнего уровня (`offer_chance_score`). `available=false`, если точек меньше двух
    или снимков нет вообще. Дни без снимка не заполняются — разрыв остаётся разрывом.
    """

    metric: str = ""
    available: bool = False
    points: list[MetricPoint] = Field(default_factory=list)


class MultiHistorySeries(BaseModel):
    """Одна серия из batch-ответа истории `GET /api/market/history/multi`.

    `key` — идентификатор серии внутри своей группы (напр. `applied`/`in_progress`/`screening`
    для группы `funnel`; `salary`/`format`/`grade`/`role`/`passed` для `gates_breakdown`;
    `p25`/`median`/`p75`/`meets_pct` для `money`; `remote`/`hybrid`/`office` для `formats`).
    `points` — точки во времени; `available` — ≥2 точек.
    """

    key: str
    label: str = ""
    unit: str = ""  # 'count' | 'pct' | 'score' | 'money' — подсказка фронту для оси Y
    available: bool = False
    points: list[MetricPoint] = Field(default_factory=list)


class MultiHistoryGroup(BaseModel):
    """Группа серий истории одного среза (воронка/гейты/деньги/форматы) — для линейных графиков
    «Рынка» во времени. Каждая группа → свой график с временной осью X."""

    group: str  # 'funnel' | 'gates' | 'money' | 'formats' | 'offer_chance'
    label: str = ""
    available: bool = False
    series: list[MultiHistorySeries] = Field(default_factory=list)


class MultiHistoryResponse(BaseModel):
    """Ответ `GET /api/market/history/multi` — набор групп серий для линейных графиков «Рынка».

    Группы, по которым нет исторических данных (мало снимков / старые снимки без расширенного
    payload), отдаются с `available=false` и пустыми series — фронт рисует честный empty.
    """

    groups: list[MultiHistoryGroup] = Field(default_factory=list)


def _today() -> date:
    return datetime.now(UTC).date()


def clamp_history_days(days: int) -> int:
    """Кламп окна истории шанса офферов в 7…180."""
    return max(_HISTORY_DAYS_MIN, min(int(days), _HISTORY_DAYS_MAX))


def _metric_value(payload: dict, metric: str) -> float | None:
    """Достаёт значение `metric` из снимка: сперва headline-KPI (`payload["metrics"]`), иначе
    агрегат верхнего уровня (`offer_chance_score` и т.п. — считаются отдельно от KPI-стены)."""
    if not isinstance(payload, dict):
        return None
    metrics = payload.get("metrics")
    raw = (
        metrics.get(metric)
        if isinstance(metrics, dict) and metric in metrics
        else payload.get(metric)
    )
    return float(raw) if isinstance(raw, (int, float)) else None


def metric_history_from_snapshots(snapshots: list[MarketSnapshot], metric: str) -> MetricHistory:
    """Чистая сборка истории величины `metric` из снимков: без интерполяции, available при ≥2
    точках. Общая сборка для любого ключа — `history_from_snapshots` её частный случай."""
    points = [
        MetricPoint(day=snap.day, value=value)
        for snap in snapshots
        if (value := _metric_value(snap.payload, metric)) is not None
    ]
    return MetricHistory(metric=metric, available=len(points) >= 2, points=points)


def history_from_snapshots(snapshots: list[MarketSnapshot]) -> OfferChanceHistory:
    """Чистая сборка истории шанса офферов — частный случай `metric_history_from_snapshots`."""
    generic = metric_history_from_snapshots(snapshots, "offer_chance_score")
    return OfferChanceHistory(
        available=generic.available,
        points=[OfferChancePoint(day=p.day, score=p.value) for p in generic.points],
    )


async def save_market_snapshot(
    payload: dict, *, account_id: int, day: date | None = None, db: Executor | None = None
) -> MarketSnapshot:
    """Upsert снимка аккаунта за календарный день (по умолчанию — сегодня). Перезаписывает payload."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into market_snapshots (account_id, day, captured_at, payload) "
        "values ($1, $2, now(), $3) "
        "on conflict (account_id, day) do update set "
        "captured_at = excluded.captured_at, payload = excluded.payload "
        "returning id, day, captured_at, payload, created_at",
        account_id,
        day or _today(),
        payload,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return MarketSnapshot(**row_to_dict(row))


async def get_previous_snapshot(
    *, account_id: int, before: date | None = None, db: Executor | None = None
) -> MarketSnapshot | None:
    """Последний снимок аккаунта СТРОГО до дня `before` (по умолчанию — до сегодня).

    «Вчера, или если вчера не было данных — последний известный» реализуется автоматически:
    сортировка по `day desc limit 1` берёт ближайший день < before, каким бы старым он ни был.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "select id, day, captured_at, payload, created_at from market_snapshots "
        "where account_id = $1 and day < $2 order by day desc limit 1",
        account_id,
        before or _today(),
    )
    return MarketSnapshot(**row_to_dict(row)) if row is not None else None


async def list_snapshots(
    since: date, *, account_id: int, until: date | None = None, db: Executor | None = None
) -> list[MarketSnapshot]:
    """Снимки аккаунта с `day >= since` (и `day <= until`, если задано) по возрастанию дня.
    Пропуски дней не заполняются. `until=None` — без верхней границы (до последнего снимка)."""
    db = db or get_pool()
    if until is not None:
        rows = await db.fetch(
            "select id, day, captured_at, payload, created_at from market_snapshots "
            "where account_id = $1 and day >= $2 and day <= $3 order by day asc",
            account_id,
            since,
            until,
        )
    else:
        rows = await db.fetch(
            "select id, day, captured_at, payload, created_at from market_snapshots "
            "where account_id = $1 and day >= $2 order by day asc",
            account_id,
            since,
        )
    return [MarketSnapshot(**row_to_dict(r)) for r in rows]


async def get_metric_history(
    metric: str,
    *,
    account_id: int,
    from_days: int = 30,
    to_days: int = 0,
    db: Executor | None = None,
) -> MetricHistory:
    """История произвольной величины «Рынка» из дневных снимков аккаунта: headline-KPI
    (`hr_response`, `avg_fit`, ...) и агрегаты верхнего уровня (`offer_chance_score`).

    `from_days`/`to_days` — обе границы окна как «дней назад от сегодня» (шкала периода
    двигает обе, план п. 2): `from_days` клампится в 7…180 (кламп истории), `to_days` — в
    0…`from_days` (граница «до» не может быть старше границы «от»). Нет PG → available=false,
    не 500.
    """
    window = clamp_history_days(from_days)
    to_clamped = max(0, min(int(to_days), window))
    since = _today() - timedelta(days=window)
    until = _today() - timedelta(days=to_clamped)
    try:
        snaps = await list_snapshots(since, account_id=account_id, until=until, db=db)
    except Exception as exc:  # noqa: BLE001 — нет PG → пустая история, не 500
        logger.debug("metric-history(%s): снимки недоступны (нет PG?): %s", metric, exc)
        return MetricHistory(metric=metric, available=False)
    return metric_history_from_snapshots(snaps, metric)


async def get_offer_chance_history(
    *, account_id: int, from_days: int = 30, to_days: int = 0, db: Executor | None = None
) -> OfferChanceHistory:
    """История шанса офферов — частный случай `get_metric_history`."""
    generic = await get_metric_history(
        "offer_chance_score", account_id=account_id, from_days=from_days, to_days=to_days, db=db
    )
    return OfferChanceHistory(
        available=generic.available,
        points=[OfferChancePoint(day=p.day, score=p.value) for p in generic.points],
    )


# --- Расширенная история: воронка/гейты/деньги/форматы во времени ---
# Расширенный payload снимка (funnel/gates/money) появляется с момента деплоя этой правки —
# старые снимки читаются корректно (нет ключа → нет точек), просто серии будут короткими
# первые ~2 недели. Это совпадает с философией available=false/empty по всему домену.

# Группа → (ключ серии, подпись, единица). Единица — подсказка фронту для оси Y и форматирования.
_FUNNEL_SERIES: tuple[tuple[str, str, str], ...] = (
    ("applied", "Отклики", "count"),
    ("in_progress", "В работе", "count"),
    ("screening", "Скрининг", "count"),
    ("tech", "Техничка", "count"),
    ("final", "Финал", "count"),
    ("offer", "Оффер", "count"),
)
_GATES_SERIES: tuple[tuple[str, str, str], ...] = (
    ("salary", "Зарплата", "count"),
    ("format", "Формат", "count"),
    ("grade", "Грейд", "count"),
    ("role", "Роль", "count"),
    ("passed", "Прошло", "count"),
)
_MONEY_SERIES: tuple[tuple[str, str, str], ...] = (
    ("p25", "P25 (нет/мес)", "money"),
    ("median", "Медиана (нет/мес)", "money"),
    ("p75", "P75 (нет/мес)", "money"),
    ("meets_pct", "В целевой зоне", "pct"),
)
_FORMATS_SERIES: tuple[tuple[str, str, str], ...] = (
    ("remote", "Удалённо", "count"),
    ("hybrid", "Гибрид", "count"),
    ("office", "Офис", "count"),
)


def _funnel_point(payload: dict[str, Any], series_key: str) -> float | None:
    """Свести двухуровневую воронку снимка в плоские счётчики по сериям."""
    funnel = payload.get("funnel")
    if not isinstance(funnel, list) or not funnel:
        return None
    # Первая строка — «Отклики» (base=applied), вторая — «В работе» (base=in_progress, сегменты
    # по активным стадиям). Форма стабильна: compute_overview_funnel.
    applied = _as_int(_safe_index(funnel, 0, "base"))
    if series_key == "applied":
        return applied
    in_progress = _safe_index(funnel, 0, "segments")
    in_progress_count = _segment_count(in_progress, "in_progress")
    if series_key == "in_progress":
        return in_progress_count
    # Стадии — из второй строки (сегменты «В работе»).
    stages = _safe_index(funnel, 1, "segments")
    return _segment_count(stages, series_key)


def _gates_point(payload: dict[str, Any], series_key: str) -> float | None:
    """Гейты из снимка: breakdown (взаимоисключающая сегментация S-04)."""
    gates = payload.get("gates")
    if not isinstance(gates, dict):
        return None
    breakdown = gates.get("breakdown")
    if not isinstance(breakdown, list):
        return None
    for seg in breakdown:
        if not isinstance(seg, dict):
            continue
        if str(seg.get("key") or "") == series_key:
            return _as_int(seg.get("count"))
    return None


def _money_point(payload: dict[str, Any], series_key: str) -> float | None:
    """Деньги из снимка: квартили зарплаты + доля в целевой зоне."""
    money = payload.get("money")
    if not isinstance(money, dict):
        return None
    supply = money.get("supply")
    if not isinstance(supply, dict):
        return None
    if series_key == "p25":
        return _as_int(supply.get("salary_p25_net"))
    if series_key == "median":
        return _as_int(supply.get("salary_median_net"))
    if series_key == "p75":
        return _as_int(supply.get("salary_p75_net"))
    if series_key == "meets_pct":
        # salary_meets_pct нет в supply; считаем из kill_factors гейта salary (pct поля).
        gates = payload.get("gates")
        if isinstance(gates, dict):
            kf = gates.get("kill_factors")
            if isinstance(kf, list):
                for seg in kf:
                    if isinstance(seg, dict) and str(seg.get("key") or "") == "salary":
                        return _as_float(seg.get("pct"))
        return None
    return None


def _formats_point(payload: dict[str, Any], series_key: str) -> float | None:
    """Форматы работы из снимка (work_formats: remote/hybrid/office)."""
    money = payload.get("money")
    if not isinstance(money, dict):
        return None
    supply = money.get("supply")
    if not isinstance(supply, dict):
        return None
    formats = supply.get("work_formats")
    if not isinstance(formats, list):
        return None
    for seg in formats:
        if (
            isinstance(seg, dict)
            and str(seg.get("label_key") or seg.get("key") or "") == series_key
        ):
            return _as_int(seg.get("count"))
    return None


def _segment_count(segments: object, key: str) -> float | None:
    if not isinstance(segments, list):
        return None
    for seg in segments:
        if isinstance(seg, dict) and str(seg.get("key") or "") == key:
            return _as_int(seg.get("count"))
    return None


def _safe_index(seq: object, idx: int, field: str) -> object:
    if not isinstance(seq, list) or idx >= len(seq):
        return None
    item = seq[idx]
    if not isinstance(item, dict):
        return None
    return item.get(field)


def _as_int(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_float(value: object) -> float | None:
    return _as_int(value)


_SERIES_EXTRACTORS: dict[
    str, tuple[tuple[tuple[str, str, str], ...], Callable[[dict[str, Any], str], float | None]]
] = {
    "funnel": (_FUNNEL_SERIES, _funnel_point),
    "gates": (_GATES_SERIES, _gates_point),
    "money": (_MONEY_SERIES, _money_point),
    "formats": (_FORMATS_SERIES, _formats_point),
}

_GROUP_LABELS: dict[str, str] = {
    "funnel": "Воронка во времени",
    "gates": "Что режет поток во времени",
    "money": "Деньги во времени",
    "formats": "Форматы работы во времени",
}


def multi_history_from_snapshots(
    snapshots: list[MarketSnapshot], *, groups: tuple[str, ...]
) -> MultiHistoryResponse:
    """Чистая сборка набора групп серий из снимков. Без интерполяции, available при ≥2 точках.

    Для каждой запрошенной группы идёт по своим сериям (ключ/подпись/единица), extractor достаёт
    значение из payload снимка по ключу серии. Нет значения в снимке → точка пропускается.
    """
    out_groups: list[MultiHistoryGroup] = []
    for group in groups:
        spec = _SERIES_EXTRACTORS.get(group)
        if spec is None:
            continue
        series_spec, extractor = spec
        out_series: list[MultiHistorySeries] = []
        for key, label, unit in series_spec:
            points = [
                MetricPoint(day=snap.day, value=value)
                for snap in snapshots
                if isinstance(snap.payload, dict)
                and (value := extractor(snap.payload, key)) is not None
            ]
            out_series.append(
                MultiHistorySeries(
                    key=key, label=label, unit=unit, available=len(points) >= 2, points=points
                )
            )
        any_avail = any(s.available for s in out_series)
        out_groups.append(
            MultiHistoryGroup(
                group=group,
                label=_GROUP_LABELS.get(group, group),
                available=any_avail,
                series=out_series,
            )
        )
    return MultiHistoryResponse(groups=out_groups)


async def get_multi_history(
    *,
    account_id: int,
    groups: tuple[str, ...],
    from_days: int = 30,
    to_days: int = 0,
    db: Executor | None = None,
) -> MultiHistoryResponse:
    """Batch-история «Рынка» во времени: несколько групп серий одним запросом.

    `groups` — список из `funnel`/`gates`/`money`/`formats`. `from_days`/`to_days` — окно как в
    `get_metric_history`. Нет PG → пустые группы (available=false), не 500. Снимки без
    расширенного payload (старые, до этой правки) дают пустые серии — фронт рисует что есть.
    """
    window = clamp_history_days(from_days)
    to_clamped = max(0, min(int(to_days), window))
    since = _today() - timedelta(days=window)
    until = _today() - timedelta(days=to_clamped)
    try:
        snaps = await list_snapshots(since, account_id=account_id, until=until, db=db)
    except Exception as exc:  # noqa: BLE001 — нет PG → пустой ответ, не 500
        logger.debug("multi-history: снимки недоступны (нет PG?): %s", exc)
        return MultiHistoryResponse(groups=[])
    return multi_history_from_snapshots(snaps, groups=groups)


async def record_daily_pulse_state(
    pulse: Any, *, account_id: int, db: Executor | None = None, overview: Any = None
) -> None:
    """Дневной снимок ВСЕХ агрегатов «Рынка» аккаунта из уже посчитанного `MarketPulse` (+ опц.
    `MarketOverview`) — вход для точной дельты день-ко-дню в `pulse.py` и для линейных графиков
    «Рынка» во времени (воронка/гейты/деньги/форматы — если передан `overview`).

    Общий для планового фона (`snapshot_refresh.py`, каждые 5 мин — туда передают и overview) и
    live-фолбэка роутера (кэша ещё нет — L-25, туда overview не передают, пишется базовый
    снимок KPI + шанс офферов + search-metrics). `pulse`/`overview` типизированы как `Any`, чтобы
    не тянуть `pulse.py`/`overview.py` на уровне модуля (те стороны уже лениво импортируют этот
    файл — цикл). Ошибка (нет PG/таблицы) не должна ронять вызывающего — только логируется.
    """
    if not pulse.available:
        return
    try:
        from core.domains.market.search_metrics import get_search_metrics

        sm = await get_search_metrics(account_id=account_id, db=db)
        payload: dict[str, Any] = {
            "metrics": {k.key: k.value for k in pulse.kpis},
            "offer_chance_score": pulse.offer_chance.score,
            "search_metrics": sm.model_dump(mode="json"),
        }
        # Расширенный снимок для линейных графиков «Рынка» во времени (воронка/гейты/деньги/
        # форматы) — кладётся только когда фон уже собрал overview (не в live-фолбэке роутера,
        # чтобы не дублировать расчёт на каждый запрос). Старые снимки без этих ключей
        # корректно читаются `multi_history_from_snapshots` (нет ключа → нет точек для серии).
        if overview is not None and getattr(overview, "available", False):
            payload["funnel"] = [lvl.model_dump(mode="json") for lvl in overview.funnel]
            payload["gates"] = overview.gates.model_dump(mode="json")
            payload["money"] = overview.money.model_dump(mode="json")
            payload["market_index"] = overview.market_index.model_dump(mode="json")
            payload["demand"] = overview.demand.model_dump(mode="json")
            payload["offer_chance_components"] = [
                c.model_dump(mode="json") for c in overview.offer_chance.components
            ]
        await save_market_snapshot(payload, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — снимок не критичен для вызывающего
        logger.debug("market_snapshots: снимок не сохранён (нет PG?): %s", exc)


__all__ = [
    "MarketSnapshot",
    "MetricHistory",
    "MetricPoint",
    "MultiHistoryGroup",
    "MultiHistoryResponse",
    "MultiHistorySeries",
    "OfferChanceHistory",
    "OfferChancePoint",
    "clamp_history_days",
    "get_metric_history",
    "get_multi_history",
    "get_offer_chance_history",
    "get_previous_snapshot",
    "history_from_snapshots",
    "list_snapshots",
    "metric_history_from_snapshots",
    "multi_history_from_snapshots",
    "record_daily_pulse_state",
    "save_market_snapshot",
]
