"""Транспортные схемы API: jobs."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from api.schemas.chat import AskMessage
from core.domains.opportunities.jobs import Job as _CoreJob
from core.domains.opportunities.jobs import JobLink as _CoreJobLink
from core.domains.opportunities.jobs import JobsPage as _CoreJobsPage
from core.domains.opportunities.models import (
    AnketaState,
    CompetitionInsight,
    RemoteFeasibility,
    ScoreResult,
    VacancyWorkTerms,
)

logger = logging.getLogger(__name__)

# --- Экспорт вакансии (`GET /api/jobs`, `GET /api/jobs/by-vacancy/{id}`), B-03 ---
# `core.domains.opportunities.jobs.Job.score` осознанно голый `dict[str, Any]` (см. его
# docstring) — репозиторный слой обязан читать jsonb и от легаси-записей, которые ещё не
# валидируются в ScoreResult (до бэкфилла B-01 или из списка «требует перескоринга»). На
# транспортном контракте это, наоборот, полная форма ScoreResult — иначе schema.d.ts не даёт
# фронту `score_breakdown`/`gate_triggered`/`company_fit`. Невалидный score на выдаче не должен
# ронять всю ручку 500 — мягкая деградация в `None` + лог, не исключение.


class JobLink(_CoreJobLink):
    """Площадочная ссылка логической вакансии (транспортная копия доменной JobLink)."""


class Job(_CoreJob):
    score: ScoreResult | None = None
    anketa: AnketaState | None = None
    work_terms: VacancyWorkTerms | None = None
    links: list[JobLink] = Field(default_factory=list)

    @field_validator("score", mode="before")
    @classmethod
    def _soft_score(cls, value: Any) -> Any:
        if not value or isinstance(value, ScoreResult):
            return value or None
        try:
            return ScoreResult.model_validate(value)
        except ValidationError as exc:
            logger.warning("jobs.score не провалидировался в ScoreResult, отдаю null: %s", exc)
            return None

    @field_validator("anketa", mode="before")
    @classmethod
    def _soft_anketa(cls, value: Any) -> Any:
        if not value or isinstance(value, AnketaState):
            return value or None
        try:
            return AnketaState.model_validate(value)
        except ValidationError as exc:
            logger.warning("jobs.anketa не провалидировался в AnketaState, отдаю null: %s", exc)
            return None

    @field_validator("work_terms", mode="before")
    @classmethod
    def _soft_work_terms(cls, value: Any) -> Any:
        if not value or isinstance(value, VacancyWorkTerms):
            return value or None
        try:
            return VacancyWorkTerms.model_validate(value)
        except ValidationError as exc:
            logger.warning("jobs.work_terms не провалидировался, отдаю null: %s", exc)
            return None


class JobsPage(_CoreJobsPage):
    jobs: list[Job]


# --- Скоринг (контракт совместим по смыслу с расширением, подшаг 4) ---


class ScoreRequest(BaseModel):
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
    employer_id: str | None = None
    source: str | None = None
    is_archived: bool = False
    # Структурированные поля Хабр Карьеры (интеграция habr): несут разметку отдельно от
    # склеенного `text` — для детерминированного маппинга грейда/валюты/стека без повторного
    # LLM-извлечения. Опциональны и не ломают контракт hh/getmatch/telegram.
    skills: list[str] | None = None
    qualification: str | None = None
    salary_currency: str | None = None
    specialization: str | None = None
    seniority: str | None = None
    # Observability: метод парсинга в расширении. hh: config|default|structural;
    # getmatch: rsc|jsonld|dom. Не персистится и не участвует в скоринге.
    parse_method: str | None = None
    # Структурные подсказки площадки (Э2.6): то, что DOM/JSON-LD отдаёт сам. Опциональны.
    employment_type: str | None = None
    location_raw: str | None = None
    remote_type: str | None = None


class ScoreResponse(BaseModel):
    """VacancyRecord-подобный ответ: метаданные вакансии + ScoreResult. `persisted` — легла ли
    запись в PG (при недоступной БД скоринг всё равно возвращается)."""

    id: int | None = None
    vacancy_id: str | None = None
    url: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    area: str | None = None
    work_format: str | None = None
    work_schedule: str | None = None
    total_responses: int | None = None
    letter_required: bool | None = None
    published_at: str | None = None
    employer_id: str | None = None
    source: str | None = None
    is_archived: bool = False
    status: str | None = None
    scored_at: datetime | None = None
    persisted: bool = False
    score: ScoreResult
    # Под-скор реальности полной удалёнки (feature_ideas 2.2); None - не посчитан (best-effort).
    remote_feasibility: RemoteFeasibility | None = None
    # Под-скор «шанс на отклик» (Этап 6 §6.2) — считается всегда (чистая функция), level="unknown"
    # означает «нет total_responses», не «не посчитан».
    competition: CompetitionInsight | None = None


class SalaryEstimatePoll(BaseModel):
    """Ответ полла фоновой оценки вилки (`GET /score/{vacancy_id}/salary`)."""

    vacancy_id: str | None = None
    estimate_pending: bool = False
    estimated_range: str = ""
    estimated_min: int | None = None
    estimated_max: int | None = None
    value_or_range: str = ""
    meets_min: bool = False
    note: str = ""
    confidence: str = "low"
    source: str = "none"
    task_running: bool = False


class WeightsVersionOut(BaseModel):
    """Версия рубрики скоринга ПРЯМО СЕЙЧАС (Этап 5 §5.1/§5.3) — для сравнения с
    `Job.score_weights_version` на карточке: карточка «отстала», если строки не совпадают.
    `second_job_weights_version` — та же идея для рубрики второго трека."""

    weights_version: str = ""
    second_job_weights_version: str = ""


class WeightsRecomputeOut(BaseModel):
    """Ответ кнопки «Пересчитать» на карточке (`POST /score/{vacancy_id}/recompute-weights`):
    узкий пересчёт по текущей рубрике в обход полного `/score` — без LLM."""

    vacancy_id: str | None = None
    overall_score: int | None = None
    recommendation: str | None = None
    score: ScoreResult | None = None
    weights_version: str = ""


class SimulateWeightsRequest(BaseModel):
    """Тело `POST /score/axis-alignment/simulate` (Этап 7 §7.3): гипотетическая правка веса
    поверх текущей рубрики — превью «как изменится топ-20». Ничего не применяет/не сохраняет."""

    overrides: dict[str, int] = Field(min_length=1, max_length=6)


class SkipReasonItem(BaseModel):
    """Один чип причины пропуска (LLM-сгенерированный под вакансию)."""

    text: str
    canonical: str


class SkipReasonsPoll(BaseModel):
    """Ответ полла LLM-причин пропуска (`GET /vacancies/{vacancy_id}/skip-reasons`).

    Пустой `reasons` — LLM ещё не сгенерировал (или недоступен); UI падает на
    статичные канонические чипы из `SELF_SKIP_REASONS`. `task_running` — фон ещё
    работает, стоит поллить.
    """

    vacancy_id: str | None = None
    reasons: list[SkipReasonItem] = Field(default_factory=list)
    task_running: bool = False


class VacancyAskRequest(BaseModel):
    """Вопрос по конкретной вакансии: текст вакансии + оценка + история диалога."""

    question: str = Field(min_length=1, max_length=2000)
    history: list[AskMessage] = Field(default_factory=list, max_length=20)
    vacancy_text: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    score: ScoreResult | None = None


class VacancyAskResponse(BaseModel):
    vacancy_id: str
    answer: str
    context_source: Literal["db", "request"] = "request"


class JobStageUpdate(BaseModel):
    """Смена стадии воронки по числовому job.id (kanban-доска веба).

    `stage` — каноническое значение FunnelStatus («Просмотр», «Отклик»…).
    """

    stage: str = Field(min_length=1)


class JobStageResponse(BaseModel):
    id: int
    vacancy_id: str | None = None
    status: str


class JobDeleteResponse(BaseModel):
    """Результат `DELETE /api/jobs/{id}` — удаление вакансии целиком (кривая карточка)."""

    id: int
    vacancy_id: str | None = None
    deleted: bool = True


class JobSkipUpdate(BaseModel):
    """Пометить вакансию «Пропущено» с доски веба (решение «не подавать»).

    `reason` — короткая причина (по умолчанию нейтральная: с доски причину не выбирают, можно
    уточнить в дровере). Пропуск ОРТОГОНАЛЕН статусу воронки — не меняет `jobs.status`.
    """

    reason: str = Field(default="Пропущено вручную", min_length=1, max_length=500)


class JobSkipResponse(BaseModel):
    id: int
    vacancy_id: str | None = None
    skipped: bool = False


# Ручной выбор формата в шапке чата, когда площадка/LLM не смогли его определить —
# те же 4 значения, что фронт различает в чипе (funnel.ts:workFormatChip). Свободный текст сюда
# не пускаем: это Select, а не поле ввода, значение либо из этого канона, либо не меняется (None).
WorkFormatManual = Literal["Офис", "Гибрид", "Удалённо", "Валютная удалёнка"]


class JobApplyFieldsUpdate(BaseModel):
    """Редактируемые поля карточки вакансии в вебе: заметка, дата отклика, письмо.

    Все поля опциональны (PATCH-семантика): None = «не менять». Для заметки пустая строка
    очищает её. `applied_at` — дата отклика «YYYY-MM-DD» (не дата публикации вакансии).
    `cover_letter_text` — ручная правка сопроводительного (генерация — отдельная ручка).
    `letter_required` — сигнал «площадка требует письмо» (писатель: расширение); веб не выводит
    его из факта сохранения текста. `work_format` — ручной выбор, когда площадка
    формат не отдала и LLM не смог его определить по тексту.
    """

    note: str | None = Field(default=None, max_length=10000)
    applied_at: str | None = Field(default=None, max_length=32)
    letter_required: bool | None = None
    cover_letter_text: str | None = Field(default=None, max_length=10000)
    work_format: WorkFormatManual | None = None


class JobApplyFieldsResponse(BaseModel):
    id: int
    vacancy_id: str | None = None
    note: str | None = None
    applied_at: str | None = None
    letter_required: bool | None = None
    cover_letter_text: str | None = None
    work_format: str | None = None


class JobTrackUpdate(BaseModel):
    """Ручная поправка трека карточки (`PATCH /api/jobs/{id}/track`)."""

    track: Literal["primary", "second_job"]


class JobTrackResponse(BaseModel):
    id: int
    vacancy_id: str | None = None
    track: str
    track_override: bool = True
    overall_score: int | None = None
    recommendation: str | None = None


class ScoreThesesUpdate(BaseModel):
    """Ручная правка тезисов скора (расширение, Решение 3 — drag-and-drop между Плюсы/Минусы/
    Красные флаги + удаление). Всегда все три списка целиком (не diff) — проще и надёжнее, чем
    патчить отдельные индексы при гонках между вкладками. `pros`/`cons` не могут опустеть — тот
    же инвариант, что у `ScoreResult` (иначе `job_to_score_response` падает на model_validate);
    `red_flags` могут — по умолчанию их может не быть вовсе.
    """

    pros: list[str] = Field(min_length=1)
    cons: list[str] = Field(min_length=1)
    red_flags: list[str] = Field(default_factory=list)


class CoverLetterRequest(BaseModel):
    """Тело `POST /api/jobs/{id}/cover-letter` (Э4.4) — переключалка RU/EN в дровере/расширении.

    `lang=None` (или тело не прислано вовсе) — язык выводится из текста резюме.
    """

    lang: Literal["ru", "en"] | None = None


class CoverLetterResponse(BaseModel):
    """Сгенерированное сопроводительное: текст уже записан в `jobs.cover_letter_text`."""

    id: int
    vacancy_id: str | None = None
    cover_letter_text: str
    lang: Literal["ru", "en"] = "ru"


class VacancySeenResponse(BaseModel):
    vacancy_id: str
    seen: bool = False
    source: str | None = None


class VacancyTextFormatResponse(BaseModel):
    """Текст вакансии с абзацами и **выделениями** (дешёвая extract-модель, результат кэшируется
    бэкендом по тексту — L-17). Пустая строка — LLM недоступен/нет текста, фронт показывает сырой."""

    vacancy_id: str
    formatted: str = ""


# --- Провенанс пересчёта скоринга по HR-фактам ---


class ScoreRevisionOut(BaseModel):
    """Одна ревизия скоринга: JD-первичная (jd_only) или подтверждённая HR (hr_confirmed).

    `delta` — сдвиг overall_score относительно прошлого; `facts` — извлечённые HR-факты, на которых
    стоит пересчёт; `rationale` — короткое обоснование (что учли и куда сдвинуло)."""

    vacancy_id: str
    basis: Literal["jd_only", "hr_confirmed"]
    trigger: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)
    overall_score: int = 0
    recommendation: str = ""
    delta: int = 0
    rationale: str = ""
    id: int | None = None
    created_at: datetime | None = None


class ScoreRevisionHistory(BaseModel):
    """История ревизий скоринга по вакансии (накопление): свежие первыми. Нет PG → пусто."""

    vacancy_id: str
    score_basis: str = "jd_only"
    items: list[ScoreRevisionOut] = Field(default_factory=list)


class VacancyActivityEvent(BaseModel):
    """Одно действие по вакансии для ленты дровера: короткая подпись, без rationale."""

    id: str
    kind: str
    at: datetime
    label: str
    source: str = ""


class VacancyActivityHistory(BaseModel):
    """Лента действий по вакансии (свежие сверху). Нет PG → пусто."""

    vacancy_id: str
    items: list[VacancyActivityEvent] = Field(default_factory=list)

    @classmethod
    def from_items(cls, vacancy_id: str, items: Sequence[object]) -> VacancyActivityHistory:
        """Доменный `ActivityItem` — другой класс с теми же полями.

        `model_validate(item)` без `from_attributes` в Pydantic 2 отвергает инстанс
        (`Input should be a valid dictionary or instance of VacancyActivityEvent`) —
        пустая лента проходит, непустая даёт 500 на дровере.
        """
        return cls(
            vacancy_id=vacancy_id,
            items=[VacancyActivityEvent.model_validate(it, from_attributes=True) for it in items],
        )


# --- Пропущенные вакансии (кнопка «Пропустить» в расширении; S7) ---


class SkipVacancyRequest(BaseModel):
    """Ручная фиксация пропуска — решение «не подавать»."""

    vacancy_id: str = Field(min_length=1)
    skip_reason: str = Field(min_length=1, max_length=500)
    url: str | None = None
    title: str | None = None
    company: str | None = None
    overall_score: int | None = Field(default=None, ge=0, le=100)
    recommendation: Literal["strong_apply", "apply", "maybe", "skip"] | None = None


class SkipDeleteResponse(BaseModel):
    """Результат снятия пропуска (DELETE /skip/{id}): была ли запись и текущее состояние."""

    vacancy_id: str
    skipped: bool = False
    removed: bool = False


# --- Компании: полный реестр ---


class CompanyRegistryItem(BaseModel):
    """Одна компания реестра: агрегаты вакансий + вердикт из резюме."""

    company: str
    vacancy_count: int
    avg_score: float
    best_stage: str | None = None
    last_seen_at: datetime | None = None
    verdict: Literal["target", "avoid", "neutral"] = "neutral"


class CompanyRegistryResponse(BaseModel):
    """Реестр компаний для доски на «Рынке» (включая уже размеченные)."""

    items: list[CompanyRegistryItem] = Field(default_factory=list)


__all__ = [
    "Job",
    "JobLink",
    "JobsPage",
    "ScoreRequest",
    "ScoreResponse",
    "SalaryEstimatePoll",
    "SkipReasonItem",
    "SkipReasonsPoll",
    "VacancyAskRequest",
    "VacancyAskResponse",
    "JobStageUpdate",
    "JobStageResponse",
    "JobDeleteResponse",
    "JobSkipUpdate",
    "JobSkipResponse",
    "JobApplyFieldsUpdate",
    "JobApplyFieldsResponse",
    "JobTrackUpdate",
    "JobTrackResponse",
    "ScoreThesesUpdate",
    "CoverLetterResponse",
    "VacancySeenResponse",
    "ScoreRevisionOut",
    "ScoreRevisionHistory",
    "VacancyActivityEvent",
    "VacancyActivityHistory",
    "SkipVacancyRequest",
    "SkipDeleteResponse",
    "CompanyRegistryItem",
    "CompanyRegistryResponse",
]
