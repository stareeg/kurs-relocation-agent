"""Инструмент `hh_discovery`: когда-то ходил на hh.ru с сервера.

Серверный обход выдачи выключен (Шаг 5): `discover_from_search_url` сети не делает.
Живой просмотр — расширение (`discovery-runner.ts`); этот модуль остаётся для тестов
пайплайна (подмена fetch) и явного отказа, если кто-то ещё зовёт `hh_discovery`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from pydantic import BaseModel

from core.domains.opportunities.sources.hh import discover_from_search_url

logger = logging.getLogger(__name__)

# Ранг рекомендаций для порога min_recommendation ().
REC_RANK = {"strong_apply": 3, "apply": 2, "maybe": 1, "skip": 0}


def recommendation_meets_min(rec: str, min_rec: str) -> bool:
    """True, если рекомендация не ниже порога (apply >= apply, strong_apply >= apply, ...)."""
    return REC_RANK.get(rec, 0) >= REC_RANK.get(min_rec, 0)


class DiscoveredVacancy(BaseModel):
    vacancy_id: str
    title: str | None = None
    company: str | None = None
    url: str | None = None
    text: str = ""


async def hh_discovery(
    search_url: str,
    *,
    max_pages: int = 1,
    limit: int | None = 10,
    fetch_full_description: bool = False,
) -> list[DiscoveredVacancy]:
    """Найти вакансии по search-URL hh.ru (read-only). Возвращает заголовки + текст для скоринга."""
    vacancies, _pages = await discover_from_search_url(
        search_url,
        max_pages=max_pages,
        limit=limit,
        fetch_full_description=fetch_full_description,
    )
    return [
        DiscoveredVacancy(
            vacancy_id=d.vacancy_id,
            title=d.title or None,
            company=d.company or None,
            url=d.url,
            text=d.build_text(),
        )
        for d in vacancies
    ]


async def run_batch_discovery_stream(
    search_url: str,
    *,
    max_pages: int = 1,
    limit: int | None = 10,
    min_recommendation: str = "apply",
    skip_existing: bool = True,
    fetch_full_description: bool = False,
    page_delay_sec: float = 1.0,
    score_delay_sec: float = 0.5,
    account_id: int,
) -> AsyncIterator[dict]:
    """Стрим batch-discovery по search-URL hh.ru.

    Конвейер на чистом core: fetch SERP (`discover_from_search_url`) → пропуск уже известных
    (`get_job_by_vacancy_id` / `is_skipped`) → score+persist (`score_and_persist` = `score_vacancy`
    + `persist_scored`). Postgres — источник истины (persist пишет jobs/stage/skipped).
    События (поле `event`):
        started | fetched | scored | skipped | error | done.

    Тяжёлый персист импортируется лениво — `hh_discovery` остаётся дешёвым на импорт.
    """
    import asyncio

    from core.domains.opportunities.jobs import backfill_total_responses, get_job_by_vacancy_id
    from core.domains.opportunities.models import VacancyInput
    from core.domains.opportunities.persist import score_and_persist
    from core.domains.opportunities.skipped import is_skipped

    min_rec = "skip" if min_recommendation == "all" else min_recommendation
    counts = {"discovered": 0, "scored": 0, "skipped": 0, "errors": 0, "matches": 0}

    yield {"event": "started", "search_url": search_url, "max_pages": max_pages, "limit": limit}

    try:
        vacancies, pages = await discover_from_search_url(
            search_url,
            max_pages=max_pages,
            limit=limit,
            fetch_full_description=fetch_full_description,
            page_delay_sec=page_delay_sec,
        )
    except Exception as exc:  # noqa: BLE001 — сбой SERP отдаём событием, не исключением
        yield {"event": "error", "where": "fetch", "error": str(exc)[:200]}
        return

    counts["discovered"] = len(vacancies)
    total = len(vacancies)
    yield {"event": "fetched", "pages": pages, "discovered": total}

    for index, disc in enumerate(vacancies, 1):
        if skip_existing and disc.vacancy_id:
            try:
                existing_job = await get_job_by_vacancy_id(disc.vacancy_id, account_id=account_id)
                exists = existing_job is not None
                if not exists:
                    exists = await is_skipped(disc.vacancy_id, account_id=account_id)
                elif disc.total_responses is not None:
                    # Этап 6 §6.1: расширение больше не может достать счётчик откликов со
                    # страницы вакансии (hh перестал его туда отдавать) — SERP несёт его и
                    # здесь. Уже существующую вакансию не пересчитываем, но пустое поле долить
                    # не помешает (backfill — no-op, если уже заполнено).
                    await backfill_total_responses(
                        disc.vacancy_id,
                        account_id=account_id,
                        total_responses=disc.total_responses,
                    )
            except Exception as exc:  # noqa: BLE001 — нет PG → не пропускаем, пробуем скорить
                logger.debug("discovery skip-check недоступен для %s: %s", disc.vacancy_id, exc)
                exists = False
            if exists:
                counts["skipped"] += 1
                yield {
                    "event": "skipped",
                    "reason": "exists",
                    "vacancy_id": disc.vacancy_id,
                    "processed": index,
                    "total": total,
                }
                continue

        text = disc.build_text()
        if len(text) < 50:
            counts["errors"] += 1
            yield {
                "event": "error",
                "where": "scoring",
                "vacancy_id": disc.vacancy_id,
                "error": "текст < 50 символов",
                "processed": index,
                "total": total,
            }
            continue

        try:
            scored = await score_and_persist(
                VacancyInput(
                    text=text,
                    url=disc.url,
                    vacancy_id=disc.vacancy_id,
                    title=disc.title or None,
                    company=disc.company or None,
                    salary_text=disc.salary_text or None,
                    area=disc.area or None,
                    work_format=disc.work_format or None,
                    work_schedule=disc.work_schedule or None,
                    total_responses=disc.total_responses,
                    letter_required=disc.letter_required,
                    employer_id=disc.employer_id or None,
                    source=disc.source,
                ),
                account_id=account_id,
            )
        except Exception as exc:  # noqa: BLE001 — ошибку одной вакансии не роняем на прогон
            counts["errors"] += 1
            yield {
                "event": "error",
                "where": "scoring",
                "vacancy_id": disc.vacancy_id,
                "error": str(exc)[:200],
                "processed": index,
                "total": total,
            }
            continue

        counts["scored"] += 1
        rec = scored.score.recommendation
        match = recommendation_meets_min(rec, min_rec)
        if match:
            counts["matches"] += 1
        yield {
            "event": "scored",
            "vacancy_id": disc.vacancy_id,
            "company": disc.company,
            "url": disc.url,
            "score": scored.score.overall_score,
            "recommendation": rec,
            "match": bool(match),
            "processed": index,
            "total": total,
        }

        if score_delay_sec > 0:
            await asyncio.sleep(score_delay_sec)

    yield {"event": "done", **counts}
