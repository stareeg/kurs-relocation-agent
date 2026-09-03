"""Пульс поиска: единый показатель «Шанс офферов» + headline-KPI с суточной динамикой.

Под вкладку «Рынок». Отвечает на «как я иду» одним числом 0..100 (`offer_chance`) плюс набором
ключевых KPI, у каждого — дельта за сутки (динамика день-ко-дню). Динамика честная: не храним
снимки в отдельной таблице, а реконструируем состояние «сутки назад» фильтром существующих строк
по их временным меткам (`created_at`/`scored_at`/`changed_at`) и прогоняем те же чистые
`compute_*`-функции на подмножестве. Дельта = сейчас − (сутки назад).

`compute_offer_chance` — чистая функция над нормализованным входом (тестируется без БД);
`get_market_pulse` тянет PG (jobs + application_stages + offers + resume_stats) и собирает оба
среза (сейчас и сутки назад). Best-effort: нет PG / нет заскоренных вакансий → `available=false`.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from core.domains.market.market import (
    GateFunnel,
    MarketBucket,
    MarketSlices,
    compute_market_slices,
)
from core.domains.market.relevance import (
    KillFactor,
    SupplyReport,
    _fmt_salary_short,
    _score_of,
    compute_gate_breakdown,
    compute_supply_report,
)
from core.domains.offers.models import OfferConfidence, offer_confidence
from core.domains.pipeline.analytics import FunnelAnalytics, compute_funnel_analytics
from core.domains.profile.profile import SearchProfile
from core.domains.profile.resume_stats import GETMATCH_PROFILE_RESUME_ID
from core.kernel.schemas.funnel import FunnelStatus, funnel_stage_number, resolve_funnel_status
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

# Окно динамики: «сутки назад» = базовая точка для дельт всех KPI и композита (день-ко-дню).
PULSE_WINDOW_DAYS = 1

# --- Якоря нормализации композита ---
# Пересобрано 2026-08-09: раньше якоря были зашиты под одного кандидата (senior IC → удалёнка),
# что нарушало no-owner-hardcode правило и давало кривой скор для PM/junior/не-удалёнщика.
# Теперь это либеральные общие ориентиры, не привязанные к конкретному профилю:
#   * response_rate 0.20 — умеренный темп ответов HR (в ниже – выше насыщается плавно);
#   * gate_share 0.25 — четверть потока проходит оба жёстких гейта = насыщенный рынок;
#   * depth/invitations/views/new_30d/scored_7d — мягкие насыщающиеся якоря (log1p/линейные),
#     не «достиг X = 100%»: композит нарастает плавно, не прыгает на одном отклике.
# Принципиально: «100» = явно сильная позиция, не недостижимый идеал и не копия профиля владельца.
RESPONSE_RATE_TARGET = (
    0.20  # доля ответов HR = сильный темп (было 0.30 — занижало для всех не-senior)
)
GATE_SHARE_TARGET = 0.25  # доля потока через оба гейта = насыщенный рынок
# Градиентные сигналы насыщаются логарифмически — один скрининг ≠ 50 скринингов (правка 2026-08-09).
# log1p(x)/log1p(target) даёт 1.0 в точке target и продолжает расти дальше, плавно замедляясь.
DEPTH_TARGET = 12  # параллельных активных процессов — log1p-якорь
# Правка 2026-08-11 (жалоба «слишком оптимистично на старте»): отклик hh (invitations/views —
# пассивный сигнал показов резюме) заменён на «Отклики» — собственную активность заявок в
# выбранном периоде (см. `applied`, теперь период-скоуп через `_build_bundle(period_start=…)`).
# 20 откликов за период — активный темп, не «нашёл минимум данных» (тот порог — `_MIN_APPLIED`).
APPLICATIONS_TARGET = 20  # log1p-якорь
NEW_30D_TARGET = 25  # новых вакансий за 30д — log1p-якорь
SCORED_7D_TARGET = 12  # заскорено за 7д — log1p-якорь
# avg_score и resume_quality — линейные якори 40..80 (слабо → сильно), без owner-привязки.
FIT_FLOOR = 40.0
FIT_CEIL = 80.0
# Правка 2026-08-14: якоря качества резюме 0..100 (не 40..80). Раньше суб-балл насыщался на 80,
# и балл резюме 92+ рисовал столбец «Резюме» в «Шансе офферов» заполненным на 100 («макс») —
# визуально неотличимо от 80, хотя реальный балл выше. Теперь высота столбца = реальному баллу
# резюме напрямую (38 → 0.38, 92 → 0.92), вклад фактора в композит тоже честнее.
RESUME_QUALITY_FLOOR = 0.0
RESUME_QUALITY_CEIL = 100.0

# Confidence-мультипликаторы «Оффера» (§1.1 offer_chance_rework_2026_08_11): устный пре-оффер
# (дошёл до FunnelStatus.OFFER, ничего бумажного) — всё ещё сильный сигнал, просто не
# максимальный; письменный (OfferRecord с raw_text) — почти макс; подписанный (accepted) — макс.
_OFFER_CONFIDENCE_MULT: dict[OfferConfidence, float] = {
    "verbal": 0.5,
    "written": 0.85,
    "signed": 1.0,
}
_offer_stage_num = funnel_stage_number(FunnelStatus.OFFER)
assert isinstance(_offer_stage_num, int)  # FunnelStatus.OFFER всегда резолвится в номер ступени
_OFFER_STAGE_NUM: int = _offer_stage_num

# Техготовность (§1.2 offer_chance_rework_2026_08_11, Шаг 3): очки по свежему per-topic уровню
# из `competency_ledger` (confident/medium/weak, копится от собеса к собесу) + насыщение по
# охвату тем — одна тема на confident не даёт 100% фактора, но и не проваливает в ноль.
LEVEL_POINTS: dict[str, float] = {"confident": 100.0, "medium": 55.0, "weak": 15.0}
TOPIC_SATURATION_TARGET = 6  # log1p-якорь: одна тема ≠ шесть тем

# Правка 2026-08-14: «Отклики» теперь учитывают ДИНАМИКУ. Темп (откликов в день) насыщается
# логарифмически — 1 отклик/день уже активный темп (не «100% фактор»), плавно растёт дальше.
# Регулярность = доля активных дней от длины периода; бонус за «откликаюсь каждый день», а не
# «20 откликов в один день и тишина».
APPLICATIONS_DAILY_TARGET = 2.0  # откликов/день — log1p-якорь темпа (2/день = насыщенный поток)
APPLICATIONS_REGULARITY_WEIGHT = 0.4  # доля регулярности в суб-балле «Отклики» (0.6 — темп)

# Правка 2026-08-14: «Общение» теперь — скорость движения процессов в Чатах, не поток новых
# вакансий. `chat_progressing / chat_active` — доля двигающихся тредов; штраф за зависшие
# (`chat_stalled / chat_active`). Порог «завис» — отдельная константа, не owner-hardcode.
CHAT_STALL_DAYS = 10  # дней без ответа кандидата или без смены этапа = «завис»
CHAT_PROGRESS_WEIGHT = 0.7  # доля «двигаются» в суб-балле; 0.3 — анти-штраф за зависшие

# Минимальный порог данных воронки: меньше — композит помечается preliminary (фронт рисует
# пунктир, не уверенное число) И дополнительно демпфируется (см. `_DAMPING_FLOOR`) — раньше
# preliminary был только косметическим пунктиром, а число всё равно читалось уверенно (жалоба
# «1-2 скрининга и техничка, а шанс уже 66» — тонкая воронка не должна звучать как зрелая).
# Совпадает с `_MIN_APPLIED` в relevance.py и funnel._MIN_APPLIED.
_MIN_APPLIED = 10

# Демпфер итогового балла при applied < _MIN_APPLIED: score *= max(_DAMPING_FLOOR, applied/_MIN_APPLIED).
# Пол 0.4 — не обнуляем совсем (рынок/резюме — реальный сигнал даже без откликов), но не даём
# тонкой воронке звучать как уверенные 60+.
_DAMPING_FLOOR = 0.4

# Веса факторов композита (сумма = 1.0). §1 offer_chance_rework_2026_08_11, Шаг 6: 7 факторов —
# добавлена Техготовность (competency_ledger, §1.2), вес воронки/рынка/резюме пересмотрен под неё
# (funnel 35→25, resume_quality 25→15, market — без изменений 15), «Отклики»/«Активность» слегка
# урезаны (10→8 / 10→7) в пользу нового фактора. Порядок кортежа = порядок столбцов гистограммы
# (§3 плана) — не по весу, семантический (воронка → техготовность → резюме → рынок → отклики →
# активность → глубина), чтобы столбцы не «прыгали» местами при динамическом сдвиге весов (§1.3).
_WEIGHTS: tuple[tuple[str, str, float], ...] = (
    ("funnel", "Воронка", 0.25),
    ("skill", "Скиллы", 0.25),
    ("resume_quality", "Качество резюме", 0.15),
    ("market", "Рынок под вас", 0.15),
    ("applications", "Отклики", 0.08),
    ("activity", "Активность", 0.07),
    # Правка 2026-08-14: «Портфель» → «Этапы» — точнее отражает суть (глубина воронки =
    # сколько параллельных живых этапов, не «портфель» в финансовом смысле).
    ("depth", "Этапы", 0.05),
)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _log_norm(x: float, target: float) -> float:
    """Насыщающаяся логарифмическая нормировка: 0 в нуле, ~1.0 в target, плавно растёт дальше.

    Один скрининг не даёт «100% фактор» (правка 2026-08-09) — log1p(x)/log1p(target) нарастает
    плавно и не прыгает на первом отклике, как старые бинарные offer_sig/interview_sig.
    """
    if target <= 0:
        return 0.0
    return _clamp(math.log1p(max(0.0, x)) / math.log1p(target))


# --- §1.3 offer_chance_rework_2026_08_11 (Шаг 4, подключено в Шаге 6): динамический сдвиг
# весов по стадии воронки. Пулы совпадают с таблицей весов §1 (funnel 25 / skill 25 /
# applications 8 / activity 7 из `_WEIGHTS`) — `_apply_progress_shift` остаётся отдельной чистой
# функцией над произвольным `base_weights` (тестируется таблицей входов/выходов без БД),
# `compute_offer_chance` вызывает её на пересчитанных в п.п. базовых весах перед has_data-
# перенормировкой (см. ниже).
_PROGRESS_SHIFT_MAX_PP = 8.0  # максимальный сдвиг на пике прогресса, п.п.
_VOLUME_POOL: dict[str, float] = {"applications": 8.0, "activity": 7.0}
_PROGRESS_POOL: dict[str, float] = {"funnel": 25.0, "skill": 25.0}
_VOLUME_POOL_SUM = sum(_VOLUME_POOL.values())  # 15
_PROGRESS_POOL_SUM = sum(_PROGRESS_POOL.values())  # 50


def _progress_level(
    *,
    reached_final: bool,
    weighted_offer_signal: float,
    interviewing: int,
    responded: int,
) -> float:
    """Ступень прогресса воронки → 0.0 / 0.33 / 0.66 / 1.0 (§1.3).

    Финал ИЛИ ненулевой offer-сигнал (`_weighted_offer_signal`, устный оффер уже считается) —
    максимум; иначе — по самой дальней фактически достигнутой стадии (Техничка → Скрининг →
    только Отклик).
    """
    if reached_final or weighted_offer_signal > 0:
        return 1.0
    if interviewing > 0:
        return 0.66
    if responded > 0:
        return 0.33
    return 0.0


def _apply_progress_shift(
    base_weights: dict[str, float], progress_level: float
) -> dict[str, float]:
    """Сдвинуть базовые веса по ступени прогресса воронки (§1.3).

    Объём (`applications`+`activity`, пул 15 п.п.) перетекает в прогресс (`funnel`+`skill`,
    пул 50 п.п.) — доля сдвига внутри каждого пула пропорциональна базовому весу ключа в этом
    пуле. Сумма весов сохраняется; `resume_quality`/`market`/`depth` не трогаются. Ключи, которых
    нет в `base_weights`, тихо пропускаются (позволяет тестировать урезанными таблицами).
    """
    shift = _clamp(progress_level) * _PROGRESS_SHIFT_MAX_PP
    weights = dict(base_weights)
    for key, pool_weight in _VOLUME_POOL.items():
        if key in weights:
            weights[key] -= shift * (pool_weight / _VOLUME_POOL_SUM)
    for key, pool_weight in _PROGRESS_POOL.items():
        if key in weights:
            weights[key] += shift * (pool_weight / _PROGRESS_POOL_SUM)
    return weights


@dataclass
class OfferChanceInput:
    """Нормализованный вход композита на один момент времени (сейчас ИЛИ неделю назад).

    `applied` — воронка «Отклики»/период-скоуп: когда вызывающий передаёт `period_start`/
    `period_end` в `_build_bundle`, это число уже ограничено выбранным периодом (см.
    `get_market_pulse`) — тот же `applied` кормит и `s_funnel`/`depth`, и новый фактор
    «Отклики» (`s_applications`), без отдельного поля.
    """

    # Воронка
    response_rate: float | None
    applied: int
    interviewing: int
    rejected: int
    # Σ confidence_mult(v) по уникальным вакансиям периода, дошедшим до `FunnelStatus.OFFER`
    # ИЛИ имеющим `OfferRecord` (дедуп по vacancy_id — не offers+offers_active по отдельности,
    # см. offer_confidence). Устный/письменный/подписанный оффер весят по-разному.
    weighted_offer_signal: float
    # Рынок под вас
    avg_score: float
    gate_both: int
    gate_total: int
    salary_meets_pct: float  # 0..100
    real_remote: int
    measured_remote: int
    # Качество резюме (детерминированный скор 0..100 из resume_score_history).
    # None = снимков ещё нет (bootstrap) — композит берёт нейтральный базис, не штраф.
    resume_quality_total: int | None = None
    # Активность
    new_30d: int = 0
    scored_7d: int = 0
    # Техготовность (§1.2): topic_canon → самый свежий уровень в периоде (`_latest_topic_levels`
    # из `competency_ledger`). Пусто = кандидат не проходил интервью с извлечённой competency-
    # картой в периоде — фактор зануляется (`has_data`), не «нейтральный балл из воздуха».
    skill_topics: dict[str, str] = field(default_factory=dict)
    # §1.3: сигналы прогресса воронки для `_progress_level` (динамический сдвиг весов). `responded`
    # — достигли «Скрининг» (`FunnelAnalytics.responded`); `reached_final` — хоть одна вакансия
    # периода дошла до `FunnelStatus.FINAL` (история этапов, не текущий статус).
    responded: int = 0
    reached_final: bool = False
    # Правка 2026-08-14: «Отклики» теперь реагируют на ДИНАМИКУ (темп + регулярность), а не
    # только на объём. `application_days_active` — сколько разных дней в периоде пользователь
    # откликался (0 = не откликался вообще). `application_days_total` — дней в периоде (для
    # регулярности). При нуле — фактор зануляется через старый `applications_has_data`.
    application_days_active: int = 0
    application_days_total: int = 0
    # Правка 2026-08-14: «Общение» теперь — скорость движения процессов в Чатах, а не поток
    # новых вакансий. `chat_active_threads` — активных тредов в периоде; `chat_stalled_threads`
    # — зависших (последняя реплика HR, ждём кандидата, ИЛИ без продвижения по этапу > порога).
    # `chat_progressing_threads` — тредов, где за период сменился этап воронки (двигаются).
    chat_active_threads: int = 0
    chat_stalled_threads: int = 0
    chat_progressing_threads: int = 0


class OfferChanceComponent(BaseModel):
    """Один фактор композита: суб-балл 0..1, вес и вклад в итог (0..100)."""

    key: str
    label: str
    score: float = Field(description="Суб-балл фактора, 0..1")
    weight: float
    contribution: float = Field(description="Вклад в итоговый %: weight*score*100")


class OfferChance(BaseModel):
    """Единый показатель «Шанс офферов» 0..100 + дельта за сутки + разбивка по факторам.

    `preliminary=True` — данных воронки мало (`applied < _MIN_APPLIED`): композит считается, но
    фронт рисует его как предварительный (пунктир/«предварительно»), не как уверенное число.
    """

    score: int = 0
    delta: int | None = None  # пунктов за сутки (now − day_ago); + лучше
    preliminary: bool = False
    components: list[OfferChanceComponent] = Field(default_factory=list)


class KpiPoint(BaseModel):
    """Headline-KPI с динамикой: значение + дельта за сутки + единица для форматирования."""

    key: str
    label: str
    value: float
    unit: str  # 'pct' | 'score' | 'count'
    delta: float | None = None
    hint: str | None = None


# --- D-05: контрфакты на жёстких гейтах (без LLM, пересчёт по уже сохранённым оценкам) ---

# Ступени смягчения зарплатной планки — доля от текущего порога профиля.
SALARY_COUNTERFACTUAL_STEPS: tuple[tuple[str, float], ...] = (
    ("−10%", 0.9),
    ("−20%", 0.8),
)


class GateCounterfactualStep(BaseModel):
    """Одна точка смягчения гейта: подпись ступени, сколько прошло бы на ней и на сколько больше,
    чем сейчас (`delta` всегда ≥ 0 — ступени только мягче текущей планки)."""

    label: str
    passes: int
    delta: int = 0


class SalaryGateCounterfactual(BaseModel):
    """Зарплатная планка: сколько проходит сейчас и сколько прошло бы при −10% / −20%."""

    threshold: int = 0
    passes_now: int = 0
    steps: list[GateCounterfactualStep] = Field(default_factory=list)


class FormatGateCounterfactual(BaseModel):
    """Формат: сколько проходит с текущим требованием (`verdict=real`) и сколько прошло бы при
    смягчении до условно реальной удалёнки / вовсе без требования к формату."""

    passes_now: int = 0
    steps: list[GateCounterfactualStep] = Field(default_factory=list)


class GateCounterfactuals(BaseModel):
    """Контрфакты на обоих жёстких гейтах — измеримое «сколько прошло бы», без совета
    снижать планку (риск 4 плана: решение владельца, не подсказка модели)."""

    available: bool = False
    measured: int = 0
    salary: SalaryGateCounterfactual = Field(default_factory=SalaryGateCounterfactual)
    format: FormatGateCounterfactual = Field(default_factory=FormatGateCounterfactual)


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def compute_gate_counterfactuals(
    rows: list[tuple[dict, dict | None, dict | None]],
    *,
    salary_min: int,
) -> GateCounterfactuals:
    """Контрфакты на жёстких гейтах из уже сохранённых оценок — ни одного нового LLM-вызова.

    `rows` — (score-jsonb, salary-jsonb, remote_feasibility-jsonb), та же форма входа, что у
    `compute_market_slices`; заскоренными считаем строки с читаемым `overall_score`.

    Зарплата: `estimated_min` (gross) сравнивается с порогом на той же основе, на которой уже
    хранится `salary.meets_min` (`salary_estimator.finalize_estimate` сравнивает с
    `load_candidate_min_salary()`) — при пороге, равном текущему `salary_min` профиля, `passes_now`
    сходится с прямым запросом к базе по `estimated_min >= порог`. Формат: смягчение от
    `verdict=real` до `real+conditional` и до «формат не гейтит вовсе».
    """
    scored: list[tuple[dict, dict]] = []
    for score_raw, salary_raw, remote_raw in rows:
        sd = score_raw if isinstance(score_raw, dict) else {}
        if _score_of(None, sd) is None:
            continue  # не заскорено — в контрфакт не идёт
        salary = salary_raw if isinstance(salary_raw, dict) else _as_dict(sd.get("salary"))
        remote = remote_raw if isinstance(remote_raw, dict) else {}
        scored.append((salary, remote))

    measured = len(scored)
    if measured == 0:
        return GateCounterfactuals()

    salary_lows: list[int | float] = []
    for s, _ in scored:
        v = s.get("estimated_min")
        if isinstance(v, (int, float)):
            salary_lows.append(v)

    def _salary_passes(threshold: int) -> int:
        return sum(1 for v in salary_lows if v >= threshold)

    passes_now_salary = _salary_passes(salary_min) if salary_min > 0 else len(salary_lows)
    salary_steps: list[GateCounterfactualStep] = []
    if salary_min > 0:
        for label, factor in SALARY_COUNTERFACTUAL_STEPS:
            p = _salary_passes(int(round(salary_min * factor)))
            salary_steps.append(
                GateCounterfactualStep(label=label, passes=p, delta=max(0, p - passes_now_salary))
            )
    salary_cf = SalaryGateCounterfactual(
        threshold=salary_min, passes_now=passes_now_salary, steps=salary_steps
    )

    verdicts = [
        r.get("verdict")
        for _, r in scored
        if isinstance(r.get("verdict"), str) and r.get("verdict")
    ]
    passes_now_format = sum(1 for v in verdicts if v == "real")
    passes_conditional = sum(1 for v in verdicts if v in ("real", "conditional"))
    passes_any = len(verdicts)
    format_cf = FormatGateCounterfactual(
        passes_now=passes_now_format,
        steps=[
            GateCounterfactualStep(
                label="+ условная удалёнка",
                passes=passes_conditional,
                delta=max(0, passes_conditional - passes_now_format),
            ),
            GateCounterfactualStep(
                label="без ограничения формата",
                passes=passes_any,
                delta=max(0, passes_any - passes_now_format),
            ),
        ],
    )

    return GateCounterfactuals(
        available=True, measured=measured, salary=salary_cf, format=format_cf
    )


class MarketPulse(BaseModel):
    """Ответ `GET /api/analytics/pulse`: композит + KPI-стена + два actionable-среза.

    Нет PG / нет заскоренных вакансий → `available=false` и пустые блоки (фронт честный empty)."""

    available: bool = False
    offer_chance: OfferChance = Field(default_factory=OfferChance)
    kpis: list[KpiPoint] = Field(default_factory=list)
    kill_factors: list[KillFactor] = Field(default_factory=list)
    stack_niches: list[MarketBucket] = Field(default_factory=list)
    grade_levels: list[MarketBucket] = Field(default_factory=list)
    # L-25: снапшот из кэша — когда посчитан и не устарел ли (роутер отдаёт кэш мгновенно,
    # признак `stale` включает индикатор «обновляется» на фронте вместо спиннера).
    generated_at: datetime | None = None
    stale: bool = False
    gate_counterfactuals: GateCounterfactuals = Field(default_factory=GateCounterfactuals)
    gate_breakdown: list[KillFactor] = Field(default_factory=list)


def compute_offer_chance(inp: OfferChanceInput) -> OfferChance:
    """Свести вход в единый 0..100 + разбивку. Чистая — тестируется без БД.

    Пересборка 2026-08-09:
    * Градиентные сигналы воронки вместо бинарных offer_sig/interview_sig — log1p-нормировка,
      один скрининг не даёт «100% фактор», насыщается плавно.
    * Min-data gate: applied < _MIN_APPLIED → `preliminary=True` (фронт рисует пунктир).
    * Пустая воронка не даёт «баллы из воздуха»: веса funnel/depth/activity обнуляются и
      перераспределяются на оставшиеся факторы (рынок/качество резюме/отклики), а не
      нейтральные 0.4. Bootstrap-аккаунт с нулём откликов больше не получает ~40 баллов «из ниоткуда».
    * Якоря либеральные общие (RESPONSE_RATE_TARGET=0.20 и т.д.), не привязанные к профилю
      владельца — no-owner-hardcode правило (см. CLAUDE.md).

    Пересборка 2026-08-11 (жалоба «слишком оптимистично на старте — 1-2 скрининга и техничка,
    а шанс уже 66»):
    * «Отклик резюме на hh» (пассивный сигнал показов hh) заменён на «Отклики» — период-скоуп
      активности заявок (`inp.applied`, см. `OfferChanceInput`), весит те же 0.10.
    * `funnel` 0.30→0.35, `market` 0.20→0.15: статичный фит рынка/резюме не должен тянуть
      итог наравне с реальным прогрессом воронки, пока реальных этапов почти нет.
    * `_DAMPING_FLOOR`-демпфер: applied < _MIN_APPLIED домножает и суб-баллы, и итог на
      `max(_DAMPING_FLOOR, applied/_MIN_APPLIED)` — тонкая воронка больше не звучит как зрелая
      только потому, что `preliminary` раньше был косметическим пунктиром, не влиявшим на число.

    Шаг 2 плана `offer_chance_rework_2026_08_11` (§1.1): `offer_sig` больше не считает офферы
    по количеству (`offers + offers_active` смешивало «дошёл до стадии Оффер» и «есть запись
    OfferRecord» как два независимых числа). Вход — `inp.weighted_offer_signal`, честная сумма
    confidence-весов по уникальным вакансиям (устный пре-оффер вроде кейса «Сбер»
    из `funnel_collapse_resilience_2026_08_07` весит меньше подписанного).

    Шаг 5 плана (§1.4): «Отклики»/«Активность» домножаются на `conversion_mult` — долю
    `response_rate` от `RESPONSE_RATE_TARGET`, зажатую в [0.4, 1.0]. Без этого объём заявок без
    ответов HR выглядел «активным» наравне с конвертирующимся потоком. `response_rate is None`
    (заявок в периоде нет) — не штраф, а отсутствие данных, зануляется отдельно через `has_data`.

    Шаг 6 плана (§1, §1.3): 7-й фактор Техготовность (`inp.skill_topics` → `_skill_signal`)
    заведён в композит наравне с остальными шестью — пустой `skill_topics` зануляет фактор через
    тот же `has_data`, что и `resume_quality`/`market`. Базовые веса `_WEIGHTS` перед has_data-
    перенормировкой дополнительно сдвигаются `_apply_progress_shift` по ступени прогресса воронки
    (`_progress_level`) — на пике (дошли до Финала/Оффера) `funnel`/`skill` весят больше за счёт
    `applications`/`activity`, см. §1.3.
    """
    # Воронка: конверсия ответов + градиентные сигналы «дошёл до технички / есть оффер»
    # (log1p-нормировка: 1 скрининг ≠ 50 скринингов, плавно насыщается).
    rr = inp.response_rate or 0.0
    offer_sig = _log_norm(inp.weighted_offer_signal, 3.0)
    interview_sig = _log_norm(float(inp.interviewing), 3.0)
    s_funnel = _clamp(
        0.5 * _clamp(rr / RESPONSE_RATE_TARGET) + 0.3 * offer_sig + 0.2 * interview_sig
    )

    # Качество резюме: ResumeScoreBreakdown.total (0..100). Нет снимков (bootstrap) → фактор
    # обнуляется (вес перераспределится), НЕ нейтральный 0.4 (правка 2026-08-09).
    if inp.resume_quality_total is None:
        s_resume_quality = 0.0
        resume_quality_has_data = False
    else:
        s_resume_quality = _clamp(
            (float(inp.resume_quality_total) - RESUME_QUALITY_FLOOR)
            / (RESUME_QUALITY_CEIL - RESUME_QUALITY_FLOOR)
        )
        resume_quality_has_data = True

    # Рынок под вас: адресуемость (оба гейта) + зарплатная зона + средний фит.
    gate_share = inp.gate_both / inp.gate_total if inp.gate_total else 0.0
    s_gate = _clamp(gate_share / GATE_SHARE_TARGET)
    s_salary = _clamp(inp.salary_meets_pct / 100.0)
    s_fit = _clamp((inp.avg_score - FIT_FLOOR) / (FIT_CEIL - FIT_FLOOR))
    s_market = _clamp(0.4 * s_gate + 0.3 * s_salary + 0.3 * s_fit)
    market_has_data = inp.gate_total > 0 or inp.avg_score > 0

    # Отклики: собственная активность заявок в выбранном периоде (не пассивный отклик hh —
    # `inp.applied` уже период-скоуп, когда вызывающий передал period_start/period_end в
    # `_build_bundle`). Всегда посчитан — 0 откликов за период тоже честный сигнал, не «нет
    # данных» (в отличие от resume_quality/market, где реально может не быть снимка).
    # Правка 2026-08-14: «Отклики» реагируют на ДИНАМИКУ, не только на объём. Темп
    # (откликов/день) + регулярность (доля активных дней от длины периода) — побуждает
    # откликаться каждый день, а не «20 откликов в один день и тишина на неделю». Старый
    # `_log_norm(applied, APPLICATIONS_TARGET)` завышал: 20 откликов за день = 100% фактор,
    # хотя реальная регулярность нулевая. Теперь темп 2/день уже сильный, а регулярность
    # добавляет до 40% сверху за ежедневную активность.
    if inp.application_days_total > 0 and inp.applied > 0:
        daily_pace = inp.applied / max(1, inp.application_days_total)
        pace_score = _log_norm(daily_pace, APPLICATIONS_DAILY_TARGET)
        regularity = _clamp(inp.application_days_active / max(1, inp.application_days_total))
        s_applications = _clamp(
            (1.0 - APPLICATIONS_REGULARITY_WEIGHT) * pace_score
            + APPLICATIONS_REGULARITY_WEIGHT * regularity
        )
    else:
        # Период не задан (старые прямые вызовы) или откликов нет — фолбэк на старый объёмный
        # сигнал, чтобы не сломать обратную совместимость тестов без новых полей.
        s_applications = _log_norm(float(inp.applied), APPLICATIONS_TARGET)
    applications_has_data = True

    # Общение (правка 2026-08-14): скорость движения процессов в Чатах, а не поток новых
    # вакансий. Старая логика (`new_30d` + `scored_7d`) мерила обработку бэклога, а не то,
    # что чувствует кандидат: «двигается ли процесс или завис». Теперь — доля двигающихся
    # тредов (`progressing/active`) со штрафом за зависшие (`stalled/active`). Пустые Чаты
    # (нет активных тредов) → фактор зануляется через `has_data`, не «баллы из воздуха».
    if inp.chat_active_threads > 0:
        progress_ratio = inp.chat_progressing_threads / inp.chat_active_threads
        stall_ratio = inp.chat_stalled_threads / inp.chat_active_threads
        s_activity = _clamp(
            CHAT_PROGRESS_WEIGHT * progress_ratio - (1.0 - CHAT_PROGRESS_WEIGHT) * stall_ratio
        )
    else:
        s_activity = 0.0
    # Фолбэк для старых вызовов без chat_* полей: если чатов нет, но есть поток новых
    # вакансий (new_30d/scored_7d) — используем старую логику, чтобы не занулять фактор
    # для аккаунтов, где Чаты ещё не используются. Это сохраняет обратную совместимость
    # и не даёт «Общение» обнулиться просто потому, что бэк не прислал chat_* сигналы.
    if inp.chat_active_threads == 0 and (inp.new_30d > 0 or inp.scored_7d > 0):
        s_activity = _clamp(
            0.6 * _log_norm(float(inp.new_30d), NEW_30D_TARGET)
            + 0.4 * _log_norm(float(inp.scored_7d), SCORED_7D_TARGET)
        )
    activity_has_data = inp.chat_active_threads > 0 or inp.new_30d > 0 or inp.scored_7d > 0

    # Дисконт конверсии (§1.4 offer_chance_rework_2026_08_11, Шаг 5): «Отклики»/«Активность»
    # считают только объём — ничего не мешает льющему воду в пустоту процессу выглядеть
    # «активным». `response_rate is None` (`applied=0`) не штрафуем — это отсутствие данных,
    # его уже занулит `has_data` ниже (отдельный, более старый механизм), а не «льём воду мимо
    # цели». Пол 0.4 — тот же, что `_DAMPING_FLOOR`: суб-балл не проваливается в ноль просто из-за
    # временного затишья с ответами.
    if inp.response_rate is None:
        conversion_mult = 1.0
    else:
        conversion_mult = max(_DAMPING_FLOOR, min(1.0, inp.response_rate / RESPONSE_RATE_TARGET))
    s_applications *= conversion_mult
    s_activity *= conversion_mult

    # Глубина: сколько параллельных живых процессов (откликнулся, не отказали).
    depth = max(0, inp.applied - inp.rejected)
    s_depth = _log_norm(float(depth), DEPTH_TARGET)
    depth_has_data = inp.applied > 0

    # Техготовность (§1.2, Шаг 6): средний уровень по свежим темам competency_ledger × насыщение
    # по охвату. Пустой `skill_topics` (кандидат не проходил интервью с извлечённой competency-
    # картой в периоде) → фактор зануляется через `has_data`, не «нейтральный балл из воздуха».
    s_skill = _skill_signal(inp.skill_topics)
    skill_has_data = bool(inp.skill_topics)

    # §1.3 Шаг 6: базовые веса сдвигаются по ступени прогресса воронки ПЕРЕД has_data-
    # перенормировкой ниже (сначала сдвиг по стадии, потом — если фактор без данных —
    # перераспределение на измеримые, как и раньше). `_apply_progress_shift` работает в п.п.
    # (0..100), `_WEIGHTS` хранит доли (0..1) — переводим туда и обратно.
    progress_level = _progress_level(
        reached_final=inp.reached_final,
        weighted_offer_signal=inp.weighted_offer_signal,
        interviewing=inp.interviewing,
        responded=inp.responded,
    )
    base_weights_pp = {k: w * 100.0 for k, _, w in _WEIGHTS}
    shifted_pp = _apply_progress_shift(base_weights_pp, progress_level)
    weights = {k: shifted_pp[k] / 100.0 for k in shifted_pp}
    labels = {k: lbl for k, lbl, _ in _WEIGHTS}
    order = [k for k, _, _ in _WEIGHTS]

    # Пустая воронка → перераспределение весов. Старая логика давала ~40 баллов «из воздуха»
    # (resume_quality 0.4 neutral + market + activity). Теперь факторы без данных обнуляются,
    # их вес равномерно перекидывается на факторы с данными — композит держат только те, что
    # реально измеримы. Если вообще ничего не измерено — честный 0.
    has_data = {
        "funnel": inp.applied > 0,
        "skill": skill_has_data,
        "resume_quality": resume_quality_has_data,
        "market": market_has_data,
        "applications": applications_has_data,
        "activity": activity_has_data,
        "depth": depth_has_data,
    }
    subs = {
        "funnel": s_funnel,
        "skill": s_skill,
        "resume_quality": s_resume_quality,
        "market": s_market,
        "applications": s_applications,
        "activity": s_activity,
        "depth": s_depth,
    }
    # Эффективный вес: исходный (уже сдвинутый по прогрессу), если есть данные, иначе 0; затем
    # нормируем на сумму активных, чтобы сумма активных весов = 1.0 (вес обнуленного фактора
    # перераспределён на остальные).
    total_active_weight = sum(weights[k] for k in order if has_data[k])
    if total_active_weight <= 0:
        # Нет ни одного измеримого фактора — честный ноль, не нейтральный балл.
        components = [
            OfferChanceComponent(
                key=k, label=labels[k], score=0.0, weight=weights[k], contribution=0.0
            )
            for k in order
        ]
        return OfferChance(score=0, preliminary=inp.applied < _MIN_APPLIED, components=components)

    components = [
        OfferChanceComponent(
            key=k,
            label=labels[k],
            score=round(subs[k], 3),
            # Эффективный вес: исходный (сдвинутый), если есть данные, иначе 0 (доля перераспределена).
            weight=round((weights[k] if has_data[k] else 0.0) / total_active_weight, 4),
            contribution=round(
                (weights[k] if has_data[k] else 0.0) / total_active_weight * subs[k] * 100, 1
            ),
        )
        for k in order
    ]

    # Демпфер тонкой воронки: applied < _MIN_APPLIED домножает КАЖДЫЙ вклад на один и тот же
    # коэффициент — так столбцы вкладов на фронте (`CategoryBars`) в сумме всё ещё сходятся
    # к итоговому числу, не только заголовок.
    if inp.applied < _MIN_APPLIED:
        damping = max(_DAMPING_FLOOR, inp.applied / _MIN_APPLIED)
        components = [
            c.model_copy(update={"contribution": round(c.contribution * damping, 1)})
            for c in components
        ]

    score = round(sum(c.contribution for c in components))
    return OfferChance(
        score=int(score),
        preliminary=inp.applied < _MIN_APPLIED,
        components=components,
    )


# --- Сборка из Postgres (реконструкция «сейчас» и «неделю назад») ---


@dataclass
class _Job:
    id: int
    overall: int | None
    score: dict
    salary: dict | None
    remote: dict | None
    status: str | None
    created_at: datetime | None
    scored_at: datetime | None
    is_skipped: bool = False
    # HH vacancy_id (в отличие от `id` — внутренний PK): нужен, чтобы дедупить сигнал оффера по
    # вакансии (join с `_Offer.vacancy_id`), не по счётчику строк jobs/offers по отдельности.
    vacancy_id: str | None = None


@dataclass
class _Stage:
    job_id: int
    stage: str
    changed_at: datetime | None


@dataclass
class _Offer:
    status: str
    created_at: datetime | None
    # Как у `_Job` — HH vacancy_id для join'а по вакансии; `raw_text` — вход для
    # `offer_confidence` (пусто = устный оффер, непусто = письменный).
    vacancy_id: str | None = None
    raw_text: str = ""


@dataclass
class _Snap:
    captured_at: datetime | None
    impressions: int
    views: int
    invitations: int
    recommended_vacancies: int = 0


@dataclass
class _CompetencyEntry:
    """Одна строка `competency_ledger` (§1.2 offer_chance_rework_2026_08_11, Шаг 3).

    Таблица уже несёт `account_id` напрямую (0104_prep_account_id.sql) — план предполагал join
    через `interview_debriefs.account_id` (`debrief_id` FK, у леджера своего аккаунта не было на
    момент `0046_competency_ledger.sql`), это устарело: RLS-ретрофит завёл колонку прямо на
    таблице, `get_market_pulse` фильтрует `where account_id = $1` без join.
    """

    topic_canon: str
    level: str
    created_at: datetime | None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _weighted_offer_signal(
    funnel_jobs: list[tuple[int, str | None]],
    funnel_stages: list[tuple[int, str, datetime]],
    vacancy_id_by_job: dict[int, str | None],
    offers_by_vacancy: dict[str, _Offer],
) -> float:
    """Σ confidence_mult(v) по уникальным вакансиям периода (§1.1 offer_chance_rework_2026_08_11).

    Дедуп по vacancy_id: вакансия, дошедшая до `FunnelStatus.OFFER` И имеющая `_Offer`,
    учитывается один раз (`offer_confidence` сам решает verbal/written/signed) — не складываем
    «дошёл до стадии» и «есть запись оффера» как два независимых числа, как раньше
    `offers + offers_active`.
    """
    history: dict[int, list[str]] = {}
    for job_id, stage, _changed_at in funnel_stages:
        history.setdefault(job_id, []).append(stage)

    reached_offer_vids: set[str] = set()
    for job_id, status in funnel_jobs:
        vid = vacancy_id_by_job.get(job_id)
        if not vid:
            continue
        for s in (status, *history.get(job_id, [])):
            n = funnel_stage_number(s)
            if isinstance(n, int) and n >= _OFFER_STAGE_NUM:
                reached_offer_vids.add(vid)
                break

    total = 0.0
    for vid in reached_offer_vids | offers_by_vacancy.keys():
        confidence = offer_confidence(vid in reached_offer_vids, offers_by_vacancy.get(vid))
        if confidence is not None:
            total += _OFFER_CONFIDENCE_MULT[confidence]
    return total


def _latest_topic_levels(rows: list[tuple[str, str, datetime]]) -> dict[str, str]:
    """Самый свежий уровень по каждой `topic_canon` в периоде (§1.2 offer_chance_rework_2026_08_11).

    Дедуп, не среднее по истории — отражает текущее состояние кандидата, не волатильность (рост/
    просадка между собесами — материал для career-трека, не для этого композита).
    """
    latest: dict[str, tuple[datetime, str]] = {}
    for topic_canon, level, created_at in rows:
        seen = latest.get(topic_canon)
        if seen is None or created_at > seen[0]:
            latest[topic_canon] = (created_at, level)
    return {topic: level for topic, (_, level) in latest.items()}


def _skill_signal(topics: dict[str, str]) -> float:
    """Техготовность 0..1 (§1.2): средний уровень по свежим темам × насыщение по охвату тем.

    `0.5 + 0.5·saturation` — одна тема на `confident` не даёт 100% фактора (насыщение по объёму
    покрытия, тот же принцип, что `_log_norm` для остальных сигналов), но и не проваливает в
    ноль — сигнал реальный, просто узкий. Пустой `topics` (кандидат не проходил интервью с
    извлечённым competency-картой) → 0.0; has_data решает вызывающий (`bool(topics)`), а не эта
    функция — 0.0 здесь означает и «нет данных», и «все темы weak», это не одно и то же.
    """
    if not topics:
        return 0.0
    avg_ratio = sum(LEVEL_POINTS[level] for level in topics.values()) / len(topics) / 100.0
    saturation = _log_norm(float(len(topics)), TOPIC_SATURATION_TARGET)
    return avg_ratio * (0.5 + 0.5 * saturation)


@dataclass
class _Bundle:
    """Срез агрегатов на момент времени — общий вход и для KPI, и для композита."""

    supply: SupplyReport
    slices: MarketSlices
    funnel: FunnelAnalytics
    # Вход offer_sig (§1.1) — заменил offers_active (простой счётчик «активных» офферов по
    # статусу): теперь честная сумма confidence-весов по уникальным вакансиям периода.
    weighted_offer_signal: float
    # Вход фактора Техготовность (§1.2) — topic_canon → самый свежий уровень в периоде,
    # прокидывается в композит через `OfferChanceInput.skill_topics` (`_input_of`, Шаг 6).
    skill_topics: dict[str, str]
    snap: _Snap | None
    gm_snap: _Snap | None
    new_30d: int
    scored_7d: int
    # Качество резюме на этот срез (ResumeScoreBreakdown.total 0..100); None = bootstrap.
    resume_quality_total: int | None = None
    # S3: метка времени последнего успешного синка getmatch /applications. Только для now-среза
    # (cutoff=None) — для «сутки назад» не реконструируется (одна точка во времени, не история).
    gm_last_sync_at: datetime | None = None
    # D-05: контрфакты на гейтах — снапшот состояния, не история, поэтому тоже только now-срез.
    gate_counterfactuals: GateCounterfactuals | None = None
    # S-04: взаимоисключающая сегментация одной полосы «Что режет поток» — снапшот, только now-срез.
    gate_breakdown: list[KillFactor] | None = None
    # Правка 2026-08-14: входы «Отклики» (динамика) и «Общение» (скорость Чатов).
    # `application_days_active`/`application_days_total` — сколько разных дней пользователь
    # откликался / дней в периоде. `chat_*` — активные/зависшие/двигающиеся треды Чатов.
    application_days_active: int = 0
    application_days_total: int = 0
    chat_active_threads: int = 0
    chat_stalled_threads: int = 0
    chat_progressing_threads: int = 0


def _build_bundle(
    jobs: list[_Job],
    stages: list[_Stage],
    offers: list[_Offer],
    snaps: list[_Snap],
    gm_snaps: list[_Snap],
    competency: list[_CompetencyEntry],
    *,
    cutoff: datetime | None,
    resume_score_now: int | None = None,
    resume_score_ago: int | None = None,
    gm_last_sync_at: datetime | None = None,
    profile: SearchProfile | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    application_days_active: int = 0,
    application_days_total: int = 0,
    chat_active_threads: int = 0,
    chat_stalled_threads: int = 0,
    chat_progressing_threads: int = 0,
) -> _Bundle:
    """Собрать агрегаты на `cutoff` (None = сейчас, иначе состояние на момент `cutoff`).

    «Неделю назад» реконструируем фильтром строк по их меткам: вакансия учтена в supply/slices,
    только если была заскорена к cutoff; в воронке — если существовала (created_at) к cutoff, а
    история этапов обрезана по `changed_at`. Текущий `status` для прошлого НЕ берём (он отражает
    «сейчас») — самую дальнюю ступень даёт обрезанная история.

    `period_start`/`period_end` (2026-08-11, «Шанс офферов» — полностью период-зависимый):
    доп. ограничение сверху на cutoff — шкала периода «Рынка» (`from_days`/`to_days`,
    `get_market_overview`), одна и та же для среза «сейчас» и «сутки назад» (не сдвигается
    для ago-среза — обе точки читают один и тот же период, дельта остаётся сравнимой).
    `None` (по умолчанию, прямые вызовы без периода — старые тесты) — период не ограничивает,
    поведение как раньше. Строка без метки (`dt is None`) не может быть проверена на
    принадлежность периоду — выпадает, когда период задан (как в `search_metrics._windowed`).
    """

    def in_window(dt: datetime | None) -> bool:
        if period_start is not None:
            if dt is None or dt < period_start:
                return False
            if period_end is not None and dt > period_end:
                return False
        if cutoff is not None:
            return dt is not None and dt <= cutoff
        return True

    # Калибровка рынка (avg_fit / niches): без skipped — явный отказ не смешиваем с активными.
    scored_jobs = [j for j in jobs if in_window(j.scored_at) and not j.is_skipped]
    supply = compute_supply_report(
        [(j.overall, j.score, j.scored_at) for j in scored_jobs],
        profile=profile,
    )
    salary_min = profile.salary_min if profile is not None else 0
    grade_floor = profile.grade_floor_index if profile is not None else -1
    grade_ceil = profile.grade_ceil_index if profile is not None else -1
    slices = compute_market_slices(
        [(j.score, j.salary, j.remote) for j in scored_jobs],
        salary_min=salary_min,
        grade_floor=grade_floor,
        grade_ceil=grade_ceil,
    )
    gate_counterfactuals = (
        compute_gate_counterfactuals(
            [(j.score, j.salary, j.remote) for j in scored_jobs], salary_min=salary_min
        )
        if cutoff is None
        else None
    )
    gate_breakdown = (
        compute_gate_breakdown([(j.overall, j.score) for j in scored_jobs], profile=profile)
        if cutoff is None
        else None
    )

    funnel_jobs = [
        (j.id, (j.status if cutoff is None else None))
        for j in jobs
        if in_window(j.created_at) and not j.is_skipped
    ]
    seen_ids = {jid for jid, _ in funnel_jobs}
    funnel_stages = [
        (s.job_id, s.stage, s.changed_at)
        for s in stages
        if s.job_id in seen_ids and in_window(s.changed_at) and s.changed_at is not None
    ]
    funnel = compute_funnel_analytics(funnel_jobs, funnel_stages)

    vacancy_id_by_job = {j.id: j.vacancy_id for j in jobs if j.id in seen_ids}
    offers_by_vacancy = {
        o.vacancy_id: o for o in offers if o.vacancy_id and in_window(o.created_at)
    }
    weighted_offer_signal = _weighted_offer_signal(
        funnel_jobs, funnel_stages, vacancy_id_by_job, offers_by_vacancy
    )

    # Техготовность (competency_ledger) — это НАКОПЛЕННОЕ состояние кандидата, не событие
    # периода. Правка 2026-08-14 (жалоба «Скиллы всегда 0 при наличии расшировок»): раньше
    # `skill_topics` фильтровался тем же `in_window(c.created_at)`, что и события воронки —
    # если выбранный период короче давности дебрифов (частый случай: 14 дней шкалы при
    # собесах месяц назад), леджер выпадал полностью, и фактор занулялся через `has_data`.
    # Теперь для competency берём ВСЁ накопленное к моменту `cutoff` (для now-среза cutoff=None
    # — весь леджер), без нижней границы `period_start`: это текущая карта компетенций, а не
    # «что нового по скиллам за период». Верхняя граница — `cutoff` (для ago-среза) и
    # `period_end` (если задан), чтобы «сутки назад» честно реконструировало карту на ту точку.
    def competency_in_scope(dt: datetime | None) -> bool:
        if dt is None:
            return False
        if cutoff is not None and dt > cutoff:
            return False
        return not (period_end is not None and dt > period_end)

    skill_topics = _latest_topic_levels(
        [
            (c.topic_canon, c.level, c.created_at)
            for c in competency
            if c.created_at is not None and competency_in_scope(c.created_at)
        ]
    )

    snap = None
    for s in snaps:  # snaps hh по возрастанию captured_at
        if in_window(s.captured_at):
            snap = s
        elif cutoff is not None:
            break

    gm_snap = None
    for s in gm_snaps:
        if in_window(s.captured_at):
            gm_snap = s
        elif cutoff is not None:
            break

    active_jobs = [j for j in jobs if not j.is_skipped]
    if cutoff is None:
        now = datetime.now(UTC)
        new_30d = sum(
            1 for j in active_jobs if j.created_at and j.created_at >= now - timedelta(days=30)
        )
        scored_7d = sum(
            1 for j in active_jobs if j.scored_at and j.scored_at >= now - timedelta(days=7)
        )
    else:
        lo30, lo7 = cutoff - timedelta(days=30), cutoff - timedelta(days=7)
        new_30d = sum(1 for j in active_jobs if j.created_at and lo30 < j.created_at <= cutoff)
        scored_7d = sum(1 for j in active_jobs if j.scored_at and lo7 < j.scored_at <= cutoff)

    return _Bundle(
        supply,
        slices,
        funnel,
        weighted_offer_signal,
        skill_topics,
        snap,
        gm_snap,
        new_30d,
        scored_7d,
        resume_quality_total=resume_score_now if cutoff is None else resume_score_ago,
        gm_last_sync_at=gm_last_sync_at if cutoff is None else None,
        gate_counterfactuals=gate_counterfactuals,
        gate_breakdown=gate_breakdown,
        application_days_active=application_days_active,
        application_days_total=application_days_total,
        chat_active_threads=chat_active_threads,
        chat_stalled_threads=chat_stalled_threads,
        chat_progressing_threads=chat_progressing_threads,
    )


def _reached_final(funnel: FunnelAnalytics) -> bool:
    """Хоть одна вакансия периода дошла до `FunnelStatus.FINAL` (§1.3, вход `_progress_level`).

    По истории этапов (`FunnelAnalytics.stages`), не по текущему `status` — так же, как
    остальная воронка реконструирует «сутки назад» в `_build_bundle`.
    """
    return any(s.stage == FunnelStatus.FINAL and s.reached > 0 for s in funnel.stages)


def _application_days_signals(
    stage_rows: list,
    *,
    period_start: datetime,
    period_end: datetime,
) -> tuple[int, int]:
    """Сколько разных дней пользователь откликался в периоде (правка 2026-08-14, «Отклики»).

    `stage_rows` — уже вытянутые строки `application_stages` (любой record-like с `stage` и
    `changed_at`). Считаем уникальные даты `changed_at` строк со stage='Отклик' внутри окна —
    это «активные дни откликов». `application_days_total` — длина периода в днях (для регулярности).

    Чистая функция над record-like строками — тестируется без БД. None/naive timestamps
    нормализуются как UTC (как в `_build_bundle.in_window`).
    """
    days: set[str] = set()
    for r in stage_rows:
        stage = r["stage"] if hasattr(r, "__getitem__") else getattr(r, "stage", None)
        changed = r["changed_at"] if hasattr(r, "__getitem__") else getattr(r, "changed_at", None)
        if not stage or not changed:
            continue
        resolved = resolve_funnel_status(str(stage))
        if resolved != FunnelStatus.APPLIED:
            continue
        dt = changed if changed.tzinfo else changed.replace(tzinfo=UTC)
        if dt < period_start or dt > period_end:
            continue
        days.add(dt.strftime("%Y-%m-%d"))
    total_days = max(1, (period_end - period_start).days)
    return (len(days), total_days)


def _input_of(b: _Bundle) -> OfferChanceInput:
    g = b.slices.gates
    return OfferChanceInput(
        response_rate=b.funnel.response_rate,
        applied=b.funnel.applied,
        interviewing=b.funnel.interviewing,
        rejected=b.funnel.rejected,
        weighted_offer_signal=b.weighted_offer_signal,
        avg_score=b.supply.avg_score,
        gate_both=g.both,
        gate_total=g.total,
        salary_meets_pct=b.slices.salary_meets_min_pct,
        real_remote=g.real_remote,
        measured_remote=g.measured_remote,
        resume_quality_total=b.resume_quality_total,
        new_30d=b.new_30d,
        scored_7d=b.scored_7d,
        skill_topics=b.skill_topics,
        responded=b.funnel.responded,
        reached_final=_reached_final(b.funnel),
        application_days_active=b.application_days_active,
        application_days_total=b.application_days_total,
        chat_active_threads=b.chat_active_threads,
        chat_stalled_threads=b.chat_stalled_threads,
        chat_progressing_threads=b.chat_progressing_threads,
    )


def _metrics_of(b: _Bundle) -> dict[str, float | None]:
    """Значения headline-KPI из среза (None = метрика не измерима в этом срезе)."""
    g: GateFunnel = b.slices.gates
    gm_age: float | None
    if b.gm_last_sync_at is None:
        # Синков getmatch ещё не было (bootstrap) — метрику не показываем, не штрафуем.
        gm_age = None
    else:
        gm_age = float((datetime.now(UTC) - b.gm_last_sync_at).days)
    return {
        "impressions": float(b.snap.impressions) if b.snap else None,
        "views": float(b.snap.views) if b.snap else None,
        "invitations": float(b.snap.invitations) if b.snap else None,
        "recommended_vacancies": float(b.snap.recommended_vacancies) if b.snap else None,
        "getmatch_views": float(b.gm_snap.views) if b.gm_snap else None,
        "getmatch_last_sync_age_days": gm_age,
        "addressable": (100.0 * g.both / g.total) if g.total else 0.0,
        "salary_meets": b.slices.salary_meets_min_pct,
        "real_remote": (100.0 * g.real_remote / g.measured_remote) if g.measured_remote else 0.0,
        "avg_fit": b.supply.avg_score,
        "hr_response": 100.0 * (b.funnel.response_rate or 0.0),
        "activity_30d": float(b.new_30d),
        "depth": float(max(0, b.funnel.applied - b.funnel.rejected)),
    }


# (key, label, unit, hint) — порядок = порядок карточек. Подписи гейтов — из профиля.
def _kpi_defs(profile: SearchProfile | None = None) -> tuple[tuple[str, str, str, str | None], ...]:
    if profile is not None and profile.salary_min > 0:
        salary_bit = f"зарплата от {_fmt_salary_short(profile.salary_min)}"
        salary_meets_label = f"Зарплата от {_fmt_salary_short(profile.salary_min)}"
        salary_meets_hint = (
            f"доля вакансий с вилкой не ниже {_fmt_salary_short(profile.salary_min)}"
        )
    else:
        salary_bit = "целевая зарплата"
        salary_meets_label = "Зарплата от цели"
        salary_meets_hint = "доля вакансий с дотягивающей оценкой вилки"

    formats: list[str] = []
    if profile is not None:
        if profile.allows_remote:
            formats.append("удалённый")
        if profile.allows_hybrid:
            formats.append("гибрид")
        if profile.allows_office:
            formats.append("офис")
    format_bit = " / ".join(formats) if formats else "целевой формат"
    addressable_hint = f"доля потока, проходящая оба жёстких гейта ({salary_bit} ∧ {format_bit})"

    return (
        ("impressions", "Показы резюме", "count", "сколько раз резюме показано в поиске hh"),
        ("views", "Просмотры", "count", "работодатели открыли резюме"),
        ("invitations", "Приглашения", "count", "приглашений на вакансию"),
        (
            "recommended_vacancies",
            "Рекомендовано вакансий",
            "count",
            "hh рекомендует вакансий под резюме",
        ),
        (
            "getmatch_views",
            "getmatch · просмотры",
            "count",
            "кто смотрел профиль на getmatch за 30 дней",
        ),
        (
            "getmatch_last_sync_age_days",
            "getmatch · последний синк",
            "count",
            "дней с последнего синка откликов getmatch /applications",
        ),
        ("addressable", "Адресуемый рынок", "pct", addressable_hint),
        ("salary_meets", salary_meets_label, "pct", salary_meets_hint),
        (
            "real_remote",
            "Реальный формат",
            "pct",
            "доля с verdict=real среди оценённых на формат",
        ),
        ("avg_fit", "Средний фит", "score", "средний балл соответствия по потоку"),
        ("hr_response", "Ответ HR", "pct", "доля откликов, на которые ответил HR"),
        ("activity_30d", "Новых за 30д", "count", "приток вакансий в поток"),
        ("depth", "В работе", "count", "параллельных живых процессов (откликнулся, не отказали)"),
    )


def _round_delta(now: float | None, ago: float | None) -> float | None:
    if now is None or ago is None:
        return None
    return round(now - ago, 1)


def build_pulse(
    jobs: list[_Job],
    stages: list[_Stage],
    offers: list[_Offer],
    snaps: list[_Snap],
    gm_snaps: list[_Snap] | None = None,
    competency: list[_CompetencyEntry] | None = None,
    *,
    prior: dict | None = None,
    resume_score_now: int | None = None,
    resume_score_ago: int | None = None,
    gm_last_sync_at: datetime | None = None,
    profile: SearchProfile | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    application_days_active: int = 0,
    application_days_total: int = 0,
    chat_active_threads: int = 0,
    chat_stalled_threads: int = 0,
    chat_progressing_threads: int = 0,
) -> MarketPulse:
    """Чистая сборка пульса из уже вытянутых строк (тестируется без БД).

    `prior` — сохранённый днём ранее снимок «Рынка» (`market_snapshots`, best-effort): точная
    дельта день-ко-дню по застывшему прошлому значению вместо реконструкции по мутабельным строкам
    jobs/application_stages (переоценка вакансии задним числом иначе искажает «сутки назад»).
    Метрики, которых в снимке нет (bootstrap — снимков ещё не копилось), считаются реконструкцией.

    `resume_score_now`/`resume_score_ago` — последний снимок скора резюме на «сейчас» и
    «сутки назад». None = снимков ещё нет (bootstrap) — композит берёт нейтральный базис, не штраф.

    `gm_last_sync_at` — метка последнего успешного синка getmatch /applications (S3). Только для
    now-среза; для «сутки назад» KPI не считается (точка во времени, не история).

    `period_start`/`period_end` — шкала периода «Рынка» (2026-08-11): весь «Шанс офферов»
    (funnel/market/applications/activity/depth) считается по этому окну, не по всей истории —
    та же пара для среза «сейчас» и «сутки назад» (см. `_build_bundle`).

    Правка 2026-08-14: `application_days_*` (динамика откликов) и `chat_*` (скорость Чатов) —
    новые входы для факторов «Отклики»/«Общение». Передаются только для now-среза (ago-срез
    реконструирует дельту через `prior`-снимок, как остальные KPI) — для «сутки назад» это 0,
    что фолбэчит `compute_offer_chance` на старую объёмную/потоковую логику.
    """
    gm_snaps = gm_snaps or []
    competency = competency or []
    now_b = _build_bundle(
        jobs,
        stages,
        offers,
        snaps,
        gm_snaps,
        competency,
        cutoff=None,
        resume_score_now=resume_score_now,
        resume_score_ago=resume_score_ago,
        gm_last_sync_at=gm_last_sync_at,
        profile=profile,
        period_start=period_start,
        period_end=period_end,
        application_days_active=application_days_active,
        application_days_total=application_days_total,
        chat_active_threads=chat_active_threads,
        chat_stalled_threads=chat_stalled_threads,
        chat_progressing_threads=chat_progressing_threads,
    )
    if not now_b.supply.available:
        return MarketPulse(available=False)

    ago_b = _build_bundle(
        jobs,
        stages,
        offers,
        snaps,
        gm_snaps,
        competency,
        cutoff=datetime.now(UTC) - timedelta(days=PULSE_WINDOW_DAYS),
        resume_score_now=resume_score_now,
        resume_score_ago=resume_score_ago,
        profile=profile,
        period_start=period_start,
        period_end=period_end,
    )

    chance = compute_offer_chance(_input_of(now_b))
    chance_ago = compute_offer_chance(_input_of(ago_b))
    prior_metrics: dict = (prior or {}).get("metrics") or {}
    prior_chance_score = (prior or {}).get("offer_chance_score")
    chance.delta = int(
        chance.score - prior_chance_score
        if isinstance(prior_chance_score, int | float)
        else chance.score - chance_ago.score
    )

    m_now, m_ago = _metrics_of(now_b), _metrics_of(ago_b)
    kpis: list[KpiPoint] = []
    for key, label, unit, hint in _kpi_defs(profile):
        cur = m_now[key]
        if cur is None:
            continue
        kpis.append(
            KpiPoint(
                key=key,
                label=label,
                value=round(cur, 1),
                unit=unit,
                delta=(
                    _round_delta(cur, prior_metrics[key])
                    if key in prior_metrics and prior_metrics[key] is not None
                    else _round_delta(cur, m_ago[key])
                ),
                hint=hint,
            )
        )

    return MarketPulse(
        available=True,
        offer_chance=chance,
        kpis=kpis,
        kill_factors=now_b.supply.kill_factors,
        stack_niches=now_b.slices.stack_niches,
        grade_levels=now_b.slices.grade_levels,
        gate_counterfactuals=now_b.gate_counterfactuals or GateCounterfactuals(),
        gate_breakdown=now_b.gate_breakdown or [],
    )


async def get_market_pulse(
    *,
    account_id: int,
    db: Executor | None = None,
    from_days: int | None = None,
    to_days: int = 0,
) -> MarketPulse:
    """Собрать пульс аккаунта из Postgres. Read-only, без LLM.

    `from_days`/`to_days` — шкала периода «Рынка» («дней назад от сегодня», как в
    `get_market_overview`). `None` (по умолчанию) — без периода, вся история (обратная
    совместимость для прямых вызовов вне overview). Заданы — «Шанс офферов» считается по
    этому окну (см. `build_pulse`/`_build_bundle`).
    """
    db = db or get_pool()
    period_start: datetime | None = None
    period_end: datetime | None = None
    if from_days is not None:
        now = datetime.now(UTC)
        period_start = now - timedelta(days=from_days)
        period_end = now - timedelta(days=to_days)
    job_rows, stage_rows, offer_rows, snap_rows, competency_rows = await asyncio.gather(
        db.fetch(
            "select id, overall_score, score, salary, remote_feasibility, status, "
            "created_at, scored_at, vacancy_id, "
            "exists(select 1 from skipped_vacancies sv where sv.vacancy_id = jobs.vacancy_id "
            "and sv.account_id = jobs.account_id) "
            "as is_skipped "
            "from jobs where account_id = $1",
            account_id,
        ),
        db.fetch(
            "select job_id, stage, changed_at from application_stages where account_id = $1",
            account_id,
        ),
        db.fetch(
            "select status, created_at, vacancy_id, raw_text from offers where account_id = $1",
            account_id,
        ),
        db.fetch(
            "select captured_at, impressions, views, invitations, recommended_vacancies, resume_id "
            "from resume_stats where account_id = $1 order by captured_at asc, id asc",
            account_id,
        ),
        # §1.2 offer_chance_rework_2026_08_11: account_id живёт прямо на competency_ledger
        # (0104_prep_account_id.sql) — без join через interview_debriefs.debrief_id.
        db.fetch(
            "select topic_canon, level, created_at from competency_ledger where account_id = $1",
            account_id,
        ),
    )

    # Правка 2026-08-14: входы «Отклики» (динамика) и «Общение» (скорость Чатов). Best-effort —
    # нет PG/таблиц → нули, фактор фолбэчит на старую объёмную/потоковую логику (не роняет пульс).
    application_days_active = 0
    application_days_total = 0
    chat_active_threads = 0
    chat_stalled_threads = 0
    chat_progressing_threads = 0
    if period_start is not None:
        try:
            application_days_active, application_days_total = _application_days_signals(
                stage_rows, period_start=period_start, period_end=period_end or datetime.now(UTC)
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("application-days signals недоступны: %s", exc)
        try:
            from core.domains.pipeline.hr_threads import chat_velocity_signals

            (
                chat_active_threads,
                chat_stalled_threads,
                chat_progressing_threads,
            ) = await chat_velocity_signals(
                account_id=account_id,
                period_start=period_start,
                period_end=period_end or datetime.now(UTC),
                stall_days=CHAT_STALL_DAYS,
                db=db,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("chat-velocity signals недоступны: %s", exc)

    prior: dict | None = None
    try:
        from core.domains.market.market_snapshot import get_previous_snapshot

        prev = await get_previous_snapshot(account_id=account_id, db=db)
        if prev is not None:
            prior = prev.payload
    except Exception as exc:  # noqa: BLE001 — таблицы нет/PG недоступен → фолбэк на реконструкцию
        logger.debug("market_snapshots недоступны, дельта день-ко-дню через реконструкцию: %s", exc)

    # Качество резюме: последний снимок на «сейчас» и на «сутки назад». Best-effort:
    # нет таблицы/нет снимков → None, композит берёт нейтральный базис (bootstrap не штрафуем).
    resume_score_now: int | None = None
    resume_score_ago: int | None = None
    try:
        from core.domains.profile.resume_score import load_score_at

        snap_now = await load_score_at(None, account_id=account_id, db=db)
        if snap_now is not None:
            resume_score_now = int(snap_now.total)
        snap_ago = await load_score_at(
            datetime.now(UTC) - timedelta(days=PULSE_WINDOW_DAYS),
            account_id=account_id,
            db=db,
        )
        if snap_ago is not None:
            resume_score_ago = int(snap_ago.total)
    except Exception as exc:  # noqa: BLE001 — нет PG/нет таблицы → None, не роняем пульс
        logger.debug(
            "resume_score_history недоступен, качество резюме — нейтральный базис: %s", exc
        )

    # S3: свежесть синка getmatch /applications. Best-effort — нет PG/нет таблицы → None,
    # KPI не показываем, владельца не дёргаем.
    gm_last_sync_at: datetime | None = None
    try:
        from core.domains.opportunities.getmatch_sync import get_getmatch_last_sync_at

        gm_last_sync_at = await get_getmatch_last_sync_at(db=db)
    except Exception as exc:  # noqa: BLE001 — нет PG → None, не роняем пульс
        logger.debug("getmatch_sync_freshness недоступен: %s", exc)

    jobs = [
        _Job(
            id=r["id"],
            overall=r["overall_score"],
            score=r["score"] or {},
            salary=r["salary"],
            remote=r["remote_feasibility"],
            status=r["status"],
            created_at=_aware(r["created_at"]),
            scored_at=_aware(r["scored_at"]),
            is_skipped=bool(r["is_skipped"]),
            vacancy_id=r["vacancy_id"],
        )
        for r in job_rows
    ]
    stages = [_Stage(r["job_id"], r["stage"], _aware(r["changed_at"])) for r in stage_rows]
    offers = [
        _Offer(
            r["status"],
            _aware(r["created_at"]),
            vacancy_id=r["vacancy_id"],
            raw_text=r["raw_text"] or "",
        )
        for r in offer_rows
    ]
    snaps = [
        _Snap(
            _aware(r["captured_at"]),
            r["impressions"],
            r["views"],
            r["invitations"],
            r["recommended_vacancies"],
        )
        for r in snap_rows
        if r["resume_id"] != GETMATCH_PROFILE_RESUME_ID
    ]
    gm_snaps = [
        _Snap(
            _aware(r["captured_at"]),
            r["impressions"],
            r["views"],
            r["invitations"],
            r["recommended_vacancies"],
        )
        for r in snap_rows
        if r["resume_id"] == GETMATCH_PROFILE_RESUME_ID
    ]
    competency = [
        _CompetencyEntry(r["topic_canon"], r["level"], _aware(r["created_at"]))
        for r in competency_rows
    ]
    from core.domains.profile.profile import load_candidate_profile_enriched
    from core.domains.profile.structured_store import read_resume_data_for_account

    pulse_resume_data = await read_resume_data_for_account(account_id, db=db)
    pulse_profile = await load_candidate_profile_enriched(
        account_id=account_id, data=pulse_resume_data, db=db
    )

    return build_pulse(
        jobs,
        stages,
        offers,
        snaps,
        gm_snaps,
        competency,
        prior=prior,
        resume_score_now=resume_score_now,
        resume_score_ago=resume_score_ago,
        gm_last_sync_at=gm_last_sync_at,
        profile=pulse_profile,
        period_start=period_start,
        period_end=period_end,
        application_days_active=application_days_active,
        application_days_total=application_days_total,
        chat_active_threads=chat_active_threads,
        chat_stalled_threads=chat_stalled_threads,
        chat_progressing_threads=chat_progressing_threads,
    )
