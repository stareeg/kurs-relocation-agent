"""Международный потенциал кандидата — чистая деривация из ResumeData.

Каждое поле — вывод, ни одно не спрашивается формой. Географию берёт из
`search_criteria.market_scope` (ось «Рынок поиска»), а не из списка стран:
страна проживания отвечает за часовой пояс, ось рынка — за то, куда кандидат
смотрит. При `market_scope == "ru"` `readiness = "unknown"` и пересечения
не считаются.

Без файлов / БД / LLM (A-10). Снимок опыта из текста мержится отдельно
(`intl_experience.apply_experience_snapshot`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.domains.profile.model import (
    MARKET_SCOPE_RU,
    ResumeData,
    is_currently_employed,
    market_scope_label,
)
from core.kernel.timezones import (
    REGION_WORK_HOURS,
    city_geo,
    overlap_map,
    utc_offset_minutes,
)

HoursBand = Literal["evenings", "weekends", "part_day", "full"]
Readiness = Literal["ready", "partial", "weak", "unknown"]
ContractForm = Literal["employment", "gph", "ip", "self_employed"]
LetterLang = Literal["ru", "en"]

_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")

#: Закрытый справочник языков формы — «Английский» и латинский алиас.
_ENGLISH_NAMES = frozenset({"английский", "english", "англ"})

_CEFR_RANK: dict[str, int] = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
_NATIVE_MARKERS = ("родной", "native")
_CEFR_TOKEN_RE = re.compile(r"\b(A1|A2|B1|B2|C1|C2)\b", re.IGNORECASE)

# Дублируем строку UX6, чтобы international не импортировал scoring.
_GPH_DEALBREAKER = "Только ГПХ / ИП"
_PART_TIME_FORMS: tuple[ContractForm, ...] = ("gph", "ip", "self_employed")

READINESS_LABELS: dict[Readiness, str] = {
    "ready": "Готов",
    "partial": "Частично",
    "weak": "Слабо",
    "unknown": "Не оценивали",
}

CONTRACT_FORM_LABELS: dict[ContractForm, str] = {
    "employment": "ТК",
    "gph": "ГПХ",
    "ip": "ИП",
    "self_employed": "самозанятость",
}

HOURS_BAND_LABELS: dict[HoursBand, str] = {
    "evenings": "вечера",
    "weekends": "выходные",
    "part_day": "часть дня",
    "full": "полный день",
}


class InternationalReadiness(BaseModel):
    """Международный потенциал кандидата. Каждое поле — вывод, ни одно не спрашивается формой."""

    model_config = ConfigDict(frozen=True)

    english_level: str = ""  # CEFR из languages ("B2"); "" = не указан
    working_languages: list[str] = Field(default_factory=list)  # языки уровня B2+ (включая родной)
    home_timezone: str = ""  # IANA из personal.city ("Europe/Moscow")
    utc_offset_minutes: int = 0
    overlap: dict[str, int] = Field(default_factory=dict)  # регион → часов пересечения
    work_regions: list[str] = Field(default_factory=list)
    accepted_currencies: list[str] = Field(default_factory=list)
    contract_forms: list[str] = Field(default_factory=list)
    hours_band: HoursBand = "full"
    readiness: Readiness = "unknown"
    evidence: list[str] = Field(default_factory=list)

    # Слой 2 (LLM-снимок): заполняются только если чистая деривация их не дала.
    distributed_experience: bool = False
    english_artifacts: list[str] = Field(default_factory=list)
    client_facing: bool = False
    timezone_experience: list[str] = Field(default_factory=list)
    suggested_english_level: str = ""


def _cefr_code(level: str) -> str:
    """Строка уровня языка → CEFR-код. «Родной» = C2. Мусор → пусто."""
    raw = (level or "").strip()
    if not raw:
        return ""
    folded = raw.casefold()
    if any(folded.startswith(m) or folded == m for m in _NATIVE_MARKERS):
        return "C2"
    match = _CEFR_TOKEN_RE.search(raw)
    if match:
        return match.group(1).upper()
    token = re.split(r"[\s—–\-]+", raw, maxsplit=1)[0].upper()
    return token if token in _CEFR_RANK else ""


def _cefr_rank(code: str) -> int:
    return _CEFR_RANK.get(code, 0)


def _is_english(name: str) -> bool:
    key = (name or "").strip().casefold().rstrip(".")
    return key in _ENGLISH_NAMES


def _home_region(timezone: str) -> str:
    """Часовой пояс кандидата → регион из REGION_WORK_HOURS (фолбэк EMEA)."""
    for region, (region_tz, _, _) in REGION_WORK_HOURS.items():
        if timezone == region_tz:
            return region
    if timezone in {"America/Los_Angeles", "America/Vancouver"}:
        return "US-West"
    if timezone.startswith("America/New_York") or timezone.startswith("America/Toronto"):
        return "US-East"
    if timezone in {"Asia/Singapore", "Asia/Bangkok", "Asia/Ho_Chi_Minh"} or timezone.startswith(
        "Australia/"
    ):
        return "APAC"
    if timezone == "Europe/London":
        return "UK"
    return "EMEA"


def _english_level(data: ResumeData) -> tuple[str, str]:
    """Максимальный CEFR среди записей английского. Возвращает (код, исходное имя языка)."""
    best_code = ""
    best_rank = 0
    source_name = ""
    for lang in data.languages:
        if not _is_english(lang.name):
            continue
        code = _cefr_code(lang.level)
        rank = _cefr_rank(code)
        if rank > best_rank:
            best_code, best_rank, source_name = code, rank, lang.name.strip()
    return best_code, source_name


def _working_languages(data: ResumeData) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for lang in data.languages:
        name = (lang.name or "").strip()
        if not name:
            continue
        if _cefr_rank(_cefr_code(lang.level)) < _CEFR_RANK["B2"]:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _accepted_currencies(data: ResumeData) -> list[str]:
    currencies = ["RUB"]
    raw = (data.position.salary_currency or "RUB").strip().upper() or "RUB"
    if raw not in currencies:
        currencies.append(raw)
    return currencies


def _contract_forms(data: ResumeData) -> list[str]:
    """Допустимые формы для международного/второго трека.

    Ред-флаг «Только ГПХ / ИП» исключает подряд из *основного* трека; здесь, наоборот,
    оставляем — один факт, два знака.
    """
    employment = (data.position.employment or "").casefold()
    forms: list[str] = []
    if "подработ" in employment:
        forms.extend(_PART_TIME_FORMS)
    else:
        forms.append("employment")
    if is_currently_employed(data) and not any(f in forms for f in _PART_TIME_FORMS):
        forms.extend(_PART_TIME_FORMS)
    # Ред-флаг основного трека здесь — сигнал, что подряд допустим для второй работы.
    if _GPH_DEALBREAKER in (data.search_criteria.dealbreakers or []):
        for form in _PART_TIME_FORMS:
            if form not in forms:
                forms.append(form)
    return forms


def _hours_band(data: ResumeData) -> HoursBand:
    employed = is_currently_employed(data)
    employment = (data.position.employment or "").casefold()
    if employed:
        return "evenings"
    if "подработ" in employment:
        return "part_day"
    return "full"


def _has_intl_signal(currencies: list[str], forms: list[str]) -> bool:
    has_fx = any(c != "RUB" for c in currencies)
    has_contractor = any(f != "employment" for f in forms)
    return has_fx or has_contractor


def derive_international_readiness(data: ResumeData) -> InternationalReadiness:
    """ResumeData → готовность к международному треку. Чисто, без файлов/БД/LLM."""
    evidence: list[str] = []
    scope_label = market_scope_label(data.search_criteria.market_scope)
    market_ru = scope_label == MARKET_SCOPE_RU

    english, english_name = _english_level(data)
    if english:
        src = english_name or "Английский"
        evidence.append(f"{src} {english} — из раздела Языки")

    working = _working_languages(data)

    geo = city_geo(data.personal.city)
    home_tz = geo.timezone if geo is not None else ""
    offset = utc_offset_minutes(home_tz) if home_tz else 0
    if home_tz:
        city = data.personal.city.strip()
        evidence.append(f"Часовой пояс {home_tz} — из города {city}")
    elif data.personal.city.strip():
        evidence.append("Страну и часовой пояс не определили — город не из справочника")

    currencies = _accepted_currencies(data)
    if any(c != "RUB" for c in currencies):
        evidence.append(f"Валюта {', '.join(currencies)} — из желаемой должности")

    forms = _contract_forms(data)
    form_labels = [CONTRACT_FORM_LABELS.get(f, f) for f in forms]  # type: ignore[arg-type]
    if forms:
        evidence.append(f"Формы: {', '.join(form_labels)}")

    hours = _hours_band(data)
    if hours != "full":
        evidence.append(f"Доступные часы: {HOURS_BAND_LABELS[hours]}")

    if market_ru:
        return InternationalReadiness(
            english_level=english,
            working_languages=working,
            home_timezone=home_tz,
            utc_offset_minutes=offset,
            overlap={},
            work_regions=[_home_region(home_tz)] if home_tz else [],
            accepted_currencies=currencies,
            contract_forms=forms,
            hours_band=hours,
            readiness="unknown",
            evidence=evidence,
        )

    overlap = overlap_map(home_tz) if home_tz else {}
    if overlap:
        bits = [f"{region} {hours} ч" for region, hours in overlap.items() if hours > 0]
        if bits:
            evidence.append("Пересечение: " + ", ".join(bits))

    home = _home_region(home_tz) if home_tz else ""
    work_regions = list(REGION_WORK_HOURS.keys()) if home_tz else ([home] if home else [])

    eng_rank = _cefr_rank(english)
    tz_known = bool(home_tz)
    signal = _has_intl_signal(currencies, forms)
    if eng_rank >= _CEFR_RANK["B2"] and tz_known and signal:
        readiness: Readiness = "ready"
    elif eng_rank >= _CEFR_RANK["B1"] or tz_known:
        readiness = "partial"
    else:
        readiness = "weak"

    return InternationalReadiness(
        english_level=english,
        working_languages=working,
        home_timezone=home_tz,
        utc_offset_minutes=offset,
        overlap=overlap,
        work_regions=work_regions,
        accepted_currencies=currencies,
        contract_forms=forms,
        hours_band=hours,
        readiness=readiness,
        evidence=evidence,
    )


def detect_resume_language(data: ResumeData) -> LetterLang:
    """Язык текста резюме - кириллица vs латиница в прозе (Э4.4 dual_employment_and_contracting).

    Дефолт сопроводительного письма: не CEFR-уровень английского (`english_level` - оценка
    владения, а не язык самого текста резюме) и не язык вакансии - явно язык того, что кандидат
    сам написал о себе. Считаем только прозу (`about`, желаемая должность, позиция/описание
    опыта) - `key_skills` сознательно исключены: стек технологий почти всегда латиницей даже в
    русском резюме («Python, Kubernetes, AWS») и перекосил бы счёт. Ничья/пустая прозa -> "ru"
    (безопасный дефолт продукта).
    """
    parts: list[str] = [data.about, data.position.title]
    for exp in data.experience:
        parts.append(exp.position)
        parts.append(exp.description)
    prose = " ".join(p for p in parts if p)
    if not prose.strip():
        return "ru"
    cyrillic = len(_CYRILLIC_RE.findall(prose))
    latin = len(_LATIN_LETTER_RE.findall(prose))
    return "en" if latin > cyrillic else "ru"


def apply_experience_snapshot(
    base: InternationalReadiness,
    snap: Mapping[str, Any] | None,
) -> InternationalReadiness:
    """Наложить LLM-снимок: заполняет только пустые поля, пользовательские значения не трёт."""
    if not snap:
        return base
    updates: dict[str, Any] = {}

    if not base.distributed_experience and snap.get("distributed_experience"):
        updates["distributed_experience"] = True
    if not base.client_facing and snap.get("client_facing"):
        updates["client_facing"] = True

    artifacts = [s.strip() for s in (snap.get("english_artifacts") or []) if s and str(s).strip()]
    if artifacts and not base.english_artifacts:
        updates["english_artifacts"] = artifacts

    tz_exp = [s.strip() for s in (snap.get("timezone_experience") or []) if s and str(s).strip()]
    if tz_exp and not base.timezone_experience:
        updates["timezone_experience"] = tz_exp

    suggested = str(snap.get("suggested_english_level") or "").strip()
    if suggested and not base.english_level and not base.suggested_english_level:
        updates["suggested_english_level"] = _cefr_code(suggested) or suggested

    return base.model_copy(update=updates) if updates else base


__all__ = [
    "CONTRACT_FORM_LABELS",
    "HOURS_BAND_LABELS",
    "READINESS_LABELS",
    "InternationalReadiness",
    "LetterLang",
    "apply_experience_snapshot",
    "derive_international_readiness",
    "detect_resume_language",
]
