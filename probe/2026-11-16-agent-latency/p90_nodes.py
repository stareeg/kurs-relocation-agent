#!/usr/bin/env zsh
# A-3: тайминги узлов запусков агента из Postgres → p90 по узлам (OQ-29, порог 60 с).
#
# Источник — agent_events (type='node_timing', duration_ms), миграция 0155; узлы:
# plan / step / check / replan / finalize / confirm. По умолчанию DSN из core настроек
# продукта (та же база, что у API); аргумент --dsn переопределяет.
#
# Пример:  uv run python probe/2026-11-16-agent-latency/p90_nodes.py --dsn postgresql://...
#
# Порог (OQ-29): p90 шага ≤ 60 с. Выход за порог → exit 1 (для будущего CI-стража).

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

import asyncpg

P90_STEP_THRESHOLD_S = 60.0
"""Порог p90 шага (OQ-29): шаг дольше минуты на базовых моделях — повод разбираться."""


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(round((p / 100) * (len(sorted_values) - 1))))
    return sorted_values[idx]


async def collect(dsn: str, run_id: int | None) -> dict[str, list[float]]:
    conn = await asyncpg.connect(dsn)
    try:
        if run_id is not None:
            rows = await conn.fetch(
                "select node, duration_ms from agent_events"
                " where type = 'node_timing' and node is not null and run_id = $1"
                " order by id",
                run_id,
            )
        else:
            rows = await conn.fetch(
                "select node, duration_ms from agent_events"
                " where type = 'node_timing' and node is not null order by id"
            )
    finally:
        await conn.close()
    by_node: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["duration_ms"] is not None:
            by_node[str(row["node"])].append(float(row["duration_ms"]))
    return by_node


async def main() -> int:
    parser = argparse.ArgumentParser(description="p90 таймингов узлов запусков агента (OQ-29)")
    parser.add_argument(
        "--dsn", default=None, help="postgres DSN; по умолчанию из настроек продукта"
    )
    parser.add_argument("--run-id", type=int, default=None, help="один запуск вместо всех")
    args = parser.parse_args()

    if args.dsn is None:
        # Скрипт лежит в probe/ и запускается из корня репозитория — добавляем корень в path.
        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root))
        from core.platform.config.settings import get_settings

        args.dsn = get_settings().postgres_dsn()

    by_node = await collect(args.dsn, args.run_id)
    if not by_node:
        print("нет node_timing событий — прогоните запуск агента на стенде (A-3)")
        return 2

    scope = f"run {args.run_id}" if args.run_id is not None else "все запуски"
    print(f"Тайминги узлов ({scope}):\n")
    print(f"{'узел':<10} {'n':>5} {'p50, с':>8} {'p90, с':>8} {'max, с':>8}")
    step_p90 = None
    for node in sorted(by_node):
        values = sorted(v / 1000 for v in by_node[node])
        p50, p90, mx = percentile(values, 50), percentile(values, 90), values[-1]
        if node == "step":
            step_p90 = p90
        print(f"{node:<10} {len(values):>5} {p50:>8.1f} {p90:>8.1f} {mx:>8.1f}")

    if step_p90 is None:
        print("\nузел step не встретился — считать p90 шага нечего")
        return 2
    print(f"\np90 шага: {step_p90:.1f} с (порог {P90_STEP_THRESHOLD_S:.0f} с, OQ-29)")
    return 0 if step_p90 <= P90_STEP_THRESHOLD_S else 1


if __name__ == "__main__":
    _ = Path(__file__)  # скрипт запускается из корня репозитория
    sys.exit(asyncio.run(main()))
