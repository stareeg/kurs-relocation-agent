"""Численный вклад критериев в overall_score.

Владелец видел итоговое число и качественные уровни (grade_match.level, remote_abroad_compat.level,
burnout_risk.level / company_fit.level), но не видел, как они складываются в конкретный балл.
Эта функция формализует уровень → баллы одной чистой функцией.

Веса синхронизированы с prompts/opportunities/instructions.md §«Веса overall_score»
и prompts/opportunities/weights_spec.yaml. Пользовательские веса из AppSettings перекрывают дефолты.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.domains.opportunities.models import (
    SalaryInfo,
    ScoreResult,
    SkillRequirement,
    VacancyWorkTerms,
)
from core.domains.opportunities.skill_canon import skill_in
from core.kernel.money import detect_tax_basis, to_net
from core.kernel.schemas.track import DEFAULT_TRACK, SearchTrack

if TYPE_CHECKING:
    from core.domains.profile.international import InternationalReadiness
    from core.domains.profile.profile import SearchProfile

# role_content — самая тяжёлая ось (Этап 4, plans/scoring_precision_2026_08_17.md §1.6):
# единственная ось с доказанной предиктивной силой на решениях владельца (82 против 47 у
# откликнулся/нет), тогда как company почти плоская (+0.3), а salary внутри однородной
# группы ≥80 даже инвертирована (−1.0). Забрано у grade_match/company (15→10 каждая) —
# обе оси уже смягчены другими механизмами (grade_match — role_shift-долями, company —
# фолбэком по company_types), а не выброшены.
SALARY_WEIGHT = 20
WORK_FORMAT_WEIGHT = 20
GRADE_WEIGHT = 10
ROLE_CONTENT_WEIGHT = 25
MANAGEMENT_WEIGHT = 15
COMPANY_WEIGHT = 10

DEFAULT_WEIGHTS: dict[str, int] = {
    "salary": SALARY_WEIGHT,
    "work_format": WORK_FORMAT_WEIGHT,
    "grade_match": GRADE_WEIGHT,
    "role_content": ROLE_CONTENT_WEIGHT,
    "management": MANAGEMENT_WEIGHT,
    "company": COMPANY_WEIGHT,
}

# Второй трек (Э2.4): грейд и управление почти не значат, гибкость и ставка — почти всё.
FLEXIBILITY_WEIGHT = 25
COMPAT_WEIGHT = 20
RATE_WEIGHT = 20

SECOND_JOB_WEIGHTS: dict[str, int] = {
    "flexibility": FLEXIBILITY_WEIGHT,
    "role_content": ROLE_CONTENT_WEIGHT,
    "compat": COMPAT_WEIGHT,
    "rate": RATE_WEIGHT,
    "company": COMPANY_WEIGHT,
}

TRACK_WEIGHTS: dict[SearchTrack, dict[str, int]] = {
    "primary": DEFAULT_WEIGHTS,
    "second_job": SECOND_JOB_WEIGHTS,
}

# Булев путь: порога зарплаты в резюме нет (или вызывающий его не передал) — сравнивать числа
# не с чем, остаётся `meets_min` от модели. Доля «вилка не дотягивает» — та же, что у уровня
# "risky" остальных критериев.
_SALARY_NOT_MEETS_FRACTION = 0.45

# --- Зарплата: рампа вместо одного бита (plans/scoring_precision_2026_08_17.md §2.1) ---
#
# Самая тяжёлая ось несла ровно два значения на 336 вакансиях прода (9 или 20 баллов): вилка на
# 5% ниже порога и вилка вдвое ниже давали одно и то же число. Ниже — непрерывная доля по
# положению вилки относительно двух чисел, которые в резюме уже заполнены: `salary_min`
# («ниже не иду») и `salary_comfortable` («ради этого меняю работу»).

# Вилки нет / доверять нечему: ни плюс, ни минус.
SALARY_NEUTRAL_FRACTION = 0.55
# Ровно порог: годится, но без запаса. Между порогом и «комфортом» доля растёт до 1.0.
_SALARY_AT_MIN_FRACTION = 0.8
# Нижняя граница зоны «чуть ниже порога» (на _NEAR_MIN_EDGE × порога).
_SALARY_NEAR_MIN_FRACTION = 0.5
# Пол: ниже _HARD_LOW_EDGE × порога торговаться уже не о чем.
_SALARY_FLOOR_FRACTION = 0.15
_NEAR_MIN_EDGE = 0.85
_HARD_LOW_EDGE = 0.5

# Доверие к источнику вилки — множитель ОТКЛОНЕНИЯ от нейтрали, не самого балла: так
# `explicit` работает на полную, а `llm low` почти не двигает число. 81% решений по этой оси
# принимала LLM-догадка, и она проходила порог в 2.4 раза чаще названной вилки (§1.3).
_SALARY_TRUST_EXPLICIT = 1.0
_SALARY_TRUST_BY_CONFIDENCE: dict[str, float] = {"high": 0.8, "medium": 0.55, "low": 0.3}


@dataclass(frozen=True)
class SalaryPrefs:
    """Пороги зарплаты кандидата для рампы (срез CandidateProfile; override в тестах).

    `floor` — «Желаемая зарплата» резюме, `comfortable` — комфортная сумма (пусто →
    `floor × 1.3` — конвенция `CandidateProfile.salary_anchor_base`, второй закон не заводим).
    `basis` — шкала этих чисел (`net` / `gross`), чтобы сравнивать с вилкой в одних деньгах.
    """

    floor: int = 0
    comfortable: int = 0
    basis: str = "net"

    @property
    def is_set(self) -> bool:
        return self.floor > 0


def salary_prefs_from_profile(profile: SearchProfile) -> SalaryPrefs:
    """Срез SearchProfile → пороги зарплаты (без дублирования парсинга резюме)."""
    base = profile.salary_anchor_base()
    if base is None:
        return SalaryPrefs(basis=profile.salary_basis)
    floor, comfortable = base
    return SalaryPrefs(floor=floor, comfortable=comfortable, basis=profile.salary_basis)


def _range_tax_basis(salary: SalaryInfo) -> str:
    """Шкала сохранённой вилки — по её провенансу (см. `salary_estimator`).

    LLM просят оценить gross («gross, оценка»), корпус наблюдений хранит net «на руки»,
    у явной вилки шкала написана в самой вакансии. Молчание = как есть, без конвертации:
    та же конвенция, что у `salary_corpus.parse_net_range` (unclear не трогаем).
    """
    if salary.source == "llm":
        return "gross"
    if salary.source == "corpus":
        return "net"
    return detect_tax_basis(salary.value_or_range) or "net"


def _range_net_mid(salary: SalaryInfo) -> int | None:
    """Середина вилки в net-рублях; None — чисел нет.

    Середина, а не верх: верхняя граница переговорная и у оценок систематически оптимистична.
    Рыночная аналитика (`market._salary_net_mid`) считает распределение по той же середине.
    """
    values = [int(v) for v in (salary.estimated_min, salary.estimated_max) if v and v > 0]
    if not values:
        return None
    mid = (min(values) + max(values)) // 2
    return to_net(mid, tax_basis=_range_tax_basis(salary))


def _salary_ramp(mid_net: int, floor_net: int, comfort_net: int) -> float:
    """Положение вилки относительно порогов резюме → доля веса 0.15…1.0 (монотонно)."""
    if mid_net >= comfort_net:
        return 1.0
    if mid_net >= floor_net:
        span = comfort_net - floor_net
        if span <= 0:  # comfortable == floor: выше порога сразу максимум
            return 1.0
        share = (mid_net - floor_net) / span
        return _SALARY_AT_MIN_FRACTION + (1.0 - _SALARY_AT_MIN_FRACTION) * share

    near = floor_net * _NEAR_MIN_EDGE
    if mid_net >= near:
        share = (mid_net - near) / (floor_net - near)
        return (
            _SALARY_NEAR_MIN_FRACTION
            + (_SALARY_AT_MIN_FRACTION - _SALARY_NEAR_MIN_FRACTION) * share
        )

    hard = floor_net * _HARD_LOW_EDGE
    if mid_net <= hard:
        return _SALARY_FLOOR_FRACTION
    share = (mid_net - hard) / (near - hard)
    return _SALARY_FLOOR_FRACTION + (_SALARY_NEAR_MIN_FRACTION - _SALARY_FLOOR_FRACTION) * share


def _salary_trust(salary: SalaryInfo) -> float:
    """Насколько вилке верим: названная — полностью, оценённая — по её confidence."""
    source = salary.source or "none"
    if source == "none":
        return 0.0
    if source == "explicit":
        return _SALARY_TRUST_EXPLICIT
    return _SALARY_TRUST_BY_CONFIDENCE.get(salary.confidence, _SALARY_TRUST_BY_CONFIDENCE["low"])


def salary_fraction(salary: SalaryInfo, prefs: SalaryPrefs | None) -> float:
    """Доля веса «Зарплата»: рампа по числам вилки, приглушённая доверием к источнику.

    `prefs is None` / порог не задан → старое булево поведение по `meets_min`: числа не с чем
    сравнивать. `meets_min` остаётся в контракте для UI и фильтров, но балл на нём больше
    не висит (plans/scoring_precision_2026_08_17.md §2.1–2.2).
    """
    bool_fraction = 1.0 if salary.meets_min else _SALARY_NOT_MEETS_FRACTION
    if prefs is None or not prefs.is_set:
        return bool_fraction

    mid_net = _range_net_mid(salary)
    if mid_net is None:
        # Чисел нет (фон ещё считает / старый jsonb) — остаётся булев вердикт модели, и его
        # ниже приглушит доверие: у `source = none` оно нулевое, то есть ровно нейтраль.
        raw = bool_fraction
    else:
        comfortable = max(prefs.comfortable, prefs.floor)
        floor_net = to_net(prefs.floor, tax_basis=prefs.basis) or prefs.floor
        comfort_net = to_net(comfortable, tax_basis=prefs.basis) or floor_net
        raw = _salary_ramp(mid_net, floor_net, comfort_net)

    trust = _salary_trust(salary)
    return SALARY_NEUTRAL_FRACTION + (raw - SALARY_NEUTRAL_FRACTION) * trust


_WORK_FORMAT_FRACTION: dict[str, float] = {
    "ideal": 1.0,
    "ok": 1.0,
    "risky": 0.6,
    "blocker": 0.0,
}

# Относительно целевого грейда из резюме. above < 1.0: переквалификация вверх -
# частая причина отказа, не бонус.
_GRADE_FRACTION: dict[str, float] = {
    "above": 0.9,
    "match": 1.0,
    "slightly_below": 0.6,
    "far_below": 0.25,
    "off_profile": 0.0,
}

# `off_profile` = «не про эту роль» покрывал две разные ситуации: другую специальность и сдвиг
# IC↔менеджмент внутри своей (plans/scoring_precision_2026_08_17.md §1.8). Для второй цена
# сдвига зависит от того, насколько кандидат привязан к своей стороне: `hands_on` теряет
# заметно, `mixed` / `management` - мягко (владелец на «AI product manager» откликнулся).
# Направление задаёт role_kind резюме, а не метка модели и не спека весов.
_ROLE_SHIFT_GRADE_FRACTION: dict[str, float] = {
    "hands_on": 0.3,
    "management": 0.8,
    "mixed": 0.8,
    "unknown": 0.55,
}

# Доля баллов по «Управление» зависит от role_kind кандидата (SearchProfile).
# hands_on: мало управления = хорошо; management: наоборот; mixed: крайности чуть хуже середины,
# но людей совсем без управления — чуть хуже, чем чистый people-management (plans/
# scoring_precision_2026_08_17.md §Этап 3: для mixed управление людьми дороже, чем его отсутствие).
_MANAGEMENT_FRACTION_BY_ROLE: dict[str, dict[str, float]] = {
    "hands_on": {"low": 1.0, "medium": 0.6, "high": 0.2},
    "management": {"high": 1.0, "medium": 0.7, "low": 0.3},
    "mixed": {"medium": 1.0, "low": 0.85, "high": 0.7},
    "unknown": {"low": 0.8, "medium": 0.8, "high": 0.8},
}

_COMPANY_FRACTION: dict[str, float] = {
    "strong": 1.0,
    "ok": 0.7,
    "weak": 0.25,
    "unknown": 0.55,
}

# Фолбэк, если LLM ещё не вернула company_fit (старые score jsonb).
# Не-IT отрасли = 0.55 как unknown: сегмент сам по себе не минус; сигнал — company_fit.
_COMPANY_TYPE_FRACTION: dict[str, float] = {
    "product": 1.0,
    "fintech_product": 1.0,
    "bank": 0.75,
    "infra": 0.7,
    "startup": 0.55,
    "outsource": 0.25,
    "agency": 0.55,
    "media": 0.55,
    "retail": 0.55,
    "manufacturing": 0.55,
    "education": 0.55,
    "government": 0.55,
    "nonprofit": 0.55,
    "smb": 0.55,
    "unknown": 0.55,
}

# Этап 6 §6.4 (plans/scoring_precision_2026_08_17.md): таблица выше одинакова для всех кандидатов
# («аутсорс» всегда 0.25), хотя резюме уже несёт явное предпочтение — `position.company_types`,
# закрытый список чипов `CANDIDATE_COMPANY_TYPES` (frontend/src/lib/resume-taxonomy.ts). Кандидат,
# отметивший «Аутсорс», не должен получать тот же минус, что и тот, кто его не отмечал. Русские
# ярлыки чипов и английские слаги `company_type` (LLM-классификация вакансии) — разные словари,
# мэппинг между ними closed (5 ярлыков кандидата: биг тех / продукт / аутсорс / аутстафф /
# стартап). Ярлык «Валютка» из этого списка убран: он описывал валюту оклада, а не тип
# компании, и поэтому не мапился ни на один слаг — чип был, а влияния на балл у него не было.
_CANDIDATE_COMPANY_TYPE_MAP: dict[str, frozenset[str]] = {
    "биг тех": frozenset({"product", "infra"}),
    "продукт": frozenset({"product", "fintech_product"}),
    "аутсорс": frozenset({"outsource"}),
    "аутстафф": frozenset({"outsource"}),
    "стартап": frozenset({"startup"}),
}
_CANDIDATE_COMPANY_TYPE_MATCH_FRACTION = 0.8
_CANDIDATE_COMPANY_TYPE_MISMATCH_FRACTION = 0.35


def _company_type_fraction(
    company_type: str, candidate_company_types: Iterable[str] | None
) -> float:
    """Фолбэк-доля веса «Компания», когда LLM не смогла определить `company_fit.level`.

    Резюме-осведомлённая версия `_COMPANY_TYPE_FRACTION`: если кандидат явно отметил допустимые
    типы компаний, вакансия сверяется с НИМИ, а не с одной таблицей на всех кандидатов. Пустой
    список предпочтений (ничего не отмечено) → прежнее поведение (статическая таблица) без
    изменений — так резюме без заполненной оси не проседают в поведении.
    """
    if company_type == "unknown":
        return _COMPANY_TYPE_FRACTION["unknown"]
    accepted: set[str] = set()
    for raw in candidate_company_types or []:
        accepted |= _CANDIDATE_COMPANY_TYPE_MAP.get(str(raw).strip().casefold(), frozenset())
    if not accepted:
        return _COMPANY_TYPE_FRACTION.get(company_type, 0.55)
    return (
        _CANDIDATE_COMPANY_TYPE_MATCH_FRACTION
        if company_type in accepted
        else _CANDIDATE_COMPANY_TYPE_MISMATCH_FRACTION
    )


# --- role_content: детерминированный оверлап навыков как под-сигнал (Этап 4 §4.3) ---
#
# `vacancy_skill_requirements` уже считается фоном (события `on_vacancy_scored`) и раньше в
# скор не входил. Доля веса LLM-оценки понижена, чтобы субъективная сторона ("насколько роль
# ощущается близкой") оставалась ведущей, а детерминированный оверлап её только подтверждал.
_ROLE_CONTENT_LLM_SHARE = 0.65
_ROLE_CONTENT_SKILL_SHARE = 0.35


def _candidate_skill_credits(
    key_skills: Iterable[str], niches: Iterable[str]
) -> list[tuple[str, float]]:
    """Кандидатские названия → вес засчитываемого совпадения.

    `key_skills` — полный вес (это явный тег «я это умею»). `niches` — вес по месту в
    приоритетном списке (Этап 4 §4.4: «совпадение с приоритетом №1 весит больше, чем с №6»):
    первая ниша получает полный вес, последняя — пол в 0.5, между ними линейно. Список из
    одной ниши/пустой — тоже полный вес (ранжировать нечего).
    """
    credits = [(s, 1.0) for s in key_skills]
    ordered = list(niches)
    span = len(ordered) - 1
    for idx, niche in enumerate(ordered):
        weight = 1.0 if span <= 0 else 1.0 - 0.5 * idx / span
        credits.append((niche, weight))
    return credits


def skill_overlap_fraction(
    required: list[SkillRequirement] | None,
    *,
    key_skills: Iterable[str] = (),
    niches: Iterable[str] = (),
) -> float | None:
    """Доля required-навыков вакансии, покрытых key_skills/niches резюме (после канона).

    `None` — по вакансии ещё нет посчитанных требований (фон не успел / кэша нет) **или**
    среди них нет ни одного `required` (только preferred) — сравнивать не с чем, и это не то
    же самое, что «покрытие 0»: `role_content_fraction` тогда не подмешивает под-сигнал вовсе,
    держит долю на чистом llm_score (plans/scoring_precision_2026_08_17.md §4.3 — «если
    требований нет, компонента нейтральна», балл не должен падать из-за нехватки данных).
    """
    if required is None:
        return None
    must = [r for r in required if r.importance == "required"]
    if not must:
        return None

    candidates = _candidate_skill_credits(key_skills, niches)
    total = 0.0
    for req in must:
        best = 0.0
        for name, weight in candidates:
            if weight > best and skill_in(req.skill, [name]):
                best = weight
        total += best
    return total / len(must)


def role_content_fraction(llm_score: int, skill_overlap: float | None) -> float:
    """Доля веса «Содержание роли»: смесь субъективной оценки LLM и детерминированного оверлапа.

    `skill_overlap is None` (требований по вакансии ещё нет) → чистый llm_score, без смеси —
    компонента нейтральна, а не штраф за отсутствие данных.
    """
    llm_frac = max(0.0, min(1.0, llm_score / 100))
    if skill_overlap is None:
        return llm_frac
    return _ROLE_CONTENT_LLM_SHARE * llm_frac + _ROLE_CONTENT_SKILL_SHARE * skill_overlap


# --- Второй трек: гибкость / совместимость / ставка (Э2.4 / Э2.5) ---
#
# Нет данных ≠ ноль: неизвестное поле даёт нейтраль 0.55, как SALARY_NEUTRAL_FRACTION.
# Иначе экстракция, которая не успела, молча роняла бы балл (§4.3 плана точности).

_ASYNC_FRACTION = {"async_first": 1.0, "hybrid_sync": 0.6, "sync_heavy": 0.2, "unknown": 0.55}
_TRACKING_FRACTION = {"none": 1.0, "optional": 0.7, "required": 0.15, "unknown": 0.55}
_MEETING_FRACTION = {"low": 1.0, "medium": 0.6, "high": 0.25, "unknown": 0.55}
_FLEX_ASYNC_SHARE, _FLEX_TRACKING_SHARE, _FLEX_MEETING_SHARE = 0.40, 0.35, 0.25
_ON_CALL_PENALTY = 0.25

_ENGAGE_TO_CONTRACT = {
    "employment": "employment",
    "contractor": "gph",
    "b2b": "ip",
    "freelance": "self_employed",
    "internship": "employment",
}
_GEO_TOKEN_TO_REGION: dict[str, str] = {
    "emea": "EMEA",
    "eu": "EMEA",
    "europe": "EMEA",
    "uk": "UK",
    "gb": "UK",
    "us-east": "US-East",
    "us-west": "US-West",
    "pst": "US-West",
    "pt": "US-West",
    "pacific": "US-West",
    "et": "US-East",
    "est": "US-East",
    "eastern": "US-East",
    "us": "US-East",
    "usa": "US-East",
    "apac": "APAC",
    "asia": "APAC",
}
RATE_CORPUS_MIN = 8


def flexibility_fraction(terms: VacancyWorkTerms | None) -> float:
    """Доля веса «Гибкость». `terms is None` → 0.55 (нейтраль, не штраф за отсутствие данных)."""
    if terms is None:
        return SALARY_NEUTRAL_FRACTION
    base = (
        _FLEX_ASYNC_SHARE * _ASYNC_FRACTION.get(terms.async_culture, 0.55)
        + _FLEX_TRACKING_SHARE * _TRACKING_FRACTION.get(terms.time_tracking, 0.55)
        + _FLEX_MEETING_SHARE * _MEETING_FRACTION.get(terms.meeting_load, 0.55)
    )
    if terms.on_call:
        base = max(0.0, base - _ON_CALL_PENALTY)
    return max(0.0, min(1.0, base))


def _region_from_hiring_geo(hiring_geo: list[str]) -> str | None:
    """Первый распознанный регион из того, как написано в JD. Неизвестное → None, не угадываем."""
    for raw in hiring_geo:
        token = (raw or "").strip().casefold().replace("_", "-")
        if token in ("worldwide", "world", "anywhere", "remote"):
            return None
        mapped = _GEO_TOKEN_TO_REGION.get(token)
        if mapped:
            return mapped
        for key, region in _GEO_TOKEN_TO_REGION.items():
            if key in token:
                return region
    return None


def _overlap_component(terms: VacancyWorkTerms, intl: InternationalReadiness) -> float:
    required = terms.overlap_hours_required
    overlap = intl.overlap or {}
    if required is None:
        return SALARY_NEUTRAL_FRACTION
    if required <= 0:
        return 1.0
    region = _region_from_hiring_geo(terms.hiring_geo)
    if region:
        available = int(overlap.get(region, 0))
    elif overlap:
        available = max(overlap.values())
    else:
        return SALARY_NEUTRAL_FRACTION
    return max(0.0, min(1.0, available / required))


def _engagement_component(terms: VacancyWorkTerms, intl: InternationalReadiness) -> float:
    if terms.engagement == "unknown":
        return SALARY_NEUTRAL_FRACTION
    wanted = _ENGAGE_TO_CONTRACT.get(terms.engagement)
    accepted = set(intl.contract_forms or ())
    if not wanted or not accepted:
        return SALARY_NEUTRAL_FRACTION
    return 1.0 if wanted in accepted else 0.3


def _geo_component(terms: VacancyWorkTerms, intl: InternationalReadiness) -> float:
    if terms.geo_scope == "worldwide":
        return 1.0
    if terms.residency_required:
        return 0.2
    if terms.geo_scope == "unknown":
        return SALARY_NEUTRAL_FRACTION
    if terms.geo_scope == "single_city":
        return 0.25
    regions = set(intl.work_regions or ())
    if not regions:
        return SALARY_NEUTRAL_FRACTION
    mapped = _region_from_hiring_geo(terms.hiring_geo)
    if mapped is None:
        return 0.7 if terms.geo_scope == "region" else SALARY_NEUTRAL_FRACTION
    return 1.0 if mapped in regions else 0.35


def compat_fraction(terms: VacancyWorkTerms | None, intl: InternationalReadiness | None) -> float:
    """0.45 × пересечение часов + 0.35 × форма найма + 0.20 × география."""
    if terms is None or intl is None:
        return SALARY_NEUTRAL_FRACTION
    return max(
        0.0,
        min(
            1.0,
            0.45 * _overlap_component(terms, intl)
            + 0.35 * _engagement_component(terms, intl)
            + 0.20 * _geo_component(terms, intl),
        ),
    )


def rate_fraction(
    terms: VacancyWorkTerms | None,
    *,
    floor: int | None = None,
    n_obs: int = 0,
) -> float:
    """Ставка в валюте вакансии против пола корпуса той же валюты/периода.

    Наблюдений меньше `RATE_CORPUS_MIN` или нет чисел → нейтраль 0.55. Без FX:
    рубли и доллары на одну шкалу не смешиваются.
    """
    if terms is None:
        return SALARY_NEUTRAL_FRACTION
    values = [v for v in (terms.rate_min, terms.rate_max) if v and v > 0]
    if not values or n_obs < RATE_CORPUS_MIN or not floor or floor <= 0:
        return SALARY_NEUTRAL_FRACTION
    mid = (min(values) + max(values)) // 2
    # Та же рампа, что у рублёвой оси, но без налоговой конвертации: шкала уже в валюте JD.
    comfort = max(floor, int(floor * 1.3))
    return _salary_ramp(mid, floor, comfort)


def resolve_weights(
    weights: Mapping[str, int] | None, *, track: SearchTrack = DEFAULT_TRACK
) -> dict[str, int]:
    """Сырой вход → канонический словарь весов своего трека, сумма всегда 100."""
    base = dict(TRACK_WEIGHTS.get(track, DEFAULT_WEIGHTS))
    if not weights:
        return base
    out = dict(base)
    legacy = dict(weights)
    if track == "primary" and "management" not in legacy and "burnout" in legacy:
        legacy["management"] = int(legacy["burnout"])
    for key in base:
        if key in legacy:
            out[key] = int(legacy[key])
    total = sum(out.values())
    if total != 100 and total > 0:
        scaled = {k: round(v * 100 / total) for k, v in out.items()}
        diff = 100 - sum(scaled.values())
        top = max(scaled, key=lambda k: scaled[k])
        scaled[top] += diff
        return scaled
    return out


def _company_points(
    score: ScoreResult,
    weight: int,
    candidate_company_types: Iterable[str] | None,
) -> int:
    company_level = score.company_fit.level if score.company_fit.level != "unknown" else ""
    if company_level:
        company_frac = _COMPANY_FRACTION.get(company_level, 0.55)
    else:
        company_frac = _company_type_fraction(score.company_type, candidate_company_types)
    return round(weight * company_frac)


def compute_score_breakdown(
    score: ScoreResult,
    weights: Mapping[str, int] | None = None,
    *,
    role_kind: str = "unknown",
    salary_prefs: SalaryPrefs | None = None,
    skill_overlap: float | None = None,
    candidate_company_types: Iterable[str] | None = None,
    track: SearchTrack = DEFAULT_TRACK,
    terms: VacancyWorkTerms | None = None,
    intl: InternationalReadiness | None = None,
    rate_floor: int | None = None,
    rate_n_obs: int = 0,
) -> dict[str, int]:
    """Вклад каждого критерия в баллах overall_score.

    Считается по под-полям ответа модели, не по итоговому overall_score. При переданных
    `weights` вклад масштабируется под приоритеты. `track` выбирает рубрику: основной
    набор осей или второй (гибкость / совместимость / ставка). `terms is None` и
    неизвестные поля второго трека дают нейтраль 0.55, не ноль.
    """
    w = resolve_weights(weights, track=track)
    if track == "second_job":
        return {
            "flexibility": round(w["flexibility"] * flexibility_fraction(terms)),
            "role_content": round(
                w["role_content"]
                * role_content_fraction(score.role_content_match.score, skill_overlap)
            ),
            "compat": round(w["compat"] * compat_fraction(terms, intl)),
            "rate": round(w["rate"] * rate_fraction(terms, floor=rate_floor, n_obs=rate_n_obs)),
            "company": _company_points(score, w["company"], candidate_company_types),
        }

    salary_points = round(w["salary"] * salary_fraction(score.salary, salary_prefs))
    work_format_points = round(
        w["work_format"] * _WORK_FORMAT_FRACTION.get(score.remote_abroad_compat.level, 0.5)
    )
    if score.grade_match.is_role_shift:
        grade_frac = _ROLE_SHIFT_GRADE_FRACTION.get(
            role_kind, _ROLE_SHIFT_GRADE_FRACTION["unknown"]
        )
    else:
        grade_frac = _GRADE_FRACTION.get(score.grade_match.level, 0.0)
    grade_points = round(w["grade_match"] * grade_frac)
    role_content_points = round(
        w["role_content"] * role_content_fraction(score.role_content_match.score, skill_overlap)
    )
    mgmt_table = _MANAGEMENT_FRACTION_BY_ROLE.get(
        role_kind, _MANAGEMENT_FRACTION_BY_ROLE["unknown"]
    )
    management_points = round(w["management"] * mgmt_table.get(score.burnout_risk.level, 0.8))

    return {
        "salary": salary_points,
        "work_format": work_format_points,
        "grade_match": grade_points,
        "role_content": role_content_points,
        "management": management_points,
        "company": _company_points(score, w["company"], candidate_company_types),
    }
