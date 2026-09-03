"""GM-13: сравнение getmatch-профиля кандидата с Copilot-резюме (расхождения резюме).

getmatch хранит собственную копию профиля кандидата (summary, skills, опыт, образование,
зарплатные ожидания, локации) — `GET /api/profiles`. Владелец мог обновлять getmatch отдельно
от `resume_data.json` в Copilot: то, что видит работодатель на getmatch, может отличаться от
того, по чему Copilot скорит вакансии и пишет сопроводительные. Здесь модель профиля getmatch,
сравнение с `ResumeData` (список расхождений) и персист последнего снимка (account-scoped,
по образцу `resume_stats.py`).

Сравнение — чистая функция (`diff_gm_profile`), без LLM и без событий: читается и при приёме
снимка из расширения (`POST /api/resume/gm-profile-diff`), и при чтении на вкладке «Резюме»
(`GET /api/resume/gm-profile-diff`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.domains.profile.model import ResumeData
from core.domains.profile.structured_store import read_resume_data_for_account
from core.platform.db.pool import Executor, get_pool, row_to_dict

_GM_COLS = "id, captured_at, raw, created_at"


class GmSpecialization(BaseModel):
    """Специализация (роль/грейд) профиля getmatch."""

    name: str = ""
    grade: str = ""
    salary_min: int | None = None
    salary_desired: int | None = None


class GmExperience(BaseModel):
    """Место работы в профиле getmatch."""

    company: str = ""
    position: str = ""
    start: str = ""
    end: str = ""
    current: bool = False
    description: str = ""


class GmEducation(BaseModel):
    """Образование в профиле getmatch."""

    institution: str = ""
    degree: str = ""
    field: str = ""
    year: str = ""


class GmSalaryExpectation(BaseModel):
    """Зарплатные ожидания getmatch (вилка + валюта + период).

    `from_` — поле-алиас `from`: расширение шлёт `{currency, period, from, to}`;
    `populate_by_name` принимает и поле (`from_`) — для round-trip снимка из PG.
    """

    model_config = ConfigDict(populate_by_name=True)

    currency: str = "RUB"
    period: str = "month"
    from_: int | None = Field(default=None, alias="from")
    to: int | None = None


class GmProfile(BaseModel):
    """Профиль кандидата getmatch (парсится расширением из `GET /api/profiles`)."""

    full_name: str = ""
    locations: list[str] = Field(default_factory=list)
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    specializations: list[GmSpecialization] = Field(default_factory=list)
    experience: list[GmExperience] = Field(default_factory=list)
    education: list[GmEducation] = Field(default_factory=list)
    salary_expectation: GmSalaryExpectation | None = None
    current_position: str = ""


class GmProfileDiscrepancy(BaseModel):
    """Одно расхождение getmatch ↔ Copilot (для подсветки на вкладке «Резюме»).

    `getmatch`/`copilot` — человекочитаемые строки значений с обеих сторон (не разметка).
    """

    field: str = ""
    label: str = ""
    getmatch: str = ""
    copilot: str = ""


def _norm(text: str) -> str:
    return " ".join(str(text).split()).strip().casefold()


def _fmt_salary(lo: int | None, hi: int | None, currency: str) -> str:
    cur = (currency or "RUB").strip()
    if lo is not None and hi is not None:
        return f"от {lo:,} до {hi:,} {cur}".replace(",", " ")
    if lo is not None:
        return f"от {lo:,} {cur}".replace(",", " ")
    if hi is not None:
        return f"до {hi:,} {cur}".replace(",", " ")
    return ""


def _fmt_count(n: int, one: str, few: str, many: str) -> str:
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        word = one
    elif 2 <= mod10 <= 4 and (mod100 < 10 or mod100 >= 20):
        word = few
    else:
        word = many
    return f"{n} {word}"


def diff_gm_profile(gm: GmProfile, resume: ResumeData) -> list[GmProfileDiscrepancy]:
    """Расхождения между getmatch-профилем и Copilot-резюме.

    Подсвечивает только содержательные расхождения: разные зарплатные ожидания, отсутствующие
    скиллы, иной summary/позиция, разное число мест опыта/образования. Пусто = совпадает.
    """
    out: list[GmProfileDiscrepancy] = []

    # 1. Зарплатные ожидания: вилка getmatch vs Copilot position.salary_min/salary_comfortable.
    sal = gm.salary_expectation
    gm_min = sal.from_ if sal else None
    gm_max = sal.to if sal else None
    gm_salary = _fmt_salary(gm_min, gm_max, sal.currency if sal else "")
    cp_salary = _fmt_salary(
        resume.position.salary_min,
        resume.position.salary_comfortable,
        resume.position.salary_currency,
    )
    if (gm_salary or cp_salary) and (
        gm_min != resume.position.salary_min or gm_max != resume.position.salary_comfortable
    ):
        out.append(
            GmProfileDiscrepancy(
                field="salary",
                label="Зарплатные ожидания",
                getmatch=gm_salary or "не указаны",
                copilot=cp_salary or "не указаны",
            )
        )

    # 2. Скиллы: есть на getmatch, нет в Copilot, и наоборот.
    gm_skills = {_norm(s) for s in gm.skills if _norm(s)}
    cp_skills = {_norm(s) for s in resume.key_skills if _norm(s)}
    only_gm = sorted(gm_skills - cp_skills)
    only_cp = sorted(cp_skills - gm_skills)
    if only_gm or only_cp:
        out.append(
            GmProfileDiscrepancy(
                field="skills",
                label="Навыки",
                getmatch=", ".join(only_gm) if only_gm else "—",
                copilot=", ".join(only_cp) if only_cp else "—",
            )
        )

    # 3. Summary / Обо мне: содержательное текстовое расхождение (по нормализованному тексту).
    gm_about = _norm(gm.summary)
    cp_about = _norm(resume.about)
    if bool(gm_about) != bool(cp_about) or (gm_about and cp_about and gm_about != cp_about):
        out.append(
            GmProfileDiscrepancy(
                field="summary",
                label="Обо мне / Summary",
                getmatch=gm.summary.strip() or "не заполнено",
                copilot=resume.about.strip() or "не заполнено",
            )
        )

    # 4. Позиция: getmatch current_position vs Copilot title (или текущее место работы).
    cp_position = resume.position.title.strip()
    if not cp_position:
        for exp in resume.experience:
            if exp.current and exp.position.strip():
                cp_position = exp.position.strip()
                break
    if _norm(gm.current_position) != _norm(cp_position):
        out.append(
            GmProfileDiscrepancy(
                field="position",
                label="Желаемая/текущая позиция",
                getmatch=gm.current_position.strip() or "не указана",
                copilot=cp_position or "не указана",
            )
        )

    # 5. Опыт: разное число мест работы.
    if len(gm.experience) != len(resume.experience):
        out.append(
            GmProfileDiscrepancy(
                field="experience",
                label="Опыт работы",
                getmatch=_fmt_count(len(gm.experience), "место", "места", "мест"),
                copilot=_fmt_count(len(resume.experience), "место", "места", "мест"),
            )
        )

    # 6. Образование: разное число записей.
    if len(gm.education) != len(resume.education):
        out.append(
            GmProfileDiscrepancy(
                field="education",
                label="Образование",
                getmatch=_fmt_count(len(gm.education), "запись", "записи", "записей"),
                copilot=_fmt_count(len(resume.education), "запись", "записи", "записей"),
            )
        )

    return out


class GmProfileSnapshot(BaseModel):
    """Снимок getmatch-профиля (для истории; сравнение всегда по последнему)."""

    id: int | None = None
    captured_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


async def save_gm_profile(
    gm: GmProfile, *, account_id: int, db: Executor | None = None
) -> GmProfileSnapshot:
    """Сохранить снимок getmatch-профиля аккаунта запроса (история, свежий — последний)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into gm_profile_snapshots (account_id, captured_at, raw) "
        "values ($1, $2, $3) "
        f"returning {_GM_COLS}",
        account_id,
        datetime.now(UTC),
        gm.model_dump(mode="json"),
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return GmProfileSnapshot(**row_to_dict(row))


async def load_latest_gm_profile(
    *, account_id: int, db: Executor | None = None
) -> GmProfile | None:
    """Последний снимок getmatch-профиля аккаунта запроса; `None` — снимков ещё нет."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select raw from gm_profile_snapshots "
        "where account_id = $1 order by captured_at desc, id desc limit 1",
        account_id,
    )
    if row is None:
        return None
    return GmProfile.model_validate(row["raw"])


def _to_out(discrepancies: list[GmProfileDiscrepancy]) -> list[dict[str, str]]:
    """Доменный список расхождений → plain-dict (transport-тип роутер собирает сам)."""
    return [d.model_dump() for d in discrepancies]


async def ingest_and_diff_gm_profile(
    raw_profile: dict[str, Any], *, account_id: int
) -> tuple[bool, list[GmProfileDiscrepancy]]:
    """Принять getmatch-профиль из расширения, сохранить снимок, сравнить с Copilot-резюме.

    Возвращает `(stored, discrepancies)`. Приём мягко деградирует (нет PG → `stored=False`,
    но diff всё равно считается из присланного профиля). Валидация мягкая: битый контракт
    расширения → пустой `GmProfile` (не 500), расхождения по пустому профилю будут «всё
    расходится», что безопаснее молчаливого пропуска.
    """
    try:
        gm = GmProfile.model_validate(raw_profile or {})
    except Exception:  # noqa: BLE001 — контракт расширения, мягко отбрасываем
        gm = GmProfile()

    stored = False
    try:
        await save_gm_profile(gm, account_id=account_id)
        stored = True
    except Exception:  # noqa: BLE001 — нет PG → не сохранили, не 500
        stored = False

    resume = await read_resume_data_for_account(account_id)
    return stored, diff_gm_profile(gm, resume)


async def diff_latest_gm_profile(*, account_id: int) -> tuple[bool, list[GmProfileDiscrepancy]]:
    """Сравнить последний сохранённый снимок getmatch с Copilot-резюме.

    Возвращает `(available, discrepancies)`. `available=False` — снимок ещё не приходил
    (расширение не слало) или PG недоступен.
    """
    try:
        gm = await load_latest_gm_profile(account_id=account_id)
    except Exception:  # noqa: BLE001 — нет PG → available=False, не 500
        return False, []

    if gm is None:
        return False, []

    resume = await read_resume_data_for_account(account_id)
    return True, diff_gm_profile(gm, resume)


__all__ = [
    "GmProfile",
    "GmProfileDiscrepancy",
    "GmProfileSnapshot",
    "GmSalaryExpectation",
    "GmSpecialization",
    "GmExperience",
    "GmEducation",
    "diff_gm_profile",
    "save_gm_profile",
    "load_latest_gm_profile",
    "ingest_and_diff_gm_profile",
    "diff_latest_gm_profile",
]
