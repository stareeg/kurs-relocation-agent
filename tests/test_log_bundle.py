"""Бандл логов: строго свой аккаунт, читаемый состав, устойчивость к лежащему Postgres.

Архив читает разработчик, а не пользователь, поэтому тест закрепляет ровно то, ради чего он
переделан: шапка со счётчиками, лента по возрастанию времени, отдельный файл ошибок и сырые
строки. Плюс инвариант приватности — выборка только по своему `account_id`.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO

from core.platform.repo import log_bundle as m

_EXPECTED_FILES = {
    "manifest.json",
    "timeline.txt",
    "errors.txt",
    "copilot_logs.json",
    "llm_calls.json",
}


class _Row(dict):
    """Строка выдачи asyncpg: в коде она приводится через dict(r)."""


async def test_build_log_bundle_zip_without_pg(monkeypatch) -> None:
    """Нет PG → архив всё равно собирается, просто пустой (друг присылает бандл после падения)."""

    class _BrokenPool:
        async def fetch(self, *args, **kwargs):
            raise RuntimeError("PG down")

    monkeypatch.setattr(m, "get_pool", lambda: _BrokenPool())

    data = await m.build_log_bundle_zip(1)
    assert data[:2] == b"PK"  # zip magic

    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert set(zf.namelist()) == _EXPECTED_FILES
        assert json.loads(zf.read("copilot_logs.json")) == []
        assert json.loads(zf.read("llm_calls.json")) == []
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["rows"] == 0
        assert manifest["account_id"] == 1


async def test_bundle_queries_own_account_and_window(monkeypatch) -> None:
    """Оба источника (логи и LLM-вызовы) идут по своему account_id и одному окну."""

    calls: list[tuple[str, int, datetime]] = []

    class _Pool:
        async def fetch(self, sql, *args):
            calls.append((sql, args[0], args[1]))
            return []

    monkeypatch.setattr(m, "get_pool", lambda: _Pool())
    await m.build_log_bundle_zip(7, window_hours=48)

    assert len(calls) == 2
    assert {sql.split()[3] for sql, _, _ in calls}  # оба запроса — select ... from
    for _sql, account_id, since in calls:
        assert account_id == 7
        assert timedelta(hours=47) <= (datetime.now(UTC) - since) <= timedelta(hours=48, seconds=5)


async def test_bundle_timeline_is_chronological_and_errors_separated(monkeypatch) -> None:
    """timeline.txt — по возрастанию времени; errors.txt — только WARNING+ со стеком."""

    older = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
    newer = datetime(2026, 8, 10, 11, 0, tzinfo=UTC)

    class _Pool:
        async def fetch(self, sql, *args):
            if "llm_usage" in sql:
                return []
            return [
                _Row(
                    ts=older,
                    level="INFO",
                    logger="api.main",
                    event="HTTP",
                    task_id=None,
                    msg="POST /api/offers -> 200 за 120 мс",
                    fields={"status": 200},
                ),
                _Row(
                    ts=newer,
                    level="ERROR",
                    logger="frontend",
                    event="ФРОНТ",
                    task_id=None,
                    msg="TypeError: x is not a function",
                    fields={"stack": "at Foo\nat Bar"},
                ),
            ]

    monkeypatch.setattr(m, "get_pool", lambda: _Pool())
    data = await m.build_log_bundle_zip(3)

    with zipfile.ZipFile(BytesIO(data)) as zf:
        timeline = zf.read("timeline.txt").decode("utf-8")
        errors = zf.read("errors.txt").decode("utf-8")
        manifest = json.loads(zf.read("manifest.json"))

    assert timeline.index("POST /api/offers") < timeline.index("TypeError")
    assert "POST /api/offers" not in errors
    assert "TypeError" in errors
    assert "at Foo" in errors  # стектрейс разворачивается только в errors.txt
    assert manifest["levels"] == {"INFO": 1, "ERROR": 1}
    assert manifest["rows"] == 2


def test_window_hours_is_clamped() -> None:
    """Окно: пусто/мусор → дефолт, слишком большое → потолок (архив остаётся подъёмным)."""
    assert m.resolve_window_hours(None) == m.DEFAULT_WINDOW_HOURS
    assert m.resolve_window_hours(0) == m.DEFAULT_WINDOW_HOURS
    assert m.resolve_window_hours(-5) == m.DEFAULT_WINDOW_HOURS
    assert m.resolve_window_hours(6) == 6
    assert m.resolve_window_hours(10_000) == m.MAX_WINDOW_HOURS
