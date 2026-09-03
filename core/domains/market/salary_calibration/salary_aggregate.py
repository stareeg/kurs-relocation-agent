"""Агрегация собранных вилок для отчёта калибровки + обучаемый приор сегмента."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from pydantic import BaseModel

from core.domains.market.salary_calib import CalibSample


def _sample_fingerprint(sample: CalibSample) -> tuple:
    company = (sample.company or "").strip().lower()[:40]
    position = (sample.position or "").strip().lower()[:80]
    smin = sample.salary_min_net
    smax = sample.salary_max_net if sample.salary_max_net is not None else smin
    return (company, position, smin, smax)


def dedupe_samples(samples: list[CalibSample]) -> list[CalibSample]:
    """Один fingerprint — один образец (повторные пересылки одной вакансии)."""
    unique: dict[tuple, CalibSample] = {}
    for s in samples:
        unique.setdefault(_sample_fingerprint(s), s)
    return list(unique.values())


def filter_outliers(samples: list[CalibSample]) -> list[CalibSample]:
    """Убрать явные выбросы (low confidence + нереалистичная вилка)."""
    out: list[CalibSample] = []
    for s in samples:
        conf = (s.confidence or "medium").lower()
        smin = s.salary_min_net
        smax = s.salary_max_net if s.salary_max_net is not None else smin
        if smin is None:
            out.append(s)
            continue
        mid = (int(smin) + int(smax if smax is not None else smin)) / 2
        if conf == "low" and (mid > 700_000 or mid < 150_000):
            continue
        out.append(s)
    return out


def _median_int(values: list[int]) -> int | None:
    if not values:
        return None
    return int(median(values))


def build_calibration_report(samples: list[CalibSample], *, dedupe: bool = True) -> str:
    """Текстовый отчёт для Telegram (HTML экранируется снаружи)."""
    if not samples:
        return (
            "Нет релевантных образцов с цифрами. "
            "Перешлите посты с вилками и запустите /calib flush."
        )

    raw_n = len(samples)
    if dedupe:
        samples = dedupe_samples(samples)
    samples = filter_outliers(samples)

    by_seg: dict[tuple[str, str], list[CalibSample]] = defaultdict(list)
    for s in samples:
        ct = (s.company_type or "unknown").strip() or "unknown"
        gr = (s.grade or "unknown").strip() or "unknown"
        by_seg[(ct, gr)].append(s)

    lines = [
        f"📊 Калибровка зарплат: {len(samples)} уникальных образцов с цифрами",
        "",
    ]
    if dedupe and raw_n > len(samples):
        lines.insert(1, f"(без дублей; в базе записей: {raw_n})")
        lines.insert(2, "")

    for (ct, gr), rows in sorted(by_seg.items(), key=lambda x: (-len(x[1]), x[0])):
        mins = [int(r.salary_min_net) for r in rows if r.salary_min_net]
        maxs = [int(r.salary_max_net or r.salary_min_net) for r in rows if r.salary_min_net]
        mid_vals = [int((a + b) / 2) for a, b in zip(mins, maxs, strict=False)]
        lo = _median_int(mins)
        hi = _median_int(maxs)
        mid = _median_int(mid_vals)
        if lo is None:
            continue
        lines.append(
            f"• {ct} / {gr}: n={len(rows)}, "
            f"медиана min={lo // 1000}k, max={(hi or lo) // 1000}k, mid≈{(mid or lo) // 1000}k"
        )

    all_mid = []
    for s in samples:
        a = s.salary_min_net
        b = s.salary_max_net or a
        if a is None:
            continue
        all_mid.append(int((int(a) + int(b if b is not None else a)) / 2))
    if all_mid:
        lines.append("")
        lines.append(f"Общая медиана (mid): {int(median(all_mid)) // 1000}k net")

    scales = defaultdict(int)
    for s in samples:
        scales[s.salary_scale or "unclear"] += 1
    lines.append("")
    lines.append("Шкала: " + ", ".join(f"{k}={v}" for k, v in sorted(scales.items())))

    return "\n".join(lines)


# ---- обучаемый приор сегмента ----

# Грейды сэмплов — свободный текст LLM (junior/middle/senior/teamlead/...); грейды скоринга —
# senior_plus|mid|junior|generic_backend|wrong_domain_senior. Сводим сэмплы к трём корзинам, по
# которым реально есть наблюдения ML/LLM-ролей; off-target грейды скоринга приора не получают.
_PRIOR_BUCKETS = ("senior_plus", "mid", "junior")
# Минимум наблюдений в сегменте, чтобы приор перебивал статический бенчмарк (осторожно с шумом,
# один пользователь — как enough_data в воронке). Ниже порога → фоллбэк на якорь резюме /
# опциональный сид `SALARY_BENCHMARKS_PATH`.
MIN_SEGMENT_SAMPLES = 5


class SalaryPrior(BaseModel):
    """Сегментный приор вилки из наблюдений, net ₽/мес. widened — расширен на все компании."""

    company_type: str
    grade: str
    n: int
    median_min_net: int
    median_max_net: int
    widened: bool = False

    def label(self) -> str:
        scope = "все компании" if self.widened else self.company_type
        return f"{scope}/{self.grade}"


def _grade_bucket(raw: str | None) -> str | None:
    """Свободный грейд сэмпла → корзина приора (senior_plus|mid|junior) либо None (нерелевантно)."""
    g = (raw or "").strip().lower()
    if not g:
        return None
    if any(k in g for k in ("senior", "lead", "principal", "staff")):
        return "senior_plus"
    if "middle" in g or "mid" in g:
        return "mid"
    if "junior" in g:
        return "junior"
    return None


def _segment_rows(
    samples: list[CalibSample], company_type: str, grade_bucket: str
) -> list[CalibSample]:
    return [
        s
        for s in samples
        if _grade_bucket(s.grade) == grade_bucket
        and (company_type == "unknown" or (s.company_type or "unknown").strip() == company_type)
    ]


def _iqr_trim(rows: list[CalibSample]) -> list[CalibSample]:
    """Срезать выбросы по mid через 1.5·IQR (при n≥4; меньше — оставляем как есть)."""
    if len(rows) < 4:
        return rows
    mids = sorted(
        (int(r.salary_min_net) + int(r.salary_max_net or r.salary_min_net)) / 2
        for r in rows
        if r.salary_min_net
    )
    if len(mids) < 4:
        return rows
    q1 = mids[len(mids) // 4]
    q3 = mids[(len(mids) * 3) // 4]
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    kept = [
        r
        for r in rows
        if r.salary_min_net
        and lo <= (int(r.salary_min_net) + int(r.salary_max_net or r.salary_min_net)) / 2 <= hi
    ]
    return kept or rows


def compute_segment_prior(
    samples: list[CalibSample],
    company_type: str,
    grade: str,
    *,
    min_n: int = MIN_SEGMENT_SAMPLES,
) -> SalaryPrior | None:
    """Медианный net-приор для (company_type, grade) из наблюдений. None — мало точек/off-target.

    Сначала пытаемся по точному типу компании; если в нём < min_n — расширяем до всех компаний
    того же грейда (widened=True). Дедуп + фильтр выбросов переиспользуем из отчёта калибровки.
    """
    bucket = grade if grade in _PRIOR_BUCKETS else None
    if bucket is None:
        return None

    pool = filter_outliers(dedupe_samples([s for s in samples if s.salary_min_net]))
    ct = (company_type or "unknown").strip() or "unknown"

    rows = _segment_rows(pool, ct, bucket)
    widened = False
    if len(rows) < min_n and ct != "unknown":
        wide = _segment_rows(pool, "unknown", bucket)
        if len(wide) > len(rows):
            rows, widened = wide, True

    rows = _iqr_trim(rows)
    if len(rows) < min_n:
        return None

    mins = [int(r.salary_min_net) for r in rows if r.salary_min_net]
    maxs = [int(r.salary_max_net or r.salary_min_net) for r in rows if r.salary_min_net]
    lo, hi = _median_int(mins), _median_int(maxs)
    if lo is None or hi is None:
        return None
    if hi < lo:
        lo, hi = hi, lo
    return SalaryPrior(
        company_type=ct,
        grade=grade,
        n=len(rows),
        median_min_net=lo,
        median_max_net=hi,
        widened=widened,
    )
