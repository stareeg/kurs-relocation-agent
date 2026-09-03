"""Рыночные срезы под фокус владельца: зарплата, реальная удалёнка, спрос на стек,
пересечение жёстких гейтов, типы компаний.

Отвечает на «что предлагает рынок» (slices). Динамика отклика резюме (показы/просмотры/
приглашения во времени) живёт отдельным эндпоинтом `/api/resume-stats` и сшивается на фронте.

Чистый `compute_market_slices` над списком словарей (тестируется без БД) — переиспользуется
`pulse.py` («Пульс поиска»).
"""

from __future__ import annotations

from collections import Counter
from statistics import median

from pydantic import BaseModel, Field

from core.domains.market.relevance import _score_of
from core.domains.profile.profile import GRADE_SCALE
from core.kernel.money import gross_to_net

# Корзина (lo, hi inclusive, label). Строится от profile.salary_min — без owner-хардкода.


def _fmt_band_k(amount: int) -> str:
    """Число тысяч без суффикса: 175_000 → «175»."""
    return str(int(round(amount / 1000)))


def salary_bands_net(salary_min: int) -> tuple[tuple[int, int, str], ...] | None:
    """Зарплатные бэнды относительно целевого минимума.

    Корзины: <0.7×, 0.7–1.0×, 1.0–1.4×, >1.4×. None — зарплата в профиле не задана.
    Подписи: «до 175к», «175-250к», «250-350к», «350к+».
    """
    if salary_min <= 0:
        return None
    t07 = max(1, int(round(salary_min * 0.7)))
    t10 = salary_min
    t14 = max(t10 + 1, int(round(salary_min * 1.4)))
    return (
        (0, max(0, t07 - 1), f"до {_fmt_band_k(t07)}к"),
        (t07, max(t07, t10 - 1), f"{_fmt_band_k(t07)}-{_fmt_band_k(t10)}к"),
        (t10, t14, f"{_fmt_band_k(t10)}-{_fmt_band_k(t14)}к"),
        (t14 + 1, 10**9, f"{_fmt_band_k(t14)}к+"),
    )


# Реальность формата (RemoteFeasibility.verdict) → RU-метка, порядок «реальный → вряд ли».
_REMOTE_VERDICTS: tuple[tuple[str, str], ...] = (
    ("real", "Реальный формат"),
    ("conditional", "Условная"),
    ("unlikely", "Вряд ли"),
)

# Типы компаний (ScoreResult.company_type) → RU-метка.
_COMPANY_TYPES: tuple[tuple[str, str], ...] = (
    ("product", "Продукт"),
    ("fintech_product", "Финтех-продукт"),
    ("bank", "Банк"),
    ("startup", "Стартап"),
    ("infra", "Инфра"),
    ("outsource", "Аутсорс"),
    ("agency", "Агентство"),
    ("media", "Медиа"),
    ("retail", "Ритейл"),
    ("manufacturing", "Производство"),
    ("education", "Образование"),
    ("government", "Госсектор"),
    ("nonprofit", "НКО"),
    ("smb", "МСБ"),
    ("unknown", "Не определено"),
)

# Сколько топ-ниш стека показывать (matched_niche). Хвост сворачиваем, чтобы не было свалки.
_TOP_NICHES = 8

# Абсолютная лестница грейда вакансии (канон SearchProfile.GRADE_SCALE) — не относительный
# fit (above/match/slightly_below). График «Грейд» в блоке «Условия» показывает Junior /
# Middle / Senior / Lead / C-level.
_GRADE_LEVELS: tuple[tuple[str, str], ...] = tuple((name, name) for name in GRADE_SCALE)

# Алиасы в reasoning модели → канон лестницы. Длинные ключи раньше коротких.
_GRADE_ALIASES: tuple[tuple[str, str], ...] = (
    ("c-level", "C-level"),
    ("c level", "C-level"),
    ("clevel", "C-level"),
    ("techlead", "Lead"),
    ("teamlead", "Lead"),
    ("tech lead", "Lead"),
    ("team lead", "Lead"),
    ("lead", "Lead"),
    ("senior", "Senior"),
    ("middle", "Middle"),
    ("mid", "Middle"),
    ("junior", "Junior"),
)


class MarketBucket(BaseModel):
    """Универсальная корзина рыночного среза: метка + количество + доля внутри среза (0..100)."""

    label: str
    count: int
    pct: float = 0.0


class GateFunnel(BaseModel):
    """Сужение supply жёсткими гейтами владельца (зарплата + реальная удалёнка).

    `total` — заскоренных вакансий; `meets_salary` — дотягивают до целевой; `real_remote` —
    удалёнка реальна (verdict=real); `both` — пересечение, настоящий адресуемый рынок. Удалёнка
    меряется только там, где посчитан под-скор (`measured_remote`) — иначе verdict неизвестен и в
    `real_remote`/`both` вакансия честно не зачитывается.
    """

    total: int = 0
    measured_remote: int = 0
    meets_salary: int = 0
    real_remote: int = 0
    both: int = 0


class MarketSlices(BaseModel):
    """Рыночные срезы под топ-4 критерия владельца. `measured` — заскоренных вакансий."""

    available: bool = Field(
        default=False, description="Есть заскоренные вакансии. False → секции пустые"
    )
    measured: int = 0
    # Зарплата
    salary_measured: int = 0  # вакансий с читаемой оценкой вилки
    salary_meets_min: int = 0
    salary_meets_min_pct: float = 0.0
    salary_median_net: int | None = None
    salary_bands: list[MarketBucket] = Field(default_factory=list)
    salary_bands_available: bool = Field(
        default=True,
        description="False — в резюме нет salary_min, корзины не нормированы (одна «все»)",
    )
    # Удалёнка / стек / компании
    remote_verdicts: list[MarketBucket] = Field(default_factory=list)
    stack_niches: list[MarketBucket] = Field(default_factory=list)
    company_types: list[MarketBucket] = Field(default_factory=list)
    # Относительный грейд вакансии к профилю кандидата (2026-08-11, «Форматы работы»
    # совмещённая визуализация Формат/Грейд/Роль).
    grade_levels: list[MarketBucket] = Field(default_factory=list)
    # Жёсткие гейты
    gates: GateFunnel = Field(default_factory=GateFunnel)


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _salary_net_mid(salary: dict) -> int | None:
    """Net-середина оценочной вилки: gross estimated_min/max → net (gross_to_net). None — нет оценки."""
    lo = salary.get("estimated_min")
    hi = salary.get("estimated_max")
    vals = [v for v in (lo, hi) if isinstance(v, (int, float)) and v > 0]
    if not vals:
        return None
    mid_gross = int(sum(vals) / len(vals))
    return gross_to_net(mid_gross)


def _band_label_net(net: int, bands: tuple[tuple[int, int, str], ...]) -> str | None:
    for lo, hi, label in bands:
        if lo <= net <= hi:
            return label
    return None


def _grade_from_text(text: str) -> str | None:
    """Достать канон лестницы из reasoning модели, если там явно назван грейд вакансии."""
    folded = text.casefold()
    if not folded:
        return None
    normalized = "".join(ch if ch.isalnum() or ch in "- " else " " for ch in folded)
    padded = f" {normalized} "
    for alias, canon in _GRADE_ALIASES:
        if f" {alias} " in padded:
            return canon
    return None


def _vacancy_grade_key(
    sd: dict,
    *,
    grade_floor: int,
    grade_ceil: int,
) -> str | None:
    """Абсолютный грейд вакансии: сначала reasoning, иначе реконструкция от цели кандидата.

    `grade_match.level` — относительный fit, не лестница. Без цели (floor < 0) и без
    названия в reasoning корзину не ставим — честнее пустой столбец, чем «Точно»=Senior
    для Junior-кандидата.
    """
    gm = sd.get("grade_match")
    if not isinstance(gm, dict):
        return None
    named = _grade_from_text(str(gm.get("reasoning") or ""))
    if named:
        return named
    level = gm.get("level")
    if not isinstance(level, str) or grade_floor < 0:
        return None
    n = len(GRADE_SCALE)
    ceil = grade_ceil if grade_ceil >= 0 else grade_floor
    if level == "match":
        return GRADE_SCALE[(grade_floor + ceil) // 2]
    if level == "slightly_below":
        return GRADE_SCALE[max(0, grade_floor - 1)]
    if level == "far_below":
        return GRADE_SCALE[max(0, grade_floor - 2)]
    if level == "above":
        return GRADE_SCALE[min(n - 1, ceil + 1)]
    return None


def _ordered_buckets(
    counter: Counter[str], order: tuple[tuple[str, str], ...], total: int
) -> list[MarketBucket]:
    """Корзины в заданном порядке (только присутствующие), доля от total внутри среза."""
    out: list[MarketBucket] = []
    for key, label in order:
        c = counter.get(key, 0)
        if c:
            out.append(MarketBucket(label=label, count=c, pct=round(100 * c / total, 1)))
    return out


def compute_market_slices(
    rows: list[tuple[dict, dict | None, dict | None]],
    *,
    salary_min: int = 0,
    grade_floor: int = -1,
    grade_ceil: int = -1,
) -> MarketSlices:
    """Рыночные срезы из (score-jsonb, salary-jsonb, remote_feasibility-jsonb). Чистый — без БД.

    Заскоренной считаем вакансию с читаемым `overall_score` (стаб `{}` отбрасываем). Зарплату
    берём из денорм-колонки `salary`, с фолбэком на `score["salary"]`; удалёнку — из
    `remote_feasibility` (отдельная колонка, у старых вакансий пусто).

    `salary_min` — якорь корзин из SearchProfile; без него срез зарплаты помечаем
    `salary_bands_available=False` и отдаём одну корзину «все».

    `grade_floor`/`grade_ceil` — индексы целевых грейдов кандидата на GRADE_SCALE (−1 = нет
    цели). Нужны, чтобы перевести относительный `grade_match.level` в Junior/Middle/…
    """
    scored: list[tuple[dict, dict, dict]] = []
    for score_raw, salary_raw, remote_raw in rows:
        sd = _as_dict(score_raw)
        if _score_of(None, sd) is None:
            continue  # стаб без скоринга в срезы не идёт
        salary = _as_dict(salary_raw) or _as_dict(sd.get("salary"))
        remote = _as_dict(remote_raw)
        scored.append((sd, salary, remote))

    n = len(scored)
    if n == 0:
        return MarketSlices(available=False)

    bands = salary_bands_net(salary_min)
    bands_available = bands is not None

    # --- Зарплата ---
    band_counts: Counter[str] = Counter()
    net_mids: list[int] = []
    salary_measured = 0
    salary_meets = 0
    for _, salary, _ in scored:
        if isinstance(salary.get("meets_min"), bool):
            salary_measured += 1
            if salary["meets_min"]:
                salary_meets += 1
        net = _salary_net_mid(salary)
        if net is not None:
            net_mids.append(net)
            if bands is not None:
                label = _band_label_net(net, bands)
                if label:
                    band_counts[label] += 1
    band_total = sum(band_counts.values())
    if bands is None:
        # Зарплата в профиле не задана — одна корзина «все», срез недоступен для нормировки.
        all_count = len(net_mids) if net_mids else n
        salary_bands = [MarketBucket(label="все", count=all_count, pct=100.0)]
    else:
        salary_bands = [
            MarketBucket(
                label=label,
                count=band_counts[label],
                pct=round(100 * band_counts[label] / band_total, 1) if band_total else 0.0,
            )
            for _, _, label in bands
            if band_counts.get(label)
        ]

    # --- Удалёнка / стек / компании / грейд ---
    remote_counter: Counter[str] = Counter()
    niche_counter: Counter[str] = Counter()
    company_counter: Counter[str] = Counter()
    grade_counter: Counter[str] = Counter()
    real_remote = 0
    measured_remote = 0
    for sd, _, remote in scored:
        verdict = remote.get("verdict")
        if isinstance(verdict, str) and verdict:
            measured_remote += 1
            remote_counter[verdict] += 1
            if verdict == "real":
                real_remote += 1
        rc = sd.get("role_content_match")
        if isinstance(rc, dict):
            for niche in rc.get("matched_niche") or []:
                tag = str(niche).strip()
                if tag:
                    niche_counter[tag] += 1
        ctype = sd.get("company_type")
        if isinstance(ctype, str) and ctype:
            company_counter[ctype] += 1
        gm = sd.get("grade_match")
        if isinstance(gm, dict):
            key = _vacancy_grade_key(sd, grade_floor=grade_floor, grade_ceil=grade_ceil)
            if key:
                grade_counter[key] += 1

    remote_verdicts = _ordered_buckets(remote_counter, _REMOTE_VERDICTS, measured_remote or 1)
    company_types = _ordered_buckets(company_counter, _COMPANY_TYPES, n)
    grade_levels = _ordered_buckets(grade_counter, _GRADE_LEVELS, sum(grade_counter.values()) or 1)
    niche_total = sum(niche_counter.values()) or 1
    stack_niches = [
        MarketBucket(label=tag, count=c, pct=round(100 * c / niche_total, 1))
        for tag, c in niche_counter.most_common(_TOP_NICHES)
    ]

    # --- Жёсткие гейты (пересечение зарплата ∧ реальная удалёнка) ---
    both = 0
    for _, salary, remote in scored:
        if salary.get("meets_min") is True and remote.get("verdict") == "real":
            both += 1
    gates = GateFunnel(
        total=n,
        measured_remote=measured_remote,
        meets_salary=salary_meets,
        real_remote=real_remote,
        both=both,
    )

    meets_min_pct = round(100 * salary_meets / salary_measured, 1) if salary_measured else 0.0
    return MarketSlices(
        available=True,
        measured=n,
        salary_measured=salary_measured,
        salary_meets_min=salary_meets,
        salary_meets_min_pct=meets_min_pct,
        salary_median_net=int(median(net_mids)) if net_mids else None,
        salary_bands=salary_bands,
        salary_bands_available=bands_available,
        remote_verdicts=remote_verdicts,
        stack_niches=stack_niches,
        company_types=company_types,
        grade_levels=grade_levels,
        gates=gates,
    )
