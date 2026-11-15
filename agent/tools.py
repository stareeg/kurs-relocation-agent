"""Три инструмента агента курса и их исполнение.

Инструменты: поиск вакансий (чтение), правила страны (чтение), отклик (действие с
подтверждением). Клиент и гражданство берутся из `ToolContext`, а не из аргументов модели —
это то, что код знает сам.

`execute_tool` — harness: проверяет аргументы по схеме, права, подтверждение человека,
таймаут и повторы, и всегда возвращает результат или ошибку как данные.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from agent.contracts import (
    ConfirmationCard,
    Tool,
    ToolCall,
    ToolContext,
    ToolError,
    error_payload,
    short,
)
from agent.data import COUNTRY_RULES, MAX_RESULT_ITEMS, VACANCIES

Role = Literal["backend", "frontend", "data", "qa"]
Country = Literal["Польша", "Сербия", "Германия", "Чехия"]


class SearchVacanciesArgs(BaseModel):
    """Найти вакансии по роли, стране и зарплате."""

    role: Role = Field(description="Роль: backend, frontend, data или qa")
    country: Country | None = Field(
        default=None, description="Страна работы; не указана — ищем во всех четырёх"
    )
    min_salary_eur: int = Field(
        default=0, ge=0, le=20_000, description="Минимальная зарплата в евро в месяц"
    )
    remote_only: bool = Field(default=False, description="Только полностью удалённые вакансии")


class CountryRulesArgs(BaseModel):
    """Правила страны: виза, разрешение на работу, налоги."""

    country: Country = Field(description="Страна, по которой нужны правила")


class SubmitApplicationArgs(BaseModel):
    """Отправить отклик на найденную вакансию. Действие, требует подтверждения."""

    vacancy_id: str = Field(
        pattern=r"^v\d{2}$", description="id вакансии из search_vacancies, например v01"
    )
    cover_note: str = Field(
        min_length=40,
        max_length=600,
        description="Короткое сопроводительное сообщение на русском, 40–600 символов",
    )


def search_vacancies(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    assert isinstance(args, SearchVacanciesArgs)
    found = [
        item
        for item in VACANCIES
        if item["role"] == args.role
        and (args.country is None or item["country"] == args.country)
        and int(item["salary_eur"]) >= args.min_salary_eur  # type: ignore[call-overload]
        and (not args.remote_only or bool(item["remote"]))
    ]
    items = found[:MAX_RESULT_ITEMS]
    result: dict[str, Any] = {
        "items": items,
        "total": len(found),
        "shown": len(items),
    }
    if len(found) > len(items):
        result["hint"] = (
            f"показано {len(items)} из {len(found)}: сузьте страну, роль или поднимите зарплату"
        )
    if not found:
        result["hint"] = "подходящих вакансий нет: ослабьте фильтры и попробуйте снова"
    return result


def country_rules(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    assert isinstance(args, CountryRulesArgs)
    rules = COUNTRY_RULES.get(args.country)
    if rules is None:
        return error_payload(
            ToolError(
                type="not_found",
                message=f"нет правил для страны {args.country}",
                hint="доступны: " + ", ".join(COUNTRY_RULES),
            )
        )
    # Гражданство берём из сессии: модель его не выбирает.
    return {"country": args.country, "citizenship": ctx.citizenship, **rules}


def submit_application(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    assert isinstance(args, SubmitApplicationArgs)
    vacancy = next((item for item in VACANCIES if item["id"] == args.vacancy_id), None)
    if vacancy is None:
        return error_payload(
            ToolError(
                type="not_found",
                message=f"вакансии {args.vacancy_id} нет в базе",
                hint="сначала вызовите search_vacancies и возьмите id оттуда",
            )
        )
    # Ключ идемпотентности: одно намерение клиента — один отклик, даже при повторе.
    fingerprint = hashlib.sha256(
        f"{ctx.applicant_id}:{args.vacancy_id}:{args.cover_note}".encode()
    ).hexdigest()[:12]
    if fingerprint in ctx.submissions:
        return {**ctx.submissions[fingerprint], "idempotent_replay": True}
    submission = {
        "queued": True,
        "submission_id": f"sub_{fingerprint}",
        "vacancy_id": args.vacancy_id,
        "title": vacancy["title"],
        "company": vacancy["company"],
        "country": vacancy["country"],
        "note_chars": len(args.cover_note),
    }
    ctx.submissions[fingerprint] = submission
    return submission


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="search_vacancies",
        description=(
            "Возвращает вакансии по роли, стране и минимальной зарплате в евро. "
            "Новые и более дорогие идут сверху, не больше 5 записей и поле total. "
            "Используй, когда человек ищет работу или просит подобрать варианты. "
            "Не используй для вопросов о правилах страны — для этого country_rules. "
            "Если вакансий нет, в ответе будет hint с тем, что ослабить."
        ),
        args_model=SearchVacanciesArgs,
        kind="read",
        fn=search_vacancies,
    ),
    Tool(
        name="country_rules",
        description=(
            "Возвращает правила страны для гражданства клиента: виза, разрешение на работу, "
            "налоги и одно замечание. Гражданство берётся из сессии, передавать его не нужно. "
            "Используй, когда человек спрашивает, можно ли работать в стране или что нужно "
            "для переезда. Не используй как юридическую консультацию — это условные правила."
        ),
        args_model=CountryRulesArgs,
        kind="read",
        fn=country_rules,
    ),
    Tool(
        name="submit_application",
        description=(
            "Ставит отклик на вакансию в очередь отправки. Это действие: код покажет человеку "
            "карточку с вакансией и текстом, и выполнит только после его «да». "
            "Используй только для vacancy_id, который вернул search_vacancies. "
            "Сопроводительное сообщение пиши на русском, 40–600 символов, без выдуманных фактов."
        ),
        args_model=SubmitApplicationArgs,
        kind="action",
        fn=submit_application,
        requires_confirmation=True,
    ),
)

TOOL_BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}

_READ_ATTEMPTS = 2
_RETRYABLE = {"timeout", "unavailable", "busy"}


def tool_by_name(name: str) -> Tool | None:
    return TOOL_BY_NAME.get(name)


def _validation_error(exc: ValidationError) -> ToolError:
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first.get("loc", ())) or "аргументы"
    return ToolError(
        type="validation",
        message=f"{field}: {first.get('msg', 'неверное значение')}",
        hint="исправьте аргумент и вызовите инструмент снова; допустимые значения — в схеме",
    )


def _fault_error(tool: Tool, kind: str) -> ToolError:
    if kind == "timeout":
        return ToolError(
            type="timeout",
            message=f"{tool.name} не ответил за отведённое время",
            hint="не выдумывайте данные: повторите чтение позже или предложите оператора",
        )
    if kind == "unavailable":
        return ToolError(
            type="unavailable",
            message=f"{tool.name} временно недоступен",
            hint="попробуйте другой инструмент или честно скажите, что сервис недоступен",
        )
    return ToolError(type="busy", message=f"{tool.name} перегружен", hint="повторите позже")


def execute_tool(
    call: ToolCall, ctx: ToolContext
) -> tuple[dict[str, Any], ToolError | None, str | None]:
    """Проверить, подтвердить, выполнить. Возвращает (результат, ошибка, кто подтвердил)."""
    tool = TOOL_BY_NAME.get(call.name)
    if tool is None:
        error = ToolError(
            type="not_found",
            message=f"инструмента {call.name} нет",
            hint="доступны: " + ", ".join(sorted(TOOL_BY_NAME)),
        )
        return error_payload(error), error, None

    raw = call.arguments
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            error = ToolError(
                type="validation",
                message="аргументы не разбираются как JSON",
                hint="передайте объект аргументов по схеме инструмента",
            )
            return error_payload(error), error, None

    try:
        parsed = tool.args_model.model_validate(raw)
    except ValidationError as exc:
        error = _validation_error(exc)
        return error_payload(error), error, None

    confirmed_by: str | None = None
    if tool.requires_confirmation:
        card = ConfirmationCard(action=tool.name, params=parsed.model_dump())
        confirmed = bool(ctx.confirm(card)) if ctx.confirm is not None else False
        if not confirmed:
            return (
                {"cancelled": True, "reason": "человек не подтвердил действие"},
                None,
                None,
            )
        confirmed_by = ctx.applicant_id

    # Сбои сервиса: у чтения пробуем ещё раз, у действия повторов нет (нужен ключ
    # идемпотентности и проверка статуса — слайд 32 лекции 2).
    attempts = _READ_ATTEMPTS if tool.kind == "read" else 1
    for attempt in range(1, attempts + 1):
        fault = ctx.take_fault(tool.name)
        if fault is None:
            result = tool.fn(parsed, ctx)
            if isinstance(result, dict) and "error" in result:
                err = ToolError.model_validate(result["error"])
                return result, err, confirmed_by
            return result, None, confirmed_by
        if fault not in _RETRYABLE or attempt == attempts:
            error = _fault_error(tool, fault)
            if tool.kind == "action":
                error = ToolError(
                    type=error.type,
                    message=error.message,
                    hint="статус действия проверьте вручную: повтор без ключа идемпотентности "
                    "может выполнить его дважды",
                )
            return error_payload(error), error, confirmed_by
    # Недостижимо: цикл выше всегда возвращает результат или ошибку.
    raise RuntimeError("execute_tool: цикл повторов завершился без результата")


def summarize_result(result: dict[str, Any]) -> str:
    """Короткая строка для журнала."""
    return short(result)
