"""Сравнение собранных вилок с бенчмарками salary_estimator."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from core.domains.market.salary_calib import CalibSample
from core.domains.market.salary_calibration.salary_aggregate import dedupe_samples, filter_outliers
from core.domains.opportunities.salary_estimator import get_benchmark
from core.kernel.money import GROSS_TO_NET_RATIO, gross_to_net

# grade из LLM → ключ бенчмарка в estimator
_GRADE_TO_BENCH: dict[str, str] = {
    "junior": "junior",
    "junior_plus": "junior",
    "middle": "mid",
    "middle_plus": "mid",
    "senior": "senior_plus",
    "teamlead": "senior_plus",
    "techlead": "senior_plus",
    "other": "senior_plus",
    "": "senior_plus",
}


def _bench_key(company_type: str, grade: str) -> tuple[str, str]:
    ct = (company_type or "unknown").strip() or "unknown"
    gr = _GRADE_TO_BENCH.get((grade or "").strip(), "senior_plus")
    return (ct, gr)


def _benchmark_net_range(company_type: str, grade: str) -> tuple[int, int] | None:
    key = _bench_key(company_type, grade)
    bench = get_benchmark(*key)
    if not bench:
        return None
    lo, hi = bench
    return gross_to_net(lo) or lo, gross_to_net(hi) or hi


def build_benchmark_insights(samples: list[CalibSample]) -> str:
    """Текст: медианы по сегментам vs текущие бенчмарки (net)."""
    cleaned = filter_outliers(dedupe_samples(samples))
    if not cleaned:
        return ""

    by_seg: dict[tuple[str, str], list[int]] = defaultdict(list)
    for s in cleaned:
        a = s.salary_min_net
        b = s.salary_max_net or a
        if a is None:
            continue
        mid = int((int(a) + int(b if b is not None else a)) / 2)
        ct = (s.company_type or "unknown").strip() or "unknown"
        gr = (s.grade or "unknown").strip() or "unknown"
        by_seg[(ct, gr)].append(mid)

    lines = ["💡 Бенчмарки vs собранные медианы (net):"]
    for (ct, gr), mids in sorted(by_seg.items(), key=lambda x: (-len(x[1]), x[0])):
        if len(mids) < 2:
            continue
        med = int(median(mids))
        bench = _benchmark_net_range(ct, gr)
        if not bench:
            lines.append(f"• {ct}/{gr}: n={len(mids)}, медиана {med // 1000}k (нет бенчмарка)")
            continue
        blo, bhi = bench
        bmid = (blo + bhi) // 2
        delta = med - bmid
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"• {ct}/{gr}: n={len(mids)}, собр. {med // 1000}k, "
            f"бенч {blo // 1000}–{bhi // 1000}k ({sign}{delta // 1000}k)"
        )
    return "\n".join(lines) if len(lines) > 1 else ""


def export_calibration_snapshot(
    samples: list[CalibSample],
    *,
    report_text: str,
    insights_text: str,
    export_path: str,
) -> Path:
    """Сохранить отчёт на диск для ручной правки бенчмарков."""
    path = Path(export_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    body = [
        f"# Калибровка зарплат — снимок {ts}",
        "",
        f"Образцов с цифрами (после дедупа): {len(dedupe_samples(samples))}",
        "",
        "## Сводка",
        "",
        report_text,
        "",
    ]
    if insights_text:
        body.extend(["## Бенчмарки", "", insights_text, ""])
    body.extend(
        [
            "## Примечание",
            "",
            f"Gross→net в estimator: ×{GROSS_TO_NET_RATIO}.",
            "Правка сида бенчмарков (`SALARY_BENCHMARKS_PATH` / "
            "deploy/salary_benchmarks.example.json) — вручную после review.",
            "",
        ]
    )
    path.write_text("\n".join(body), encoding="utf-8")
    return path
