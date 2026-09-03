"""Оффер: парсинг письма HR, сравнение, торг.

Кросс-доменный сценарий: сам оффер — `offers`, компания/позиция и leverage воронки —
`opportunities`, бенчмарк вилки — `market`, зарплатная строка кандидата — `profile`. Раньше эта
склейка жила в `api/routers/offers/offers.py`.

Ошибки LLM здесь превращаются в `UpstreamError` (502) — так исторически отвечали ручки офферов,
в отличие от подготовки, где сбой модели читается как «сервис временно недоступен» (503).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.domains.assistant.attachments.models import AttachmentMeta
from core.domains.offers.bonus import needs_monthly_bonus_estimate, offer_bonus_types
from core.domains.offers.models import NegotiationBrief, OfferComparison, OfferRecord
from core.domains.offers.offers_chat import OffersChatMessage, load_offers_chat
from core.domains.offers.store import (
    Offer,
    load_active_offers,
    load_all_offers,
    load_offer,
    load_offer_comparison_cache,
    load_offers_by_ids,
    save_offer_comparison_cache,
    save_offer_negotiation,
    upsert_offer,
)
from core.kernel.errors import InvalidInput, LlmError, NotFound, UpstreamError

logger = logging.getLogger(__name__)

NOT_FOUND = "Оффер не найден"

#: Статусы офферов, которые считаются «на руках» и работают как рычаг в торге.
_LEVERAGE_STAGES = ["Техничка", "Финал", "Оффер"]


class ComparisonResult(BaseModel):
    """Итог сравнения: набор офферов + вердикт LLM (или причина, почему сравнивать нечего)."""

    offers: list[OfferRecord] = []
    comparison: OfferComparison | None = None
    detail: str = ""


class NegotiationResult(BaseModel):
    """Итог торга: обновлённый оффер + сохранённый бриф аргументов."""

    offer: OfferRecord
    negotiation: NegotiationBrief


def to_record(offer: Offer) -> OfferRecord:
    return OfferRecord.model_validate(offer.model_dump())


async def load_offers_chat_view(
    *, account_id: int
) -> tuple[list[OffersChatMessage], dict[int, list[AttachmentMeta]]]:
    """История чата вкладки «Офферы» + вложения. Нет PG → пустая лента, вкладка не падает."""
    from core.domains.assistant.attachments.service import load_for_offers_chat_messages

    try:
        messages = await load_offers_chat(account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG / нет таблицы → пустой чат
        logger.debug("offers chat: история недоступна: %s", exc)
        return [], {}
    message_ids = [m.id for m in messages if m.id is not None]
    try:
        attachments = await load_for_offers_chat_messages(message_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — вложения вторичны к ленте
        logger.debug("offers chat: вложения недоступны: %s", exc)
        attachments = {}
    return messages, attachments


async def parse_and_store(
    vacancy_id: str, text: str, *, account_id: int, overwrite: bool = False
) -> OfferRecord:
    """Извлечь структуру оффера из письма HR и сохранить (merge или overwrite).

    Компанию и позицию подсказываем из `jobs` — письмо HR часто не повторяет очевидное.
    """
    from core.domains.offers.offer_parser import parse_offer_text

    company, position = await _job_hints(vacancy_id, account_id=account_id)
    try:
        parsed = await parse_offer_text(
            text,
            vacancy_id=vacancy_id,
            fallback_company=company,
            fallback_position=position,
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    except LlmError as exc:
        logger.error("Offer parse OpenRouter: %s", exc)
        raise UpstreamError(str(exc)) from exc

    saved = await upsert_offer(
        Offer.model_validate(parsed.model_dump()), account_id=account_id, merge=not overwrite
    )
    return to_record(saved)


async def compare(
    *,
    account_id: int,
    vacancy_ids: list[str] | None = None,
    max_age_days: int | None = None,
    save_to_disk: bool = False,
) -> ComparisonResult:
    """Сравнить активные офферы под приоритеты кандидата (LLM, с кэшом по слепку набора)."""
    from core.domains.offers.offer_compare import compare_offers, render_markdown

    offers = (
        await load_offers_by_ids(vacancy_ids, account_id=account_id)
        if vacancy_ids
        else await load_active_offers(max_age_days=max_age_days or 30, account_id=account_id)
    )
    if not offers:
        return ComparisonResult(detail="Нет активных офферов")
    records = [to_record(o) for o in offers]
    if len(records) == 1:
        return ComparisonResult(offers=records, detail="Только один оффер — сравнивать не с чем")

    source_hash = _comparison_hash(records)
    comparison = await load_offer_comparison_cache(source_hash, account_id=account_id)
    if comparison is None:
        try:
            comparison = await compare_offers(records, account_id=account_id)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        except LlmError as exc:
            logger.error("Offers compare OpenRouter: %s", exc)
            raise UpstreamError(str(exc)) from exc
        await save_offer_comparison_cache(source_hash, comparison, account_id=account_id)

    if save_to_disk:
        md = comparison.markdown or render_markdown(records, comparison)
        await asyncio.to_thread(_dump_markdown, md)
    return ComparisonResult(offers=records, comparison=comparison)


async def compare_events(
    *,
    account_id: int,
    vacancy_ids: list[str] | None = None,
    max_age_days: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Поток сравнения офферов: `rankings`/`verdict` по мере готовности.

    Ошибку не поднимаем наружу — SSE-соединение уже открыто, клиент ждёт кадр: последним уходит
    `{"type": "error"}` (транспорт A-14 кодирует в `event: error`).
    """
    from core.domains.offers.offer_compare import compare_offers_events

    try:
        offers = (
            await load_offers_by_ids(vacancy_ids, account_id=account_id)
            if vacancy_ids
            else await load_active_offers(max_age_days=max_age_days or 30, account_id=account_id)
        )
        if not offers:
            yield {"type": "done", "result": ComparisonResult(detail="Нет активных офферов")}
            return
        records = [to_record(o) for o in offers]
        if len(records) == 1:
            yield {
                "type": "done",
                "result": ComparisonResult(
                    offers=records, detail="Только один оффер — сравнивать не с чем"
                ),
            }
            return

        source_hash = _comparison_hash(records)
        cached = await load_offer_comparison_cache(source_hash, account_id=account_id)
        if cached is not None:
            yield {"type": "done", "result": ComparisonResult(offers=records, comparison=cached)}
            return

        async for event in compare_offers_events(records, account_id=account_id):
            etype = event.get("type")
            if etype in ("status", "rankings", "verdict", "part_error"):
                yield event
            elif etype == "done":
                comparison = event["comparison"]
                await save_offer_comparison_cache(source_hash, comparison, account_id=account_id)
                yield {
                    "type": "done",
                    "result": ComparisonResult(offers=records, comparison=comparison),
                }
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
    except LlmError as exc:
        logger.error("Offers compare OpenRouter: %s", exc)
        yield {"type": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 — SSE-соединение уже открыто, клиент ждёт кадр
        logger.exception("Offers compare stream error: %s", exc)
        yield {"type": "error", "detail": "Не удалось сравнить офферы"}


async def negotiate(vacancy_id: str, *, account_id: int) -> NegotiationResult:
    """Аргументы для торга: бенчмарк рынка + другие офферы на руках + leverage воронки.

    Результат персистится на офере — вкладка перечитывает его без нового вызова модели
    (cost-гард: LLM дёргается только явной кнопкой «Торг»).
    """
    from core.domains.offers.offer_negotiation import negotiate_offer

    offer = await load_offer(vacancy_id, account_id=account_id)
    if offer is None:
        raise NotFound(NOT_FOUND)

    others = [
        to_record(o)
        for o in await load_all_offers(limit=100, account_id=account_id)
        if o.vacancy_id != vacancy_id and o.status in ("thinking", "accepted")
    ]
    try:
        brief = await negotiate_offer(
            to_record(offer),
            account_id=account_id,
            other_offers=others,
            benchmark=await _benchmark_segment(account_id=account_id),
            leverage=await _leverage(vacancy_id, account_id=account_id),
            salary_line=await _salary_line(account_id),
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    except LlmError as exc:
        logger.error("Offer negotiate OpenRouter: %s", exc)
        raise UpstreamError(str(exc)) from exc

    saved = await save_offer_negotiation(
        vacancy_id, brief.model_dump(mode="json"), account_id=account_id
    )
    if saved is None:
        raise NotFound(NOT_FOUND)
    return NegotiationResult(offer=to_record(saved), negotiation=brief)


async def feed_offer_corpus(vacancy_id: str, *, account_id: int) -> None:
    """Best-effort: сумма сохранённого оффера → корпус калибровки (source='funnel').

    company_type/grade берём из стора скоринга вакансии; нет PG/оффера/суммы → молча выходим.
    Дедуп по content_hash в `insert_funnel_sample` не даёт повторным правкам плодить дубли.
    """
    try:
        from core.domains.opportunities.jobs import get_job_by_vacancy_id
        from core.domains.opportunities.salary_corpus import feed_offer_sample

        offer = await load_offer(vacancy_id, account_id=account_id)
        if offer is None or not offer.base_salary:
            return
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
        score = job.score if job else {}
        company_type = (score.get("company_type") or "unknown") if score else "unknown"
        grade = (score.get("grade_match") or {}).get("level") or "senior_plus"
        await feed_offer_sample(offer, company_type, grade, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — кормление корпуса не критично для сохранения оффера
        logger.debug("Оффер в корпус калибровки не записан (best-effort): %s", exc)


async def recompute_bonus_estimate(
    vacancy_id: str, *, account_id: int, allow_llm: bool = True
) -> Offer | None:
    """Пересчёт `bonus_monthly_equiv`. Детерминированный путь — в том же запросе (шапка «₽/год»
    и PATCH-ответ не должны ждать фон). LLM (KPI) — по-прежнему best-effort.

    Хэш входов не даёт дёргать LLM на каждый patch оффера (правка ячейки матрицы — частая).
    """
    try:
        from core.domains.offers.offer_bonus_estimate import (
            deterministic_bonus_monthly_equiv,
            estimate_bonus_monthly_equiv,
        )
        from core.domains.offers.store import save_offer_bonus_estimate

        offer = await load_offer(vacancy_id, account_id=account_id)
        if offer is None:
            return None
        types = offer_bonus_types(offer.bonus_types, offer.bonus_type)
        new_hash = _bonus_hash(offer)
        if new_hash == offer.bonus_monthly_equiv_source_hash:
            return offer
        if not needs_monthly_bonus_estimate(types):
            return await save_offer_bonus_estimate(
                vacancy_id, None, new_hash, account_id=account_id
            )
        record = to_record(offer)
        value = deterministic_bonus_monthly_equiv(record)
        if value is None:
            if not allow_llm:
                return offer
            value = await estimate_bonus_monthly_equiv(record)
        return await save_offer_bonus_estimate(vacancy_id, value, new_hash, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — оценка премии не критична для сохранения оффера
        logger.debug("Оффер: премия не пересчитана (best-effort): %s", exc)
        return None


# --------------------------------------------------------------------------- внутреннее


async def _job_hints(vacancy_id: str, *, account_id: int) -> tuple[str, str]:
    from core.domains.opportunities.jobs import get_job_by_vacancy_id

    try:
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG/вакансии → парсим без подсказок
        logger.debug("Offer parse: fallback из jobs недоступен: %s", exc)
        return "", ""
    return (job.company or "", job.title or "") if job is not None else ("", "")


async def _benchmark_segment(*, account_id: int):
    """Сегмент бенчмарка под грейд/стек кандидата; нет точного — берём по грейду."""
    from core.domains.market.salary_benchmark import get_salary_benchmark_report

    report = await get_salary_benchmark_report(account_id=account_id)
    return next(
        (s for s in report.segments if s.grade == "senior_plus" and s.stack == "llm"), None
    ) or next((s for s in report.segments if s.grade == "senior_plus"), None)


async def _leverage(vacancy_id: str, *, account_id: int) -> dict[str, int]:
    from core.domains.opportunities.jobs import count_jobs_by_status

    return await count_jobs_by_status(
        _LEVERAGE_STAGES, exclude_vacancy_id=vacancy_id, account_id=account_id
    )


async def _salary_line(account_id: int) -> str:
    try:
        from core.domains.profile.model import _salary_range_md
        from core.domains.profile.structured_store import read_resume_data_for_account

        resume = await read_resume_data_for_account(account_id)
        return _salary_range_md(resume.position)
    except Exception as exc:  # noqa: BLE001 — нет резюме/PG → дефолт из шаблона промпта
        logger.debug("Offer negotiate: зарплатная вилка недоступна: %s", exc)
        return ""


def _bonus_hash(offer: Offer) -> str:
    types = ",".join(offer_bonus_types(offer.bonus_types, offer.bonus_type))
    raw = (
        f"{types}|{offer.bonus}|{offer.bonus_amount}|{offer.base_salary}|"
        f"{offer.base_salary_period}|{offer.annual_bonus_pct}|{offer.quarterly_bonus_pct}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _comparison_hash(records: list[OfferRecord]) -> str:
    """Слепок состава+состояния набора: «изменилось ли что-то с прошлого сравнения».

    `updated_at` освежается на каждый upsert, поэтому кэш инвалидируется и при смене состава,
    и при правке любого поля любого оффера.
    """
    parts = sorted(f"{r.vacancy_id}:{r.updated_at.isoformat()}" for r in records)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _dump_markdown(markdown: str) -> None:
    try:
        out_dir = Path.cwd() / "plans"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"offers_compare_{datetime.now(tz=UTC).strftime('%Y-%m-%d')}.md"
        path.write_text(markdown, encoding="utf-8")
        logger.info("Offers compare сохранён: %s", path)
    except Exception as exc:  # noqa: BLE001 — сохранение на диск не критично
        logger.warning("Offers compare: не сохранил md: %s", exc)


__all__ = [
    "ComparisonResult",
    "NegotiationResult",
    "compare",
    "compare_events",
    "feed_offer_corpus",
    "load_offers_chat_view",
    "negotiate",
    "parse_and_store",
    "recompute_bonus_estimate",
    "to_record",
]
