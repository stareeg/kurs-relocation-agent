"""Контракты скоринга (перенос из backend/schemas/score.py, задача 1.5).

`ScoreResult` теперь живёт в ядре (раньше jobs.py держал score как сырой jsonb-словарь,
см. его docstring). `VacancyInput` — лёгкий вход скоринга.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Старые абсолютные уровни в jsonb `jobs.score` (до относительной шкалы) → канон.
_LEGACY_GRADE_LEVELS: dict[str, str] = {
    "senior_plus": "match",
    "senior": "match",
    "techlead": "match",
    "teamlead": "match",
    "lead": "match",
    "mid": "slightly_below",
    "middle": "slightly_below",
    "junior": "far_below",
    "generic_backend": "off_profile",
    "wrong_domain_senior": "off_profile",
}


class RemoteAbroadCompat(BaseModel):
    level: Literal["ideal", "ok", "risky", "blocker"]
    reasoning: str


class GradeMatch(BaseModel):
    """Совпадение грейда вакансии с целевым грейдом из резюме (относительная шкала).

    Не абсолютная лестница Senior/Middle: `match` = попадание в цель кандидата,
    `above` / `slightly_below` / `far_below` = сдвиг относительно неё, `off_profile` = не про
    эту роль/профиль.
    """

    level: Literal["above", "match", "slightly_below", "far_below", "off_profile"]
    reasoning: str
    off_profile_kind: Literal["other_profession", "role_shift", ""] = Field(
        default="",
        description=(
            "Уточнение к level=off_profile: other_profession - другая специальность; "
            "role_shift - та же профессия, но сдвиг IC↔менеджмент. Пусто = other_profession "
            "(старый jsonb или модель не заполнила)."
        ),
    )

    @field_validator("level", mode="before")
    @classmethod
    def _coerce_legacy_level(cls, value: object) -> object:
        if isinstance(value, str):
            mapped = _LEGACY_GRADE_LEVELS.get(value.strip().lower())
            if mapped is not None:
                return mapped
        return value

    @property
    def is_role_shift(self) -> bool:
        """`off_profile`, который на самом деле сдвиг IC↔менеджмент, а не другая специальность.

        Одна метка `off_profile` накрывала и «консультант по нефинансовой отчётности»
        (`role_content` 5), и «AI product manager» (`role_content` 82, владелец откликнулся) —
        и обрабатывала их одинаково: ×0.5 + форс skip
        (plans/scoring_precision_2026_08_17.md §1.8). Разводим по этому флагу.

        Пустой `off_profile_kind` → False: старый сохранённый jsonb ведёт себя как раньше
        (other_profession, жёсткий гейт).
        """
        return self.level == "off_profile" and self.off_profile_kind == "role_shift"


class SalaryInfo(BaseModel):
    meets_min: bool
    value_or_range: str
    estimated_range: str = ""
    estimated_min: int | None = None
    estimated_max: int | None = None
    note: str
    # Провенанс вилки (шаги 19–22). estimate_pending — фоновый LLM ещё считает.
    # explicit — названная вилка (JD / страница / HR); дальше не пересчитываем.
    # "anchor" убран из Literal (Этап 8 §8.5, D14): якорный путь удалён 2026-08-08
    # (scorer.py), на проде 0 строк с этим значением (проверено перед удалением).
    confidence: Literal["high", "medium", "low"] = "low"
    source: Literal["explicit", "corpus", "llm", "none"] = "none"
    estimate_pending: bool = False


class RoleContentMatch(BaseModel):
    score: int = Field(ge=0, le=100)
    matched_niche: list[str]
    reasoning: str


class BurnoutRisk(BaseModel):
    """Доля управления в роли (UI: «Управление»; имя поля jsonb не менять).

    `low` = мало людей / много своей работы; `high` = в основном управление людьми и процессами.
    Направление шкалы (плюс/минус) задаёт `role_kind` профиля в `compute_score_breakdown`, не LLM.
    """

    level: Literal["low", "medium", "high"]
    reasoning: str


class CompanyFit(BaseModel):
    """Размер/репутация компании относительно предпочтений кандидата (вес «Компания»)."""

    level: Literal["strong", "ok", "weak", "unknown"] = "unknown"
    reasoning: str = ""


class ScoreAdjustment(BaseModel):
    """Одна мягкая калибровка `overall_score`: не гейт-cap, а +N/-N с причиной.

    Раньше причина только логировалась (`apply_calibration`) и терялась — строка остатка
    «сумма breakdown != overall_score» в UI не могла объяснить, откуда остаток взялся.
    """

    delta: int
    reason: str


class ScoreResult(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    recommendation: Literal["strong_apply", "apply", "maybe", "skip"]
    remote_abroad_compat: RemoteAbroadCompat
    grade_match: GradeMatch
    salary: SalaryInfo
    role_content_match: RoleContentMatch
    burnout_risk: BurnoutRisk
    company_fit: CompanyFit = Field(default_factory=CompanyFit)
    company_type: Literal[
        "product",
        "fintech_product",
        "bank",
        "startup",
        "outsource",
        "infra",
        "agency",
        "media",
        "retail",
        "manufacturing",
        "education",
        "government",
        "nonprofit",
        "smb",
        "unknown",
    ]
    pros: list[str] = Field(min_length=1)
    cons: list[str] = Field(min_length=1)
    red_flags: list[str]
    one_line_verdict: str
    work_city: str = Field(
        default="",
        description="Город офиса/работы (Москва, Казань…); пусто если удалёнка или не указан",
    )
    currency_remote: bool = Field(
        default=False,
        description=(
            "Валютная удалёнка: вакансия явно от зарубежной компании/найм оформлен на "
            "зарубежное юрлицо, зарплата в валюте (USD/EUR) - не просто удалёнка по РФ."
        ),
    )
    score_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Не заполнять — считается детерминированно постпроцессингом (EXT-S1), не моделью."
        ),
    )
    gate_triggered: str | None = Field(
        default=None,
        description=(
            "Не заполнять — заполняется постпроцессингом, если жёсткий гейт срезал "
            "overall_score (EXT-S1)."
        ),
    )
    adjustments: list[ScoreAdjustment] = Field(
        default_factory=list,
        description=(
            "Не заполнять — заполняется постпроцессингом: мягкие калибровки (target/avoid "
            "компания, формат, командировки), применённые к overall_score до caps."
        ),
    )
    weights_version: str = Field(
        default="",
        description=(
            "Не заполнять — версия рубрики (хэш весов/role_kind/порогов), которой посчитан "
            "score_breakdown (Этап 5, EXT-S1). Пусто = старая запись до введения версии."
        ),
    )
    track: Literal["primary", "second_job"] = Field(
        default="primary",
        description=(
            "Не заполнять — трек вакансии (постпроцессинг `track_classify`, Э2.2). "
            "primary = основная работа, second_job = подработка/контракт."
        ),
    )


class RemoteSignal(BaseModel):
    """Один сигнал про реальность удалёнки: цитата/факт из текста вакансии + полярность.

    `text` — по возможности дословная цитата из вакансии (чтобы UI подсветил место в тексте).
    `polarity` — «pro» (за реальность полной удалёнки) или «contra» (против: офис/гибрид/
    присутствие/удалёнка только релокантам за рубеж и т.п.).
    """

    text: str
    polarity: Literal["pro", "contra"]


class RemoteFeasibility(BaseModel):
    """Под-скор «реально ли в этой команде полная удалёнка» (feature_ideas 2.2).

    Параллелен `ScoreResult` и НЕ влияет на его вердикт — отдельный сигнал под жёсткое условие
    владельца (полная удалёнка, целевая зарплата — см. резюме). Отсекает фейк-ремоут до того,
    как слили время на диалог.
    `score` 0..100 (выше = удалёнка реальнее), `verdict` — итог, `signals` — обосновывающие
    цитаты, `note` — одна фраза «стоит ли тратить время».
    """

    score: int = Field(ge=0, le=100)
    verdict: Literal["real", "conditional", "unlikely"]
    signals: list[RemoteSignal] = Field(default_factory=list)
    note: str = ""


class CompetitionInsight(BaseModel):
    """Под-скор «шанс на отклик» (Этап 6 §6.2, plans/scoring_precision_2026_08_17.md).

    Параллелен `ScoreResult` и НЕ влияет на его вердикт — намеренно НЕ входит в overall_score,
    пока нет данных, чтобы измерить корреляцию с реальными исходами (Этап 7). Чисто
    детерминированный расчёт (`competition.py`) из `total_responses`/`published_at`/
    `letter_required` — без LLM, без сетевых вызовов, считается синхронно при скоринге.

    `level` — «favorable» (мало заявок относительно возраста вакансии) / «neutral» /
    «crowded» (много заявок за короткий срок) / «unknown» (нет `total_responses` — сейчас
    почти всегда: hh.ru не отдаёт счётчик на странице вакансии, см. `competition.py`).
    """

    level: Literal["favorable", "neutral", "crowded", "unknown"] = "unknown"
    responses_per_day: float | None = None
    age_days: int | None = None
    reasoning: str = ""


class AnketaOption(BaseModel):
    id: str
    label: str


class AnketaQuestion(BaseModel):
    """Один вопрос анкеты работодателя при отклике (Фаза 3, hh.ru — единственная площадка,
    где эта механика вообще заявлена, см. auto_apply_roadmap_2026_08_17.md §3).

    `type` — по факту живой разведки DOM (`plans/hh_integration/anketa_example_bankssoft.md`):
    `single_choice` (radio) / `multi_choice` (checkbox) / `text` (textarea). Отдельного
    `boolean` не завели — живые «да/нет»-подобные вопросы приходят с 3-4 вариантами, не
    строго двумя. `options` — только для choice-типов, `id`/`label` варианта (для choice
    `id` — числовой ID варианта на стороне hh.ru, нужен для реальной отправки, не просто
    текст).
    """

    id: str
    text: str
    type: Literal["text", "single_choice", "multi_choice"]
    options: list[AnketaOption] = Field(default_factory=list)


class AnketaAnswer(BaseModel):
    """Ответ на один вопрос анкеты — для choice-типов `value` это `AnketaOption.id`, для
    `text` — сам сгенерированный/отредактированный текст."""

    question_id: str
    value: str


class AnketaState(BaseModel):
    """Состояние очереди подтверждения одной вакансии — анкета работодателя (Фаза 3.3) ИЛИ,
    начиная с Фазы 3.4, простое подтверждение отклика в режиме «Тест» (`require_confirmation`)
    без анкеты вовсе. `questions`/`answers` пустые в случае 3.4 — единственное, что владелец
    подтверждает тогда, это сопроводительное (`jobs.cover_letter_text`, отдельная колонка, не
    дублируется сюда — раннер на повторном визите берёт письмо оттуда как есть, правка через
    обычный `PATCH /api/jobs/{id}` уже работает для этого поля). Не два разных механизма —
    одна очередь `pending → approved/rejected → applied/failed`, различается только тем, есть
    ли вопросы.

    `pending` — сгенерировано (анкета) или запарковано (простое подтверждение), ждёт владельца;
    `approved` — владелец подтвердил (для анкеты — возможно отредактированные `answers`),
    раннер подхватит на следующем тике и заполнит форму заново; `rejected` — владелец отклонил,
    дальше не идём; `applied`/`failed` — раннер попытался реально отправить. `platform` сегодня
    почти всегда `"hh"` (анкета — только hh.ru; простое подтверждение, Фаза 3.4, доступно на
    любой площадке через `require_confirmation`).
    """

    status: Literal["pending", "approved", "rejected", "applied", "failed"] = "pending"
    platform: str = "hh"
    questions: list[AnketaQuestion] = Field(default_factory=list)
    answers: list[AnketaAnswer] = Field(default_factory=list)
    requested_at: str = ""
    resolved_at: str | None = None


class SkillRequirement(BaseModel):
    """Один требуемый навык вакансии.

    `importance` — «required» (явно обязательное требование) или «preferred» (плюс/желательно).
    `skill` — очищенное от HR-обвязки название, не цитата целиком.
    """

    skill: str
    importance: Literal["required", "preferred"]


class VacancySkillRequirements(BaseModel):
    """Structured-выход фичи `vacancy_skill_requirements` — обёртка списка под LLM-схему."""

    skills: list[SkillRequirement] = Field(default_factory=list)


class TermEvidence(BaseModel):
    """Дословная цитата из вакансии + поле, которое она обосновывает."""

    field: str
    quote: str = Field(max_length=400)


class VacancyWorkTerms(BaseModel):
    """Условия работы, извлечённые из текста вакансии (фича `vacancy_work_terms`).

    Только факты и цитаты. Ни одного вердикта: «подходит / не подходит» считает
    `score_breakdown` из этих полей и профиля кандидата.
    """

    engagement: Literal["employment", "contractor", "b2b", "freelance", "internship", "unknown"] = (
        "unknown"
    )
    scope: Literal["full_time", "part_time", "project", "unknown"] = "unknown"

    geo_scope: Literal["worldwide", "region", "country_list", "single_city", "unknown"] = "unknown"
    hiring_geo: list[str] = Field(default_factory=list)
    residency_required: bool = False
    payroll_form: Literal["w2", "eor", "local_entity", "contractor_invoice", "unknown"] = "unknown"

    timezone_requirement: str = ""
    overlap_hours_required: int | None = None
    async_culture: Literal["async_first", "hybrid_sync", "sync_heavy", "unknown"] = "unknown"
    time_tracking: Literal["required", "optional", "none", "unknown"] = "unknown"
    meeting_load: Literal["low", "medium", "high", "unknown"] = "unknown"
    on_call: bool = False

    exclusivity: Literal["required", "not_mentioned", "allowed"] = "not_mentioned"
    ip_scope: Literal["work_only", "all_inventions", "unclear"] = "unclear"
    weekly_hours: int | None = None

    currency: str = ""
    rate_period: Literal["hour", "day", "month", "year", "unknown"] = "unknown"
    rate_min: int | None = None
    rate_max: int | None = None

    evidence: list[TermEvidence] = Field(default_factory=list, max_length=16)


class VacancyInput(BaseModel):
    """Вход скоринга + персиста."""

    text: str = Field(min_length=50, description="Полный текст вакансии")
    url: str | None = None
    vacancy_id: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    area: str | None = None
    work_format: str | None = None
    work_schedule: str | None = None
    total_responses: int | None = Field(default=None, ge=0)
    letter_required: bool | None = None
    published_at: str | None = None
    cover_letter_text: str | None = None
    employer_id: str | None = None
    # Каноничные значения — `core.repo.jobs.ALL_JOB_SOURCES`; поле осталось свободным str
    # (не Literal), чтобы не валить приём с внешних поверхностей (расширение/бот) на неизвестном
    # значении — источник только на чтение/аналитику, не гейт.
    source: str | None = None
    is_archived: bool = False
    # Начальный статус воронки; None → "Просмотр" (DEFAULT_FUNNEL_STATUS).
    status: str | None = None
    # Структурированные поля Хабр Карьеры (интеграция habr): несут разметку отдельно от
    # склеенного `text` — для детерминированного маппинга грейда/валюты/стека без повторного
    # LLM-извлечения. Опциональны и не ломают контракт hh/getmatch/telegram.
    skills: list[str] | None = None
    qualification: str | None = None
    salary_currency: str | None = None
    specialization: str | None = None
    seniority: str | None = None
    # Observability: метод парсинга вакансии в расширении (getmatch: 'rsc' | 'jsonld' | 'dom').
    # Не персистится и не участвует в скоринге — только уровень лог-события источника парсинга.
    parse_method: str | None = None
    # Структурные подсказки площадки (Э2.6): то, что DOM/JSON-LD отдаёт сам, без LLM.
    # Инжектятся в экстракцию `vacancy_work_terms` доверенным блоком и побеждают догадку модели.
    employment_type: str | None = None
    location_raw: str | None = None
    remote_type: str | None = None


class SkipReasonSuggestion(BaseModel):
    """Одна конкретная причина пропуска, сгенерированная LLM под вакансию.

    `text` — короткий лаконичный лейбл чипа (что именно смутило в этой вакансии);
    пользователь видит его на кнопке. `canonical` — каноническая причина из
    `SELF_SKIP_REASONS`, куда чип мапится под капотом (для аналитики/грид-метрик).
    LLM генерирует обе части сразу, чтобы маппинг был точным, а не угадывался
    regex-каскадом по тексту.
    """

    text: str = Field(min_length=2, max_length=80, description="Краткий лейбл чипа")
    canonical: Literal[
        "Низкий грейд",
        "Низкая зарплата",
        "Не тот стек/домен",
        "Не тот формат",
        "Не та роль (IC vs рук)",
    ]


class SkipReasonsPack(BaseModel):
    """Structured-выход фичи `skip_reasons_gen` — 6 конкретных причин под вакансию.

    «Избегать компанию» не входит в LLM-генерацию: это отдельная статичная кнопка
    (не зависит от текста вакансии), а LLM-причины покрывают только содержательные
    оси (грейд/зарплата/домен/формат/роль). Если для какой-то оси нет осмысленной
    причины, LLM всё равно обязан выдать ровно одну на каждую из 5 осей — итого 5;
    шестую (любую ось, где есть второй нюанс) LLM добавляет по своему выбору, чтобы
    дать 6 чипов. На UI чипы показываются как есть, маппинг в канон уже готов.
    """

    reasons: list[SkipReasonSuggestion] = Field(min_length=6, max_length=6)
