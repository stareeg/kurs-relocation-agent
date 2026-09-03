"""Этап 1.1: `/overview` разрезан на `/summary` + `/people` + `/attention` + `/spend`.

Проверяем две вещи: ручки собирают то, что обещают, и подстановка фрагментов SQL идёт строго
по белым спискам — `sort`/`onboarding`/`group_by` приезжают из URL, а имя колонки нельзя
передать параметром запроса.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

import core.platform.admin.service as admin_svc
from core.platform.admin import (
    AdminError,
    load_attention,
    load_people,
    load_spend,
    load_summary,
    people_sort_keys,
)


class _RecordingPool:
    """Пул, который запоминает SQL и аргументы и отдаёт заранее заданные строки."""

    def __init__(self, rows: dict[str, Any] | None = None) -> None:
        self.rows = rows or {}
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    def _resolve(self, sql: str) -> Any:
        self.queries.append((sql, ()))
        for marker, value in self.rows.items():
            if marker in sql:
                return value
        return None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        value = self._resolve(sql)
        self.queries[-1] = (sql, args)
        return list(value or [])

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        value = self._resolve(sql)
        self.queries[-1] = (sql, args)
        return dict(value) if isinstance(value, dict) else None

    def sql_containing(self, marker: str) -> str:
        for sql, _ in self.queries:
            if marker in sql:
                return sql
        raise AssertionError(f"нет запроса с {marker!r}: {[q[:60] for q, _ in self.queries]}")

    def args_for(self, marker: str) -> tuple[Any, ...]:
        for sql, args in self.queries:
            if marker in sql:
                return args
        raise AssertionError(f"нет запроса с {marker!r}")


def _install(monkeypatch: pytest.MonkeyPatch, rows: dict[str, Any] | None = None) -> _RecordingPool:
    pool = _RecordingPool(rows)
    monkeypatch.setattr(admin_svc, "get_pool", lambda: pool)
    return pool


# --- сортировка списка людей ------------------------------------------------------------


def test_sort_keys_cover_both_directions() -> None:
    keys = people_sort_keys()
    assert "cost_month" in keys and "-cost_month" in keys
    assert len(keys) == len(set(keys)), "дубли в белом списке сортировок"


@pytest.mark.parametrize(
    "sort",
    ["", "неизвестно", "-неизвестно", "p.account_id; drop table accounts", "1=1"],
)
def test_unknown_sort_falls_back_to_default(sort: str) -> None:
    """Сортировка приезжает из URL: устаревшая ссылка обязана открыть список, а не 500."""
    assert admin_svc._resolve_people_order(sort) == admin_svc._DEFAULT_PEOPLE_ORDER


def test_known_sort_uses_whitelisted_column_and_stable_tiebreak() -> None:
    order = admin_svc._resolve_people_order("-cost_month")
    assert order.startswith("p.month_cost_usd desc")
    # Вторичный ключ обязателен: без него строки с равными значениями скачут между опросами.
    assert order.endswith("p.account_id")
    assert admin_svc._resolve_people_order("cost_month").startswith("p.month_cost_usd asc")


@pytest.mark.asyncio
async def test_people_sort_never_interpolates_raw_input(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _install(monkeypatch)
    await load_people(sort="username; drop table accounts")
    sql = pool.sql_containing("total_count")
    assert "drop table" not in sql
    assert admin_svc._DEFAULT_PEOPLE_ORDER in sql


# --- фильтры списка людей ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_people_passes_filters_as_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _install(monkeypatch)
    await load_people(query="  kate ", status="active", limit=50, offset=100)
    args = pool.args_for("total_count")
    assert args == ("active", "kate", 50, 100), "строка поиска обязана уходить параметром"
    sql = pool.sql_containing("total_count")
    assert "p.telegram_user_id::text" in sql
    assert "p.key_hint ilike" in sql


@pytest.mark.asyncio
async def test_people_ignores_unknown_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Чужой статус — «любой», а не отказ: фильтр живёт в URL."""
    pool = _install(monkeypatch)
    await load_people(status="deleted")
    assert pool.args_for("total_count")[0] == ""


@pytest.mark.asyncio
async def test_people_onboarding_filter_is_whitelisted(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _install(monkeypatch)
    await load_people(onboarding="no_key")
    assert "not p.has_openrouter_key" in pool.sql_containing("total_count")


@pytest.mark.asyncio
async def test_people_rejects_unknown_onboarding(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    with pytest.raises(AdminError):
        await load_people(onboarding="true or 1=1")


@pytest.mark.parametrize("signal,fragment", [("errors", "p.errors_24h > 0"), ("stale", "7 days")])
@pytest.mark.asyncio
async def test_people_signal_filter_is_whitelisted(
    signal: str, fragment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = _install(monkeypatch)
    await load_people(signal=signal)
    assert fragment in pool.sql_containing("total_count")


@pytest.mark.asyncio
async def test_people_rejects_unknown_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    with pytest.raises(AdminError):
        await load_people(signal="true or 1=1")


@pytest.mark.asyncio
async def test_people_total_is_full_count_not_page_size(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "account_id": 1,
            "telegram_username": "u1",
            "telegram_user_id": 10,
            "role": "member",
            "status": "active",
            "total_count": 137,
        }
    ]
    _install(monkeypatch, {"total_count": rows})
    page = await load_people(limit=1)
    assert len(page.items) == 1
    assert page.total == 137


@pytest.mark.asyncio
async def test_people_empty_page_has_zero_total(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    page = await load_people()
    assert page.items == []
    assert page.total == 0
    assert page.degraded is False


def test_spend_sparkline_fills_missing_days() -> None:
    """Дырка в днях — ноль, иначе спарклайн врёт наклоном."""
    series = admin_svc.spend_sparkline_series(
        [1, 2],
        [{"account_id": 1, "day": date(2026, 8, 25), "cost": 1.5}],
        days=3,
        today=date(2026, 8, 25),
    )
    assert series[1] == [0.0, 0.0, 1.5]
    assert series[2] == [0.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_people_attaches_sparkline_for_page(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "account_id": 1,
            "telegram_username": "u1",
            "telegram_user_id": 10,
            "role": "member",
            "status": "active",
            "total_count": 1,
        }
    ]
    pool = _install(
        monkeypatch,
        {
            "total_count": rows,
            "account_id = any": [{"account_id": 1, "day": date.today(), "cost": 0.4}],
        },
    )
    page = await load_people(limit=1)
    assert len(page.items[0].spend_14d) == admin_svc.SPEND_SPARKLINE_DAYS
    assert page.items[0].spend_14d[-1] == pytest.approx(0.4)
    assert pool.args_for("account_id = any")[0] == [1]


# --- сводка -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_maps_all_kpi(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "accounts_active": {"accounts_active": 4, "seen_24h": 2},
            "from llm_usage": {"total": 1.5, "system": 0.25, "month": 9.5},
            "from copilot_logs where ts": {"total": 7, "system": 3},
            "as failed_tasks": {"failed_tasks": 12, "pending_keys": 2},
        },
    )
    summary = await load_summary()
    assert (summary.accounts_active, summary.seen_24h) == (4, 2)
    assert summary.today_cost_usd == pytest.approx(1.5)
    assert summary.today_cost_system_usd == pytest.approx(0.25)
    assert summary.month_cost_usd == pytest.approx(9.5)
    assert (summary.errors_24h, summary.errors_24h_system) == (7, 3)
    assert (summary.failed_tasks, summary.pending_keys) == (12, 2)
    assert summary.degraded is False


@pytest.mark.asyncio
async def test_summary_does_not_load_people(monkeypatch: pytest.MonkeyPatch) -> None:
    """Смысл лёгкой ручки: шесть чисел без выгрузки всего флота."""
    pool = _install(monkeypatch)
    await load_summary()
    assert not any("a.id as account_id" in sql for sql, _ in pool.queries)


# --- очередь внимания -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attention_counters_survive_list_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "from background_tasks \nwhere status": [],
            "as tasks": {"tasks": 137, "errors": 44},
        },
    )
    attention = await load_attention()
    assert attention.failed_tasks_total == 137
    assert attention.errors_total == 44


@pytest.mark.asyncio
async def test_attention_stale_keeps_never_seen_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Не заходил ни разу» — не ноль дней молчания, а отсутствие значения."""
    _install(
        monkeypatch,
        {
            "days_silent": [
                {"account_id": 3, "telegram_username": "u3", "days_silent": None},
                {"account_id": 4, "telegram_username": "u4", "days_silent": 21},
            ]
        },
    )
    attention = await load_attention()
    assert [s.days_silent for s in attention.stale] == [None, 21]


@pytest.mark.asyncio
async def test_attention_stale_requires_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без резюме молчание ничего не значит — человек просто не начал."""
    pool = _install(monkeypatch)
    await load_attention()
    assert "from resumes r" in pool.sql_containing("days_silent")


# --- расход -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spend_rejects_unknown_group(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    with pytest.raises(AdminError):
        await load_spend(group_by="cost_usd; drop table llm_usage")


@pytest.mark.parametrize("group_by", ["day", "model", "feature", "account"])
@pytest.mark.asyncio
async def test_spend_supports_every_documented_group(
    group_by: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(
        monkeypatch,
        {
            "llm_usage u": [
                {"key": "k1", "cost_usd": 0.5, "tokens_in": 10, "tokens_out": 5, "calls": 2},
                {"key": "k2", "cost_usd": 0.25, "tokens_in": 4, "tokens_out": 2, "calls": 1},
            ]
        },
    )
    spend = await load_spend(days=14, group_by=group_by)
    assert spend.group_by == group_by
    assert spend.days == 14
    assert spend.total_usd == pytest.approx(0.75), "итог обязан сходиться с суммой строк"
    assert [r.key for r in spend.rows] == ["k1", "k2"]


@pytest.mark.asyncio
async def test_spend_window_is_parameterised(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _install(monkeypatch)
    await load_spend(days=30, group_by="model")
    assert pool.args_for("from llm_usage u") == (30,)


@pytest.mark.asyncio
async def test_spend_filters_by_account_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вкладка «Расход» в карточке — та же витрина, суженная до человека."""
    pool = _install(monkeypatch)
    await load_spend(days=14, group_by="day", account_id=7)
    assert pool.args_for("generate_series") == (14, 7)
    assert "u.account_id = $2" in pool.sql_containing("generate_series")
    await load_spend(days=14, group_by="feature", account_id=7)
    assert pool.args_for("from llm_usage u") == (14, 7)
    assert "u.account_id = $2" in pool.sql_containing("from llm_usage u")


@pytest.mark.asyncio
async def test_spend_day_fills_empty_days(monkeypatch: pytest.MonkeyPatch) -> None:
    """По дням ось времени непрерывная: пустой день — столбик нуля, а не дырка."""
    pool = _install(monkeypatch)
    await load_spend(days=14, group_by="day")
    sql = pool.sql_containing("generate_series")
    assert "left join llm_usage u" in sql
    assert pool.args_for("generate_series") == (14,)


@pytest.mark.asyncio
async def test_spend_totals_match_kpi_window(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "generate_series": [
                {"key": "2026-08-25", "cost_usd": 0.5, "tokens_in": 1, "tokens_out": 1, "calls": 1}
            ],
            "as today_usd": {
                "today_usd": 0.5,
                "month_usd": 12.0,
                "cache_hits": 3,
                "cache_calls": 10,
            },
        },
    )
    spend = await load_spend(days=14, group_by="day")
    assert spend.today_usd == pytest.approx(0.5)
    assert spend.month_usd == pytest.approx(12.0)
    assert spend.cache_hit_rate == pytest.approx(0.3)
    assert spend.forecast_month_usd > 0


@pytest.mark.asyncio
async def test_spend_sql_includes_latency_cache_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _install(monkeypatch)
    await load_spend(days=14, group_by="model")
    sql = pool.sql_containing("from llm_usage u")
    assert "percentile_cont(0.5)" in sql
    assert "percentile_cont(0.95)" in sql
    assert "u.cache_hit" in sql
    assert "u.attempt" in sql


@pytest.mark.asyncio
async def test_people_spend_signal_uses_threshold_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _install(monkeypatch, {"as spend_alert_usd": {"spend_alert_usd": 8}})
    await load_people(signal="spend")
    sql = pool.sql_containing("total_count")
    assert "p.spend_month_usd > $5" in sql
    assert pool.args_for("total_count") == ("", "", 200, 0, 8.0)


@pytest.mark.asyncio
async def test_people_spend_signal_empty_when_alert_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Порог 0 = сигнал выключен: фильтр не должен показывать весь флот."""
    pool = _install(monkeypatch, {"as spend_alert_usd": {"spend_alert_usd": 0}})
    await load_people(signal="spend")
    sql = pool.sql_containing("total_count")
    assert "false" in sql
    assert "spend_month_usd >" not in sql
