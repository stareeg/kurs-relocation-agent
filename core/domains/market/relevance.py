"""Релевантность вакансий / качество потока. Адаптивность поиска без AI-slop.

Два независимых среза (не смешивать — см. задачу JS-7.1):

Срез A — качество потока (supply diagnostic, без LLM, работает с 1-го дня): распределение
`overall_score` по корзинам + доли по `recommendation` + разбивка «что чаще всего убивает
вакансию» по топ-4 критериям отбора (зарплата/формат/грейд/стек) + недельный тренд по
`scored_at`. Отвечает на «насколько годные вакансии вообще попадаются». ВАЖНО: срез A меряет в
первую очередь качество hh-фильтров владельца + selection bias (видим только открытое), а НЕ
«плохую модель» — формулировки в UI не должны винить скоринг.

Срез B — калибровка (предиктивная валидность): корзина `overall_score` × конверсия в «Скрининг+»
(HR ответил). Монотонный рост по корзинам = скоринг калиброван, плоско = врёт (крутить рубрику).
Под тем же гейтом `enough_data`, что воронка (`funnel.py`): мало данных → честная плашка, выводов
на трёх точках не делаем.

Чистые `compute_*` над списками (тестируются без БД); переиспользуются `market.py` (срезы
«Рынка») и `pulse.py` (пульс поиска). Загрузчик среза B и HTTP — в `service.get_calibration_report`
/ `GET /api/analytics/calibration`; здесь только расчёт.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from core.domains.profile.profile import SearchProfile
from core.kernel.schemas.funnel import funnel_stage_number

# Корзины overall_score (high→low для показа). Общие для среза A (гистограмма) и B (калибровка).
SCORE_BANDS: tuple[tuple[int, int, str], ...] = (
    (80, 100, "80–100"),
    (60, 79, "60–79"),
    (40, 59, "40–59"),
    (0, 39, "0–39"),
)

# role_content_match.score ниже этого = «роль/домен далёкий» (kill-фактор содержания роли).
_ROLE_FIT_KILL = 50

_KILL_ORDER: tuple[str, ...] = ("salary", "remote", "grade", "stack")

# Порядок рекомендаций (сильный → пропустить); незнакомые ключи в хвост.
_REC_ORDER: tuple[str, ...] = ("strong_apply", "apply", "maybe", "skip")

# Порог «данных достаточно для калибровки» — тот же, что воронка (funnel._MIN_APPLIED). Держим
# свою копию, чтобы compute оставался чистым/тестируемым без зависимости на funnel.
_MIN_APPLIED = 10

# Скор «хита» для недельного тренда (зелёная вакансия).
_HIT_SCORE = 70


# --- Срез A: качество потока ---


class ScoreBand(BaseModel):
    """Корзина балла фита: сколько заскоренных вакансий попало в диапазон."""

    label: str
    score_min: int
    score_max: int
    count: int = 0


class RecShare(BaseModel):
    """Доля по рекомендации скорера (strong_apply/apply/maybe/skip/unknown)."""

    recommendation: str
    count: int


class KillFactor(BaseModel):
    """Один из топ-4 критериев как «убийца»: сколько вакансий по нему отсеялось."""

    key: str
    label: str
    count: int
    pct: float = Field(description="Доля заскоренных вакансий, 0..100")


class TrendPoint(BaseModel):
    """Недельный срез потока (по scored_at): объём, хиты, средний балл."""

    period: str  # ISO-дата понедельника недели
    count: int
    hits: int  # score >= 70
    avg_score: float


class SupplyReport(BaseModel):
    available: bool = Field(
        default=False, description="Есть заскоренные вакансии (PG поднят). False → панель пустая"
    )
    total_scored: int = 0
    avg_score: float = 0.0
    bands: list[ScoreBand] = Field(default_factory=list)
    recommendations: list[RecShare] = Field(default_factory=list)
    kill_factors: list[KillFactor] = Field(default_factory=list)  # спрос убыв.
    over_time: list[TrendPoint] = Field(default_factory=list)  # по возрастанию недель


# --- Срез B: калибровка скоринга ---


class CalibrationBand(BaseModel):
    """Корзина балла × конверсия: дошло до отклика/скрининга, доля ответов."""

    label: str
    score_min: int
    score_max: int
    total: int = 0
    applied: int = 0  # дошли до «Отклик» (база конверсии)
    responded: int = 0  # дошли до «Скрининг+» (HR ответил)
    conversion_rate: float | None = None  # responded / applied


class CalibrationReport(BaseModel):
    available: bool = Field(
        default=False,
        description="Есть заскоренные вакансии с воронкой. False → нечего калибровать",  # noqa: E501
    )
    enough_data: bool = Field(
        default=False, description="Хватает воронки для выводов о калибровке (как funnel)"
    )
    applied: int = 0
    responded: int = 0
    offers: int = 0
    bands: list[CalibrationBand] = Field(default_factory=list)
    note: str | None = None  # RU-плашка, когда данных мало


def _ratio(num: int, denom: int) -> float | None:
    return round(num / denom, 4) if denom else None


def _band_for(score: int) -> tuple[int, int, str] | None:
    for lo, hi, label in SCORE_BANDS:
        if lo <= score <= hi:
            return lo, hi, label
    return None


def _fmt_salary_short(amount: int) -> str:
    """Короткая подпись суммы: 250_000 → «250к»."""
    if amount <= 0:
        return ""
    if amount >= 1000:
        return f"{int(round(amount / 1000))}к"
    return str(amount)


def kill_labels(profile: SearchProfile | None = None) -> dict[str, str]:
    """Подписи kill-факторов из профиля поиска (без зашитых сумм и грейдов владельца)."""
    if profile is not None and profile.salary_min > 0:
        salary = f"Зарплата ниже {_fmt_salary_short(profile.salary_min)}"
    else:
        salary = "Зарплата ниже целевой"

    formats: list[str] = []
    if profile is not None:
        if profile.allows_remote:
            formats.append("удалённый")
        if profile.allows_hybrid:
            formats.append("гибрид")
        if profile.allows_office:
            formats.append("офис")
    remote = f"Формат не подходит: нужен {' / '.join(formats)}" if formats else "Формат не подходит"

    return {
        "salary": salary,
        "remote": remote,
        "grade": "Грейд не тот",
        "stack": "Роль не по профилю",
    }


def _score_of(overall: int | None, score_dict: dict) -> int | None:
    """Балл вакансии: денормализованный `overall_score` → из jsonb. None = вакансия не заскорена."""
    if overall is not None:
        return int(overall)
    raw = score_dict.get("overall_score")
    return int(raw) if isinstance(raw, (int, float)) else None


def _kill_flags(score_dict: dict) -> dict[str, bool]:
    """По каким из топ-4 критериев вакансия отсеивается. Ключ есть только если измерение читаемо."""
    flags: dict[str, bool] = {}
    salary = score_dict.get("salary")
    if isinstance(salary, dict) and "meets_min" in salary:
        flags["salary"] = salary.get("meets_min") is False
    remote = score_dict.get("remote_abroad_compat")
    if isinstance(remote, dict) and remote.get("level"):
        flags["remote"] = remote.get("level") in {"risky", "blocker"}
    grade = score_dict.get("grade_match")
    if isinstance(grade, dict) and grade.get("level"):
        # Новая относительная шкала: match/above = ок; остальное (и legacy senior_plus) - kill.
        flags["grade"] = grade.get("level") not in ("match", "above")
    role = score_dict.get("role_content_match")
    if isinstance(role, dict) and isinstance(role.get("score"), (int, float)):
        flags["stack"] = role["score"] < _ROLE_FIT_KILL
    return flags


def _ordered_recs(counter: Counter[str]) -> list[tuple[str, int]]:
    known = [(r, counter[r]) for r in _REC_ORDER if r in counter]
    rest = sorted(
        ((r, c) for r, c in counter.items() if r not in _REC_ORDER),
        key=lambda kv: kv[1],
        reverse=True,
    )
    return known + rest


def _weekly_trend(scored: list[tuple[int, datetime]]) -> list[TrendPoint]:
    """Сгруппировать баллы по неделям (понедельник) для тренда качества потока."""
    weeks: dict[datetime, list[int]] = {}
    for score, at in scored:
        day = at.date()
        monday = datetime(day.year, day.month, day.day) - timedelta(days=day.weekday())
        weeks.setdefault(monday, []).append(score)
    points: list[TrendPoint] = []
    for monday in sorted(weeks):
        scores = weeks[monday]
        points.append(
            TrendPoint(
                period=monday.date().isoformat(),
                count=len(scores),
                hits=sum(1 for s in scores if s >= _HIT_SCORE),
                avg_score=round(sum(scores) / len(scores), 1),
            )
        )
    return points


def compute_supply_report(
    rows: list[tuple[int | None, dict, datetime | None]],
    *,
    profile: SearchProfile | None = None,
) -> SupplyReport:
    """Срез A из (overall_score, score-jsonb, scored_at). Чистый — тестируется без БД.

    Заскоренной считаем вакансию с читаемым баллом; стаб-вакансии (`{}`) в диагностику не идут.
    """
    labels = kill_labels(profile)
    scored: list[tuple[int, dict]] = []
    scored_at: list[tuple[int, datetime]] = []
    for overall, raw, at in rows:
        sd = raw if isinstance(raw, dict) else {}
        score = _score_of(overall, sd)
        if score is None:
            continue
        scored.append((score, sd))
        if at is not None:
            scored_at.append((score, at))

    n = len(scored)
    if n == 0:
        return SupplyReport(available=False)

    band_counts = {label: 0 for _, _, label in SCORE_BANDS}
    rec_counter: Counter[str] = Counter()
    kill_hit: Counter[str] = Counter()
    for score, sd in scored:
        band = _band_for(score)
        if band:
            band_counts[band[2]] += 1
        rec = sd.get("recommendation")
        rec_counter[rec if isinstance(rec, str) and rec else "unknown"] += 1
        for key, killed in _kill_flags(sd).items():
            if killed:
                kill_hit[key] += 1

    bands = [
        ScoreBand(label=label, score_min=lo, score_max=hi, count=band_counts[label])
        for lo, hi, label in SCORE_BANDS
    ]
    recommendations = [RecShare(recommendation=r, count=c) for r, c in _ordered_recs(rec_counter)]
    kill_factors = sorted(
        (
            KillFactor(
                key=key,
                label=labels[key],
                count=kill_hit[key],
                pct=round(100 * kill_hit[key] / n, 1),
            )
            for key in _KILL_ORDER
            if kill_hit.get(key)
        ),
        key=lambda k: k.count,
        reverse=True,
    )

    return SupplyReport(
        available=True,
        total_scored=n,
        avg_score=round(sum(s for s, _ in scored) / n, 1),
        bands=bands,
        recommendations=recommendations,
        kill_factors=kill_factors,
        over_time=_weekly_trend(scored_at),
    )


def compute_gate_breakdown(
    rows: list[tuple[int | None, dict]],
    *,
    profile: SearchProfile | None = None,
) -> list[KillFactor]:
    """Взаимоисключающая версия `kill_factors` для одной полосы «Что режет поток» (план
    market_redesign_v3, S-04): каждая заскоренная вакансия попадает ровно в один сегмент — первый
    сработавший критерий по приоритету зарплата → формат → грейд → роль, иначе «прошли». `kill_factors`
    для сегментов одной полосы не годится: вакансия, упавшая по двум критериям сразу, считается там
    в обоих, и сумма сегментов превысила бы базу (см. докстринг `SupplyReport.kill_factors`).
    """
    labels = kill_labels(profile)
    scored = [(overall, raw if isinstance(raw, dict) else {}) for overall, raw in rows]
    scored = [(o, sd) for o, sd in scored if _score_of(o, sd) is not None]
    n = len(scored)
    if n == 0:
        return []

    bucket: Counter[str] = Counter()
    for _, sd in scored:
        flags = _kill_flags(sd)
        hit = next((key for key in _KILL_ORDER if flags.get(key)), None)
        bucket[hit or "passed"] += 1

    def _seg(key: str, label: str) -> KillFactor:
        count = bucket.get(key, 0)
        return KillFactor(key=key, label=label, count=count, pct=round(100 * count / n, 1))

    segments = [_seg("passed", "Прошли оба гейта")]
    segments += [_seg(key, labels[key]) for key in _KILL_ORDER]
    return [s for s in segments if s.count > 0]


def compute_calibration_report(rows: list[tuple[int, int]]) -> CalibrationReport:
    """Срез B из (score, furthest_stage). Чистый — тестируется без БД.

    `furthest_stage` — самая дальняя восходящая ступень воронки (1..6; см. `_furthest`). База
    конверсии — дошедшие до «Отклик» (>=2); ответ HR = «Скрининг+» (>=3).
    """
    if not rows:
        return CalibrationReport(available=False)

    applied = sum(1 for _, f in rows if f >= 2)
    responded = sum(1 for _, f in rows if f >= 3)
    offers = sum(1 for _, f in rows if f >= 6)
    enough = applied >= _MIN_APPLIED and (responded >= 3 or offers >= 1)

    acc = {label: {"total": 0, "applied": 0, "responded": 0} for _, _, label in SCORE_BANDS}
    for score, furthest in rows:
        band = _band_for(score)
        if not band:
            continue
        cell = acc[band[2]]
        cell["total"] += 1
        if furthest >= 2:
            cell["applied"] += 1
        if furthest >= 3:
            cell["responded"] += 1

    bands = [
        CalibrationBand(
            label=label,
            score_min=lo,
            score_max=hi,
            total=acc[label]["total"],
            applied=acc[label]["applied"],
            responded=acc[label]["responded"],
            conversion_rate=_ratio(acc[label]["responded"], acc[label]["applied"]),
        )
        for lo, hi, label in SCORE_BANDS
    ]

    note: str | None = None
    if not enough:
        note = (
            f"Калибровку скоринга включим, когда наберётся воронка: пока {applied} откл., "
            f"{responded} ответ., {offers} офф. Выводы на трёх точках не делаем."
        )

    return CalibrationReport(
        available=True,
        enough_data=enough,
        applied=applied,
        responded=responded,
        offers=offers,
        bands=bands,
        note=note,
    )


def _furthest(statuses: list[str | None]) -> int:
    """Самая дальняя восходящая ступень из набора статусов (зеркало funnel._furthest_stage).

    Любая запись в `jobs` = минимум «Просмотр» (база 1); «Отказ»/«Архив» (stage 0) не двигают
    шкалу — отклонённая после скрининга всё равно числится дошедшей до «Скрининг».
    """
    nums = [1]
    for s in statuses:
        n = funnel_stage_number(s)
        if isinstance(n, int) and n > 0:
            nums.append(n)
    return max(nums)
