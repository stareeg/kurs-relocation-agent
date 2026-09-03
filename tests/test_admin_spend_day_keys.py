"""Этап 1 редизайна админки: ключ дневного разреза расхода — календарный день, не таймстемп.

`generate_series(current_date - N, current_date, interval '1 day')` возвращает **timestamptz**,
поэтому `g.day::text` давал «2026-08-12 00:00:00+00». Фронт (`admin-spend.ts::spendRowLabel`)
сводит ключ к «12.08» только если он выглядит как ISO-день, иначе печатает строку как есть —
и подпись оси графика вылезала на 45° поверх заголовка таблицы под ним.

Тест держит именно каст: SQL здесь не исполняется (пул подменён), поэтому проверяем форму
запроса, а не результат. Настоящее значение проверяет прод — но регрессию `::date` тест ловит.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

import core.platform.admin.service as admin_svc
from core.platform.admin.service import load_spend

DAY_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _Pool:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def fetch(self, sql: str, *_args: Any) -> list[dict[str, Any]]:
        self.queries.append(sql)
        return []

    async def fetchrow(self, sql: str, *_args: Any) -> dict[str, Any] | None:
        self.queries.append(sql)
        return None

    def query_with(self, marker: str) -> str:
        for sql in self.queries:
            if marker in sql:
                return sql
        raise AssertionError(f"нет запроса с {marker!r}")


@pytest.mark.asyncio
async def test_day_group_selects_calendar_day_not_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _Pool()
    monkeypatch.setattr(admin_svc, "get_pool", lambda: pool)

    await load_spend(days=14, group_by="day")

    sql = pool.query_with("generate_series")
    assert "g.day::date::text as key" in sql, "день обязан кастоваться к date до ::text"
    assert "g.day::text as key" not in sql
    assert "order by 1 desc" in sql


def test_day_key_shape_is_what_the_frontend_expects() -> None:
    """Зеркало охранника `isIsoDay` из `frontend/src/features/admin/admin-spend.ts`.

    Если формат ключа когда-нибудь поменяют на бэкенде, фронт не упадёт — он молча начнёт
    печатать сырую строку. Поэтому форма зафиксирована с обеих сторон.
    """
    assert DAY_KEY_RE.match("2026-08-12")
    assert not DAY_KEY_RE.match("2026-08-12 00:00:00+00")
