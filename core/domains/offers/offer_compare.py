"""LLM-сравнение нескольких офферов под приоритеты кандидата (порт из backend, S8).

Транспорт — порт `kernel.ports.llm().complete`; резюме/инструкции — из `core.domains.opportunities.prompt`; схемы —
`core.domains.offers.models`. Без БД: чистый LLM + парсинг. Ошибки LLM — core `LlmError`.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from core.app.pipeline import Pipeline, PipelineError, Step
from core.config import get_settings
from core.domains.offers.models import (
    OfferComparison,
    OfferProsCons,
    OfferRanking,
    OfferRecord,
    OfferSensitivity,
)
from core.domains.opportunities.prompt import (
    load_candidate_identity,
    load_instructions,
    load_resume,
)
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.ids import VacancyId
from core.platform.observability import event

logger = logging.getLogger(__name__)


async def _build_system_prompt(*, account_id: int) -> str:
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    instructions = load_instructions()
    resume = load_resume(data=resume_data)
    identity = load_candidate_identity(data=resume_data)
    return f"""Ты — карьерный коуч и переговорщик. Кандидат — {identity}, имеет несколько
офферов и должен выбрать один. Твоя задача — ранжировать офферы под приоритеты кандидата,
дать pros/cons по каждому и sensitivity-анализ (что изменилось бы при изменении условий).

## Резюме кандидата

{resume}

## Стратегические приоритеты кандидата (веса важности)

{instructions}

## Правила вывода

1. Верни СТРОГО валидный JSON по схеме:
   {{
     "rankings": [
       {{
         "rank": 1,
         "vacancy_id": "...",
         "summary": "1-2 предложения почему этот оффер на этом месте",
         "pros": ["..."],
         "cons": ["..."]
       }}, ...
     ],
     "sensitivity": [
       {{
         "scenario": "если оффер X добавит +50k к окладу",
         "impact": "тогда он обходит оффер Y из-за weight=...",
         "affected_vacancy_id": "..."
       }}, ...
     ],
     "recommendation": "финальный совет: какой оффер брать, какие пункты дожимать в переговорах",
     "favorable_fields": {{
       "vacancy_id_1": ["base_salary", "bonus_monthly_equiv"],
       "vacancy_id_2": ["vacation_days"]
     }}
   }}
2. rank — 1 = лучший, без пропусков и дубликатов.
3. Никакого markdown, никакого текста до/после JSON.
4. pros/cons — конкретно под этого кандидата: «удалёнка для семьи в РФ», «грейд совпадает с целевым
   из резюме», «команда 8 человек, риск burn-out низкий». Не общие «хороший коллектив».
5. sensitivity — 2-4 сценария по реально дожимаемым переговорным позициям (оклад, бонус,
   удалёнка, релокация, equity).
6. recommendation — прямо: «бери X, дожми Y», или «возьми A под условием B, иначе переговори
   с C об удалёнке».
7. Числа сравнивай аккуратно: годовая ЗП = base_salary × 12 если period=month.
8. favorable_fields — ключ: vacancy_id оффера, значение: список ключей полей, где ИМЕННО ЭТОТ
   оффер объективно лучше остальных. Допустимые ключи (ровно эти строки, другие не использовать):
   "base_salary", "annual_bonus_pct", "quarterly_bonus_pct", "bonus_monthly_equiv",
   "signon", "equity", "vacation_days", "work_format", "location", "deadline".
   Клади поле только если оффер реально выигрывает по нему (не «нейтрально»,
   не «все поля подряд») — максимум 2-3 поля на оффер. Если ни одно поле не выделяется — не включай
   этот vacancy_id в объект вовсе.
"""


def _format_offer_block(offer: OfferRecord, idx: int) -> str:
    parts = [f"### Оффер #{idx} — vacancy_id={offer.vacancy_id}"]
    if offer.company:
        parts.append(f"Компания: {offer.company}")
    if offer.position:
        parts.append(f"Позиция: {offer.position}")
    if offer.base_salary is not None:
        period_label = "/мес" if offer.base_salary_period == "month" else "/год"
        parts.append(f"База: {offer.base_salary:,} {offer.base_salary_currency}{period_label}")
    if offer.bonus:
        parts.append(f"KPI, детали: {offer.bonus}")
    if offer.annual_bonus_pct:
        parts.append(f"Годовая премия: {offer.annual_bonus_pct}% от года")
    if offer.quarterly_bonus_pct:
        parts.append(f"Квартальная премия: {offer.quarterly_bonus_pct}% от квартала")
    if offer.bonus_amount is not None:
        parts.append(f"Размер бонуса: {offer.bonus_amount:,}")
    if offer.equity:
        parts.append(f"Акции: {offer.equity}")
    if offer.signon is not None:
        parts.append(f"Sign-on: {offer.signon:,}")
    if offer.vacation_days is not None:
        parts.append(f"Отпуск: {offer.vacation_days} дн.")
    if offer.notice_period:
        parts.append(f"Нотис: {offer.notice_period}")
    if offer.start_date:
        parts.append(f"Старт: {offer.start_date.strftime('%Y-%m-%d')}")
    if offer.deadline:
        parts.append(f"Дедлайн ответа: {offer.deadline.strftime('%Y-%m-%d %H:%M')}")
    if offer.work_format != "unknown":
        parts.append(f"Формат: {offer.work_format}")
    if offer.location:
        parts.append(f"Локация: {offer.location}")
    if offer.relocation_package:
        parts.append(f"Релокация: {offer.relocation_package}")
    if offer.notes:
        parts.append(f"Заметки: {offer.notes}")
    return "\n".join(parts)


def _build_user_prompt(offers: list[OfferRecord]) -> str:
    blocks = [_format_offer_block(o, i + 1) for i, o in enumerate(offers)]
    return (
        "## Офферы для сравнения\n\n"
        + "\n\n".join(blocks)
        + "\n\nРанжируй и проанализируй. ТОЛЬКО JSON."
    )


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
            raise LlmError(f"Comparison: невалидный JSON ({exc})") from exc
        data = json.loads(match.group())
    if not isinstance(data, dict):
        raise LlmError("Comparison: корень ответа должен быть объектом")
    return data


def _parse_rankings(items: Any, offers: list[OfferRecord]) -> list[OfferRanking]:
    if not isinstance(items, list):
        return []
    by_vid = {o.vacancy_id: o for o in offers}
    out: list[OfferRanking] = []
    seen_ranks: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        vid = VacancyId(str(item.get("vacancy_id") or "").strip())
        if not vid or vid not in by_vid:
            continue
        try:
            rank = int(item.get("rank") or len(out) + 1)
        except (TypeError, ValueError):
            rank = len(out) + 1
        if rank in seen_ranks:
            rank = max(seen_ranks) + 1
        seen_ranks.add(rank)
        pros = [str(x).strip()[:500] for x in (item.get("pros") or []) if str(x).strip()]
        cons = [str(x).strip()[:500] for x in (item.get("cons") or []) if str(x).strip()]
        out.append(
            OfferRanking(
                rank=rank,
                vacancy_id=vid,
                company=by_vid[vid].company,
                position=by_vid[vid].position,
                summary=str(item.get("summary") or "").strip()[:1500],
                pros_cons=OfferProsCons(pros=pros[:10], cons=cons[:10]),
            )
        )
    out.sort(key=lambda r: r.rank)
    return out


_FAVORABLE_FIELD_KEYS = {
    "base_salary",
    "annual_bonus_pct",
    "quarterly_bonus_pct",
    "bonus_amount",
    "bonus_monthly_equiv",
    "signon",
    "equity",
    "vacation_days",
    "work_format",
    "location",
    "deadline",
}


def _parse_favorable_fields(raw: Any, offers: list[OfferRecord]) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    by_vid = {o.vacancy_id for o in offers}
    out: dict[str, list[str]] = {}
    for vid, keys in raw.items():
        vid = str(vid).strip()
        if vid not in by_vid or not isinstance(keys, list):
            continue
        fields = [str(k).strip() for k in keys if str(k).strip() in _FAVORABLE_FIELD_KEYS]
        if fields:
            out[vid] = fields[:3]
    return out


def _parse_sensitivity(items: Any) -> list[OfferSensitivity]:
    if not isinstance(items, list):
        return []
    out: list[OfferSensitivity] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        scenario = str(item.get("scenario") or "").strip()
        impact = str(item.get("impact") or "").strip()
        if not scenario or not impact:
            continue
        out.append(
            OfferSensitivity(
                scenario=scenario[:500],
                impact=impact[:1000],
                affected_vacancy_id=str(item.get("affected_vacancy_id") or "").strip(),
            )
        )
        if len(out) >= 6:
            break
    return out


def render_markdown(offers: list[OfferRecord], comparison: OfferComparison) -> str:
    """Markdown-форма сравнения для Telegram/файла."""
    lines = [
        "# Сравнение офферов",
        f"_Сгенерировано: {comparison.compared_at.strftime('%Y-%m-%d %H:%M')}_",
        "",
    ]
    for r in comparison.rankings:
        lines.append(f"## #{r.rank}. {r.company or '?'} — {r.position or '?'}")
        lines.append(f"`vacancy_id: {r.vacancy_id}`")
        if r.summary:
            lines.append("")
            lines.append(r.summary)
        if r.pros_cons.pros:
            lines.append("")
            lines.append("**Плюсы:**")
            for p in r.pros_cons.pros:
                lines.append(f"- {p}")
        if r.pros_cons.cons:
            lines.append("")
            lines.append("**Минусы:**")
            for c in r.pros_cons.cons:
                lines.append(f"- {c}")
        lines.append("")
    if comparison.sensitivity:
        lines.append("## Sensitivity-анализ")
        lines.append("")
        for s in comparison.sensitivity:
            target = f" → `{s.affected_vacancy_id}`" if s.affected_vacancy_id else ""
            lines.append(f"- **{s.scenario}**{target}: {s.impact}")
        lines.append("")
    if comparison.recommendation:
        lines.append("## Рекомендация")
        lines.append("")
        lines.append(comparison.recommendation)
    return "\n".join(lines).strip()


# L-49: Pipeline-сплит compare_offers — сравнительные факты (rankings/favorable_fields)
# параллельно прескриптивному выводу (sensitivity/recommendation), общий system/user, разный
# фокус-хвост (тот же приём, что `_DIAGNOSIS_FOCUS`/`_ACTIONS_FOCUS` в core.domains.market.situation
# и `_ANSWER_FOCUS`/`_ASK_THEM_FOCUS` в prep.py). Оба вызова — обычный complete() (не structured()),
# как и раньше — offer_compare не пробовал structured() и не имеет своего DBR-7-инцидента, но менять
# способ парсинга не в объёме этой задачи.
_RANKINGS_FOCUS = """

ЭТОТ ВЫЗОВ — только сравнительные факты. Верни ТОЛЬКО поля "rankings" и "favorable_fields".
Про "sensitivity"/"recommendation" не думай - их считает отдельный параллельный вызов по тем же
офферам."""

_VERDICT_FOCUS = """

ЭТОТ ВЫЗОВ — только вывод. Верни ТОЛЬКО поля "sensitivity" и "recommendation".
Про "rankings"/"favorable_fields" не думай - их считает отдельный параллельный вызов по тем же
офферам."""


def _compare_pipeline(system: str, user: str) -> Pipeline:
    """DAG сравнения офферов: rankings ∥ verdict — два меньших вызова по одним данным."""

    async def _call(focus: str) -> dict[str, Any]:
        raw = await ports.llm().complete(
            "offer_compare",
            system=system,
            dynamic_tail=focus,
            user=user,
            temperature=0.3,
        )
        return _parse_response(raw)

    async def rankings_step(_ctx: Any) -> dict[str, Any]:
        return await _call(_RANKINGS_FOCUS)

    async def verdict_step(_ctx: Any) -> dict[str, Any]:
        return await _call(_VERDICT_FOCUS)

    return Pipeline(
        [
            Step("rankings", rankings_step, required=True),
            Step("verdict", verdict_step, required=False, default_factory=dict),
        ],
        name="offer_compare",
    )


def _assemble_comparison(
    offers: list[OfferRecord], rankings_data: dict[str, Any], verdict_data: dict[str, Any]
) -> OfferComparison:
    comparison = OfferComparison(
        rankings=_parse_rankings(rankings_data.get("rankings"), offers),
        sensitivity=_parse_sensitivity(verdict_data.get("sensitivity")),
        recommendation=str(verdict_data.get("recommendation") or "").strip()[:4000],
        favorable_fields=_parse_favorable_fields(rankings_data.get("favorable_fields"), offers),
        compared_at=datetime.now(UTC),
    )
    comparison.markdown = render_markdown(offers, comparison)
    return comparison


def _validate_offers(offers: list[OfferRecord]) -> list[OfferRecord]:
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    if len(offers) < 2:
        raise ValueError("Для сравнения нужно минимум 2 оффера")
    return offers[:6] if len(offers) > 6 else offers


async def compare_offers(offers: list[OfferRecord], *, account_id: int) -> OfferComparison:
    """Сравнить ≥2 офферов через LLM. Поднимает ValueError / LlmError при сбоях."""
    offers = _validate_offers(offers)
    system = await _build_system_prompt(account_id=account_id)
    user = _build_user_prompt(offers)

    try:
        parts = await _compare_pipeline(system, user).run()
    except PipelineError as exc:
        if isinstance(exc.cause, LlmError):
            raise exc.cause from exc
        raise LlmError(f"Comparison: {exc.cause or exc}") from exc

    comparison = _assemble_comparison(
        offers, parts.get("rankings") or {}, parts.get("verdict") or {}
    )
    verdict_degraded = not parts.get("verdict")
    event(
        logger,
        "LLM",
        "offer_compare: сравнено %d офферов, sensitivity=%d, verdict_degraded=%s",
        len(offers),
        len(comparison.sensitivity),
        verdict_degraded,
        offers=len(offers),
        rankings=len(comparison.rankings),
        sensitivity=len(comparison.sensitivity),
        verdict_degraded=verdict_degraded,
        level=logging.WARNING if verdict_degraded else logging.INFO,
    )
    return comparison


async def compare_offers_events(
    offers: list[OfferRecord], *, account_id: int
) -> AsyncIterator[dict[str, Any]]:
    """Тот же расчёт, но части (`rankings`/`verdict`) отдаются по мере готовности."""
    offers = _validate_offers(offers)
    system = await _build_system_prompt(account_id=account_id)
    user = _build_user_prompt(offers)

    rankings_data: dict[str, Any] = {}
    verdict_data: dict[str, Any] = {}

    async for pipeline_event in _compare_pipeline(system, user).stream():
        if pipeline_event.type == "step_start":
            yield {
                "type": "status",
                "stage": pipeline_event.step,
                "label": "Ранжирую офферы"
                if pipeline_event.step == "rankings"
                else "Считаю сценарии",
            }
        elif pipeline_event.type == "step_done" and pipeline_event.step == "rankings":
            rankings_data = pipeline_event.data or {}
            yield {
                "type": "rankings",
                "rankings": [
                    r.model_dump(mode="json")
                    for r in _parse_rankings(rankings_data.get("rankings"), offers)
                ],
                "favorable_fields": _parse_favorable_fields(
                    rankings_data.get("favorable_fields"), offers
                ),
            }
        elif pipeline_event.type == "step_done" and pipeline_event.step == "verdict":
            verdict_data = pipeline_event.data or {}
            yield {
                "type": "verdict",
                "sensitivity": [
                    s.model_dump(mode="json")
                    for s in _parse_sensitivity(verdict_data.get("sensitivity"))
                ],
                "recommendation": str(verdict_data.get("recommendation") or "").strip()[:4000],
            }
        elif pipeline_event.type == "error" and pipeline_event.step == "rankings":
            if isinstance(pipeline_event.cause, LlmError):
                raise pipeline_event.cause
            raise LlmError(
                f"Comparison: {pipeline_event.cause or pipeline_event.message}"
            ) from pipeline_event.cause
        elif pipeline_event.type == "error" and pipeline_event.step == "verdict":
            yield {
                "type": "part_error",
                "stage": "verdict",
                "message": pipeline_event.message,
            }
        elif pipeline_event.type == "done":
            comparison = _assemble_comparison(offers, rankings_data, verdict_data)
            yield {"type": "done", "comparison": comparison}


__all__ = ["compare_offers", "compare_offers_events", "render_markdown"]
