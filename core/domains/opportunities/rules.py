"""Постпроцессинг overall_score: гейты, мягкие калибровки и правила компаний.

Предпочтения кандидата — из SearchProfile (`allows_*`, `travel_is_dealbreaker`, `role_kind`),
не из owner-хардкода. FR2-43: автоправила target/avoid (+5 / гейт→skip); ручные
`company_adjustments` в AppSettings — опциональный power-user слой (дефолт []).

Гейт — флаг, а не множитель (plans/scoring_precision_2026_08_17.md §1.4): он форсит
`recommendation = skip`, но `overall_score` остаётся взвешенной суммой «насколько подходит
по существу». Мультипликативный кап делал две вещи сразу — помечал дилбрейкер и портил число —
из-за чего середина шкалы 40–60 проваливалась (7% базы), а «зарезанная сильная» вакансия
сортировалась выше честной средней.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.domains.opportunities.jobs import company_canonical_for
from core.domains.opportunities.models import ScoreAdjustment, ScoreResult, VacancyWorkTerms
from core.domains.opportunities.score_breakdown import (
    SalaryPrefs,
    compute_score_breakdown,
    resolve_weights,
)
from core.domains.opportunities.weights_version import compute_weights_version
from core.kernel.schemas.track import DEFAULT_TRACK, SearchTrack
from core.platform.observability import event

if TYPE_CHECKING:
    from core.domains.profile.international import InternationalReadiness
    from core.domains.profile.model import ResumeData
    from core.domains.profile.profile import SearchProfile

logger = logging.getLogger(__name__)

# Единые константы лайк/дизлайк. Avoid — жёсткий гейт (флаг) → recommendation=skip.
TARGET_COMPANY_DELTA = 5

# Маркеры секции «### Жёсткие гейты» в prompts/opportunities/instructions.md, которые
# `detect_gates` реально форсит в recommendation=skip (бейдж gate_triggered).
# Порядок = порядок маркеров в промпте (без «Зарплата»: её цену считает рампа в
# `score_breakdown.salary_fraction`, гейтом зарплата не бывает — Этап 2 §2.1).
# FR2-79: тест парсит заголовки секции и сверяет с этим списком.
HARD_GATE_SKIP_MARKERS: tuple[str, ...] = (
    "Формат",
    "Компания из «избегать»",
    "Грейд (предпочтение, мягче)",
)

HARD_GATE_SKIP_MARKERS_BY_TRACK: dict[SearchTrack, tuple[str, ...]] = {
    "primary": HARD_GATE_SKIP_MARKERS,
    "second_job": (
        "Право на работу",
        "Физическое присутствие",
        "Эксклюзивность",
        "Окно пересечения",
        "Компания из «избегать»",
        "Другая профессия",
    ),
}

# Мягкие минусы, когда из двух улик второго трека сработала одна (не гейт).
WORK_AUTH_CONFLICT_DELTA = -12
PRESENCE_CONFLICT_DELTA = -10
EXCLUSIVITY_CONFLICT_DELTA = -15
OVERLAP_NEAR_DELTA = -8
MARKET_SCOPE_CONFLICT_DELTA = -10

_WORK_AUTH_PATTERNS = (
    "must be authorized to work",
    "w-2 only",
    "w2 only",
    "no c2c",
    "eligible to work in",
    "требуется резидентство",
)
_EXCLUSIVITY_PATTERNS = (
    "full-time only",
    "no other employment",
    "no moonlighting",
    "не совмещать",
)
_ONSITE_RE = re.compile(
    r"on-?site|офис\s*\d|hybrid\s+\d|гибрид\s+\d",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Adjustment:
    delta: int
    reason: str


@dataclass(frozen=True)
class CandidateFormatPrefs:
    """Срез SearchProfile для гейтов формата/командировок (override в тестах).

    Канон парсинга — `core.domains.profile.profile`, срез строит `format_prefs_from_profile`.
    Файлового фолбэка сознательно нет (Этап 8 §8.5, D14): `load_candidate_format_prefs()`
    читала `load_search_profile()` без account_id — в мульти-аккаунтном деплое это могло тихо
    подставить резюме владельца вместо резюме аккаунта запроса. `scorer` всегда резолвит профиль
    сам и передаёт срез явно.
    """

    allows_office: bool
    allows_hybrid: bool
    allows_remote: bool
    travel_is_dealbreaker: bool

    @property
    def schedule_filled(self) -> bool:
        return self.allows_office or self.allows_hybrid or self.allows_remote


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


def _is_office_only(text: str) -> bool:
    """Строка «формат работы: …» говорит «только на месте».

    «Гибрид» в allowlist обязателен: «на месте работодателя или гибрид» — штатная формулировка
    hh именно для гибрида, а не для офиса-only. Без него 21 из 58 формат-гейтов на проде были
    ложными (plans/scoring_precision_2026_08_17.md §1.2).
    """
    fmt = re.search(r"формат работы:\s*([^\n]+)", text)
    if fmt:
        line = fmt.group(1)
        if _contains_any(line, ("удалён", "удален", "remote", "дистанцион", "гибрид", "hybrid")):
            return False
        if _contains_any(line, ("на месте", "офис")):
            return True
    return _contains_any(text, ("только офис", "офис 5/5"))


def _is_hybrid_only(text: str) -> bool:
    has_hybrid = _contains_any(text, ("гибрид", "hybrid"))
    has_remote = _contains_any(text, ("удалённо", "удаленно", "remote"))
    return has_hybrid and not has_remote


def _is_remote_uncertain(text: str) -> bool:
    return _contains_any(
        text,
        (
            "по договорённости с руководителем",
            "по договоренности с руководителем",
            "удалёнка по договорённости",
        ),
    )


def _has_travel(text: str) -> bool:
    # Только «командиров*». Города из личной истории владельца к командировкам
    # не относятся — не хардкодить.
    return "командиров" in text


# Мягкие минусы формата, когда регекс по JD и вердикт модели расходятся (§1.2 плана):
# модель сказала «формат подходит», а в тексте офис-only — сигнал есть, но на дилбрейкер
# двух независимых улик не набралось.
FORMAT_CONFLICT_DELTA = -8
# Модель сказала `risky` (формат вне допустимых, но вакансия гибкая), JD подтверждает офис —
# вес формата уже срезан на 40% в breakdown, здесь только добавка за подтверждение из текста.
FORMAT_RISKY_DELTA = -5


@dataclass(frozen=True)
class FormatVerdict:
    """Решение по формату: жёсткий гейт, мягкий минус или ничего.

    `conflict` — улики спорят (повод для WARNING в логах: либо регекс слеп, либо модель).
    """

    gate: bool = False
    delta: int = 0
    reason: str = ""
    conflict: bool = False


def evaluate_format(
    level: str,
    text: str,
    prefs: CandidateFormatPrefs,
    hr_format_override: str = "unknown",
) -> FormatVerdict:
    """Формат-гейт по двум независимым уликам: вердикт модели + регекс по тексту вакансии.

    `level` — `score.remote_abroad_compat.level`, `text` — текст вакансии в lower().

    До Этапа 1 гейт читал только регекс, хотя instructions.md §«Жёсткие гейты» объявляла
    условием именно `level == "blocker"`. На проде это давало расхождение в обе стороны:
    21 ложный гейт из 58 («на месте работодателя или гибрид») и 51 непойманный blocker из 91
    (plans/scoring_precision_2026_08_17.md §1.2). Правило:

    - `blocker` → гейт, даже если регекс молчит (модель прочитала текст лучше регекса);
    - регекс говорит офис-only, а модель `ok`/`ideal` → не гейт, а мягкий минус + пометка
      о расхождении;
    - `risky` → мягкий минус, не гейт.

    Слова HR (`hr_format_override`) перекрывают и JD, и вердикт модели. Пустой schedule
    в резюме — гейты формата молчат (кандидат ещё не заполнил допустимые форматы).
    """
    if not prefs.schedule_filled or hr_format_override in ("remote", "hybrid"):
        return FormatVerdict()

    office_only = _is_office_only(text)
    if level == "blocker":
        return FormatVerdict(
            gate=True,
            reason="формат вакансии вне допустимых форматов резюме",
            conflict=not office_only,
        )
    # Регекс ловит только «офис-only», и это проблема, лишь когда офис не среди допустимых.
    if not office_only or prefs.allows_office:
        return FormatVerdict()
    if level in ("ok", "ideal"):
        return FormatVerdict(
            delta=FORMAT_CONFLICT_DELTA,
            reason="расхождение: в тексте офис-only, вердикт модели — формат подходит",
            conflict=True,
        )
    return FormatVerdict(
        delta=FORMAT_RISKY_DELTA,
        reason="формат под вопросом: в тексте офис-only",
    )


def format_prefs_from_profile(profile: SearchProfile) -> CandidateFormatPrefs:
    """Срез SearchProfile → prefs формата (без дублирования парсинга резюме)."""
    return CandidateFormatPrefs(
        allows_office=profile.allows_office,
        allows_hybrid=profile.allows_hybrid,
        allows_remote=profile.allows_remote,
        travel_is_dealbreaker=profile.travel_is_dealbreaker,
    )


@dataclass(frozen=True)
class CompanyAdjustmentRule:
    """Одна строка персональной калибровки компаний/доменов.

    `match` — варианты подстрок (OR, lower-cased текст вакансии) для ручных AppSettings.
    `company_canonical` — матч по канону работодателя (лайк/дизлайк из критериев поиска);
    когда задан, подстроки `match` не используются.
    `gate` — правило-дилбрейкер: `detect_gates` вернёт по нему бейдж → recommendation=skip.
    """

    match: tuple[str, ...]
    delta: int
    reason: str
    gate: bool = False
    company_canonical: str | None = None


def rules_from_search_lists(
    target_companies: Iterable[str] | None,
    avoid_companies: Iterable[str] | None,
) -> list[CompanyAdjustmentRule]:
    """Автоправила из лайк/дизлайк списков резюме. Без LLM."""
    rules: list[CompanyAdjustmentRule] = []
    seen: set[str] = set()

    for name in target_companies or ():
        canon = company_canonical_for(name) or (name or "").strip()
        if not canon or canon in seen:
            continue
        seen.add(canon)
        rules.append(
            CompanyAdjustmentRule(
                match=(),
                delta=TARGET_COMPANY_DELTA,
                reason=f"целевая компания: {canon}",
                company_canonical=canon,
            )
        )

    for name in avoid_companies or ():
        canon = company_canonical_for(name) or (name or "").strip()
        if not canon or canon in seen:
            continue
        seen.add(canon)
        rules.append(
            CompanyAdjustmentRule(
                match=(),
                delta=0,
                reason=f"избегать: {canon}",
                gate=True,
                company_canonical=canon,
            )
        )
    return rules


def _manual_covers_company(rule: CompanyAdjustmentRule, company_canon: str) -> bool:
    """Ручное правило «про эту компанию» — конфликт с list-rule для того же канона."""
    folded = company_canon.casefold()
    for raw in rule.match:
        token = (raw or "").strip()
        if not token:
            continue
        if company_canonical_for(token) == company_canon:
            return True
        low = token.casefold()
        if low in folded or folded in low:
            return True
    return False


def company_rules_from_settings(raw: list[dict] | None) -> list[CompanyAdjustmentRule]:
    """jsonb AppSettings → правила. Битые элементы пропускаем.

    Ключ `cap` в сохранённых настройках (и в транспортной `api.schemas.resume.CompanyAdjustment`)
    остаётся маркером «это дилбрейкер»: само число с Этапа 1 ничего не умножает (§1.4 плана),
    поэтому любой непустой `cap` читаем как `gate=True` — форму настроек ради этого не ломаем.
    """
    if not raw:
        return []
    out: list[CompanyAdjustmentRule] = []
    for item in raw:
        try:
            match = tuple(str(m) for m in (item.get("match") or []) if str(m).strip())
            if not match:
                continue
            out.append(
                CompanyAdjustmentRule(
                    match=match,
                    delta=int(item.get("delta") or 0),
                    reason=str(item.get("reason") or ""),
                    gate=bool(item.get("gate")) or item.get("cap") is not None,
                )
            )
        except (TypeError, ValueError):
            continue
    return out


async def load_manual_company_adjustments(account_id: int | None) -> list[CompanyAdjustmentRule]:
    """Ручные правила аккаунта запроса. Дефолт/ошибка PG → [] (без owner-хардкода).

    `account_id` — обязателен явно (plans/multitenancy_gaps_2026_08_06.md §3.14): скоринг
    (единственный вызывающий) уже знает аккаунт запроса, подстановка владельца-по-умолчанию
    здесь была бы ровно той доменной глубиной, которая теряет личность.
    """
    try:
        from core.platform.repo.settings import DEFAULT_COMPANY_ADJUSTMENTS, get_setting

        raw = await get_setting(
            "company_adjustments", default=DEFAULT_COMPANY_ADJUSTMENTS, account_id=account_id
        )
        if not isinstance(raw, list):
            return []
        return company_rules_from_settings(raw)
    except Exception as exc:  # noqa: BLE001 — нет PG → без ручных правил
        logger.debug("company_adjustments из настроек недоступны: %s", exc)
        return []


def load_list_company_adjustments(data: ResumeData) -> list[CompanyAdjustmentRule]:
    """Правила из target/avoid резюме аккаунта запроса (уже резолвленного вызывающим)."""
    try:
        sc = data.search_criteria
        return rules_from_search_lists(sc.target_companies, sc.avoid_companies)
    except Exception as exc:  # noqa: BLE001 — битое резюме → без list-правил
        logger.debug("list company_adjustments из резюме недоступны: %s", exc)
        return []


def _matched_company_adjustments(
    text: str,
    company_adjustments: list[CompanyAdjustmentRule] | None,
    *,
    company: str | None = None,
    list_rules: list[CompanyAdjustmentRule] | None = None,
) -> list[CompanyAdjustmentRule]:
    """Сработавшие правила: ручные (подстрока JD) + списки (канон компании).

    При конфликте по одной компании (лайкнули Сбербанк, а в AppSettings есть ручной штраф
    по «сбербанк») — только ручная запись. `None` и `[]` — без ручных правил.
    """
    manual = company_adjustments or []
    manual_matched = [r for r in manual if r.match and _contains_any(text, r.match)]

    company_canon = company_canonical_for(company)
    list_matched: list[CompanyAdjustmentRule] = []
    if company_canon:
        for rule in list_rules or ():
            if rule.company_canonical != company_canon:
                continue
            if any(_manual_covers_company(mr, company_canon) for mr in manual_matched):
                continue
            list_matched.append(rule)

    return manual_matched + list_matched


def compute_adjustments(
    score: ScoreResult,
    vacancy_text: str,
    hr_format_override: str = "unknown",
    company_adjustments: list[CompanyAdjustmentRule] | None = None,
    *,
    company: str | None = None,
    list_rules: list[CompanyAdjustmentRule] | None = None,
    format_prefs: CandidateFormatPrefs,
    vacancy_id: str | None = None,
) -> list[Adjustment]:
    text = vacancy_text.lower()
    adj: list[Adjustment] = []
    prefs = format_prefs

    for rule in _matched_company_adjustments(
        text, company_adjustments, company=company, list_rules=list_rules
    ):
        if rule.delta:
            adj.append(Adjustment(rule.delta, rule.reason))

    # Командировки — только если кандидат отметил это стоп-условием в резюме.
    if prefs.travel_is_dealbreaker and _has_travel(text):
        adj.append(Adjustment(-5, "обязательные командировки"))

    # Формат: мягкие минусы только относительно допустимых форматов резюме.
    # Пустой schedule — не навязываем remote-only (друг ещё не заполнил).
    # JS-8.1: HR подтвердил удалёнку → stale JD-минусы снимаем.
    if hr_format_override != "remote" and prefs.schedule_filled:
        fmt = evaluate_format(score.remote_abroad_compat.level, text, prefs, hr_format_override)
        if fmt.conflict:
            # Этот сигнал сидел в проде 21 строкой и не появился в логах ни разу — без него
            # «почему у сильной вакансии skip» приходится выяснять перескором. `vacancy_id` —
            # Этап 9 §9.2: без него WARNING не давал перейти от «есть расхождение» к «у какой
            # именно вакансии».
            event(
                logger,
                "ЗАДАЧА",
                "формат: JD и вердикт модели расходятся — %s",
                "гейт по вердикту модели" if fmt.gate else "мягкий минус вместо гейта",
                level=logging.WARNING,
                vacancy_id=vacancy_id or "",
                model_level=score.remote_abroad_compat.level,
                jd_office_only=_is_office_only(text),
                gate=fmt.gate,
            )
        if fmt.delta:
            adj.append(Adjustment(fmt.delta, fmt.reason))
        elif _is_hybrid_only(text) and not prefs.allows_hybrid:
            adj.append(Adjustment(-8, "гибрид вне допустимых форматов резюме"))
        elif (
            _is_remote_uncertain(text)
            and prefs.allows_remote
            and not (prefs.allows_hybrid or prefs.allows_office)
        ):
            adj.append(Adjustment(-5, "формат работы по договорённости"))

    return adj


def _work_auth_extracted(terms: VacancyWorkTerms | None) -> bool:
    if terms is None:
        return False
    return terms.residency_required or terms.payroll_form in ("w2", "local_entity")


def _work_auth_regex(text: str) -> bool:
    return _contains_any(text, _WORK_AUTH_PATTERNS)


def _exclusivity_regex(text: str) -> bool:
    return _contains_any(text, _EXCLUSIVITY_PATTERNS)


def _onsite_regex(text: str) -> bool:
    return bool(_ONSITE_RE.search(text)) or _is_office_only(text)


def _region_overlap_gap(
    terms: VacancyWorkTerms | None, intl: InternationalReadiness | None
) -> int | None:
    """Сколько часов не хватает до требуемого окна. None — считать нечего."""
    if terms is None or intl is None or terms.overlap_hours_required is None:
        return None
    required = terms.overlap_hours_required
    overlap = intl.overlap or {}
    if not overlap:
        return required
    from core.domains.opportunities.score_breakdown import _region_from_hiring_geo

    region = _region_from_hiring_geo(terms.hiring_geo)
    available = int(overlap.get(region, 0)) if region else max(overlap.values())
    return required - available


def _cities_differ(work_city: str, candidate_city: str) -> bool:
    a = (work_city or "").strip().casefold()
    b = (candidate_city or "").strip().casefold()
    if not a or not b:
        return False
    return a != b and a not in b and b not in a


def _second_job_gate_labels(
    score: ScoreResult,
    vacancy_text: str,
    *,
    terms: VacancyWorkTerms | None,
    intl: InternationalReadiness | None,
    market_scope: str,
    candidate_city: str,
    company_adjustments: list[CompanyAdjustmentRule] | None,
    company: str | None,
    list_rules: list[CompanyAdjustmentRule] | None,
    vacancy_id: str | None,
) -> tuple[list[str], list[Adjustment]]:
    """Гейты второго трека + мягкие минусы при одной улике. Возвращает (бейджи, дельты)."""
    text = vacancy_text.lower()
    labels: list[str] = []
    adj: list[Adjustment] = []

    extracted_auth = _work_auth_extracted(terms)
    regex_auth = _work_auth_regex(text)
    if extracted_auth and regex_auth:
        labels.append("Балл срезан: Право на работу")
    elif extracted_auth or regex_auth:
        adj.append(Adjustment(WORK_AUTH_CONFLICT_DELTA, "право на работу: одна улика без второй"))
        event(
            logger,
            "ЗАДАЧА",
            "гейт «Право на работу»: улики разошлись",
            level=logging.WARNING,
            vacancy_id=vacancy_id or "",
            extracted=extracted_auth,
            regex=regex_auth,
        )

    if market_scope == "ru" and extracted_auth:
        if score.remote_abroad_compat.level == "blocker":
            labels.append("Балл срезан: Право на работу")
        else:
            adj.append(
                Adjustment(
                    MARKET_SCOPE_CONFLICT_DELTA,
                    "рынок «Только РФ», зарубежное резидентство",
                )
            )

    geo_single = bool(terms and terms.geo_scope == "single_city")
    city_mismatch = _cities_differ(score.work_city, candidate_city)
    onsite = _onsite_regex(text)
    presence_regex = city_mismatch and onsite
    if geo_single and presence_regex:
        labels.append("Балл срезан: Физическое присутствие")
    elif geo_single or presence_regex:
        adj.append(
            Adjustment(PRESENCE_CONFLICT_DELTA, "физическое присутствие: одна улика без второй")
        )
        event(
            logger,
            "ЗАДАЧА",
            "гейт «Физическое присутствие»: улики разошлись",
            level=logging.WARNING,
            vacancy_id=vacancy_id or "",
            geo_single=geo_single,
            city_mismatch=city_mismatch,
            onsite=onsite,
        )

    excl_extracted = bool(terms and terms.exclusivity == "required")
    excl_regex = _exclusivity_regex(text)
    if excl_extracted and excl_regex:
        labels.append("Балл срезан: Эксклюзивность")
    elif excl_extracted or excl_regex:
        adj.append(Adjustment(EXCLUSIVITY_CONFLICT_DELTA, "эксклюзивность: одна улика без второй"))
        event(
            logger,
            "ЗАДАЧА",
            "гейт «Эксклюзивность»: улики разошлись",
            level=logging.WARNING,
            vacancy_id=vacancy_id or "",
            extracted=excl_extracted,
            regex=excl_regex,
        )

    gap = _region_overlap_gap(terms, intl)
    has_required = terms is not None and terms.overlap_hours_required is not None
    if has_required and gap is not None and gap >= 3:
        labels.append("Балл срезан: Окно пересечения")
    elif has_required and gap is not None and 0 < gap < 3:
        adj.append(Adjustment(OVERLAP_NEAR_DELTA, "окно пересечения: разрыв меньше 3 часов"))

    for rule in _matched_company_adjustments(
        text, company_adjustments, company=company, list_rules=list_rules
    ):
        if rule.gate:
            labels.append(f"Балл срезан: {rule.reason}")

    if score.grade_match.level == "off_profile" and not score.grade_match.is_role_shift:
        labels.append("Балл срезан: Другая профессия")

    return labels, adj


def detect_gates(
    score: ScoreResult,
    vacancy_text: str,
    hr_format_override: str = "unknown",
    company_adjustments: list[CompanyAdjustmentRule] | None = None,
    *,
    company: str | None = None,
    list_rules: list[CompanyAdjustmentRule] | None = None,
    format_prefs: CandidateFormatPrefs,
    vacancy_id: str | None = None,
    track: SearchTrack = DEFAULT_TRACK,
    terms: VacancyWorkTerms | None = None,
    intl: InternationalReadiness | None = None,
    market_scope: str = "ru",
    candidate_city: str = "",
) -> str | None:
    """Сработавшие жёсткие гейты → бейдж `gate_triggered` (None, если дилбрейкеров нет).

    Балл при гейте не режется (§1.4 плана): число отвечает «насколько подходит по существу»,
    бейдж — «есть дилбрейкер», и `apply_calibration` форсит по нему `recommendation = skip`.

    Бейдж один, при нескольких сработавших гейтах побеждает последний по порядку проверок
    (формат → грейд → правила компаний) — как и во времена цепочки капов.

    Префикс «Балл срезан: » сохранён намеренно: это проводной маркер, а не текст для глаз —
    `parseScoreGate` (shared/score-breakdown.ts) срезает его и в вебе, и в расширении, а в jsonb
    прода уже лежат сотни строк этой формы. Менять его ради формулировки — заводить второй
    словарь на ровном месте.
    """
    if track == "second_job":
        labels, _adj = _second_job_gate_labels(
            score,
            vacancy_text,
            terms=terms,
            intl=intl,
            market_scope=market_scope,
            candidate_city=candidate_city,
            company_adjustments=company_adjustments,
            company=company,
            list_rules=list_rules,
            vacancy_id=vacancy_id,
        )
        if not labels:
            return None
        event(
            logger,
            "ЗАДАЧА",
            "гейты вакансии: %s",
            ", ".join(labels),
            vacancy_id=vacancy_id or "",
            gates=labels,
            track=track,
        )
        return labels[-1]

    text = vacancy_text.lower()
    labels: list[str] = []
    prefs = format_prefs

    if evaluate_format(score.remote_abroad_compat.level, text, prefs, hr_format_override).gate:
        labels.append("Балл срезан: формат-гейт")

    if score.grade_match.level == "far_below":
        labels.append("Балл срезан: грейд-гейт")

    # off_profile гейтит только как «другая специальность». role_shift (IC↔менеджмент) —
    # не дилбрейкер: его цена уже учтена долей грейда по role_kind в compute_score_breakdown.
    if score.grade_match.level == "off_profile" and not score.grade_match.is_role_shift:
        labels.append("Балл срезан: грейд-гейт")

    for rule in _matched_company_adjustments(
        text, company_adjustments, company=company, list_rules=list_rules
    ):
        if rule.gate:
            labels.append(f"Балл срезан: {rule.reason}")

    if not labels:
        return None
    # Список целиком, а не только победивший бейдж: в jsonb уезжает один, а «почему skip»
    # объясняют все сработавшие. `vacancy_id` — Этап 9 §9.1: без него список гейтов в логе
    # не привязать к конкретной вакансии без перескора.
    event(
        logger,
        "ЗАДАЧА",
        "гейты вакансии: %s",
        ", ".join(labels),
        vacancy_id=vacancy_id or "",
        gates=labels,
    )
    return labels[-1]


def _weights_version(
    scoring_weights: dict[str, int] | None, role_kind: str, *, track: SearchTrack = DEFAULT_TRACK
) -> str:
    """Версия рубрики для штампа в `ScoreResult.weights_version` (Этап 5 §5.1).

    Хэш резолвленных весов (не сырого `scoring_weights`, который может быть `None`/неполным) +
    `role_kind` (сам код фракций `_MANAGEMENT_FRACTION_BY_ROLE`/`_ROLE_SHIFT_GRADE_FRACTION`
    зависит от него, а не только цифры весов) + пороги recommendation. `track` входит в хэш
    второго трека, чтобы две рубрики не считались одной линейкой.
    """
    resolved = resolve_weights(scoring_weights, track=track)
    return compute_weights_version(
        resolved,
        role_kind=role_kind,
        thresholds=(STRONG_APPLY_MIN, APPLY_MIN, MAYBE_MIN),
        track=track,
    )


def apply_calibration(
    score: ScoreResult,
    vacancy_text: str,
    *,
    format_prefs: CandidateFormatPrefs,
    role_kind: str,
    hr_format_override: str = "unknown",
    company_adjustments: list[CompanyAdjustmentRule] | None = None,
    company: str | None = None,
    list_rules: list[CompanyAdjustmentRule] | None = None,
    scoring_weights: dict[str, int] | None = None,
    salary_prefs: SalaryPrefs | None = None,
    skill_overlap: float | None = None,
    candidate_company_types: list[str] | None = None,
    vacancy_id: str | None = None,
    track: SearchTrack = DEFAULT_TRACK,
    terms: VacancyWorkTerms | None = None,
    intl: InternationalReadiness | None = None,
    market_scope: str = "ru",
    candidate_city: str = "",
    rate_floor: int | None = None,
    rate_n_obs: int = 0,
) -> ScoreResult:
    """Применить мягкие штрафы/бонусы к overall_score и проставить гейты.

    База балла — детерминированный breakdown по весам (AppSettings или дефолт), не сырой
    overall_score LLM: так слайдеры «Веса оценки» реально влияют на итог.
    `company_adjustments` — ручные AppSettings (power-user); `None`/`[]` — без ручных правил.
    `list_rules` — авто из target/avoid резюме. `format_prefs` / `role_kind` — из SearchProfile
    аккаунта запроса (override в тестах); файлового фолбэка сознательно нет (Этап 8 §8.5, D14) —
    подстановка резюме владельца в мульти-аккаунтном деплое — ровно то, что вычищает
    `plans/multitenancy_gaps_2026_08_06.md`. То же для `salary_prefs`: `None` → булев путь
    по `meets_min` (§2.1 плана), не файловый резюме-фолбэк. `skill_overlap` — детерминированный
    под-сигнал «Содержания роли» (Этап 4 §4.3); `None` → ось на чистой оценке LLM.
    `candidate_company_types` — `CandidateProfile.company_types`; фолбэк оси «Компания» при
    неизвестном `company_fit.level` (Этап 6 §6.4). `track` выбирает рубрику и набор гейтов
    (Э2.3/Э2.4); `terms`/`intl` — факты второго трека, без них оси нейтральны.

    Гейт число не трогает (§1.4 плана): `overall_score` = взвешенная сумма + мягкие дельты,
    `gate_triggered` — отдельный флаг, по которому `recommendation` уходит в skip.
    """
    prefs = format_prefs
    breakdown = compute_score_breakdown(
        score,
        scoring_weights,
        role_kind=role_kind,
        salary_prefs=salary_prefs,
        skill_overlap=skill_overlap,
        candidate_company_types=candidate_company_types,
        track=track,
        terms=terms,
        intl=intl,
        rate_floor=rate_floor,
        rate_n_obs=rate_n_obs,
    )
    total = sum(breakdown.values())
    weights_version = _weights_version(scoring_weights, role_kind, track=track)
    if track == "second_job":
        _labels, extra = _second_job_gate_labels(
            score,
            vacancy_text,
            terms=terms,
            intl=intl,
            market_scope=market_scope,
            candidate_city=candidate_city,
            company_adjustments=company_adjustments,
            company=company,
            list_rules=list_rules,
            vacancy_id=vacancy_id,
        )
        applied = list(extra)
        for rule in _matched_company_adjustments(
            vacancy_text.lower(),
            company_adjustments,
            company=company,
            list_rules=list_rules,
        ):
            if rule.delta and not rule.gate:
                applied.append(Adjustment(rule.delta, rule.reason))
        gate_badge = _labels[-1] if _labels else None
        if _labels:
            event(
                logger,
                "ЗАДАЧА",
                "гейты вакансии: %s",
                ", ".join(_labels),
                vacancy_id=vacancy_id or "",
                gates=_labels,
                track=track,
            )
    else:
        applied = compute_adjustments(
            score,
            vacancy_text,
            hr_format_override,
            company_adjustments,
            company=company,
            list_rules=list_rules,
            format_prefs=prefs,
            vacancy_id=vacancy_id,
        )
        gate_badge = detect_gates(
            score,
            vacancy_text,
            hr_format_override,
            company_adjustments,
            company=company,
            list_rules=list_rules,
            format_prefs=prefs,
            vacancy_id=vacancy_id,
            track=track,
        )
    for item in applied:
        total += item.delta
        logger.info("Калибровка: %+d — %s", item.delta, item.reason)

    total = max(0, min(100, total))

    # Гейт решает skip явно, число остаётся мерой «насколько подходит по существу» — доска
    # сортирует гейтованные последними по флагу, а не по испорченному баллу.
    recommendation = "skip" if gate_badge else _recommendation_from_score(total)

    return score.model_copy(
        update={
            "overall_score": total,
            "recommendation": recommendation,
            "score_breakdown": breakdown,
            "gate_triggered": gate_badge,
            "adjustments": [
                ScoreAdjustment(delta=item.delta, reason=item.reason) for item in applied
            ],
            "weights_version": weights_version,
            "track": track,
        }
    )


def recompute_salary_axis(
    score: ScoreResult,
    *,
    scoring_weights: dict[str, int] | None = None,
    role_kind: str = "unknown",
    salary_prefs: SalaryPrefs | None = None,
) -> ScoreResult:
    """Пересчитать одну ось «Зарплата» в уже откалиброванном score. Без LLM.

    Нужно после фоновой оценки вилки: на момент скоринга чисел ещё нет (`estimate_pending`),
    и с рампой (§2.1 плана) ось стоит нейтрально, пока вилка не приехала. Раньше это было
    незаметно — балл висел на булевом `meets_min`, который основной скоринг уже проставил.

    Полный `apply_calibration` здесь звать нельзя: часть его входов (`hr_format_override`,
    текст вакансии на момент скоринга) в фоновой задаче не восстановить, и пересчёт молча
    снял бы поправки, которые их учитывали. Двигаем ровно одну ось: итог = старый итог +
    дельта по зарплате; гейт и мягкие дельты остаются как были.

    Старый jsonb без сохранённого breakdown → возвращаем как есть (пересчитывать не от чего).
    """
    stored = score.score_breakdown or {}
    previous = stored.get("salary")
    if not isinstance(previous, int):
        return score

    fresh = compute_score_breakdown(
        score, scoring_weights, role_kind=role_kind, salary_prefs=salary_prefs
    )["salary"]
    if fresh == previous:
        return score

    total = max(0, min(100, score.overall_score + fresh - previous))
    return score.model_copy(
        update={
            "overall_score": total,
            "recommendation": "skip" if score.gate_triggered else _recommendation_from_score(total),
            "score_breakdown": {**stored, "salary": fresh},
            "weights_version": _weights_version(scoring_weights, role_kind),
        }
    )


# Канон порогов recommendation — синхрон с prompts/opportunities/instructions.md §«Пороги».
# Граница maybe/skip = MAYBE_MIN из промпта (после относительной шкалы шагов 8/10 идеал = 100,
# типичное хорошее ≥80; более мягкий исторический порог снят как рассинхрон).
STRONG_APPLY_MIN = 80
APPLY_MIN = 65
MAYBE_MIN = 45


def _recommendation_from_score(score: int) -> str:
    if score >= STRONG_APPLY_MIN:
        return "strong_apply"
    if score >= APPLY_MIN:
        return "apply"
    if score >= MAYBE_MIN:
        return "maybe"
    return "skip"
