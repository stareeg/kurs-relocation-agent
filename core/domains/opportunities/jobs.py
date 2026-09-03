"""Repository вакансий и стадий воронки (задача 1.1).

`Job` — DB-проекция VacancyRecord: score хранится как jsonb-словарь (полный ScoreResult),
не как типизированная модель — ScoreResult переедет в core только в 1.5, и
тянуть legacy backend в core нельзя (обратная зависимость). Скорер в 1.5 строит Job из
ScoreResult сам.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.domains.opportunities.companies.normalize import normalize_company_deterministic
from core.domains.opportunities.dedup import tokens_array
from core.domains.opportunities.events import publish_application_stage_changed
from core.kernel.schemas.funnel import ENGAGED_FUNNEL_STATUSES, FunnelStatus, funnel_stage_number
from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

# Калибровка рынка / балла резюме / ATS-контекста: без вакансий, которые владелец явно отклонил.
# account_id в подзапросе обязателен (Этап 3, план §1): без него skip одного аккаунта на
# vacancy_id гасил бы точно такую же вакансию у другого аккаунта (jobs больше не unique по
# одному vacancy_id, см. 0097_pipeline_account_id.sql).
SQL_JOB_NOT_SKIPPED = (
    "not exists (select 1 from skipped_vacancies sv "
    "where sv.account_id = jobs.account_id and sv.vacancy_id = jobs.vacancy_id)"
)


def company_canonical_for(company: str | None) -> str | None:
    """Детерминированный канон для `jobs.company_canonical` (NULL, если имени нет)."""
    canon = normalize_company_deterministic(company)
    return canon or None


def canonical_exclude_set(names: Iterable[str | None]) -> list[str]:
    """Каноны для исключения из кандидатов (лайк/дизлайк). Стабильный sorted-порядок."""
    out: set[str] = set()
    for name in names:
        canon = company_canonical_for(name)
        if canon:
            out.add(canon)
            continue
        stripped = (name or "").strip()
        if stripped:
            out.add(stripped)
    return sorted(out)


class CompanyRow(BaseModel):
    """Агрегат по `jobs.company_canonical` для реестра компаний на «Рынке»."""

    company: str
    vacancy_count: int
    avg_score: float
    best_stage: str | None = None
    last_seen_at: datetime | None = None


# Восходящие ступени воронки — зеркало `pipeline.analytics.FUNNEL_ORDER` без импорта pipeline.
_ASCENDING_FUNNEL: tuple[str, ...] = (
    FunnelStatus.VIEWED,
    FunnelStatus.APPLIED,
    FunnelStatus.SCREENING,
    FunnelStatus.TECH,
    FunnelStatus.FINAL,
    FunnelStatus.OFFER,
)


def furthest_stage_label(statuses: list[str | None]) -> str:
    """Самая дальняя восходящая ступень → каноническое имя статуса.

    Любая запись в `jobs` = минимум «Просмотр». «Отказ»/«Архив» шкалу не двигают.
    """
    nums = [1]
    for s in statuses:
        n = funnel_stage_number(s)
        if isinstance(n, int) and n > 0:
            nums.append(n)
    return _ASCENDING_FUNNEL[max(nums) - 1]


# --- Источник вакансии (`jobs.source`) -------------------------------------------------
# Колонка — обычный text без CHECK (миграция 0001), поэтому это не enum на уровне схемы, а
# справочник конвенции: явный список каноничных значений в одном месте, чтобы новый источник
# (например, будущий getmatch) не плодил опечатки ("getmatch" vs "get_match" vs "Getmatch")
# вразнобой по коду. Импортировать константы, а не хардкодить строку заново.
SOURCE_VACANCY_PAGE = "vacancy_page"  # клик "Оценить" на странице вакансии hh.ru (расширение)
SOURCE_HH_NEGOTIATIONS = "hh_negotiations"  # синк /applicant/negotiations (расширение)
SOURCE_HH_APPLY_STUB = "hh_apply_stub"  # клик "Откликнуться" на hh без предварительного /score
SOURCE_HR_THREAD_STUB = "hr_thread_stub"  # HR написал первым по vacancy_id, вакансия ещё не скорена
SOURCE_SKIP_STUB = "skip_stub"  # POST /skip (расширение) без предварительного /score
SOURCE_TELEGRAM_CHANNEL = "telegram_channel"  # пересланный пост вакансийного TG-канала
SOURCE_SEARCH_BATCH = "search_batch"  # автономный поиск hh, embedded JSON (core.parsing.hh_search)
SOURCE_SEARCH_BATCH_FALLBACK = "search_batch_fallback"  # discovery, regex-фолбэк без embedded JSON
SOURCE_SCORE_CLI = "score_cli"  # исторический: бывший core.scoring.cli (модуль снесён)
SOURCE_GETMATCH = "getmatch"  # GM-2..GM-5: вакансия с getmatch.ru (Telegram-бот и/или сайт)
SOURCE_HABR = "habr"  # habr: вакансия с career.habr.com (расширение)
SOURCE_MANUAL = "manual"  # ручное создание/тесты; в БД автоматически не проставляется

# Полный список - для валидации на границах (например, фильтр по источнику).
# Не enforce'ится на самом Job.source (str | None) - исторические строки/NULL должны читаться
# как есть.
ALL_JOB_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_VACANCY_PAGE,
        SOURCE_HH_NEGOTIATIONS,
        SOURCE_HH_APPLY_STUB,
        SOURCE_HR_THREAD_STUB,
        SOURCE_SKIP_STUB,
        SOURCE_TELEGRAM_CHANNEL,
        SOURCE_SEARCH_BATCH,
        SOURCE_SEARCH_BATCH_FALLBACK,
        SOURCE_SCORE_CLI,
        SOURCE_GETMATCH,
        SOURCE_HABR,
        SOURCE_MANUAL,
    }
)

# UI-группы источника: одна колонка «Источник» = hh | getmatch | tg.
SOURCE_GROUP_HH = "hh"
SOURCE_GROUP_GETMATCH = "getmatch"
SOURCE_GROUP_HABR = "habr"
SOURCE_GROUP_TELEGRAM = "tg"

# Канонический порядок групп для UI (фильтр, иконки, легенда). Детерминированный — чтобы
# дифф schema.d.ts и снэпшоты в тестах были стабильными (7.4 / D2 / D3).
SOURCE_GROUPS_ORDER: tuple[str, ...] = (
    SOURCE_GROUP_HH,
    SOURCE_GROUP_GETMATCH,
    SOURCE_GROUP_HABR,
    SOURCE_GROUP_TELEGRAM,
)

_HH_JOB_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_VACANCY_PAGE,
        SOURCE_HH_NEGOTIATIONS,
        SOURCE_HH_APPLY_STUB,
        SOURCE_HR_THREAD_STUB,
        SOURCE_SEARCH_BATCH,
        SOURCE_SEARCH_BATCH_FALLBACK,
        SOURCE_SCORE_CLI,
        SOURCE_MANUAL,
    }
)


def resolve_job_source_group(
    source: str | None = None,
    vacancy_id: str | None = None,
) -> str:
    """Канон jobs.source → группа для UI и веб."""
    s = (source or "").strip()
    if s == SOURCE_GETMATCH:
        return SOURCE_GROUP_GETMATCH
    if s == SOURCE_HABR:
        return SOURCE_GROUP_HABR
    if s == SOURCE_TELEGRAM_CHANNEL:
        return SOURCE_GROUP_TELEGRAM
    if s in _HH_JOB_SOURCES:
        return SOURCE_GROUP_HH
    vid = (vacancy_id or "").strip()
    if vid.startswith("gm_"):
        return SOURCE_GROUP_GETMATCH
    if vid.startswith("habr_"):
        return SOURCE_GROUP_HABR
    if vid.startswith("tg_"):
        return SOURCE_GROUP_TELEGRAM
    if vid.isdigit():
        return SOURCE_GROUP_HH
    return SOURCE_GROUP_HH


# Минимальная длина текста JD, при которой вакансию считаем «с текстом» (тот же порог, что
# подготовка/письмо). Синк откликов и stub'ы часто пишут пустой `vacancy_text` — без скора
# такие карточки висят мусором, пока пользователь не откроет страницу вакансии.
MIN_VACANCY_TEXT_LEN = 50
# TTL пустого stub'а без скора: пользователь успевает открыть страницу / вставить текст
# (HR иногда скидывает JD чуть позже), дальше — автоудаление.
EMPTY_UNSCORED_TTL_HOURS = 6

# GM-9: извлечение numeric_id getmatch из текста/ссылки. Используется в боте
# (`bot_app/handlers/forwarded.py`), поэтому живёт в каноне источников, а не в хендлере бота.
# Исторические фолбэк-ключи уже приведены к канону `gm_{numeric_id}`.
_GETMATCH_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:getmatch\.ru/vacancies/(\d+)|gm\.to/(\d+))",
    re.IGNORECASE,
)


def job_needs_vacancy_text(
    *,
    vacancy_text: str | None = None,
    overall_score: int | None = None,
) -> bool:
    """True — нет скора и текст JD слишком короткий/пустой (нужно открыть страницу или вставить)."""
    if overall_score is not None:
        return False
    return len((vacancy_text or "").strip()) < MIN_VACANCY_TEXT_LEN


def job_record_needs_vacancy_text(job: Job) -> bool:
    return job_needs_vacancy_text(vacancy_text=job.vacancy_text, overall_score=job.overall_score)


async def backfill_vacancy_identity(
    job_id: int,
    *,
    vacancy_text: str,
    title: str | None = None,
    company: str | None = None,
    account_id: int,
    db: Executor | None = None,
) -> None:
    """Дозаполнить текст JD (+title/company) у уже существующей записи без скора.

    Источник бага: `set_funnel_status` заводит stub, только если вакансии ещё нет в `jobs`
    (клик «Откликнуться» без /score); если stub УЖЕ существует (skip_stub / синк hh_negotiations
    /getmatch без текста), тот же клик раньше молча отбрасывал реальный текст со страницы —
    расширение его парсило, но бэк никуда не писал. Владелец открывал настоящую вакансию с
    текстом, откликался, а в «Отклики» карточка так и оставалась пустой. Здесь — тот случай:
    вызывающая сторона (`set_funnel_status`) должна дозвать это, когда `job_record_needs_vacancy_text`
    и `vacancy_text` пришёл непустой.
    """
    db = db or get_pool()
    await db.execute(
        "update jobs set vacancy_text = $2, "
        "title = coalesce(nullif($3, ''), title), company = coalesce(nullif($4, ''), company), "
        "updated_at = now() "
        "where id = $1 and account_id = $5",
        job_id,
        vacancy_text,
        title or "",
        company or "",
        account_id,
    )


def extract_getmatch_numeric_id_from_text(text: str | None) -> str | None:
    """Вернуть numeric_id getmatch-вакансии из её ссылки в тексте, или None.

    getmatch-бот шлёт ссылку вида `https://getmatch.ru/vacancies/{id}-{slug}` (полная)
    или короткую `https://gm.to/{id}`. Возвращаем чистый numeric (без префикса `gm_`),
    либо None — тогда вызывающий код использует фолбэк (digest/origin-ключ).
    """
    if not text:
        return None
    for match in _GETMATCH_URL_RE.finditer(text):
        numeric = match.group(1) or match.group(2)
        if numeric:
            return numeric
    return None


def job_source_group_label(job: Job) -> str:
    """Метка источника для UI по Job."""
    return resolve_job_source_group(job.source, job.vacancy_id)


class Job(BaseModel):
    id: int | None = None
    vacancy_id: str | None = None
    url: str | None = None
    title: str | None = None
    company: str | None = None
    # FR2-40: канон из normalize_company_deterministic(company); пишется в save_job.
    company_canonical: str | None = None
    vacancy_text: str
    salary_text: str | None = None
    area: str | None = None
    work_format: str | None = None
    work_schedule: str | None = None
    total_responses: int | None = None
    letter_required: bool | None = None
    published_at: str | None = None
    cover_letter_text: str | None = None
    # Язык последнего сгенерированного письма (Э4.4) — денормализация, чтобы переключалка
    # RU/EN в дровере/расширении при открытии отражала фактически сгенерированное, а не
    # гадала заново. None — письма ещё не было.
    cover_letter_lang: str | None = None
    employer_id: str | None = None
    # Структурированные поля вакансии (getmatch RSC initialVacancy): навыки/специализация/грейд.
    # Пустой список = не указано (колонка text[] NOT NULL DEFAULT '{}').
    skills: list[str] = Field(default_factory=list)
    specialization: str | None = None
    seniority: str | None = None
    # Откуда вакансия попала в систему — каноничные значения см. ALL_JOB_SOURCES выше. Свободный
    # str (не Literal) намеренно: колонка без CHECK, исторические/NULL значения должны читаться.
    source: str | None = None
    is_archived: bool = False
    status: str | None = None
    overall_score: int | None = None
    recommendation: str | None = None
    # На чём стоит текущий скор: jd_only (по тексту вакансии) | hr_confirmed (пересчитан по
    # подтверждённым рекрутером фактам, JS-8.1). История пересчётов — в score_revisions.
    score_basis: str = "jd_only"
    # Версия рубрики, которой посчитан текущий score_breakdown (Этап 5 §5.1) — денормализация
    # score->>'weights_version' (core/domains/opportunities/weights_version.py) для дешёвого
    # сравнения без разбора jsonb. None — старая запись до введения версии.
    score_weights_version: str | None = None
    work_city: str | None = None
    note: str | None = None
    applied_at: str | None = None
    # Сигнал «HR открыл резюме», из hh.ru/applicant/negotiations. Ортогонален status —
    # просмотр резюме != скрининг, стадию не двигает. None = ещё не просмотрено (или неизвестно).
    hr_viewed_at: datetime | None = None
    # Флаг «пропущено» (решение «не подавать») — ОРТОГОНАЛЕН status: живёт в skipped_vacancies,
    # не в jobs. Проставляется только в выборках, которые джойнят пропуски (list_jobs); в остальных
    # местах остаётся False. Колонки в таблице jobs под него НЕТ — save_job его не пишет.
    skipped: bool = False
    # Есть переписка с HR (hr_threads + hr_messages) — для UI: диалог в личке ≈ «Отклик».
    has_hr_dialog: bool = False
    # Источник последней стадии «Отклик» (application_stages.source) — коррелированный подзапрос,
    # как has_hr_dialog. Префикс "auto_apply_" → бейдж «Автоотклик» на доске (Фаза 7.1,
    # plans/auto_apply_roadmap_2026_08_17.md). None — стадии «Отклик» ещё не было, либо выборка
    # не джойнит application_stages (только list_jobs/list_jobs_page).
    applied_source: str | None = None
    # Факт оффера по этой вакансии (коррелированный подзапрос к offers, как has_hr_dialog).
    # None — оффера нет. Точные условия оффера главнее рыночной оценки/HH-текста для UI.
    offer_status: str | None = None
    offer_base_salary: int | None = None
    offer_base_salary_currency: str | None = None
    offer_base_salary_period: str | None = None
    offer_work_format: str | None = None
    offer_bonus_monthly_equiv: int | None = None
    # Дата/статус HR-скрининга этой вакансии (коррелированный подзапрос к interview_stages,
    # как has_hr_dialog выше) — витрина рельса «Скрининги»: сортировка/подпись карточки по
    # ближайшему звонку вместо повторяющегося «Скрининг» на каждой карточке. None — этап ещё не
    # заведён (нет распознанной даты/парсинга HR-переписки).
    hr_screening_at: datetime | None = None
    hr_screening_status: str | None = None
    score: dict[str, Any] = Field(default_factory=dict)
    salary: dict[str, Any] | None = None
    # Под-скор «реальность полной удалёнки» (feature_ideas 2.2): RemoteFeasibility как jsonb.
    # None - под-скор не считался или упал (best-effort, не валит скоринг).
    remote_feasibility: dict[str, Any] | None = None
    # Под-скор «шанс на отклик» (Этап 6 §6.2): CompetitionInsight как jsonb. НЕ входит в
    # overall_score — level="unknown" почти всегда, пока total_responses не собирается (§6.1).
    competition: dict[str, Any] | None = None
    # Условия работы (Э2.1) — денормализация vacancy_work_terms, чтобы доска не джойнила кэш.
    work_terms: dict[str, Any] | None = None
    # Трек карточки (Э2.2). None — ещё не классифицировали (легаси). track_override — ручная
    # поправка владельца, рескор не перетирает (контракт is_salary_locked).
    track: str | None = None
    track_override: bool = False
    # Анкета работодателя при отклике (Фаза 3, auto_apply_roadmap_2026_08_17.md): AnketaState
    # как jsonb — {status, platform, questions, answers, requested_at, resolved_at}. None —
    # вакансия никогда не встречала анкету. Только hh.ru (единственная площадка с этой
    # механикой).
    anketa: dict[str, Any] | None = None
    scored_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Площадочные ссылки этой логической вакансии (дедупликация S12). Не колонка `jobs` —
    # заполняется из `job_links` точечно (`list_job_links`), чтобы не тянуть join в каждый
    # SELECT доски. Пусто там, где ссылки не запрашивались.
    links: list[JobLink] = Field(default_factory=list)


class ApplicationStage(BaseModel):
    id: int | None = None
    job_id: int
    stage: str
    source: str = "manual"
    changed_at: datetime | None = None


class JobLink(BaseModel):
    """Одна площадочная ссылка логической вакансии (`job_links`)."""

    id: int | None = None
    account_id: int = 0
    job_id: int
    source: str
    vacancy_id: str | None = None
    url: str | None = None
    is_primary: bool = False
    created_at: datetime | None = None


_JOB_COLUMNS = (
    "id, vacancy_id, url, title, company, company_canonical, vacancy_text, salary_text, area, "
    "work_format, work_schedule, total_responses, letter_required, published_at, "
    "cover_letter_text, cover_letter_lang, employer_id, source, is_archived, status, overall_score, "
    "recommendation, score_basis, score_weights_version, work_city, note, applied_at, "
    "hr_viewed_at, score, salary, "
    "remote_feasibility, competition, work_terms, track, track_override, anketa, skills, "
    "specialization, seniority, scored_at, created_at, updated_at"
)
# Та же колонка-лента, но с префиксом таблицы: нужна только там, где jobs не единственная
# таблица в FROM (list_jobs джойнит offers) — иначе status/work_format/created_at/updated_at
# ловят "column reference is ambiguous" (совпадают с колонками offers).
_JOB_COLUMNS_QUALIFIED = ", ".join(f"jobs.{c.strip()}" for c in _JOB_COLUMNS.split(","))

# HR-скрининг вакансии — коррелированный подзапрос к interview_stages (та же таблица, что
# core.domains.preparation.interview_stages), а не JOIN: у вакансии бывает больше одной строки
# hr_screening (до чистки _collapse_duplicate_hr_screenings), обычный join размножил бы строки
# доски. Порядок ранжирования статуса копирует _HR_STATUS_RANK/_prefer_hr_screening оттуда же —
# чтобы рельс «Скрининги» показывал тот же этап, что и степпер цепочки в Техничках.
_HR_SCREENING_RANK_CASE = (
    "case ist.status "
    "when 'completed' then 0 when 'failed' then 1 "
    "when 'scheduled' then 2 when 'rescheduled' then 2 else 3 end"
)
_HR_SCREENING_AT_SUBQUERY = (
    "(select ist.scheduled_at from interview_stages ist "
    "where ist.account_id = jobs.account_id and ist.vacancy_id = jobs.vacancy_id "
    "and ist.stage_type = 'hr_screening' "
    f"order by {_HR_SCREENING_RANK_CASE}, ist.position asc, ist.id asc limit 1)"
)
_HR_SCREENING_STATUS_SUBQUERY = (
    "(select ist.status from interview_stages ist "
    "where ist.account_id = jobs.account_id and ist.vacancy_id = jobs.vacancy_id "
    "and ist.stage_type = 'hr_screening' "
    f"order by {_HR_SCREENING_RANK_CASE}, ist.position asc, ist.id asc limit 1)"
)

# Источник последней стадии «Отклик» — коррелированный подзапрос (как _HR_SCREENING_AT_SUBQUERY),
# не JOIN: application_stages копит всю историю, у вакансии может быть несколько записей «Отклик»
# (пересинк площадки), нужна только последняя. Питает Job.applied_source (Фаза 7.1 — бейдж
# «Автоотклик» на доске, is_auto_apply_source ниже).
_APPLIED_SOURCE_SUBQUERY = (
    "(select ast.source from application_stages ast "
    "where ast.account_id = jobs.account_id and ast.job_id = jobs.id "
    f"and ast.stage = '{FunnelStatus.APPLIED.value}' "
    "order by ast.changed_at desc nulls last, ast.id desc limit 1)"
)

# Kanban: активные этапы воронки (отклик и дальше) должны попадать в limit даже без overall_score
# (getmatch-синк откликов создаёт stub без скоринга). Иначе nulls last выталкивает их за cutoff.
_TERMINAL_FUNNEL_STATUSES: frozenset[str] = frozenset(
    {FunnelStatus.REJECTED.value, FunnelStatus.ARCHIVE.value}
)


def _list_jobs_order_clause() -> str:
    engaged = ", ".join(f"'{s}'" for s in sorted(ENGAGED_FUNNEL_STATUSES))
    terminal = ", ".join(f"'{s}'" for s in sorted(_TERMINAL_FUNNEL_STATUSES))
    return (
        f"case when jobs.status in ({engaged}) then 0 "
        f"when jobs.status in ({terminal}) then 2 else 1 end, "
        "coalesce(jobs.updated_at, jobs.scored_at) desc nulls last, "
        "jobs.overall_score desc nulls last, "
        # Финальный тайбрейкер: без него ties внутри одной страницы курсорной пагинации
        # не имеют детерминированного порядка — соседние страницы могли бы терять/дублировать
        # строки. На видимый порядок доски не влияет (только разруливает полные совпадения).
        "jobs.id desc"
    )


async def save_job(
    job: Job, *, account_id: int, db: Executor | None = None, preserve_status: bool = False
) -> Job:
    """Upsert по (account_id, vacancy_id) — HH id уникален только в рамках аккаунта (Этап 3),
    иначе обычный insert.

    score/salary денормализуем для быстрых выборок: overall_score/recommendation/work_city
    берём из score-словаря, если в Job не проставлены явно.

    `preserve_status=True` — при конфликте не трогать колонку `status` (оставить как в БД).
    Нужен персисту скоринга (`persist.py`): повторный `/score` той же вакансии не должен
    откатывать реальный прогресс воронки («Отклик»/«Скрининг»/…) обратно в «Просмотр» —
    расширение зовёт `/score` и «Отметить отклик» как параллельные запросы, и порядок их
    ответов не гарантирован.
    """
    db = db or get_pool()
    overall = job.overall_score if job.overall_score is not None else job.score.get("overall_score")
    recommendation = job.recommendation or job.score.get("recommendation")
    work_city = job.work_city or job.score.get("work_city")
    salary = job.salary if job.salary is not None else job.score.get("salary")
    weights_version = job.score_weights_version or job.score.get("weights_version") or None
    # Канон всегда из сырого company (не из job.company_canonical): повторный скоринг/инжест
    # подтягивает алиасы, если словарь нормализатора расширили.
    company_canonical = company_canonical_for(job.company)

    params = [
        account_id,
        job.vacancy_id,
        job.url,
        job.title,
        job.company,
        company_canonical,
        job.vacancy_text,
        job.salary_text,
        job.area,
        job.work_format,
        job.work_schedule,
        job.total_responses,
        job.letter_required,
        job.published_at,
        job.cover_letter_text,
        job.employer_id,
        job.source,
        job.is_archived,
        job.status,
        overall,
        recommendation,
        work_city,
        job.score,
        salary,
        job.remote_feasibility,
        job.competition,
        job.work_terms,
        job.track,
        bool(job.track_override),
        tokens_array(job.vacancy_text),
        job.skills or [],
        job.specialization,
        job.seniority,
        weights_version,
    ]
    insert_cols = (
        "account_id, vacancy_id, url, title, company, company_canonical, vacancy_text, "
        "salary_text, area, work_format, work_schedule, total_responses, letter_required, "
        "published_at, cover_letter_text, employer_id, source, is_archived, status, "
        "overall_score, recommendation, work_city, score, salary, remote_feasibility, "
        "competition, work_terms, track, track_override, text_tokens, "
        "skills, specialization, seniority, score_weights_version"
    )
    placeholders = ", ".join(f"${i}" for i in range(1, len(params) + 1))

    if job.vacancy_id:
        # upsert: повторный скоринг той же вакансии обновляет запись (идемпотентность 1.3).
        update_cols = [
            c
            for c in insert_cols.split(", ")
            if c not in ("account_id", "vacancy_id", "track_override")
        ]
        if preserve_status:
            update_cols = [c for c in update_cols if c != "status"]
        update_set_parts = []
        for c in update_cols:
            if c == "track":
                update_set_parts.append(
                    "track = case when jobs.track_override then jobs.track else excluded.track end"
                )
            else:
                update_set_parts.append(f"{c} = excluded.{c}")
        update_set = ", ".join(update_set_parts)
        sql = (
            f"insert into jobs ({insert_cols}) values ({placeholders}) "
            f"on conflict (account_id, vacancy_id) do update set {update_set}, "
            f"scored_at = now(), updated_at = now() "
            f"returning {_JOB_COLUMNS}"
        )
    else:
        sql = f"insert into jobs ({insert_cols}) values ({placeholders}) returning {_JOB_COLUMNS}"

    row = await db.fetchrow(sql, *params)
    assert row is not None  # insert ... returning всегда отдаёт строку
    return Job(**row_to_dict(row))


async def update_job_score(
    vacancy_id: str,
    *,
    overall_score: int,
    recommendation: str,
    score_json: dict[str, Any],
    salary_json: dict[str, Any] | None = None,
    work_city: str | None = None,
    weights_version: str | None = None,
    basis: str = "hr_confirmed",
    work_terms: dict[str, Any] | None = None,
    track: str | None = None,
    account_id: int,
    db: Executor | None = None,
) -> Job | None:
    """Перезаписать скор вакансии по (account_id, vacancy_id) (пересчёт по HR-фактам / рубрике).

    Обновляет overall_score/recommendation/score(jsonb)/salary(jsonb)/work_city/score_basis +
    scored_at/updated_at. **НЕ трогает status/skip** — funnel-решения остаются за владельцем
    (совет модели ≠ выбор пользователя). None — вакансии с таким vacancy_id нет.

    `weights_version` — денормализация `score_json["weights_version"]` в колонку (Этап 5 §5.1);
    `None` не трогает сохранённое значение (coalesce), поэтому старые вызывающие, которые ещё не
    прокидывают версию явно, не затирают её на NULL.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "update jobs set overall_score = $2, recommendation = $3, score = $4, "
        "salary = coalesce($5, salary), work_city = coalesce($6, work_city), "
        "score_weights_version = coalesce($7, score_weights_version), "
        "score_basis = $8, "
        "work_terms = coalesce($10, work_terms), "
        "track = case when track_override then track else coalesce($11, track) end, "
        "scored_at = now(), updated_at = now() "
        "where vacancy_id = $1 and account_id = $9 "
        f"returning {_JOB_COLUMNS}",
        vacancy_id,
        overall_score,
        recommendation,
        score_json,
        salary_json,
        work_city,
        weights_version,
        basis,
        account_id,
        work_terms,
        track,
    )
    return Job(**row_to_dict(row)) if row else None


async def delete_job(job_id: int, *, account_id: int, db: Executor | None = None) -> bool:
    """Удалить вакансию целиком (кривая/мусорная карточка на доске).

    account_id в WHERE — нельзя удалить чужую вакансию по id. Каскад: application_stages
    (ON DELETE CASCADE, 0001_init.sql). Таблицы по vacancy_id без FK (offers, skipped_vacancies,
    hr_threads, ...) не трогаем — осиротевшие строки по vacancy_id уже существующий паттерн
    (см. docstring purge_empty_unscored_jobs).
    """
    db = db or get_pool()
    result = await db.execute(
        "delete from jobs where id = $1 and account_id = $2", job_id, account_id
    )
    try:
        return int(str(result).split()[-1]) > 0
    except (ValueError, IndexError):
        return False


async def get_job(job_id: int, *, account_id: int, db: Executor | None = None) -> Job | None:
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_JOB_COLUMNS} from jobs where id = $1 and account_id = $2", job_id, account_id
    )
    return Job(**row_to_dict(row)) if row else None


async def get_job_by_vacancy_id(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> Job | None:
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_JOB_COLUMNS} from jobs where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    return Job(**row_to_dict(row)) if row else None


async def list_seen_work_cities(*, account_id: int, db: Executor | None = None) -> list[str]:
    """Города из `jobs.work_city` — слой подсказок «из своих данных».

    Пустой агрегат (нет ни одной оценённой вакансии) — `[]`, не ошибка. Частота, затем имя.
    """
    db = db or get_pool()
    rows = await db.fetch(
        "select btrim(work_city) as city, count(*)::int as n "
        "from jobs "
        "where account_id = $1 and work_city is not null and btrim(work_city) <> '' "
        "group by btrim(work_city) "
        "order by n desc, city "
        "limit 50",
        account_id,
    )
    return [str(r["city"]) for r in rows]


async def find_duplicate_candidates(
    tokens: list[str],
    *,
    account_id: int,
    limit: int = 20,
    db: Executor | None = None,
) -> list[Job]:
    """Топ-N кандидатов дедупликации по пересечению токенов (GIN на `jobs.text_tokens`).

    Возвращает только строки с ненулевым пересечением токенов, отсортированные по убыванию
    пересечения. Точное сравнение (Jaccard > порога) вызывающий делает в Python через
    `dedup.find_duplicate` — здесь только префильтр, чтобы не гонять O(n) по всем jobs аккаунта.
    """
    db = db or get_pool()
    if not tokens:
        return []
    rows = await db.fetch(
        f"select {_JOB_COLUMNS} from jobs "
        "where account_id = $1 and text_tokens is not null and text_tokens && $2::text[] "
        "order by (select count(*) from unnest(text_tokens) t where t = any($2::text[])) desc "
        "limit $3",
        account_id,
        tokens,
        limit,
    )
    return [Job(**row_to_dict(r)) for r in rows]


async def add_job_link(
    job_id: int,
    *,
    source: str,
    vacancy_id: str | None,
    url: str | None,
    account_id: int,
    is_primary: bool = False,
    db: Executor | None = None,
) -> JobLink:
    """Добавить площадочную ссылку к логической вакансии. Идемпотентно по
    (account_id, source, vacancy_id): повторный инжест не плодит дубль, а дозаполняет url/
    поднимает is_primary (никогда не опускает его до false).
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into job_links (account_id, job_id, source, vacancy_id, url, is_primary) "
        "values ($1, $2, $3, $4, $5, $6) "
        "on conflict (account_id, source, vacancy_id) do update set "
        "url = coalesce(job_links.url, excluded.url), "
        "is_primary = job_links.is_primary or excluded.is_primary "
        "returning id, account_id, job_id, source, vacancy_id, url, is_primary, created_at",
        account_id,
        job_id,
        source,
        vacancy_id,
        url,
        is_primary,
    )
    assert row is not None
    return JobLink(**row_to_dict(row))


async def enrich_job(
    job_id: int,
    *,
    salary_text: str | None = None,
    title: str | None = None,
    company: str | None = None,
    work_format: str | None = None,
    published_at: str | None = None,
    url: str | None = None,
    vacancy_text: str | None = None,
    account_id: int,
    db: Executor | None = None,
) -> Job | None:
    """Дозаполнить каноническую вакансию только пустыми полями (COALESCE-семантика).

    Дедупликация приносит ту же вакансию с другой площадки, где части полей может не быть;
    пустое у канона заполняем принесённым, уже заполненное не трогаем. Статус воронки/скор не
    трогаем вовсе — обогащение не должно двигать решение пользователя. None — строки нет.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "update jobs set "
        "salary_text = coalesce(salary_text, $2), "
        "title = coalesce(title, $3), "
        "company = coalesce(company, $4), "
        "company_canonical = coalesce(company_canonical, $5), "
        "work_format = coalesce(work_format, $6), "
        "published_at = coalesce(published_at, $7), "
        "url = coalesce(url, $8), "
        "vacancy_text = coalesce(nullif(vacancy_text, ''), $9), "
        "updated_at = now() "
        "where id = $1 and account_id = $10 "
        f"returning {_JOB_COLUMNS}",
        job_id,
        salary_text,
        title,
        company,
        company_canonical_for(company),
        work_format,
        published_at,
        url,
        vacancy_text,
        account_id,
    )
    return Job(**row_to_dict(row)) if row else None


async def list_job_links(
    job_ids: list[int],
    *,
    account_id: int,
    db: Executor | None = None,
) -> dict[int, list[JobLink]]:
    """Карта job_id → ссылки площадок (`job_links`). Пустой ввод → пустая карта."""
    db = db or get_pool()
    if not job_ids:
        return {}
    rows = await db.fetch(
        "select id, account_id, job_id, source, vacancy_id, url, is_primary, created_at "
        "from job_links where account_id = $1 and job_id = any($2::bigint[]) "
        "order by is_primary desc, id asc",
        account_id,
        job_ids,
    )
    out: dict[int, list[JobLink]] = defaultdict(list)
    for r in rows:
        link = JobLink(**row_to_dict(r))
        out[link.job_id].append(link)
    return out


async def get_statuses_by_vacancy_ids(
    vacancy_ids: list[str], *, account_id: int, db: Executor | None = None
) -> dict[str, str | None]:
    """Карта vacancy_id → текущий статус воронки (`jobs.status`) для пачки vacancy_id."""
    ids = [v for v in vacancy_ids if v]
    if not ids:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        "select vacancy_id, status from jobs where vacancy_id = any($1) and account_id = $2",
        ids,
        account_id,
    )
    return {r["vacancy_id"]: r["status"] for r in rows}


async def get_jobs_by_vacancy_ids(
    vacancy_ids: list[str], *, account_id: int, db: Executor | None = None
) -> dict[str, Job]:
    """Карта vacancy_id → `Job` для пачки vacancy_id: один запрос вместо
    `get_job_by_vacancy_id` в цикле (см. `negotiations.sync_negotiations_batch`)."""
    ids = [v for v in vacancy_ids if v]
    if not ids:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_JOB_COLUMNS} from jobs where vacancy_id = any($1) and account_id = $2",
        ids,
        account_id,
    )
    return {r["vacancy_id"]: Job(**row_to_dict(r)) for r in rows}


async def list_jobs_applied_today_via(
    source: str, *, account_id: int, limit: int = 50, db: Executor | None = None
) -> list[Job]:
    """Вакансии, у которых СЕГОДНЯ зафиксирован переход в «Отклик» с данным
    `application_stages.source` — витрина «уже откликнулось сегодня» в очереди автооткликов
    (пункт 3 редизайна «Расширения», `pipeline.auto_apply.queue.preview_queue`): показывает,
    что уже ушло само, зелёной галочкой в конце списка «Автоотклик»."""
    db = db or get_pool()
    sql = (
        f"select {_JOB_COLUMNS_QUALIFIED}, {_APPLIED_SOURCE_SUBQUERY} as applied_source "
        f"from jobs "
        f"where jobs.account_id = $1 and exists ("
        f"  select 1 from application_stages ast "
        f"  where ast.account_id = jobs.account_id and ast.job_id = jobs.id "
        f"  and ast.source = $2 and ast.stage = $3 and ast.changed_at::date = current_date"
        f") "
        f"order by jobs.applied_at desc nulls last "
        f"limit $4"
    )
    rows = await db.fetch(sql, account_id, source, FunnelStatus.APPLIED.value, limit)
    return [Job(**row_to_dict(r)) for r in rows]


def company_match_tier(status: str | None, *, is_archived: bool = False) -> int:
    """Ярус приоритета матча по компании: меньше = лучше.

    0 - активная воронка (Отклик…Оффер); 1 - прочее нетерминальное (Просмотр и т.п.);
    2 - Отказ/Архив или is_archived.
    """
    if is_archived:
        return 2
    st = (status or "").strip()
    if st in ENGAGED_FUNNEL_STATUSES:
        return 0
    if st in _TERMINAL_FUNNEL_STATUSES:
        return 2
    return 1


def pick_company_match_candidates(jobs: list[Job]) -> list[Job]:
    """Лучший ярус воронки; при ≥2 в ярусе - все (дизамбигуация), не silent pick."""
    if not jobs:
        return []
    ordered = sorted(
        jobs,
        key=lambda j: (
            company_match_tier(j.status, is_archived=j.is_archived),
            # свежие раньше: инверсия timestamp через отсутствие → в хвост
            -(j.scored_at.timestamp() if j.scored_at else 0.0),
        ),
    )
    best = company_match_tier(ordered[0].status, is_archived=ordered[0].is_archived)
    return [j for j in ordered if company_match_tier(j.status, is_archived=j.is_archived) == best]


def _company_match_order_sql() -> str:
    engaged = ", ".join(f"'{s}'" for s in sorted(ENGAGED_FUNNEL_STATUSES))
    terminal = ", ".join(f"'{s}'" for s in sorted(_TERMINAL_FUNNEL_STATUSES))
    return (
        f"case when is_archived then 2 "
        f"when status in ({engaged}) then 0 "
        f"when status in ({terminal}) then 2 else 1 end, "
        "scored_at desc nulls last"
    )


async def find_jobs_by_company(
    company: str, *, account_id: int, db: Executor | None = None
) -> list[Job]:
    """Все вакансии компании: канон FR2-39, затем lower(company); порядок - ярус + scored_at.

    FR3-72: полный список для дизамбигуации; silent pick - через pick_company_match_candidates /
    find_vacancy_id_by_company.
    """
    name = (company or "").strip()
    if not name:
        return []
    db = db or get_pool()
    order = _company_match_order_sql()
    canon = company_canonical_for(name)
    rows: list[Any] = []
    if canon:
        rows = await db.fetch(
            f"select {_JOB_COLUMNS} from jobs "
            "where company_canonical = $1 and vacancy_id is not null and account_id = $2 "
            f"order by {order}",
            canon,
            account_id,
        )
    if not rows:
        rows = await db.fetch(
            f"select {_JOB_COLUMNS} from jobs "
            "where lower(company) = lower($1) and vacancy_id is not null and account_id = $2 "
            f"order by {order}",
            name,
            account_id,
        )
    return [Job(**row_to_dict(r)) for r in rows]


async def find_vacancy_id_by_company(
    company: str, *, account_id: int, db: Executor | None = None
) -> str | None:
    """Одна вакансия компании: предпочитает активные; при ≥2 в лучшем ярусе - None.

    FR2-87 / FR2-39: сначала матч по `company_canonical`, затем фолбэк на `lower(company)`.
    Пусто / нет матча / неоднозначность → None (бот и silent-callers не берут «последнюю»).
    """
    cands = pick_company_match_candidates(
        await find_jobs_by_company(company, account_id=account_id, db=db)
    )
    if len(cands) == 1:
        return cands[0].vacancy_id
    return None


async def list_jobs(
    *,
    min_score: int | None = None,
    status: str | None = None,
    limit: int = 100,
    exclude_skipped: bool = False,
    account_id: int,
    db: Executor | None = None,
) -> list[Job]:
    db = db or get_pool()
    clauses: list[str] = ["jobs.account_id = $1"]
    params: list[Any] = [account_id]
    if min_score is not None:
        params.append(min_score)
        clauses.append(f"jobs.overall_score >= ${len(params)}")
    if status is not None:
        params.append(status)
        clauses.append(f"jobs.status = ${len(params)}")
    if exclude_skipped:
        # Калибровка / ATS-контекст: пропуск - не «ещё один этап», а явный отказ.
        clauses.append(SQL_JOB_NOT_SKIPPED)
    where = f"where {' and '.join(clauses)}"
    params.append(limit)
    # skipped/has_hr_dialog — EXISTS: skipped_vacancies/hr_threads не гарантируют ровно одну
    # строку на вакансию (HR-тредов бывает несколько), поэтому джойн раздул бы доску дублями —
    # EXISTS остаётся EXISTS. account_id в обоих EXISTS обязателен (Этап 3, план §1) — иначе
    # skip/HR-тред одного аккаунта протекал бы в карточку другого при совпавшем vacancy_id.
    # offers.vacancy_id — PRIMARY KEY (0007_offers), на вакансию не может быть больше одного
    # оффера, поэтому обычный LEFT JOIN безопасен и меняет 6 отдельных коррелированных
    # подзапросов на каждую строку доски на один join; offers ещё не account-scoped
    # (домен 3 плана) — до тех пор join остаётся по одному vacancy_id, без account_id. jobs —
    # больше не единственная таблица в FROM, поэтому _JOB_COLUMNS_QUALIFIED и where идут с
    # префиксом `jobs.` (иначе status/work_format/created_at/updated_at неоднозначны с offers).
    sql = (
        f"select {_JOB_COLUMNS_QUALIFIED}, "
        f"exists(select 1 from skipped_vacancies sv "
        f"where sv.account_id = jobs.account_id and sv.vacancy_id = jobs.vacancy_id) "
        f"as skipped, "
        f"exists("
        f"select 1 from hr_threads ht "
        f"inner join hr_messages hm on hm.thread_id = ht.id "
        f"where ht.account_id = jobs.account_id and ht.vacancy_id = jobs.vacancy_id"
        f") as has_hr_dialog, "
        f"o.status as offer_status, "
        f"o.base_salary as offer_base_salary, "
        f"o.base_salary_currency as offer_base_salary_currency, "
        f"o.base_salary_period as offer_base_salary_period, "
        f"o.work_format as offer_work_format, "
        f"o.bonus_monthly_equiv as offer_bonus_monthly_equiv, "
        f"{_APPLIED_SOURCE_SUBQUERY} as applied_source "
        f"from jobs left join offers o on o.vacancy_id = jobs.vacancy_id "
        f"{where} "
        f"order by {_list_jobs_order_clause()} limit ${len(params)}"
    )
    rows = await db.fetch(sql, *params)
    return [Job(**row_to_dict(r)) for r in rows]


class JobsPage(BaseModel):
    """Курсорная страница доски: вместо одного `limit=500` на клиент."""

    jobs: list[Job]
    next_cursor: str | None = None
    # Точные тоталы по колонкам kanban — независимо от того, сколько уже догружено курсором.
    # Считаем один раз на первой странице (cursor=None), фронт держит значение между догрузками.
    column_counts: dict[str, int] | None = None


async def list_jobs_page(
    *,
    min_score: int | None = None,
    status: str | None = None,
    exclude_skipped: bool = False,
    cursor: str | None = None,
    limit: int = 200,
    account_id: int,
    db: Executor | None = None,
) -> JobsPage:
    """То же, что `list_jobs`, но курсором вместо одного большого `limit` (доска).

    Курсор — номер строки в уже отсортированной выдаче (`row_number()` поверх
    `_list_jobs_order_clause()`), не значения полей сортировки: составной порядок (ранг стадии +
    дата + скор, вперемешку asc/desc с NULLS LAST) керсетом через сравнение кортежей развернулся бы
    в громоздкую OR-цепочку ради экономии, которая не нужна — таблица на масштабе одного владельца
    (сотни-тысячи строк), полная сортировка и так быстрая (см. L-27/28/29 по узким местам). Порядок
    стабилен между страницами только если фильтры/сортировка не меняются между запросами — как и у
    любой оффсетной пагинации в этом смысле, но без её проблемы "сдвиг при вставке в начало":
    `rn` считается заново на каждый запрос от текущего состояния таблицы, не хранится.
    """
    db = db or get_pool()
    clauses: list[str] = ["jobs.account_id = $1"]
    params: list[Any] = [account_id]
    if min_score is not None:
        params.append(min_score)
        clauses.append(f"jobs.overall_score >= ${len(params)}")
    if status is not None:
        params.append(status)
        clauses.append(f"jobs.status = ${len(params)}")
    if exclude_skipped:
        clauses.append(SQL_JOB_NOT_SKIPPED)
    where = f"where {' and '.join(clauses)}"

    after_rn = 0
    if cursor:
        try:
            after_rn = int(cursor)
        except ValueError:
            after_rn = 0

    params.append(after_rn)
    after_param = len(params)
    params.append(limit)
    limit_param = len(params)

    sql = (
        "with ordered as ("
        f"select {_JOB_COLUMNS_QUALIFIED}, "
        f"exists(select 1 from skipped_vacancies sv "
        f"where sv.account_id = jobs.account_id and sv.vacancy_id = jobs.vacancy_id) "
        f"as skipped, "
        f"exists("
        f"select 1 from hr_threads ht "
        f"inner join hr_messages hm on hm.thread_id = ht.id "
        f"where ht.account_id = jobs.account_id and ht.vacancy_id = jobs.vacancy_id"
        f") as has_hr_dialog, "
        f"o.status as offer_status, "
        f"o.base_salary as offer_base_salary, "
        f"o.base_salary_currency as offer_base_salary_currency, "
        f"o.base_salary_period as offer_base_salary_period, "
        f"o.work_format as offer_work_format, "
        f"o.bonus_monthly_equiv as offer_bonus_monthly_equiv, "
        f"{_HR_SCREENING_AT_SUBQUERY} as hr_screening_at, "
        f"{_HR_SCREENING_STATUS_SUBQUERY} as hr_screening_status, "
        f"{_APPLIED_SOURCE_SUBQUERY} as applied_source, "
        f"row_number() over (order by {_list_jobs_order_clause()}) as rn "
        f"from jobs left join offers o on o.vacancy_id = jobs.vacancy_id "
        f"{where}"
        ") "
        f"select * from ordered where rn > ${after_param} order by rn limit ${limit_param}"
    )
    rows = await db.fetch(sql, *params)
    jobs: list[Job] = []
    last_rn: int | None = None
    for r in rows:
        d = row_to_dict(r)
        last_rn = int(d.pop("rn"))
        jobs.append(Job(**d))
    next_cursor = str(last_rn) if last_rn is not None and len(rows) == limit else None
    return JobsPage(jobs=jobs, next_cursor=next_cursor)


# Зеркало BOARD_COLUMNS/SKIPPED_COLUMN/ALIAS из frontend/src/features/jobs/funnel.ts: те
# же 8 колонок kanban и та же канонизация легаси-статусов. Дублирование сознательное — тот же
# паттерн, что уже держит остальная доска (см. комментарий вверху funnel.ts).
_BOARD_STAGES: tuple[str, ...] = (
    FunnelStatus.VIEWED.value,
    FunnelStatus.APPLIED.value,
    FunnelStatus.SCREENING.value,
    FunnelStatus.TECH.value,
    FunnelStatus.FINAL.value,
    FunnelStatus.OFFER.value,
    FunnelStatus.REJECTED.value,
)
_BOARD_STATUS_ALIAS: dict[str, str] = {
    "Архив": FunnelStatus.REJECTED.value,
    "Просмотрено": FunnelStatus.VIEWED.value,
}
SKIPPED_COLUMN = "Пропущено"
BOARD_COLUMNS: tuple[str, ...] = (*_BOARD_STAGES, SKIPPED_COLUMN)


def _resolve_board_column(status: str | None) -> str:
    s = (status or "").strip()
    if s in _BOARD_STAGES:
        return s
    return _BOARD_STATUS_ALIAS.get(s, FunnelStatus.VIEWED.value)


async def count_jobs_by_column(*, account_id: int, db: Executor | None = None) -> dict[str, int]:
    """Точные тоталы по колонкам kanban — не зависят от того, сколько уже догружено
    курсором на клиенте. Канонизация статуса — в Python (`_resolve_board_column`), не в SQL:
    то же зеркало frontend `resolveStage`, без второй alias-таблицы на стороне БД.
    """
    db = db or get_pool()
    rows = await db.fetch(
        "select jobs.status as status, "
        "exists(select 1 from skipped_vacancies sv "
        "where sv.account_id = jobs.account_id and sv.vacancy_id = jobs.vacancy_id) "
        "as skipped, "
        "count(*)::int as n from jobs where jobs.account_id = $1 group by jobs.status, skipped",
        account_id,
    )
    counts: dict[str, int] = dict.fromkeys(BOARD_COLUMNS, 0)
    for r in rows:
        col = SKIPPED_COLUMN if r["skipped"] else _resolve_board_column(r["status"])
        counts[col] = counts.get(col, 0) + int(r["n"])
    return counts


# Ключи `input_coverage_stats` — D11/Этап 9 §9.3: доля вакансий, у которых реально заполнены
# поля конкуренции/свежести/цены отклика. `total_responses`/`letter_required`/`published_at`
# были 0 из 342 на проде и это не всплывало нигде, кроме ручного SQL-аудита.
COVERAGE_STAT_KEYS: tuple[str, ...] = (
    "total_responses_filled",
    "letter_required_true",
    "published_at_filled",
    "salary_explicit",
)


async def input_coverage_stats(*, account_id: int, db: Executor | None = None) -> dict[str, int]:
    """Покрытие входных данных скоринга среди реально проскоренных вакансий аккаунта.

    Стаб-записи (D16: `score = '{}'`) исключены тем же условием, что `list_jobs_for_rescore` —
    у них нет ни одной из измеряемых величин по смыслу, и они раздули бы знаменатель.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "select count(*)::int as total, "
        "count(*) filter (where total_responses is not null)::int as total_responses_filled, "
        "count(*) filter (where letter_required is true)::int as letter_required_true, "
        "count(*) filter (where published_at is not null and published_at <> '')::int "
        "as published_at_filled, "
        "count(*) filter (where score->'salary'->>'source' = 'explicit')::int as salary_explicit "
        "from jobs where account_id = $1 and score is not null and score <> '{}'::jsonb",
        account_id,
    )
    if row is None:
        return {"total": 0, **dict.fromkeys(COVERAGE_STAT_KEYS, 0)}
    return dict(row)


async def list_jobs_for_rescore(*, account_id: int, db: Executor | None = None) -> list[Job]:
    """Оценённые вакансии аккаунта с `score_basis='jd_only'` — вход перескора рубрики (Этап 5 §5.2).

    `hr_confirmed` намеренно исключены: их `overall_score` уже пересчитан живым `score_vacancy`
    с текущими на тот момент весами и подтверждёнными фактами HR (`recalibrate.py`), а
    `hr_format_override` в бэктестировании рубрики не восстановить без нового LLM-вызова
    (тот же компромисс, что `recompute_salary_axis` уже делает для одной оси). Пустой/битый
    `score` (stub-записи D16) отсекается на уровне SQL — нечего пересчитывать.
    """
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_JOB_COLUMNS} from jobs "
        "where account_id = $1 and coalesce(score_basis, 'jd_only') = 'jd_only' "
        "and score is not null and score <> '{}'::jsonb",
        account_id,
    )
    return [Job(**row_to_dict(r)) for r in rows]


async def list_strong_unapplied(
    *,
    min_score: int = 80,
    days: int = 30,
    limit: int = 5,
    account_id: int,
    db: Executor | None = None,
) -> list[Job]:
    """Сильные вакансии (скор >= min_score) в «Просмотре» за последние N дней, без пропуска.

    RD-14 блок «Свежие сильные» — явный мэтч, до которого ещё не дошли руки откликнуться.

    Гейтованные отсекаем явно: с Этапа 1 (plans/scoring_precision_2026_08_17.md §1.4) дилбрейкер
    больше не режет `overall_score`, поэтому «сильная по существу, но с дилбрейкером» вакансия
    иначе всплыла бы здесь как то, до чего «не дошли руки». `recommendation = skip` при гейте
    ставит `apply_calibration` — это та же денормализованная колонка, без чтения jsonb.
    """
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_JOB_COLUMNS} from jobs "
        "where status = $1 and overall_score >= $2 "
        "and coalesce(recommendation, '') <> 'skip' "
        "and scored_at >= now() - make_interval(days => $3) "
        "and account_id = $5 "
        "and not exists(select 1 from skipped_vacancies sv "
        "where sv.account_id = jobs.account_id and sv.vacancy_id = jobs.vacancy_id) "
        "order by overall_score desc, scored_at desc limit $4",
        FunnelStatus.VIEWED.value,
        min_score,
        days,
        limit,
        account_id,
    )
    return [Job(**row_to_dict(r)) for r in rows]


async def list_companies(*, account_id: int, db: Executor | None = None) -> list[CompanyRow]:
    """Реестр канонических компаний из проскоренных вакансий.

    `best_stage` — самая дальняя ступень по всем вакансиям компании (status + история
    `application_stages`). `last_seen_at` — max(`created_at`). Сортировка: вакансий ↓,
    средний балл ↓, имя.
    """
    db = db or get_pool()
    job_rows = await db.fetch(
        f"""
        select id, company_canonical, status, overall_score, created_at
        from jobs
        where company_canonical is not null
          and trim(company_canonical) <> ''
          and overall_score is not null
          and account_id = $1
          and {SQL_JOB_NOT_SKIPPED}
        """,
        account_id,
    )
    if not job_rows:
        return []

    stage_rows = await db.fetch(
        "select job_id, stage from application_stages where account_id = $1", account_id
    )
    history: dict[int, list[str | None]] = defaultdict(list)
    for r in stage_rows:
        history[int(r["job_id"])].append(r["stage"])

    # company → (scores, furthest nums, last_seen)
    scores: dict[str, list[float]] = defaultdict(list)
    furthest: dict[str, int] = defaultdict(lambda: 1)
    last_seen: dict[str, datetime | None] = {}

    for r in job_rows:
        company = str(r["company_canonical"])
        job_id = int(r["id"])
        scores[company].append(float(r["overall_score"]))
        statuses: list[str | None] = [r["status"], *history.get(job_id, [])]
        label = furthest_stage_label(statuses)
        stage_num = _ASCENDING_FUNNEL.index(label) + 1
        furthest[company] = max(furthest[company], stage_num)
        created = r["created_at"]
        prev = last_seen.get(company)
        if created is not None and (prev is None or created > prev):
            last_seen[company] = created

    rows = [
        CompanyRow(
            company=company,
            vacancy_count=len(vals),
            avg_score=round(sum(vals) / len(vals), 1),
            best_stage=_ASCENDING_FUNNEL[furthest[company] - 1],
            last_seen_at=last_seen.get(company),
        )
        for company, vals in scores.items()
    ]
    rows.sort(key=lambda r: (-r.vacancy_count, -r.avg_score, r.company))
    return rows


async def count_active_jobs(*, account_id: int, db: Executor | None = None) -> int:
    """Активные процессы: Отклик/Скрининг/Техничка/Финал/Оффер + HR-диалог без формального отклика."""
    db = db or get_pool()
    engaged = sorted(ENGAGED_FUNNEL_STATUSES)
    row = await db.fetchrow(
        "select count(*) as n from jobs j "
        "where j.account_id = $3 "
        "and not exists("
        "  select 1 from skipped_vacancies sv "
        "  where sv.account_id = j.account_id and sv.vacancy_id = j.vacancy_id"
        ") "
        "and ("
        "  j.status = any($1::text[]) "
        "  or ("
        "    coalesce(nullif(trim(j.status), ''), $2) in ($2, 'Просмотрено') "
        "    and exists("
        "      select 1 from hr_threads ht "
        "      inner join hr_messages hm on hm.thread_id = ht.id "
        "      where ht.account_id = j.account_id and ht.vacancy_id = j.vacancy_id"
        "    )"
        "  )"
        ")",
        engaged,
        FunnelStatus.VIEWED.value,
        account_id,
    )
    assert row is not None
    return int(row["n"])


async def get_days_active(*, account_id: int, db: Executor | None = None) -> int | None:
    """Дней с первой оценённой вакансии аккаунта. Ни одной оценённой — `None`."""
    db = db or get_pool()
    earliest = await db.fetchval(
        "select min(scored_at) from jobs where account_id = $1 and scored_at is not null",
        account_id,
    )
    if not isinstance(earliest, datetime):
        return None
    anchor = earliest if earliest.tzinfo else earliest.replace(tzinfo=UTC)
    return max(0, (datetime.now(UTC) - anchor).days)


async def count_jobs_by_status(
    statuses: list[str],
    *,
    exclude_vacancy_id: str | None = None,
    account_id: int,
    db: Executor | None = None,
) -> dict[str, int]:
    """Сколько вакансий сейчас на каждой из `statuses` (leverage-счётчики для торга).

    `exclude_vacancy_id` — не считать саму вакансию, для которой собирается аргументация
    (иначе оффер по ней задвоил бы себя в счётчике «Оффер»).
    """
    if not statuses:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        "select status, count(*) as n from jobs "
        "where status = any($1::text[]) and ($2::text is null or vacancy_id != $2) "
        "and account_id = $3 "
        "group by status",
        statuses,
        exclude_vacancy_id,
        account_id,
    )
    counts = {s: 0 for s in statuses}
    counts.update({r["status"]: int(r["n"]) for r in rows})
    return counts


# Источники стадии «Отказ», проставленной владельцем (осознанное решение), а не авто-синком
# площадки. Авто-синк откликов (`hh_negotiations`) не имеет права «воскрешать» такую вакансию
# обратно в активную воронку по устаревшему бейджу площадки — вернуть её может только владелец
# вручную или HR в «Чатах» (отдельный код-путь, `hr_actions`/`outreach`). Инцидент: «Толк»,
# vacancy 89 — владелец драгнул карточку в «Отказ», а тихий heartbeat-синк каждые ~15 минут
# возвращал её в «Скрининг» по «Приглашению» на hh.ru.
MANUAL_REJECTION_SOURCES: frozenset[str] = frozenset(
    {
        "api_kanban",  # drag-and-drop на канбане «Вакансии» (web)
        "telegram_bot",  # действие владельца в Telegram-боте
        "vacancy_page",  # расширение: кнопка на странице вакансии hh.ru
        "api_funnel",  # кнопки расширения «Отклик»/«Оффер»/«Отказ»
        "chat_archive",  # закрытие диалога → «Отказ» (classify_archive_disposition)
        "debrief_auto_reject",  # дебриф: этап failed → «Отказ» (решение владельца)
    }
)


AUTO_APPLY_SOURCE_PREFIX = "auto_apply_"


def is_auto_apply_source(source: str | None) -> bool:
    """True — стадия «Отклик» поставлена раннером автооткликов (`core.app.channels.AUTO_APPLY_*`),
    не владельцем вручную. Питает бейдж «Автоотклик» на доске (Фаза 7.1) через `Job.applied_source`.
    """
    return bool(source) and source.startswith(AUTO_APPLY_SOURCE_PREFIX)


def is_manual_rejection_source(source: str | None) -> bool:
    """True — «Отказ» проставлен владельцем (осознанный выбор), а не авто-синком площадки.

    Авто-источники (`hh_negotiations`, `getmatch`, `habr`, `stale_ttl`, `funnel_sync`,
    `scoring`) сюда не входят: их «Отказ» — вывод из бейджа площадки/таймаута, и синк вправе
    вернуть вакансию в воронку, когда площадка сообщит активную стадию.
    """
    return bool(source) and source in MANUAL_REJECTION_SOURCES


async def latest_rejection_source(
    job_id: int, *, account_id: int, db: Executor | None = None
) -> str | None:
    """Источник последней стадии «Отказ» в истории вакансии (None — «Отказов» не было).

    Совпадает и по легаси «Архив» (до того как «Архив» свели к «Отказ») — у старых строк
    `stage` мог хранить «Архив», и такой отказ тоже был терминальным решением.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "select source from application_stages "
        "where job_id = $1 and account_id = $2 and stage in ($3, $4) "
        "order by changed_at desc nulls last, id desc limit 1",
        job_id,
        account_id,
        FunnelStatus.REJECTED.value,
        FunnelStatus.ARCHIVE.value,
    )
    return str(row["source"]) if row else None


async def add_stage(
    job_id: int,
    stage: str,
    *,
    source: str = "manual",
    applied_at: str | None = None,
    account_id: int,
    db: Executor | None = None,
) -> ApplicationStage:
    """Добавить стадию воронки и обновить зеркальный jobs.status (текущая стадия).

    При первом переходе в «Отклик» проставляет `jobs.applied_at` (дата отклика), если она ещё
    пуста: явно переданный `applied_at` (реальная дата из hh-откликов) приоритетнее, иначе
    текущая дата БД. Так заголовочная дата на карточке/в дровере = дата отклика, а не дата
    ПУБЛИКАЦИИ вакансии (которая бывает на 1-2 недели старше) — баг «сегодняшний отклик показан
    неделю назад». COALESCE не затирает уже выставленную дату отклика.
    """
    db = db or get_pool()
    # Прошлая стадия и vacancy_id нужны событию A-11 (и раньше читались отдельным запросом
    # в ветке «Техничка») — один select вместо условного. account_id в WHERE (не только в
    # application_stages.insert ниже) — job_id чужого аккаунта не должен даже отдать previous_stage.
    before = await db.fetchrow(
        "select vacancy_id, status from jobs where id = $1 and account_id = $2", job_id, account_id
    )
    previous_stage = str(before["status"] or "") if before else ""
    vacancy_id = str(before["vacancy_id"] or "") if before else ""

    row = await db.fetchrow(
        "insert into application_stages (job_id, stage, source, account_id) values ($1, $2, $3, $4) "
        "returning id, job_id, stage, source, changed_at",
        job_id,
        stage,
        source,
        account_id,
    )
    assert row is not None
    if stage == FunnelStatus.APPLIED.value:
        await db.execute(
            "update jobs set status = $1, "
            "applied_at = coalesce(applied_at, $3, to_char(current_date, 'YYYY-MM-DD')), "
            "updated_at = now() where id = $2 and account_id = $4",
            stage,
            job_id,
            applied_at,
            account_id,
        )
    else:
        await db.execute(
            "update jobs set status = $1, updated_at = now() where id = $2 and account_id = $3",
            stage,
            job_id,
            account_id,
        )

    # A-11: смена стадии — доменное событие. Побочные эффекты чужих доменов (Техничка ⇒
    # отметить пройденный HR-скрининг) переехали в их подписки; ждём их здесь, потому что
    # результат виден на том же экране сразу после ответа. Падение подписчика гасит шина.
    await publish_application_stage_changed(
        vacancy_id=vacancy_id,
        job_id=job_id,
        stage=stage,
        previous_stage=previous_stage,
        source=source,
        account_id=account_id,
    )

    return ApplicationStage(**row_to_dict(row))


async def purge_empty_unscored_jobs(
    *,
    older_than_hours: float = EMPTY_UNSCORED_TTL_HOURS,
    db: Executor | None = None,
) -> int:
    """Удалить stub-вакансии без скора и без нормального текста JD старше TTL.

    Источник мусора — синк списка откликов (hh negotiations / getmatch applications): создаётся
    запись с title/company и пустым `vacancy_text`, скор невозможен. Пользователю показываем
    предупреждение; если за TTL текст так и не появился — удаляем, чтобы доска не зарастала.

    До 2026-08-18 сюда же попадал `SOURCE_SKIP_STUB` («быстрый пропуск» с SERP) — эта фича
    убрана (`service.skip_and_store` больше не заводит jobs-stub на пропуск), но старые пустые
    строки с этим source могли остаться в БД до первого прогона после обновления — без
    исключения по source они тоже подчищаются здесь как обычный мусор.

    `older_than_hours=0` — удалить все такие stub'ы без возрастного фильтра (разовая чистка).

    Каскад: `application_stages` (ON DELETE CASCADE). Таблицы по `vacancy_id` без FK не трогаем —
    у пустых stub'ов там обычно пусто; осиротевшие строки по vacancy_id — существующий паттерн.

    Без `account_id`: фоновая системная чистка (планировщик), а не запрос из-под конкретного
    аккаунта — по духу «GC вложений» (план §1), работает по всем аккаунтам сразу.
    """
    if older_than_hours < 0:
        raise ValueError("older_than_hours не может быть отрицательным")
    db = db or get_pool()
    if older_than_hours == 0:
        result = await db.execute(
            """
            delete from jobs
            where overall_score is null
              and length(trim(coalesce(vacancy_text, ''))) < $1
            """,
            MIN_VACANCY_TEXT_LEN,
        )
    else:
        result = await db.execute(
            """
            delete from jobs
            where overall_score is null
              and length(trim(coalesce(vacancy_text, ''))) < $1
              and coalesce(created_at, updated_at) < now() - ($2 * interval '1 hour')
            """,
            MIN_VACANCY_TEXT_LEN,
            older_than_hours,
        )
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


async def archive_stale_jobs(
    *,
    days: int = 21,
    short_days: int = 14,
    db: Executor | None = None,
) -> int:
    """Перевести давно неактивные вакансии в «Отказ» (бывший статус «Архив» убран).

    TTL `days` (21) — для живых этапов (Просмотр / Отклик / Скрининг / Техничка / Финал).
    Уже «Отказ» / «Оффер» / skipped не трогаем: они в терминальных колонках доски.
    `short_days` оставлен в сигнатуре ради совместимости вызовов, на выборку не влияет.

    Источник вакансии (hh / getmatch / habr / telegram) НЕ влияет на TTL — единое правило.

    «Последняя активность» = максимум из `updated_at` / `scored_at` / `applied_at` (если
    парсится как YYYY-MM-DD) / `created_at` / `skipped_vacancies.scored_at` / последнего
    `hr_messages.sent_at` треда вакансии / `interview_stages.scheduled_at` (план §4,
    local_context_blind_spots_2026_08_12.md — раньше живая переписка/назначенная встреча
    никак не защищали вакансию от авто-отказа по таймауту).

    Переход проведён через `add_stage` (а не голым UPDATE) — иначе после авто-архива
    `application_stages` не пополняется, и история воронки врёт (разрыв: `jobs.status='Отказ'`,
    а последняя запись в `application_stages` — старая активная стадия).

    Без `account_id`: фоновая системная чистка (планировщик), работает по всем аккаунтам сразу
    (как `purge_empty_unscored_jobs` выше) — `account_id` вакансии читается построчно из выборки.
    """
    del short_days  # совместимость сигнатуры; короткий TTL для отказа/пропуска больше не нужен
    db = db or get_pool()
    rejected = FunnelStatus.REJECTED.value
    # Не трогаем терминальные + легаси «Архив» (уже сводится к Отказу в UI).
    terminal = (
        FunnelStatus.REJECTED.value,
        FunnelStatus.ARCHIVE.value,
        FunnelStatus.OFFER.value,
    )
    rows = await db.fetch(
        """
        with eligible as (
          select
            j.id,
            j.account_id,
            greatest(
              coalesce(j.updated_at, j.created_at),
              coalesce(j.scored_at, j.created_at),
              case
                when j.applied_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                  then to_date(substring(j.applied_at from 1 for 10), 'YYYY-MM-DD')::timestamptz
                else j.created_at
              end,
              j.created_at,
              coalesce(
                (select sv.scored_at from skipped_vacancies sv
                 where sv.vacancy_id = j.vacancy_id),
                j.created_at
              ),
              coalesce(lhr.last_hr_at, j.created_at),
              coalesce(nstg.max_scheduled_at, j.created_at)
            ) as last_activity
          from jobs j
          left join lateral (
            select max(hm.sent_at) as last_hr_at
            from hr_threads t
            join hr_messages hm on hm.thread_id = t.id
            where t.vacancy_id = j.vacancy_id and t.account_id = j.account_id
          ) lhr on true
          left join lateral (
            select max(ist.scheduled_at) as max_scheduled_at
            from interview_stages ist
            where ist.vacancy_id = j.vacancy_id and ist.account_id = j.account_id
          ) nstg on true
          where j.status <> all($1::text[])
            and not exists (
              select 1 from skipped_vacancies sv where sv.vacancy_id = j.vacancy_id
            )
        )
        select id, account_id from eligible
        where last_activity < now() - ($2 * interval '1 day')
        """,
        list(terminal),
        days,
    )
    archived_n = 0
    for row in rows:
        job_id = row["id"]
        try:
            await add_stage(
                job_id, rejected, source="stale_ttl", account_id=row["account_id"], db=db
            )
            archived_n += 1
        except Exception as exc:  # noqa: BLE001 — одна сломанная вакансия не должна валить всю чистку
            logger.warning(
                "archive_stale_jobs: не удалось перевести job %d в Отказ: %s", job_id, exc
            )
    return archived_n


async def mark_resume_viewed(job_id: int, *, account_id: int, db: Executor | None = None) -> None:
    """Зафиксировать «HR открыл резюме», один раз (COALESCE не затирает первую отметку).

    hh.ru не отдаёт точную дату просмотра в списке откликов — момент фиксируем по факту синка
    (`core.domains.pipeline.negotiations`), это приближение, не биржевая точность. Стадию воронки не трогает.
    """
    db = db or get_pool()
    await db.execute(
        "update jobs set hr_viewed_at = coalesce(hr_viewed_at, now()) "
        "where id = $1 and account_id = $2",
        job_id,
        account_id,
    )


async def backfill_total_responses(
    vacancy_id: str, *, account_id: int, total_responses: int, db: Executor | None = None
) -> None:
    """Точечно долить `total_responses`, если строка уже существует, но поле пусто.

    Этап 6 §6.1 (plans/scoring_precision_2026_08_17.md): страница вакансии hh.ru больше не
    отдаёт счётчик откликов вовсе (живая проверка 2026-08-18) — расширение физически не может
    его достать. SERP (`sources/hh.py`) счётчик несёт; discovery зовёт это при `skip_existing`
    на уже известную вакансию, а не только при первом сохранении. `where total_responses is null`
    — не перетираем более свежее значение подтверждённым позже (счётчик растёт монотонно, но
    источник у него один — SERP-снимок конкретного дня, не нужно молча заменять предыдущий).
    """
    db = db or get_pool()
    await db.execute(
        "update jobs set total_responses = $3 "
        "where vacancy_id = $1 and account_id = $2 and total_responses is null",
        vacancy_id,
        account_id,
        total_responses,
    )


async def update_apply_fields(
    job_id: int,
    *,
    cover_letter_text: str | None = None,
    cover_letter_lang: str | None = None,
    published_at: str | None = None,
    note: str | None = None,
    applied_at: str | None = None,
    letter_required: bool | None = None,
    work_format: str | None = None,
    account_id: int,
    db: Executor | None = None,
) -> None:
    """Точечно обновить поля отклика без сброса scored_at: сопроводительное (+ его язык, Э4.4),
    дата публикации, свободная заметка, дата отклика, флаг «письмо требовалось», формат работы
    (карточка вакансии в вебе, JS-1.2/JS-8.3).

    Не трогает поля, переданные как None, — это COALESCE-обновление: статус воронки идёт
    отдельно через add_stage, здесь только метаданные отклика. Пустая строка (note="")
    очищает заметку (отличается от None = «не менять»). `work_format` — ручной выбор в чате,
    когда площадка/LLM формат не определили; не влияет на скоринг (тот читает
    score.remote_abroad_compat, не эту колонку) — только на отображение.
    """
    if all(
        v is None
        for v in (
            cover_letter_text,
            cover_letter_lang,
            published_at,
            note,
            applied_at,
            letter_required,
            work_format,
        )
    ):
        return
    db = db or get_pool()
    await db.execute(
        "update jobs set cover_letter_text = coalesce($2, cover_letter_text), "
        "cover_letter_lang = coalesce($3, cover_letter_lang), "
        "published_at = coalesce($4, published_at), note = coalesce($5, note), "
        "applied_at = coalesce($6, applied_at), "
        "letter_required = coalesce($7, letter_required), "
        "work_format = coalesce($8, work_format), updated_at = now() "
        "where id = $1 and account_id = $9",
        job_id,
        cover_letter_text,
        cover_letter_lang,
        published_at,
        note,
        applied_at,
        letter_required,
        work_format,
        account_id,
    )


async def update_job_track(
    job_id: int,
    track: str,
    *,
    account_id: int,
    db: Executor | None = None,
) -> Job | None:
    """Ручная поправка трека: побеждает вывод агента, рескор не перетирает."""
    if track not in ("primary", "second_job"):
        raise ValueError(f"неизвестный трек: {track}")
    db = db or get_pool()
    row = await db.fetchrow(
        "update jobs set track = $2, track_override = true, updated_at = now() "
        f"where id = $1 and account_id = $3 returning {_JOB_COLUMNS}",
        job_id,
        track,
        account_id,
    )
    return Job(**row_to_dict(row)) if row else None


async def update_job_theses(
    vacancy_id: str,
    *,
    pros: list[str],
    cons: list[str],
    red_flags: list[str],
    account_id: int,
    db: Executor | None = None,
) -> Job | None:
    """Ручная правка тезисов скора (расширение, Решение 3 — drag-and-drop между Плюсы/Минусы/
    Красные флаги + удаление): переписывает только `score.pros/cons/red_flags` внутри jsonb.

    Не трогает overall_score/recommendation/scored_at/score_basis — это не пересчёт, а точечная
    правка списков поверх уже посчитанного скора (в отличие от `update_job_score`, которая
    зеркалит пересчёт по HR-фактам). None — вакансии с таким vacancy_id нет.
    """
    db = db or get_pool()
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
    if job is None or job.id is None:
        return None
    new_score = dict(job.score)
    new_score["pros"] = pros
    new_score["cons"] = cons
    new_score["red_flags"] = red_flags
    row = await db.fetchrow(
        f"update jobs set score = $2, updated_at = now() where id = $1 and account_id = $3 "
        f"returning {_JOB_COLUMNS}",
        job.id,
        new_score,
        account_id,
    )
    if row is None:
        return None
    return Job(**row_to_dict(row))


async def update_job_identity(
    vacancy_id: str,
    *,
    company: str,
    title: str,
    account_id: int,
    db: Executor | None = None,
) -> Job | None:
    """Ручная правка компании/должности (карандаш в шапке «Чатов», FR: executive-recruiter
    кейс — при HR-first контакте конкретная роль часто не названа сразу, плейсхолдер
    company/title правится по факту разговора). Не пересчитывает скор — это отдельный шаг
    (`core.domains.pipeline.outreach.update_vacancy_identity`), здесь только запись полей.
    None — вакансии с таким vacancy_id нет.
    """
    db = db or get_pool()
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
    if job is None or job.id is None:
        return None
    company_norm = company.strip()
    title_norm = title.strip()
    row = await db.fetchrow(
        "update jobs set company = $2, title = $3, company_canonical = $4, updated_at = now() "
        f"where id = $1 and account_id = $5 returning {_JOB_COLUMNS}",
        job.id,
        company_norm,
        title_norm,
        company_canonical_for(company_norm),
        account_id,
    )
    if row is None:
        return None
    return Job(**row_to_dict(row))


async def update_job_anketa(
    vacancy_id: str,
    *,
    anketa: dict[str, Any] | None,
    account_id: int,
    db: Executor | None = None,
) -> Job | None:
    """Записать/сбросить состояние анкеты работодателя (Фаза 3.3, jsonb `AnketaState`
    из `core.domains.opportunities.models`, здесь принимается уже как `dict` — домен
    `pipeline/auto_apply` не импортирует Job напрямую для записи, зовёт через это). `None`
    очищает поле (используется, если понадобится сбросить состояние вручную). None — вакансии
    с таким vacancy_id нет.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "update jobs set anketa = $2, updated_at = now() where vacancy_id = $1 and account_id = $3 "
        f"returning {_JOB_COLUMNS}",
        vacancy_id,
        anketa,
        account_id,
    )
    if row is None:
        return None
    return Job(**row_to_dict(row))


async def list_stages(
    job_id: int, *, account_id: int, db: Executor | None = None
) -> list[ApplicationStage]:
    db = db or get_pool()
    rows = await db.fetch(
        "select id, job_id, stage, source, changed_at from application_stages "
        "where job_id = $1 and account_id = $2 order by changed_at",
        job_id,
        account_id,
    )
    return [ApplicationStage(**row_to_dict(r)) for r in rows]
