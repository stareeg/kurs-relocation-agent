"""Профиль кандидата — производная от ResumeData + overlay из app_settings/career.

Все модули, которые раньше угадывали «кто кандидат / какой рынок / руки vs люди»,
читают `CandidateProfile` (алиас `SearchProfile`) вместо owner-хардкода.
`derive_*` — чистая функция от резюме; карьерные поля (позиция, выход, горизонт,
рост, локация/виза) подмешиваются из `app_settings` / домена `career`.
Кэш по пути JSON — как `_render_resume` в `core.domains.opportunities.prompt`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.config import CoreSettings, get_settings
from core.domains.profile.identity import candidate_identity_line, candidate_specialization_line
from core.domains.profile.international import (
    InternationalReadiness,
    derive_international_readiness,
)
from core.domains.profile.model import (
    MARKET_SCOPE_ANY,
    MARKET_SCOPE_INTL,
    MARKET_SCOPE_RU,
    ResumeData,
    is_currently_employed,
    market_scope_label,
)
from core.domains.profile.structured_store import read_default_resume_data
from core.platform.db.pool import Executor

GRADE_SCALE: tuple[str, ...] = ("Junior", "Middle", "Senior", "Lead", "C-level")

_ROLE_KIND_MAP: dict[str, Literal["hands_on", "management", "mixed", "unknown"]] = {
    "делаю руками": "hands_on",
    "управляю людьми": "management",
    "и то, и другое": "mixed",
    "hands_on": "hands_on",
    "management": "management",
    "mixed": "mixed",
    "unknown": "unknown",
}

# Редфлаг из закрытого списка UX6 — дублируем строку, чтобы profile не импортировал scoring.
_TRAVEL_DEALBREAKER = "Частые командировки"

# Рынок поиска: русская подпись резюме → слаг профиля. Пустое значение = «Только РФ»
# (`market_scope_label` уже сводит мусор и пустоту к дефолту).
_MARKET_SCOPE_MAP: dict[str, Literal["ru", "intl", "any"]] = {
    MARKET_SCOPE_RU: "ru",
    MARKET_SCOPE_INTL: "intl",
    MARKET_SCOPE_ANY: "any",
}

# Ключ jsonb в app_settings (поверх резюме; user-knobs побеждают career-hints).
CANDIDATE_PROFILE_SETTING_KEY = "candidate_profile"


class CandidateProfileOverlay(BaseModel):
    """Карьерный слой поверх резюме: app_settings и/или домен career.

    `None` = поле не задано (не трогать). Пустая строка/список при merge с
    ``skip_empty=True`` тоже не перетирает уже заполненное.
    """

    current_position: str | None = None
    available_from: str | None = None
    goal_horizon: str | None = None
    growth_directions: list[str] | None = None
    location_constraint: str | None = None
    visa_constraint: str | None = None


class CandidateProfile(BaseModel):
    """Снимок критериев поиска и карьерного контекста. Immutable."""

    model_config = ConfigDict(frozen=True)

    title: str = ""
    identity: str = ""
    specialization: str = ""
    target_grades: list[str] = Field(default_factory=list)
    grade_floor_index: int = -1
    grade_ceil_index: int = -1
    role_kind: Literal["hands_on", "management", "mixed", "unknown"] = "unknown"
    salary_min: int = 0
    salary_comfortable: int = 0
    salary_currency: str = "RUB"
    salary_basis: Literal["net", "gross"] = "net"
    market_segment: str = ""
    # Рынок поиска (ось «Критериев поиска»): ru — только РФ, intl — международный,
    # any — оба. Дефолт `ru`: сохранённые резюме без оси ведут себя как раньше.
    market_scope: Literal["ru", "intl", "any"] = "ru"
    market_scope_label: str = MARKET_SCOPE_RU
    # Работает ли кандидат сейчас (галочка «по настоящее время» в опыте). None — опыта нет.
    currently_employed: bool | None = None
    # Международный потенциал (вывод, не форма). Пустой дефолт — рынок «Только РФ».
    international: InternationalReadiness = Field(default_factory=InternationalReadiness)
    priorities: list[str] = Field(default_factory=list)
    key_skills: list[str] = Field(default_factory=list)
    company_types: list[str] = Field(default_factory=list)
    allows_office: bool = False
    allows_hybrid: bool = False
    allows_remote: bool = False
    travel_is_dealbreaker: bool = False
    is_filled: bool = False
    profile_axes_filled: bool = False

    # A-21: карьерный слой (не из резюме в derive_* — из app_settings/career).
    current_position: str = ""
    available_from: str = ""
    goal_horizon: str = ""
    growth_directions: list[str] = Field(default_factory=list)
    location_constraint: str = ""
    visa_constraint: str = ""

    def salary_anchor_base(self) -> tuple[int, int] | None:
        """База якоря зарплаты: min … comfortable (или min×1.3). None если min не задан."""
        if self.salary_min <= 0:
            return None
        hi = (
            self.salary_comfortable
            if self.salary_comfortable > 0
            else int(round(self.salary_min * 1.3))
        )
        if hi < self.salary_min:
            hi = self.salary_min
        return self.salary_min, hi


# Исторический алиас: старые импорты SearchProfile продолжают работать.
SearchProfile = CandidateProfile


def _normalize_role_kind(raw: str) -> Literal["hands_on", "management", "mixed", "unknown"]:
    key = (raw or "").strip().casefold()
    if not key:
        return "unknown"
    return _ROLE_KIND_MAP.get(key, "unknown")


def _normalize_salary_basis(raw: str) -> Literal["net", "gross"]:
    key = (raw or "").strip().casefold()
    if not key or key in {"на руки", "net"}:
        return "net"
    if key in {"до вычета", "gross"}:
        return "gross"
    # Неизвестная строка — не ломаем потребителей: как исторический дефолт.
    return "net"


def _grade_indices(grades: list[str]) -> tuple[int, int]:
    """min/max позиция целевых грейдов на GRADE_SCALE; (−1, −1), если ничего не распознано."""
    idxs: list[int] = []
    for g in grades:
        name = (g or "").strip()
        if not name:
            continue
        try:
            idxs.append(GRADE_SCALE.index(name))
        except ValueError:
            # Нестандартный ярлык (Senior+, Middle+) — пробуем префикс шкалы.
            folded = name.casefold()
            for i, canon in enumerate(GRADE_SCALE):
                if folded.startswith(canon.casefold()):
                    idxs.append(i)
                    break
    if not idxs:
        return -1, -1
    return min(idxs), max(idxs)


def _format_prefs(data: ResumeData) -> tuple[bool, bool, bool, bool]:
    """Допустимые форматы и командировки для профиля (канон для калибровки)."""
    schedule = [s.casefold() for s in (data.position.schedule or []) if s and str(s).strip()]
    dealbreakers = list(data.search_criteria.dealbreakers or [])
    trip = (data.personal.relocation or "").casefold()
    travel_db = _TRAVEL_DEALBREAKER in dealbreakers or (
        bool(trip) and ("не готов" in trip or "неготов" in trip)
    )
    return (
        any("офис" in s for s in schedule),
        any("гибрид" in s for s in schedule),
        any("удал" in s for s in schedule),
        travel_db,
    )


def _is_filled(data: ResumeData) -> bool:
    has_role = bool(data.position.title.strip()) or bool(data.experience)
    has_target = bool(data.position.grade) or bool(
        data.position.salary_min or data.position.salary_comfortable
    )
    return has_role and has_target


def derive_candidate_profile(data: ResumeData) -> CandidateProfile:
    """Чистая функция: ResumeData → CandidateProfile. Без файлов/БД/LLM.

    Карьерные поля (current_position, available_from, …) остаются пустыми —
    их заполняет ``apply_candidate_overlay`` / ``load_candidate_profile_enriched``.
    """
    pos = data.position
    sc = data.search_criteria
    grades = [g.strip() for g in (pos.grade or []) if g and str(g).strip()]
    floor_i, ceil_i = _grade_indices(grades)
    office, hybrid, remote, travel_db = _format_prefs(data)
    role_raw = (sc.role_kind or "").strip()
    segment = (sc.market_segment or "").strip()
    scope_label = market_scope_label(sc.market_scope)
    priorities = [n.strip() for n in (sc.niches or []) if n and str(n).strip()]
    skills = [s.strip() for s in (data.key_skills or []) if s and str(s).strip()]
    company_types = [t.strip() for t in (pos.company_types or []) if t and str(t).strip()]

    return CandidateProfile(
        title=pos.title.strip(),
        identity=candidate_identity_line(data),
        specialization=candidate_specialization_line(data),
        target_grades=grades,
        grade_floor_index=floor_i,
        grade_ceil_index=ceil_i,
        role_kind=_normalize_role_kind(role_raw),
        salary_min=int(pos.salary_min or 0),
        salary_comfortable=int(pos.salary_comfortable or 0),
        salary_currency=(pos.salary_currency or "RUB").strip() or "RUB",
        salary_basis=_normalize_salary_basis(pos.salary_basis),
        market_segment=segment,
        market_scope=_MARKET_SCOPE_MAP[scope_label],
        market_scope_label=scope_label,
        currently_employed=is_currently_employed(data),
        international=derive_international_readiness(data),
        priorities=priorities,
        key_skills=skills,
        company_types=company_types,
        allows_office=office,
        allows_hybrid=hybrid,
        allows_remote=remote,
        travel_is_dealbreaker=travel_db,
        is_filled=_is_filled(data),
        profile_axes_filled=bool(role_raw) and bool(segment),
    )


derive_search_profile = derive_candidate_profile


def _strip_list(items: list[str] | None) -> list[str]:
    if not items:
        return []
    return [s.strip() for s in items if s and str(s).strip()]


def apply_candidate_overlay(
    base: CandidateProfile,
    overlay: CandidateProfileOverlay | None,
    *,
    skip_empty: bool = True,
) -> CandidateProfile:
    """Наложить overlay на профиль. ``skip_empty`` — пустые значения не затирают базу."""
    if overlay is None:
        return base
    updates: dict[str, Any] = {}

    def _take_str(field: str, raw: str | None) -> None:
        if raw is None:
            return
        val = raw.strip()
        if skip_empty and not val:
            return
        updates[field] = val

    _take_str("current_position", overlay.current_position)
    _take_str("available_from", overlay.available_from)
    _take_str("goal_horizon", overlay.goal_horizon)
    _take_str("location_constraint", overlay.location_constraint)
    _take_str("visa_constraint", overlay.visa_constraint)

    if overlay.growth_directions is not None:
        dirs = _strip_list(overlay.growth_directions)
        if not skip_empty or dirs:
            updates["growth_directions"] = dirs

    return base.model_copy(update=updates) if updates else base


def overlay_from_mapping(raw: Any) -> CandidateProfileOverlay:
    """Разобрать jsonb/dict из app_settings в overlay; мусор → пустой overlay."""
    if not isinstance(raw, dict):
        return CandidateProfileOverlay()
    try:
        return CandidateProfileOverlay.model_validate(raw)
    except Exception:
        return CandidateProfileOverlay()


def default_candidate_profile_setting() -> dict[str, Any]:
    """Дефолт ключа app_settings — пустой overlay (без хардкода владельца)."""
    return CandidateProfileOverlay().model_dump(exclude_none=True)


async def load_settings_candidate_overlay(
    *,
    account_id: int | None,
    db: Executor | None = None,
) -> CandidateProfileOverlay:
    """Overlay аккаунта запроса; нет строки / ошибка PG → пустой."""
    from core.platform.repo.settings import get_setting

    raw = await get_setting(
        CANDIDATE_PROFILE_SETTING_KEY,
        default=default_candidate_profile_setting(),
        account_id=account_id,
        db=db,
    )
    return overlay_from_mapping(raw)


@lru_cache(maxsize=1)
def _cached_candidate_profile(data_path: str) -> CandidateProfile:
    settings = get_settings()
    data = read_default_resume_data(settings=settings)
    return derive_candidate_profile(data)


def load_candidate_profile(settings: CoreSettings | None = None) -> CandidateProfile:
    """Профиль из `resume_data.json` (только derive), кэш по пути."""
    settings = settings or get_settings()
    return _cached_candidate_profile(settings.resume_data_path)


load_search_profile = load_candidate_profile


async def load_candidate_profile_enriched(
    settings: CoreSettings | None = None,
    *,
    account_id: int | None = None,
    data: ResumeData | None = None,
    db: Executor | None = None,
) -> CandidateProfile:
    """Резюме + user-knobs из app_settings (settings побеждают).

    `data` — резюме аккаунта запроса, если уже резолвлено вызывающим; иначе — файловый
    файловый путь (`load_candidate_profile`, тесты/bootstrap). `account_id` уходит в
    `load_settings_candidate_overlay` — `None` читает `app_settings` (bootstrap), не «владелец
    по умолчанию».
    """
    base = derive_candidate_profile(data) if data is not None else load_candidate_profile(settings)
    settings_overlay = await load_settings_candidate_overlay(account_id=account_id, db=db)
    merged = apply_candidate_overlay(base, settings_overlay, skip_empty=True)
    if account_id and data is not None:
        try:
            from core.domains.profile.international import apply_experience_snapshot
            from core.domains.profile.intl_experience import load_snapshot, resume_content_hash

            snap = await load_snapshot(
                account_id=account_id, resume_hash=resume_content_hash(data), db=db
            )
            if snap is not None:
                intl = apply_experience_snapshot(merged.international, snap.model_dump())
                merged = merged.model_copy(update={"international": intl})
        except Exception:
            pass
    return merged


def clear_candidate_profile_cache() -> None:
    """Сброс кэша профиля. Вызывается из `clear_resume_cache` (шаг 3)."""
    _cached_candidate_profile.cache_clear()


clear_search_profile_cache = clear_candidate_profile_cache

__all__ = [
    "CANDIDATE_PROFILE_SETTING_KEY",
    "GRADE_SCALE",
    "CandidateProfile",
    "CandidateProfileOverlay",
    "InternationalReadiness",
    "SearchProfile",
    "apply_candidate_overlay",
    "clear_candidate_profile_cache",
    "clear_search_profile_cache",
    "default_candidate_profile_setting",
    "derive_candidate_profile",
    "derive_search_profile",
    "load_candidate_profile",
    "load_candidate_profile_enriched",
    "load_search_profile",
    "load_settings_candidate_overlay",
    "overlay_from_mapping",
]
