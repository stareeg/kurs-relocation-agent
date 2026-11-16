"""Инструменты агента поверх готового продукта (A-2) и мост в deepagents.

Каждый инструмент: имя и описание простыми словами (модель выбирает по описанию),
схема аргументов на Pydantic, ответ короткий и структурный, ошибка возвращается как
наблюдение, а не роняет граф (критерий A-2, PLAN 4.1). Аккаунт и БД берутся из
`ToolContext`, а не из аргументов модели — то, что код знает сам.

Инструменты-чтения ходят в домены продукта: профиль (`profile`), вакансии
(`opportunities`: поиск по собранной базе, OQ-7; условия найма; скор), письмо
(`core.app.scenarios.cover_letter`). Единственное действие — «поставить отклик
в очередь на подтверждение» (OQ-8): карточка подтверждения, после «да» человека
текст письма пишется в вакансию, а вакансия переводится в бакет «Сам откликнется»
очереди автооткликов — отправку делает расширение со своими лимитами и капчей.

Инструменты правил страны (K-1), калькулятора (K-3) и памяти (M-1) добавятся вместе
с этими модулями — здесь их нет, чтобы не плодить заглушки.

Мост из контрактов в deepagents: `StepRecorder` копит факты шага, `to_langchain_tools`
оборачивает контракты в `StructuredTool`.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from core.app.agent.contracts import (
    ConfirmationCard,
    Tool,
    ToolCall,
    ToolContext,
    ToolError,
    error_payload,
    short,
)
from core.app.agent.events import AgentEvent, RunObserver
from core.app.agent.state import Observation
from core.app.agent.toolkit import execute_tool, register_tools
from core.domains.opportunities.jobs import (
    get_job_by_vacancy_id,
    list_jobs,
    update_apply_fields,
)
from core.domains.opportunities.work_terms import get_or_extract_work_terms
from core.domains.pipeline.auto_apply.overrides import set_override
from core.domains.profile.international import derive_international_readiness
from core.domains.profile.structured_store import read_resume_data_for_account
from core.kernel.errors import DomainError, InvalidInput, NotFound, RateLimited

MAX_RESULT_ITEMS = 5
"""Потолок выдачи поиска: длинные списки съедают контекст шага (риски PLAN 3)."""
_MAX_PROFILE_SKILLS = 15
_SEARCH_SCAN_LIMIT = 200
"""Сколько вакансий базы сканирует поиск: демо-база маленькая, длинные базы придут с K-1."""


# ------------------------------------------------------------------- аргументы


class ReadProfileArgs(BaseModel):
    """Прочитать профиль кандидата."""


class SearchVacanciesArgs(BaseModel):
    """Найти вакансии в собранной базе аккаунта."""

    query: str = Field(
        default="",
        description=(
            "Слова из названия, компании или описания вакансии, например «backend python». "
            "Пусто — вернуть все вакансии базы."
        ),
    )
    work_format: Literal["remote", "hybrid", "office"] | None = Field(
        default=None, description="Формат работы; не указан — любой"
    )
    min_overall_score: int = Field(
        default=0, ge=0, le=100, description="Минимальный балл оценки 0–100; 0 — без фильтра"
    )


class VacancyIdArgs(BaseModel):
    """Аргумент-один id: вакансия должна прийти из search_vacancies."""

    vacancy_id: str = Field(
        min_length=2,
        max_length=64,
        description="id вакансии из search_vacancies, например demo-101",
    )


class WriteCoverLetterArgs(BaseModel):
    """Написать сопроводительное письмо под вакансию и сохранить его в карточке."""

    vacancy_id: str = Field(
        min_length=2,
        max_length=64,
        description="id вакансии из search_vacancies, например demo-101",
    )
    lang: Literal["ru", "en"] | None = Field(
        default=None,
        description=(
            "Язык письма; не указан — определяется по языку резюме "
            "(кириллица → русское, латиница → английское)"
        ),
    )


class QueueApplicationArgs(BaseModel):
    """Поставить отклик в очередь на подтверждение. Действие, требует подтверждения."""

    vacancy_id: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="id вакансии из search_vacancies, например demo-101",
    )
    cover_note: str = Field(
        min_length=40,
        max_length=600,
        description="Короткое сопроводительное сообщение, 40–600 символов, без выдуманных фактов",
    )


# ------------------------------------------------------------------- ошибки как данные


def _domain_tool_error(exc: DomainError) -> ToolError:
    """Ошибка домена → форма ошибки инструмента (критерий A-2: ошибка не роняет граф)."""
    kind: str = "unavailable"
    if isinstance(exc, NotFound):
        kind = "not_found"
    elif isinstance(exc, InvalidInput):
        kind = "validation"
    elif isinstance(exc, RateLimited):
        kind = "busy"
    return ToolError(
        type=kind,  # type: ignore[arg-type]
        message=str(exc),
        hint="честно скажите, что данных сейчас нет; повторите позже или смените шаг",
    )


def as_tool_data(
    fn: Callable[[BaseModel, ToolContext], Awaitable[dict[str, Any]]],
) -> Callable[[BaseModel, ToolContext], Awaitable[dict[str, Any]]]:
    """Сбой домена/сервиса → ошибка-данные, а не исключение в графе (критерий A-2)."""

    @functools.wraps(fn)
    async def wrapper(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
        try:
            return await fn(args, ctx)
        except DomainError as exc:
            return error_payload(_domain_tool_error(exc))
        except Exception as exc:  # noqa: BLE001 — сбой сервиса тоже наблюдение, не падение
            return error_payload(
                ToolError(
                    type="unavailable",
                    message=str(exc) or type(exc).__name__,
                    hint="повторите позже или предложите оператора; не выдумывайте данные",
                )
            )

    return wrapper


# ------------------------------------------------------------------- проекции


def _job_card(job: Any) -> dict[str, Any]:
    """Вакансия короткой строкой для модели: id и факты карточки без текста."""
    score = job.score if isinstance(job.score, dict) else {}
    verdict = score.get("one_line_verdict") or ""
    compat = score.get("remote_abroad_compat") or {}
    if not verdict and isinstance(compat, dict):
        verdict = compat.get("reasoning") or ""
    return {
        "id": job.vacancy_id or (f"job-{job.id}" if job.id else ""),
        "title": job.title,
        "company": job.company,
        "salary_text": job.salary_text,
        "area": job.area,
        "work_format": job.work_format,
        "status": job.status,
        "overall_score": job.overall_score,
        "recommendation": job.recommendation,
        "verdict": verdict,
        "url": job.url,
    }


def _search_hint(found: int, shown: int) -> dict[str, Any]:
    if found > shown:
        return {
            "hint": (
                f"показано {shown} из {found}: поднимите min_overall_score, добавьте слова "
                "в query или сузьте формат работы"
            )
        }
    if found == 0:
        return {
            "hint": (
                "подходящих вакансий в базе нет: ослабьте фильтры; если база пуста — "
                "попросите запустить сбор в расширении"
            )
        }
    return {}


def _score_compact(score: Any) -> dict[str, Any]:
    """Оценка вакансии коротким словарём: балл, рекомендации, ловушки."""
    return {
        "overall_score": score.overall_score,
        "recommendation": score.recommendation,
        "one_line_verdict": score.one_line_verdict,
        "currency_remote": bool(getattr(score, "currency_remote", False)),
        "remote_abroad_compat": {
            "level": score.remote_abroad_compat.level,
            "reasoning": score.remote_abroad_compat.reasoning,
        },
        "grade_match": {
            "level": score.grade_match.level,
            "reasoning": score.grade_match.reasoning,
        },
        "salary": {
            "meets_min": score.salary.meets_min,
            "value_or_range": score.salary.value_or_range,
            "note": score.salary.note,
        },
        "role_content_match": {
            "score": score.role_content_match.score,
            "matched_niche": list(score.role_content_match.matched_niche)[:4],
        },
        "pros": list(score.pros)[:4],
        "cons": list(score.cons)[:4],
        "red_flags": list(score.red_flags)[:4],
    }


def _vacancy_not_found(vacancy_id: str) -> ToolError:
    return ToolError(
        type="not_found",
        message=f"вакансии {vacancy_id} нет в собранной базе",
        hint="сначала вызовите search_vacancies и возьмите id оттуда",
    )


async def _job_or_error(vacancy_id: str, ctx: ToolContext) -> tuple[Any, dict[str, Any] | None]:
    """Вакансия по id из базы аккаунта или готовая ошибка not_found."""
    job = await get_job_by_vacancy_id(vacancy_id, account_id=ctx.account_id, db=ctx.db)
    if job is None or job.id is None:
        return None, error_payload(_vacancy_not_found(vacancy_id))
    return job, None


# ------------------------------------------------------------------- реализации


@as_tool_data
async def read_profile(_args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    """Прочитать профиль кандидата из резюме аккаунта (международный потенциал включён)."""
    data = await read_resume_data_for_account(ctx.account_id, db=ctx.db)
    intl = derive_international_readiness(data)
    filled = bool(data.position.title or data.experience or data.personal.city)
    result: dict[str, Any] = {
        "name": data.personal.full_name,
        "city": data.personal.city,
        "relocation": data.personal.relocation,
        "position": data.position.title,
        "salary_min": data.position.salary_min,
        "salary_currency": data.position.salary_currency,
        "salary_basis": data.position.salary_basis,
        "schedule": list(data.position.schedule),
        "grade": list(data.position.grade),
        "niches": list(data.search_criteria.niches),
        "market_scope": data.search_criteria.market_scope,
        "key_skills": list(data.key_skills)[:_MAX_PROFILE_SKILLS],
        "english_level": intl.english_level,
        "home_timezone": intl.home_timezone,
        "overlap_hours": intl.overlap,
        "accepted_currencies": intl.accepted_currencies,
        "contract_forms": intl.contract_forms,
        "readiness": intl.readiness,
    }
    if not filled:
        result["hint"] = "профиль пуст: попросите владельца заполнить резюме на вкладке «Резюме»"
    return result


@as_tool_data
async def search_vacancies(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    """Найти вакансии в собранной базе аккаунта (OQ-7: поиск по своему, без сети)."""
    assert isinstance(args, SearchVacanciesArgs)
    jobs = await list_jobs(
        account_id=ctx.account_id,
        db=ctx.db,
        limit=_SEARCH_SCAN_LIMIT,
        exclude_skipped=True,
    )
    tokens = [token for token in args.query.lower().split() if token]
    found = []
    for job in jobs:
        if job.is_archived:
            continue
        if args.work_format and job.work_format != args.work_format:
            continue
        if args.min_overall_score and (job.overall_score or 0) < args.min_overall_score:
            continue
        if tokens:
            haystack = " ".join(
                filter(
                    None,
                    (job.title, job.company, job.area, job.vacancy_text, " ".join(job.skills)),
                )
            ).lower()
            if not all(token in haystack for token in tokens):
                continue
        found.append(job)
    items = [_job_card(job) for job in found[:MAX_RESULT_ITEMS]]
    return {
        "items": items,
        "total": len(found),
        "shown": len(items),
        **_search_hint(len(found), len(items)),
    }


@as_tool_data
async def read_work_terms(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    """Прочитать условия найма вакансии: занятость, гео, часы, валюта — с цитатами."""
    assert isinstance(args, VacancyIdArgs)
    job, error = await _job_or_error(args.vacancy_id, ctx)
    if error is not None:
        return error
    terms = await get_or_extract_work_terms(
        args.vacancy_id,
        job.vacancy_text,
        db=ctx.db,
        location_raw=job.area,
        remote_type=job.work_format,
    )
    return {
        "vacancy_id": args.vacancy_id,
        "engagement": terms.engagement,
        "scope": terms.scope,
        "geo_scope": terms.geo_scope,
        "hiring_geo": list(terms.hiring_geo),
        "residency_required": terms.residency_required,
        "payroll_form": terms.payroll_form,
        "timezone_requirement": terms.timezone_requirement,
        "overlap_hours_required": terms.overlap_hours_required,
        "async_culture": terms.async_culture,
        "weekly_hours": terms.weekly_hours,
        "currency": terms.currency,
        "rate_period": terms.rate_period,
        "rate_min": terms.rate_min,
        "rate_max": terms.rate_max,
        "evidence": [{"field": item.field, "quote": item.quote} for item in terms.evidence[:6]],
    }


@as_tool_data
async def score_vacancy_tool(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    """Оценить вакансию 0–100 по профилю: совпадение, валюта, совместимость с удалёнкой."""
    assert isinstance(args, VacancyIdArgs)
    job, error = await _job_or_error(args.vacancy_id, ctx)
    if error is not None:
        return error
    from core.domains.opportunities.scorer import score_vacancy

    result = await score_vacancy(
        job.vacancy_text,
        account_id=ctx.account_id,
        salary_text=job.salary_text,
        company=job.company,
        vacancy_id=job.vacancy_id,
        skills=job.skills,
        specialization=job.specialization,
        seniority=job.seniority,
        location_raw=job.area,
        remote_type=job.work_format,
    )
    return {"vacancy_id": args.vacancy_id, **_score_compact(result)}


@as_tool_data
async def write_cover_letter(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    """Написать сопроводительное письмо под вакансию и записать его в карточку вакансии."""
    assert isinstance(args, WriteCoverLetterArgs)
    job, error = await _job_or_error(args.vacancy_id, ctx)
    if error is not None:
        return error
    from core.app.scenarios.cover_letter import generate_for_job

    letter = await generate_for_job(job.id, account_id=ctx.account_id, lang=args.lang)
    return {
        "vacancy_id": args.vacancy_id,
        "letter": letter.cover_letter_text,
        "lang": letter.lang,
        "saved": True,
    }


@as_tool_data
async def queue_application(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    """Поставить отклик в очередь автооткликов на подтверждение (OQ-8).

    Действие: код показывает человеку карточку с вакансией и текстом, выполняет только
    после «да». После подтверждения: текст пишется в `jobs.cover_letter_text` (его
    отправляет расширение), вакансия переводится в бакет «Сам откликнется» очереди.
    Ключ идемпотентности: одно намерение клиента — один отклик, даже при повторе.
    """
    assert isinstance(args, QueueApplicationArgs)
    job, error = await _job_or_error(args.vacancy_id, ctx)
    if error is not None:
        return error
    fingerprint = hashlib.sha256(
        f"{ctx.account_id}:{args.vacancy_id}:{args.cover_note}".encode()
    ).hexdigest()[:12]
    if fingerprint in ctx.submissions:
        return {**ctx.submissions[fingerprint], "idempotent_replay": True}
    await update_apply_fields(
        job.id,
        cover_letter_text=args.cover_note,
        account_id=ctx.account_id,
        db=ctx.db,
    )
    await set_override(job.id, "auto", account_id=ctx.account_id, db=ctx.db)
    submission = {
        "queued": True,
        "submission_id": f"sub_{fingerprint}",
        "vacancy_id": args.vacancy_id,
        "title": job.title,
        "company": job.company,
        "queue_bucket": "auto",
        "note_chars": len(args.cover_note),
    }
    ctx.submissions[fingerprint] = submission
    return submission


# ------------------------------------------------------------------- каталог


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="read_profile",
        description=(
            "Возвращает профиль кандидата из резюме: желаемая позиция и зарплата, город, "
            "рынок поиска, ключевые навыки, уровень английского, часовой пояс и пересечение "
            "часов, принятые валюты, формы договора. Аргументов нет — аккаунт берётся из "
            "сессии. Используй первым, чтобы подбирать вакансии и проверять условия под "
            "человека. Не используй для вопросов о вакансиях — для этого search_vacancies."
        ),
        args_model=ReadProfileArgs,
        kind="read",
        fn=read_profile,
    ),
    Tool(
        name="search_vacancies",
        description=(
            "Ищет по вакансиям, уже собранным в базу аккаунта (их собрало расширение). "
            "Возвращает не больше 5 записей: id, название, компания, вилка, формат работы, "
            "балл и короткий вердикт, плюс total. Фильтры: слова в query, формат работы, "
            "минимальный балл. Используй, чтобы подобрать варианты или взять id вакансии "
            "для остальных инструментов. Если база пуста — в ответе будет hint с просьбой "
            "запустить сбор в расширении. Не используй для правил страны — для этого "
            "позже появится инструмент базы знаний."
        ),
        args_model=SearchVacanciesArgs,
        kind="read",
        fn=search_vacancies,
    ),
    Tool(
        name="read_work_terms",
        description=(
            "Возвращает условия найма вакансии с цитатами из её текста: формат занятости "
            "(employment/B2B), где можно работать (гео, резидентство), часовой пояс и "
            "пересечение часов, валюта и ставка. vacancy_id бери из search_vacancies. "
            "Используй, чтобы проверить ловушки: «Right to work in the EU», гибрид вместо "
            "удалёнки, вилка не в той валюте. Не выдумывай условия, которых нет в цитатах."
        ),
        args_model=VacancyIdArgs,
        kind="read",
        fn=read_work_terms,
    ),
    Tool(
        name="score_vacancy",
        description=(
            "Оценивает вакансию по профилю кандидата: балл 0–100, рекомендация "
            "(strong_apply/apply/maybe/skip), совпадение грейда и задач, вилка против "
            "минимума, ловушки (red_flags), плюсы и минусы. vacancy_id бери из "
            "search_vacancies. Вызов может занять до минуты: модель читает текст вакансии. "
            "Не вызывай повторно для той же вакансии без изменений."
        ),
        args_model=VacancyIdArgs,
        kind="read",
        fn=score_vacancy_tool,
    ),
    Tool(
        name="write_cover_letter",
        description=(
            "Пишет сопроводительное письмо под вакансию из резюме аккаунта и сохраняет его "
            "в карточке вакансии. Язык: ru, en или не указан (по языку резюме). vacancy_id "
            "бери из search_vacancies. Используй, когда человек просит письмо или перед "
            "откликом. Текст письма приходит в ответе целиком."
        ),
        args_model=WriteCoverLetterArgs,
        kind="read",
        fn=write_cover_letter,
    ),
    Tool(
        name="queue_application",
        description=(
            "Ставит отклик на вакансию в очередь отправки. Это действие: код покажет "
            "человеку карточку с вакансией и сопроводительным текстом, и выполнит только "
            "после его «да». После подтверждения текст уходит в карточку вакансии, а "
            "вакансия — в очередь автооткликов: расширение отправит её с лимитами и "
            "остановкой на капче. Используй только для vacancy_id из search_vacancies. "
            "Сопроводительный текст пиши честно, 40–600 символов, без выдуманных фактов."
        ),
        args_model=QueueApplicationArgs,
        kind="action",
        fn=queue_application,
        requires_confirmation=True,
    ),
)

TOOL_BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def ensure_tools_registered() -> None:
    """Зарегистрировать каталог в `toolkit` (идемпотентно, вызывает сборка графа)."""
    register_tools(TOOLS)


# ------------------------------------------------------------------- мост в deepagents


class StepRecorder:
    """Копилка фактов одного шага: результаты инструментов, ошибки, вакансии, карточка.

    Один экземпляр на запуск шага; заполняется обёртками инструментов, вычитается узлом
    шага в состояние (`Observation`, `vacancies`, `pending_action`). Для инструментов
    субагента (A-8) — отдельный экземпляр с тегом `subagent`: событие уходит в поток
    с именем роли, а вакансии сливает в запись шага мидлварь `SubagentGate`.
    """

    def __init__(
        self,
        step_id: str,
        index: int,
        emit: RunObserver | None = None,
        *,
        subagent: str | None = None,
    ) -> None:
        self.step_id = step_id
        self.index = index
        self._observer = emit
        self.subagent = subagent
        self.tools: list[str] = []
        self.summaries: list[str] = []
        self.last_error: str | None = None
        self.vacancies: list[dict[str, Any]] = []
        self.pending: ConfirmationCard | None = None

    def record(
        self,
        tool: Tool,
        result: dict[str, Any],
        error: dict[str, Any] | None,
    ) -> None:
        """Запомнить один вызов: имя, короткую сводку, ошибку, вакансии; событие наружу."""
        self.tools.append(tool.name)
        if error is not None:
            message = str(error.get("message", "ошибка инструмента"))
            self.summaries.append(f"{tool.name}: ошибка — {message}")
            self.last_error = message
        elif result.get("cancelled"):
            # Действие отложено: подтвердит человек в узле confirm (A-3), это не ошибка.
            self.summaries.append(f"{tool.name}: действие отложено до подтверждения человека")
        else:
            self.summaries.append(f"{tool.name}: {short(result)}")
            items = result.get("items")
            if isinstance(items, list):
                known = {str(v.get("id")) for v in self.vacancies if isinstance(v, dict)}
                for item in items:
                    if isinstance(item, dict) and str(item.get("id")) not in known:
                        self.vacancies.append(item)
                        known.add(str(item.get("id")))
        if self._observer is not None:
            payload: dict[str, Any] = {
                "step_id": self.step_id,
                "index": self.index,
                "tool": tool.name,
                "ok": error is None,
                "summary": self.summaries[-1],
                "error": error.get("message") if error else None,
            }
            if self.subagent:
                payload["subagent"] = self.subagent
            self._observer.emit(
                AgentEvent(
                    type="tool_called",
                    payload=payload,
                    node="step",
                )
            )

    def record_pending(self, card: ConfirmationCard) -> bool:
        """Действие ждёт подтверждения: карточка уходит в состояние, выполнения нет.

        Хук всегда отвечает «нет» — execute_tool вернёт «отложено», а узел `confirm`
        поставит граф на паузу (interrupt) и выполнит действие только после «да»
        человека (A-3). Модель выбора человека не получает.
        """
        self.pending = card
        return False

    def to_observation(self, answer: str | None) -> Observation:
        return Observation(
            step_id=self.step_id,
            index=self.index,
            tools=list(self.tools),
            summaries=list(self.summaries),
            error=self.last_error,
            answer=answer,
        )


def build_run_context(base: ToolContext, recorder: StepRecorder) -> ToolContext:
    """Контекст запуска: тот же аккаунт/БД/сбои, но хук подтверждения пишет карточку."""
    return dataclasses.replace(base, confirm=recorder.record_pending)


def to_langchain_tools(
    tools: tuple[Tool, ...],
    ctx: ToolContext,
    recorder: StepRecorder,
) -> list[StructuredTool]:
    """Контракты → инструменты для deepagents (та же схема аргументов, тот же execute_tool)."""

    def make_runner(tool: Tool) -> Any:
        async def run(**kwargs: Any) -> str:
            call_id = f"{tool.name}-{recorder.index}-{len(recorder.tools) + 1}"
            call = ToolCall(id=call_id, name=tool.name, arguments=kwargs)
            result, error, _confirmed_by = await execute_tool(call, ctx)
            error_dict = error_payload(error) if error is not None else None
            recorder.record(tool, result, error_dict)
            return json.dumps(error_dict if error_dict is not None else result, ensure_ascii=False)

        return run

    return [
        StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_model,
            coroutine=make_runner(tool),
        )
        for tool in tools
    ]


__all__ = [
    "MAX_RESULT_ITEMS",
    "StepRecorder",
    "TOOLS",
    "TOOL_BY_NAME",
    "build_run_context",
    "ensure_tools_registered",
    "to_langchain_tools",
]
