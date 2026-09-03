"""Структурное резюме по полям hh.ru + сериализатор в markdown для скоринга.

Источник правды вкладки «Резюме» — `ResumeData` (поля как в форме hh.ru: личные данные,
контакты, желаемая должность, опыт, образование, навыки, языки, обо мне). Скоринг рендерит
markdown из этой модели в рантайме (`core/scoring/prompt.py` через `to_markdown`), без
промежуточного .md-файла на диске — канон один, JSON.

Модель намеренно «мягкая» (строки, не строгие enum/даты): владелец редактирует поля свободно,
как на hh; жёсткие валидаторы только мешали бы. Период — свободные строки («Март 2024»), чтобы
не тащить date-picker и совпадать со стилем hh (месяц/год).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from core.domains.profile.categories import (
    RESUME_CATEGORIES_MAX,
    normalize_categories,
    resume_categories_prompt_list,
)
from core.kernel.timezones import derived_work_countries


class Contacts(BaseModel):
    phone: str = ""
    phone_preferred: bool = True
    email: str = ""
    telegram: str = ""
    site: str = ""
    other: list[str] = Field(default_factory=list)


class Personal(BaseModel):
    full_name: str = ""
    gender: str = ""  # Мужчина / Женщина
    birth_date: str = ""  # свободная строка, опционально
    city: str = ""
    # Страна(ы) проживания. В форме поля нет: заполняется дериватом из `city` при сохранении
    # (`apply_city_derived_countries`). JSON-ключ сохранён — попадает в markdown и держит
    # редкое второе резидентство, которое руками править можно только через JSON.
    work_countries: list[str] = Field(default_factory=list)
    relocation: str = ""  # «Не готов» / «Только командировки» / «Готов полностью»


class DesiredPosition(BaseModel):
    title: str = ""
    salary_min: int | None = None
    salary_comfortable: int | None = None
    salary_currency: str = "RUB"
    # Пусто = «на руки» (историческое неявное поведение). Поле появилось потому, что
    # бенчмарки в salary_estimator считались gross, а порог кандидата - net.
    salary_basis: str = ""  # «На руки» / «До вычета»
    employment: str = ""  # Полная занятость / Подработка / Стажировка
    schedule: list[str] = Field(
        default_factory=list
    )  # допустимые форматы: Офис / Гибрид / Удалённо
    grade: list[str] = Field(
        default_factory=list
    )  # целевой грейд: Junior/Middle/Senior/Lead/C-level
    company_types: list[str] = Field(default_factory=list)  # предпочтения кандидата
    categories: list[str] = Field(
        default_factory=list,
        description=(
            f"1-{RESUME_CATEGORIES_MAX} значения из списка: {resume_categories_prompt_list()}"
        ),
    )

    @field_validator("schedule", mode="before")
    @classmethod
    def _schedule_from_legacy_string(cls, v: object) -> object:
        """До UX3-22 `schedule` был одиночной строкой — старые `resume_data.json` мигрируем на лету."""
        if isinstance(v, str):
            return [v] if v else []
        return v

    @field_validator("categories", mode="before")
    @classmethod
    def _categories_from_legacy(cls, v: object) -> object:
        """Старые getmatch-слаги («Product/Project/Architecture») → канон формы."""
        return normalize_categories(v)


class SearchCriteria(BaseModel):
    # В UI - «Приоритеты» (что важнее в вакансии), не «ниши/направления». JSON-ключ niches
    # сохранён ради истории резюме и matched_niche в скоринге. Порядок = убывание приоритета; ≤6.
    niches: list[str] = Field(default_factory=list)
    # «Делаю руками» / «Управляю людьми» / «И то, и другое». Пусто = шкала «Управление» нейтральна.
    role_kind: str = ""
    # Ключ сегмента зарплатных наблюдений и подпись в аналитике. Мульти-выбор на фронте
    # склеивает несколько отраслей запятыми («IT, Банки / Финтех»); «Любые» = пусто.
    market_segment: str = ""
    # Рынок поиска: «Только РФ» / «Международный» / «Любой». Пусто = «Только РФ» (дефолт
    # сохранённых резюме, заведённых до появления оси). Нормализация в слаг и вся логика —
    # `profile.profile.derive_candidate_profile` → `CandidateProfile.market_scope`.
    market_scope: str = ""
    target_companies: list[str] = Field(default_factory=list)  # +5 тай-брейкер калибровки
    avoid_companies: list[str] = Field(default_factory=list)  # жёсткий гейт → skip
    dealbreakers: list[str] = Field(
        default_factory=list
    )  # «Ред флаги» (UX6) — жёсткие стоп-условия из закрытого списка на фронте
    notes: str = (
        ""  # свободный контекст (локация/гражданство/специфика — раньше жили в instructions.md)
    )


class Experience(BaseModel):
    company: str = ""
    company_url: str = ""
    industry: str = ""  # отрасль/сфера компании
    position: str = ""
    start: str = ""  # «Март 2024»
    end: str = ""  # «Май 2026»; пусто + current=True → «по настоящее время»
    current: bool = False
    area: str = ""  # регион
    description: str = ""  # обязанности, функции, достижения (многострочный markdown)


class Education(BaseModel):
    degree: str = ""  # Магистр / Бакалавр / Среднее специальное …
    year: str = ""  # год окончания (или ожидаемый)
    institution: str = ""
    faculty: str = ""
    specialization: str = ""


class Course(BaseModel):
    name: str = ""
    organization: str = ""
    year: str = ""


class Language(BaseModel):
    name: str = ""
    level: str = ""  # CEFR A1..C2 или «Родной»


class ResumeData(BaseModel):
    """Резюме по полям hh.ru — источник правды вкладки «Резюме»."""

    personal: Personal = Field(default_factory=Personal)
    contacts: Contacts = Field(default_factory=Contacts)
    position: DesiredPosition = Field(default_factory=DesiredPosition)
    search_criteria: SearchCriteria = Field(default_factory=SearchCriteria)
    experience: list[Experience] = Field(default_factory=list)
    experience_total: str = ""  # «4 года 3 месяца» — справочно (hh считает сам)
    education_level: str = ""  # Высшее / Неоконченное высшее …
    education: list[Education] = Field(default_factory=list)
    courses: list[Course] = Field(default_factory=list)
    key_skills: list[str] = Field(default_factory=list)  # теги (ATS-связка)
    languages: list[Language] = Field(default_factory=list)
    about: str = ""  # «Обо мне» — свободный текст


class PersonalPatch(BaseModel):
    """Точечные автосейв-поля `Personal` (select-боксы формы) — текст ФИО/город через PUT."""

    gender: str | None = None
    work_countries: list[str] | None = None
    relocation: str | None = None


class DesiredPositionPatch(BaseModel):
    """Точечные автосейв-поля `DesiredPosition` — остальные через PUT."""

    schedule: list[str] | None = None
    grade: list[str] | None = None
    company_types: list[str] | None = None
    employment: str | None = None
    salary_min: int | None = None
    salary_comfortable: int | None = None
    salary_currency: str | None = None
    salary_basis: str | None = None
    categories: list[str] | None = None

    @field_validator("categories", mode="before")
    @classmethod
    def _categories_from_legacy(cls, v: object) -> object:
        if v is None:
            return None
        return normalize_categories(v)


class SearchCriteriaPatch(BaseModel):
    """Точечные автосейв-поля `SearchCriteria` (UX4-0/UX4-9/UX6/FR2-42) — остальные через PUT."""

    niches: list[str] | None = None
    role_kind: str | None = None
    market_segment: str | None = None
    market_scope: str | None = None
    dealbreakers: list[str] | None = None
    target_companies: list[str] | None = None
    avoid_companies: list[str] | None = None


class ResumeDataPatch(BaseModel):
    """Частичное обновление резюме (`PATCH /api/resume/data`): read-modify-write на файл.

    Автосейв для select/multi-select (без кнопки «Сохранить»). Свободный текст и длинные
    списки опыта по-прежнему через `PUT`. `education`/`languages` — полная замена массива
    (иначе нельзя точечно обновить degree/level одной строки).
    """

    personal: PersonalPatch | None = None
    position: DesiredPositionPatch | None = None
    search_criteria: SearchCriteriaPatch | None = None
    education_level: str | None = None
    education: list[Education] | None = None
    languages: list[Language] | None = None
    key_skills: list[str] | None = None


_CURRENCY_SIGN = {"RUB": "₽", "USD": "$", "EUR": "€"}

#: Рынок поиска: подписи для UI/промптов. Пустое значение резюме читается как `MARKET_SCOPE_RU`.
MARKET_SCOPE_RU = "Только РФ"
MARKET_SCOPE_INTL = "Международный"
MARKET_SCOPE_ANY = "Любой"
MARKET_SCOPE_OPTIONS: tuple[str, ...] = (MARKET_SCOPE_RU, MARKET_SCOPE_INTL, MARKET_SCOPE_ANY)


def market_scope_label(raw: str) -> str:
    """Значение резюме → подпись рынка поиска. Пусто/мусор → «Только РФ» (дефолт)."""
    value = (raw or "").strip()
    for option in MARKET_SCOPE_OPTIONS:
        if value.casefold() == option.casefold():
            return option
    return MARKET_SCOPE_RU


def is_currently_employed(data: ResumeData) -> bool | None:
    """Работает ли кандидат сейчас — по галочке «по настоящее время» в опыте.

    Даты в опыте система почти не читает (свободные строки «Март 2024»), а вот сам флаг
    `current` несёт факт, который меняет разговор: есть текущее место (нужен нотис, есть
    рычаг в торге, вторая работа — совмещение) или кандидат уже свободен. `None` — опыта в
    резюме нет вовсе, гадать не о чем.
    """
    if not data.experience:
        return None
    return any(exp.current for exp in data.experience)


def _salary_basis_suffix(pos: DesiredPosition) -> str:
    """Суффикс базиса к строке зарплаты. Пустое поле = «на руки» (исторический дефолт)."""
    raw = (pos.salary_basis or "").strip()
    if not raw or raw.casefold() in {"на руки", "net"}:
        return " на руки"
    if raw.casefold() in {"до вычета", "gross"}:
        return " до вычета"
    return f" {raw}"


def _salary_range_md(pos: DesiredPosition) -> str:
    sign = _CURRENCY_SIGN.get(pos.salary_currency, pos.salary_currency)
    basis = _salary_basis_suffix(pos)
    if pos.salary_min and pos.salary_comfortable:
        core = f"от {pos.salary_min:,} до {pos.salary_comfortable:,} {sign}".replace(",", " ")
        return f"{core}{basis}"
    if pos.salary_min:
        core = f"от {pos.salary_min:,} {sign}".replace(",", " ")
        return f"{core}{basis}"
    if pos.salary_comfortable:
        core = f"до {pos.salary_comfortable:,} {sign}".replace(",", " ")
        return f"{core}{basis}"
    return ""


_MONTHS_RU = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]


def _format_month(value: str) -> str:
    """«YYYY-MM» (DatePicker) → «март 2024». Не-ISO значения (старые записи,
    введённые до перехода на календарь) возвращаются как есть."""
    if len(value) == 7 and value[4] == "-":
        try:
            year, month = int(value[:4]), int(value[5:7])
            return f"{_MONTHS_RU[month - 1]} {year}"
        except (ValueError, IndexError):
            pass
    return value


def _experience_md(exp: Experience) -> str:
    end = exp.end or ("по настоящее время" if exp.current else "")
    period = " - ".join(_format_month(p) for p in (exp.start, end) if p)
    place = ", ".join(p for p in (exp.area, exp.company_url) if p)
    head = " — ".join(p for p in (exp.company, exp.position) if p)
    lines = [f"### {head}"]
    if period:
        lines.append("")
        lines.append(period)
    if place:
        lines.append("")
        lines.append(place)
    if exp.industry:
        lines.append("")
        lines.append(exp.industry)
    if exp.description.strip():
        lines.append("")
        lines.append(exp.description.strip())
    return "\n".join(lines)


def _education_md(ed: Education) -> str:
    head = " — ".join(p for p in (ed.degree, ed.year) if p)
    lines = [f"### {head}"]
    tail = [p for p in (ed.institution, ed.faculty, ed.specialization) if p]
    if tail:
        lines.append("")
        lines.extend(tail)
    return "\n".join(lines)


def apply_city_derived_countries(data: ResumeData) -> ResumeData:
    """Проставить `work_countries` из города. Нераспознанный город и второе резидентство
    не трогаем — страна не угадывается и руками введённое не затирается.
    """
    next_countries = derived_work_countries(data.personal.city, data.personal.work_countries)
    if next_countries is None or next_countries == data.personal.work_countries:
        return data
    return data.model_copy(
        update={"personal": data.personal.model_copy(update={"work_countries": next_countries})}
    )


def to_markdown(data: ResumeData) -> str:
    """Сериализовать структурное резюме в markdown-канон (его инжектит скоринг).

    Раскладка повторяет распарсенный из PDF канон, чтобы текст для скоринга остался
    эквивалентным полям hh.
    """
    p, c, pos = data.personal, data.contacts, data.position
    out: list[str] = []

    out.append(f"# {p.full_name}".rstrip())
    if p.gender:
        out += ["", p.gender]

    contact_lines = []
    if c.phone:
        suffix = " (предпочитаемый способ связи)" if c.phone_preferred else ""
        contact_lines.append(f"- Телефон: {c.phone}{suffix}")
    if c.telegram:
        contact_lines.append(f"- Telegram: {c.telegram}")
    if c.email:
        contact_lines.append(f"- Email: {c.email}")
    if c.site:
        contact_lines.append(f"- Сайт: {c.site}")
    for other in c.other:
        contact_lines.append(f"- {other}")
    if p.city:
        contact_lines.append(f"- Проживает: {p.city}")
    if p.work_countries:
        contact_lines.append(f"- Страна проживания: {', '.join(p.work_countries)}")
    if p.relocation:
        contact_lines.append(f"- Релокация: {p.relocation}")
    employed = is_currently_employed(data)
    if employed is not None:
        contact_lines.append(
            "- Статус: сейчас работает (нужен срок на выход)"
            if employed
            else "- Статус: сейчас без работы (может выйти быстро)"
        )
    if contact_lines:
        out += ["", *contact_lines]

    # --- Желаемая должность и зарплата ---
    out += ["", "## Желаемая должность и зарплата"]
    if pos.title:
        out += ["", f"**{pos.title}**"]
    salary_range = _salary_range_md(pos)
    if salary_range:
        out += ["", f"Желаемая зарплата: {salary_range}."]
    if pos.categories:
        out += ["", "Категории:", ""]
        out += [f"- {c}" for c in pos.categories]
    job_lines = []
    if pos.employment:
        job_lines.append(f"- Тип занятости: {pos.employment}")
    if pos.schedule:
        job_lines.append(f"- Формат работы: {', '.join(pos.schedule)}")
    if pos.grade:
        job_lines.append(f"- Целевой грейд: {', '.join(pos.grade)}")
    if pos.company_types:
        job_lines.append(f"- Интересные типы компаний: {', '.join(pos.company_types)}")
    if job_lines:
        out += ["", *job_lines]

    # --- Критерии поиска ---
    sc = data.search_criteria
    criteria_lines = []
    if sc.role_kind.strip():
        criteria_lines.append(f"- Тип роли: {sc.role_kind.strip()}")
    # Рынок поиска печатается всегда, в том числе дефолтом: «Только РФ» — такое же указание
    # кандидата, как и остальные, и модель должна его видеть, а не додумывать.
    criteria_lines.append(f"- Рынок поиска: {market_scope_label(sc.market_scope)}")
    if sc.market_segment.strip():
        criteria_lines.append(f"- Рынок / отрасль: {sc.market_segment.strip()}")
    if sc.niches:
        criteria_lines.append(f"- Приоритеты (по убыванию): {', '.join(sc.niches)}")
    if sc.target_companies:
        criteria_lines.append(f"- Целевые компании: {', '.join(sc.target_companies)}")
    if sc.avoid_companies:
        criteria_lines.append(
            f"- Компании, которых лучше избегать: {', '.join(sc.avoid_companies)}"
        )
    if sc.dealbreakers:
        criteria_lines.append("- Ред флаги:")
        criteria_lines += [f"  - {d}" for d in sc.dealbreakers]
    if criteria_lines or sc.notes.strip():
        out += ["", "## Критерии поиска"]
        if criteria_lines:
            out += ["", *criteria_lines]
        if sc.notes.strip():
            out += ["", sc.notes.strip()]

    # --- Опыт работы ---
    if data.experience:
        head = "## Опыт работы"
        if data.experience_total:
            head += f" — {data.experience_total}"
        out += ["", head]
        for exp in data.experience:
            out += ["", _experience_md(exp)]

    # --- Образование ---
    if data.education or data.education_level:
        out += ["", "## Образование"]
        if data.education_level:
            out += ["", f"Уровень образования: {data.education_level}"]
        for ed in data.education:
            out += ["", _education_md(ed)]

    # --- Повышение квалификации ---
    if data.courses:
        out += ["", "## Повышение квалификации, курсы"]
        for course in data.courses:
            parts = " — ".join(x for x in (course.name, course.organization, course.year) if x)
            out += ["", f"- {parts}"]

    # --- Навыки + языки ---
    out += ["", "## Навыки"]
    if data.languages:
        out.append("")
        for lang in data.languages:
            pair = " — ".join(x for x in (lang.name, lang.level) if x)
            out.append(f"- Знание языков: {pair}")
    if data.key_skills:
        out += ["", f"**Навыки:** {', '.join(data.key_skills)}"]

    # --- Обо мне ---
    if data.about.strip():
        out += ["", "## Дополнительная информация", "", "**Обо мне**", "", data.about.strip()]

    return "\n".join(out).strip() + "\n"
