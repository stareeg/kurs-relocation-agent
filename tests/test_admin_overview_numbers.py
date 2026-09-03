"""Этап 0+2: KPI сводки == список/график под ним.

Каждый тест закрывает дефект из таблицы «Диагноз А». Фикстура подменяет пул (не `_fetch`):
обработка сбоя и `degraded` проверяются на настоящем коде сервиса. `/overview` снят в
конце Этапа 2 — те же инварианты живут на `/summary` + `/attention` + `/spend`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

import core.platform.admin.service as admin_svc
from core.platform.admin.service import (
    forecast_month_usd,
    load_attention,
    load_spend,
    load_summary,
)

_NOW = datetime.now(UTC)


# Отличимый кусок каждого запроса → логическое имя. Маркеры обязаны быть уникальными:
# витрина людей тянет copilot_logs и llm_usage подзапросами.
_SQL_MARKERS: list[tuple[str, str]] = [
    ("as spend_alert_usd", "порог расхода"),
    ("having coalesce(sum(u.cost_usd)", "превысили порог"),
    ("as accounts_active", "аккаунты"),
    ("as has_extension", "воронка онбординга"),
    ("pg_database_size", "размер postgres"),
    ("group by status", "глубина очереди"),
    ("as last_finished", "последняя задача"),
    ("from schema_migrations", "применённые миграции"),
    # Скользящие 30 дней в KPI-шапке — то же окно, что month_cost_usd у человека.
    ("day >= current_date - 29", "расход за сегодня и месяц"),
    ("count(*) filter (where account_id is null)::int as system", "счётчик ошибок"),
    ("as failed_tasks", "очереди"),
    ("generate_series", "расход"),
    ("coalesce(nullif(u.model, ''), 'без модели')", "расход по моделям дня"),
    ("from llm_usage u left join accounts", "расход"),
    ("as today_usd", "итоги расхода"),
    ("as tasks", "счётчики очереди"),
    ("from background_tasks \nwhere status = 'failed'", "упавшие задачи"),
    ("select id, kind, account_id, last_error", "упавшие задачи"),
    ("order by l.ts desc limit 20", "ошибки"),
    ("interval '1 hour'", "пачки ошибок"),
    ("from openrouter_key_requests r join", "заявки на ключ"),
    ("as days_silent", "отвалившиеся"),
    ("as days_waiting", "ждут ключ без заявки"),
    ("a.id as account_id", "люди"),
]


def _query_name(sql: str) -> str | None:
    for marker, name in _SQL_MARKERS:
        if marker in sql:
            return name
    return None


class _FakePool:
    def __init__(self, rows: dict[str, Any], fail: set[str]) -> None:
        self.rows = rows
        self.fail = fail
        self.unmatched: list[str] = []

    def _resolve(self, sql: str) -> Any:
        name = _query_name(sql)
        if name is None:
            self.unmatched.append(sql)
            return None
        if name in self.fail:
            raise RuntimeError("postgres недоступен")
        return self.rows.get(name)

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        _ = args
        value = self._resolve(sql)
        return list(value or [])

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        _ = args
        value = self._resolve(sql)
        return dict(value) if isinstance(value, dict) else None


class _Fixture:
    def __init__(self, **rows: Any) -> None:
        self.rows: dict[str, Any] = {
            "аккаунты": {"accounts_active": 0, "seen_24h": 0},
            "воронка онбординга": {
                "telegram": 0,
                "has_key": 0,
                "has_resume": 0,
                "has_extension": 0,
            },
            "размер postgres": {"size": 1_048_576, "postgres_ok": True},
            "глубина очереди": [],
            "последняя задача": {"last_finished": None},
            "применённые миграции": {"applied": 141},
            "порог расхода": {"spend_alert_usd": 0},
            "превысили порог": [],
            "расход за сегодня и месяц": {"total": 0.0, "system": 0.0, "month": 0.0},
            "счётчик ошибок": {"total": 0, "system": 0},
            "очереди": {"failed_tasks": 0, "pending_keys": 0},
            "расход": [],
            "расход по моделям дня": [],
            "итоги расхода": {
                "today_usd": 0.0,
                "month_usd": 0.0,
                "cache_hits": 0,
                "cache_calls": 0,
                "median_ms": None,
                "p95_ms": None,
                "retries": 0,
            },
            "упавшие задачи": [],
            "счётчики очереди": {"tasks": 0, "errors": 0},
            "ошибки": [],
            "пачки ошибок": [],
            "заявки на ключ": [],
            "отвалившиеся": [],
            "ждут ключ без заявки": [],
            "люди": [],
        }
        self.rows.update(rows)
        self.fail: set[str] = set()
        self.pool = _FakePool(self.rows, self.fail)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> _FakePool:
        self.pool = _FakePool(self.rows, self.fail)
        monkeypatch.setattr(admin_svc, "get_pool", lambda: self.pool)
        monkeypatch.setattr(admin_svc, "migration_numbers", lambda: [141])
        return self.pool


@pytest.mark.asyncio
async def test_a1_failed_tasks_not_capped_by_list_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """А1: список упавших задач урезан `limit 20`, счётчик — полный."""
    tasks = [
        {"id": i, "kind": "tg_push", "account_id": 1, "last_error": "boom", "finished_at": _NOW}
        for i in range(20)
    ]
    pool = _Fixture(
        **{"упавшие задачи": tasks, "счётчики очереди": {"tasks": 137, "errors": 0}}
    ).install(monkeypatch)

    attention = await load_attention()

    assert pool.unmatched == []
    assert len(attention.failed_tasks) == 20
    assert attention.failed_tasks_total == 137


@pytest.mark.asyncio
async def test_a2_today_cost_matches_chart_not_sum_over_people(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """А2: расход за сегодня — по всей llm_usage, как и график; хвост без account_id виден."""
    today = date.today().isoformat()
    pool = _Fixture(
        **{
            "расход за сегодня и месяц": {"total": 0.75, "system": 0.25, "month": 2.5},
            "расход": [
                {"key": today, "cost_usd": 0.75, "tokens_in": 0, "tokens_out": 0, "calls": 3}
            ],
            "итоги расхода": {
                "today_usd": 0.75,
                "month_usd": 0.75,
                "cache_hits": 1,
                "cache_calls": 3,
            },
        }
    ).install(monkeypatch)

    summary = await load_summary()
    spend = await load_spend(days=14, group_by="day")

    assert pool.unmatched == []
    assert summary.today_cost_usd == pytest.approx(0.75)
    assert summary.today_cost_system_usd == pytest.approx(0.25)
    assert summary.month_cost_usd == pytest.approx(2.5)
    assert spend.today_usd == pytest.approx(summary.today_cost_usd)
    chart_today = next(r.cost_usd for r in spend.rows if r.key == today)
    assert spend.today_usd == pytest.approx(chart_today)


@pytest.mark.asyncio
async def test_a3_errors_counter_covers_rows_without_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """А3: «0 ошибок» над непустым списком — системные строки не попадали в счётчик."""
    errors = [
        {
            "ts": _NOW,
            "level": "ERROR",
            "event": "БД",
            "msg": "пул недоступен",
            "account_id": None,
            "telegram_username": None,
        }
    ]
    pool = _Fixture(
        **{
            "ошибки": errors,
            "счётчик ошибок": {"total": 1, "system": 1},
            "счётчики очереди": {"tasks": 0, "errors": 1},
        }
    ).install(monkeypatch)

    summary = await load_summary()
    attention = await load_attention()

    assert pool.unmatched == []
    assert len(attention.errors) == 1
    assert summary.errors_24h == 1
    assert summary.errors_24h_system == 1
    assert attention.errors_total == summary.errors_24h


@pytest.mark.asyncio
async def test_a4_pending_keys_counts_same_statuses_as_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """А4: блок «Ждут ключ» рисует pending и approved — счётчик считает то же множество."""
    requests = [
        {
            "id": 1,
            "account_id": 2,
            "telegram_username": "u2",
            "status": "pending",
            "requested_at": _NOW,
            "note": None,
        },
        {
            "id": 2,
            "account_id": 3,
            "telegram_username": "u3",
            "status": "approved",
            "requested_at": _NOW,
            "note": None,
        },
    ]
    pool = _Fixture(
        **{
            "заявки на ключ": requests,
            "очереди": {"failed_tasks": 0, "pending_keys": 2},
        }
    ).install(monkeypatch)

    summary = await load_summary()
    attention = await load_attention()

    assert pool.unmatched == []
    assert len(attention.key_requests) == 2
    assert summary.pending_keys == len(attention.key_requests)


def test_a5_active_jobs_sql_excludes_archived_and_skipped() -> None:
    """А5: колонка обещает активные — SQL обязан отсекать архив и пропущенные."""
    sql = admin_svc._USERS_SQL_BODY
    assert "not j.is_archived" in sql
    assert "coalesce(j.status, '') <> 'skipped'" in sql


@pytest.mark.asyncio
async def test_a6_seen_24h_counts_only_active_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    """А6: «Заходили за сутки» считает только активные — подпись в UI об этом говорит."""
    pool = _Fixture(**{"аккаунты": {"accounts_active": 2, "seen_24h": 1}}).install(monkeypatch)

    summary = await load_summary()

    assert pool.unmatched == []
    assert summary.accounts_active == 2
    assert summary.seen_24h == 1


@pytest.mark.asyncio
async def test_degraded_marks_partial_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.2: упавший запрос — это «не знаю», а не «ноль». Флаг и причина доезжают до фронта."""
    fixture = _Fixture()
    fixture.fail.update({"счётчик ошибок", "очереди"})
    pool = fixture.install(monkeypatch)

    summary = await load_summary()

    assert pool.unmatched == []
    assert summary.degraded is True
    assert "счётчик ошибок" in summary.degraded_reason
    assert "очереди" in summary.degraded_reason
    assert summary.health.postgres_ok is True


@pytest.mark.asyncio
async def test_healthy_summary_is_not_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Fixture().install(monkeypatch)

    summary = await load_summary()

    assert pool.unmatched == [], "незастабленный запрос выглядел бы как сбой БД"
    assert summary.degraded is False
    assert summary.degraded_reason == ""
    assert summary.health.postgres_ok is True


@pytest.mark.asyncio
async def test_postgres_failure_marks_health_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _Fixture()
    fixture.fail.add("размер postgres")
    fixture.install(monkeypatch)

    summary = await load_summary()

    assert summary.health.postgres_ok is False
    assert summary.degraded is True


def test_forecast_month_usd_is_linear_extrapolation() -> None:
    """25-е, потрачено $25 → август (31 день) прогнозируется как $31."""
    assert forecast_month_usd(25.0, today=date(2026, 8, 25)) == pytest.approx(31.0)
    assert forecast_month_usd(0.0, today=date(2026, 8, 25)) == 0.0
    assert forecast_month_usd(10.0, today=date(2026, 8, 1)) == pytest.approx(310.0)


@pytest.mark.asyncio
async def test_spend_cache_hit_rate_none_when_no_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    _Fixture().install(monkeypatch)
    spend = await load_spend(days=14, group_by="model")
    assert spend.cache_hit_rate is None
    assert spend.cache_calls == 0


@pytest.mark.asyncio
async def test_onboarding_funnel_maps_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Fixture(
        **{
            "воронка онбординга": {
                "telegram": 5,
                "has_key": 4,
                "has_resume": 3,
                "has_extension": 2,
            }
        }
    ).install(monkeypatch)
    summary = await load_summary()
    assert pool.unmatched == []
    assert (summary.onboarding.telegram, summary.onboarding.has_key) == (5, 4)
    assert (summary.onboarding.has_resume, summary.onboarding.has_extension) == (3, 2)


@pytest.mark.asyncio
async def test_attention_error_bursts_and_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _Fixture(
        **{
            "пачки ошибок": [{"account_id": 7, "telegram_username": "kate", "n": 7}],
            "ждут ключ без заявки": [
                {"account_id": 4, "telegram_username": "lena", "days_waiting": 3}
            ],
        }
    ).install(monkeypatch)
    attention = await load_attention()
    assert pool.unmatched == []
    assert attention.error_bursts[0].count == 7
    assert attention.no_key[0].days_waiting == 3

