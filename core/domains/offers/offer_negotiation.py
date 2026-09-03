"""LLM-аргументы для торга по офферу.

Кнопка «Торг» на колонке оффера сводит в переговорную позицию то, что уже лежит в системе
россыпью: сам оффер, рыночный бенчмарк по грейду (`core.domains.market.salary_benchmark`),
остальные активные офферы кандидата (leverage «есть альтернативы») и счётчики воронки (сколько
вакансий сейчас на Техничке/Финале/Оффере — тоже leverage). Результат персистится на оффере
(`core.domains.offers.store.save_offer_negotiation`) и перечитывается при заходе — LLM не дёргается
на каждый рендер (cost-гард, тот же принцип, что RD-1/RD-15).

Границы (feedback_llm_advice_not_user_decision): модель НЕ советует принять/отклонить оффер —
только факты + формулировки для переговоров. Решение всегда владельца.

Стиль черновика ответа HR — тот же блок, что `core.domains.pipeline.hr_draft` (`HR_STYLE_BLOCK`), чтобы
торг и обычная переписка не расходились в тоне (план: «один промпт-модуль на обоих»).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from core.config import get_settings
from core.domains.market.salary_benchmark import SalaryBenchmarkSegment
from core.domains.offers.models import NegotiationArgument, NegotiationBrief, OfferRecord
from core.domains.pipeline.hr_draft import HR_STYLE_BLOCK
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)


def _format_money(amount: int | None, currency: str = "RUB") -> str:
    if not amount:
        return "?"
    return f"{amount:,}".replace(",", " ") + f" {currency}"


def _format_offer_line(offer: OfferRecord) -> str:
    period_label = "/мес" if offer.base_salary_period == "month" else "/год"
    tax_label = "на руки" if offer.base_salary_tax_basis == "net" else "до вычета налогов"
    parts = [
        f"База: {_format_money(offer.base_salary, offer.base_salary_currency)}{period_label} "
        f"({tax_label})"
    ]
    if offer.bonus_monthly_equiv:
        parts.append(
            f"Премия: {_format_money(offer.bonus_monthly_equiv)}/мес (помесячный эквивалент)"
        )
    elif offer.bonus_amount:
        parts.append(f"Бонус: {_format_money(offer.bonus_amount)}")
    if offer.signon:
        parts.append(f"Sign-on: {_format_money(offer.signon)}")
    if offer.work_format != "unknown":
        parts.append(f"Формат: {offer.work_format}")
    return ", ".join(parts)


def _format_target_offer(offer: OfferRecord) -> str:
    lines = [f"Компания: {offer.company or '?'}", f"Позиция: {offer.position or '?'}"]
    lines.append(_format_offer_line(offer))
    if offer.equity:
        lines.append(f"Акции: {offer.equity}")
    if offer.vacation_days:
        lines.append(f"Отпуск: {offer.vacation_days} дн.")
    if offer.notice_period:
        lines.append(f"Нотис: {offer.notice_period}")
    if offer.deadline:
        lines.append(f"Дедлайн ответа: {offer.deadline.strftime('%Y-%m-%d %H:%M')}")
    if offer.notes:
        lines.append(f"Заметки: {offer.notes}")
    return "\n".join(lines)


def _format_other_offers(others: list[OfferRecord]) -> str:
    if not others:
        return "(других активных офферов сейчас нет)"
    blocks = []
    for o in others:
        blocks.append(f"- {o.company or '?'} ({o.position or '?'}): {_format_offer_line(o)}")
    return "\n".join(blocks)


def _format_benchmark(segment: SalaryBenchmarkSegment | None) -> str:
    if segment is None:
        return "(рыночного бенчмарка по грейду пока недостаточно — не выдумывать цифры рынка)"
    obs, decl = segment.observations, segment.declared
    lines = [f"Сегмент: {segment.grade_label} × {segment.stack_label}"]
    if obs.enough_data:
        lines.append(
            f"Наблюдения (реальные факты, n={obs.n}): медиана вилки "
            f"{obs.median_min_net:,} - {obs.median_max_net:,} net/мес".replace(",", " ")
        )
    if decl.enough_data:
        lines.append(
            f"Объявленные вилки JD (менее надёжно, n={decl.n}): медиана "
            f"{decl.median_min_net:,} - {decl.median_max_net:,} net/мес".replace(",", " ")
        )
    if len(lines) == 1:
        return "(данных в этом сегменте пока мало — не выдумывать цифры рынка)"
    return "\n".join(lines)


def _format_leverage(leverage: dict[str, int]) -> str:
    tech = leverage.get("Техничка", 0)
    final = leverage.get("Финал", 0)
    offer = leverage.get("Оффер", 0)
    parts = [
        f"На Техничке сейчас: {tech}",
        f"На Финале сейчас: {final}",
        f"Активных офферов кроме этого: {offer}",
    ]
    return ", ".join(parts)


# L-11: статичный prefix (роль/стиль/формат) кэшируется; факты оффера — dynamic_tail.
_SYSTEM_STATIC_TEMPLATE = """Ты - переговорщик, помогаешь кандидату ({identity}) вести торг по офферу.
Кандидат хочет улучшить условия перед ответом на оффер.

## Стиль черновика ответа HR (живой человек, не ИИ)

{style_block}

## Задача

1. Дай 3-5 аргументов для торга. Каждый аргумент - конкретный факт (число, сравнение,
   состояние воронки) + готовая формулировка, как произнести это HR. Опирайся ТОЛЬКО на цифры
   из блоков контекста - если бенчмарк или сравнение офферов недоступны, не выдумывай их, используй
   то, что реально есть (например только leverage воронки).
2. Дай ОДИН черновик сообщения HR, который сводит эти аргументы в связный текст с конкретной
   просьбой (какое условие подвинуть - база/бонус/sign-on/старт).
3. НЕ советуй принять или отклонить оффер целиком - только аргументы и формулировки для торга.
   Решение принимает кандидат сам.

## Формат вывода

Верни СТРОГО валидный JSON, без markdown, без текста до/после:
{{
  "arguments": [
    {{"fact": "...", "wording": "..."}}, ...
  ],
  "draft_message": "..."
}}
"""

_DYNAMIC_TEMPLATE = """## Оффер, по которому торгуемся

Компания: {company}
Позиция: {title}

{offer_block}

## Рыночный бенчмарк по грейду (свой корпус наблюдений, не выдумка)

{benchmark_block}

## Другие активные офферы кандидата (leverage «есть альтернативы»)

{others_block}

## Состояние воронки (leverage «есть куда идти помимо этого оффера»)

{leverage_block}

## Целевая вилка кандидата

От {salary_line}.
"""


async def _build_system_parts(
    *,
    account_id: int,
    offer: OfferRecord,
    others: list[OfferRecord],
    benchmark: SalaryBenchmarkSegment | None,
    leverage: dict[str, int],
    salary_line: str,
) -> tuple[str, str]:
    from core.domains.opportunities.prompt import load_candidate_identity, load_candidate_min_salary
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    fallback_salary = f"{load_candidate_min_salary(data=resume_data):,} ₽".replace(",", " ")
    static = _SYSTEM_STATIC_TEMPLATE.format(
        identity=load_candidate_identity(data=resume_data),
        style_block=HR_STYLE_BLOCK,
    )
    dynamic = _DYNAMIC_TEMPLATE.format(
        title=offer.position or "без названия",
        company=offer.company or "компания не указана",
        offer_block=_format_target_offer(offer),
        benchmark_block=_format_benchmark(benchmark),
        others_block=_format_other_offers(others),
        leverage_block=_format_leverage(leverage),
        salary_line=salary_line or fallback_salary,
    )
    return static, dynamic


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_response(raw: str) -> dict[str, Any]:
    text = _strip_fences(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise LlmError(f"Negotiation: невалидный JSON ({exc})") from exc
        data = json.loads(match.group())
    if not isinstance(data, dict):
        raise LlmError("Negotiation: корень ответа должен быть объектом")
    return data


def _parse_arguments(items: Any) -> list[NegotiationArgument]:
    if not isinstance(items, list):
        return []
    out: list[NegotiationArgument] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact") or "").strip()
        wording = str(item.get("wording") or "").strip()
        if not fact or not wording:
            continue
        out.append(NegotiationArgument(fact=fact[:500], wording=wording[:800]))
        if len(out) >= 5:
            break
    return out


async def negotiate_offer(
    offer: OfferRecord,
    *,
    account_id: int,
    other_offers: list[OfferRecord] | None = None,
    benchmark: SalaryBenchmarkSegment | None = None,
    leverage: dict[str, int] | None = None,
    salary_line: str = "",
) -> NegotiationBrief:
    """Собрать аргументы для торга по одному офферу через LLM. Резюме — аккаунта запроса."""
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    system, dynamic_tail = await _build_system_parts(
        account_id=account_id,
        offer=offer,
        others=other_offers or [],
        benchmark=benchmark,
        leverage=leverage or {},
        salary_line=salary_line,
    )
    raw = await ports.llm().complete(
        "offer_negotiation",
        system=system,
        dynamic_tail=dynamic_tail,
        user="Собери аргументы и черновик. ТОЛЬКО JSON.",
        temperature=0.3,
    )
    parsed = _parse_response(raw)
    arguments = _parse_arguments(parsed.get("arguments"))
    draft_message = str(parsed.get("draft_message") or "").strip()[:4000]
    event(
        logger,
        "LLM",
        "offer_negotiation: аргументов=%d, черновик=%d симв.",
        len(arguments),
        len(draft_message),
        vacancy_id=offer.vacancy_id,
        arguments=len(arguments),
        draft_chars=len(draft_message),
    )
    return NegotiationBrief(
        arguments=arguments,
        draft_message=draft_message,
        generated_at=datetime.now(UTC),
    )


__all__ = ["negotiate_offer"]
