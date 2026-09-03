"""LLM-сводка ситуации для «Рынка»: «как идём / что по рынку» + недельное ретро воронки
(слито в один вызов в UX5-20 — раньше «Собрать ретро» был отдельной кнопкой/бэкендом).

`GET /api/narrative/situation` — последняя сохранённая сводка (кэш, БЕЗ LLM-вызова). Нет PG/нет
сводки → `available=false` + `note` (фронт честный empty с кнопкой «Обновить»), не 500.
`POST /api/narrative/situation` — сгенерировать свежую reasoning-моделью (GLM-5.2 high) по реальным
агрегатам (grid + факты периода) и положить в кэш; вручную по кнопке, либо раз в сутки фоновым
`situation_refresh` (`core.domains.market.snapshot_refresh`) — GET просто отдаёт то, что уже
лежит в кэше, отмечая `stale=true`, если суточный цикл отстал дольше `SITUATION_STALE_AFTER_SEC`.

Мало данных → 400, лимит бюджета → 429, нет ключа OpenRouter / битый structured output → 503,
Postgres недоступен → 503.

M5 (plans/multitenancy_gaps_2026_08_06.md §3.6): `require_account_context` — раньше
`situation_narratives` была append-only лентой одну на всю систему, последняя сводка
показывалась всем (S1: текст описывает личную ситуацию поиска).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.schemas import SituationResponse
from api.security import AccountContext, require_account_context
from api.streaming import sse_response, wants_sse
from core.domains.market.situation import (
    LEGACY_CACHE_NOTE,
    SCHEMA_VERSION,
    SituationNarrative,
    generate_situation_narrative,
    generate_situation_narrative_events,
    narrative_to_storage,
    parse_stored_narrative,
)
from core.domains.market.snapshot_refresh import is_situation_stale
from core.kernel.errors import LlmError

logger = logging.getLogger(__name__)

_EMPTY_NOTE = "Сводка ещё не сгенерирована. Нажми «Обновить сводку»."


router = APIRouter(prefix="/api/narrative", tags=["narrative"])


@router.get("/situation", response_model=SituationResponse)
async def get_situation(
    account: AccountContext = Depends(require_account_context),
) -> SituationResponse:
    """Последняя сохранённая сводка аккаунта (кэш). Нет PG/сводки → честный empty, не 500."""
    try:
        from core.domains.market.situation_store import load_latest_situation

        record = await load_latest_situation(account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → пустой кэш, не валим вкладку
        logger.debug("situation: кэш недоступен (нет PG?): %s", exc)
        return SituationResponse(available=False, note=_EMPTY_NOTE)

    if record is None:
        return SituationResponse(available=False, note=_EMPTY_NOTE)

    if record.schema_version != SCHEMA_VERSION:
        return SituationResponse(available=False, note=LEGACY_CACHE_NOTE)

    narrative = parse_stored_narrative(
        record.narrative,
        db_schema_version=record.schema_version,
    )
    if narrative is None:
        return SituationResponse(available=False, note=LEGACY_CACHE_NOTE)

    return SituationResponse(
        available=True,
        narrative=narrative,
        generated_at=record.created_at,
        stale=is_situation_stale(record.created_at),
    )


async def _save_narrative(narrative: SituationNarrative, *, account_id: int) -> datetime | None:
    """Сохранить свежую сводку аккаунта в кэш. Нет PG → сводка отдаётся без кэша (не валим
    ответ)."""
    try:
        from core.domains.market.situation_store import save_situation

        saved = await save_situation(
            narrative.conclusion,
            narrative_to_storage(narrative),
            account_id=account_id,
            schema_version=SCHEMA_VERSION,
        )
        return saved.created_at
    except Exception as exc:  # noqa: BLE001 — нет PG → сводка отдаётся без кэша
        logger.debug("situation: сводка не сохранена (нет PG?): %s", exc)
        return None


async def _situation_sse_events(*, account_id: int) -> AsyncIterator[dict[str, Any]]:
    """Статус, затем терминальный кадр (один LLM-вызов вместо diagnosis/actions)."""
    try:
        async for event in generate_situation_narrative_events(account_id=account_id):
            etype = event.get("type")
            if etype == "status":
                yield event
            elif etype == "done":
                narrative = SituationNarrative.model_validate(event["narrative"])
                generated_at = await _save_narrative(narrative, account_id=account_id)
                response = SituationResponse(
                    available=True, narrative=narrative, generated_at=generated_at
                )
                yield {"type": "done", "response": response.model_dump(mode="json")}
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
    except LlmError as exc:
        logger.error("situation OpenRouter error: %s", exc)
        yield {"type": "error", "detail": str(exc)}
    except RuntimeError as exc:  # пул PG не поднят — сводке нужны агрегаты из БД
        logger.warning("situation: нет Postgres для агрегатов: %s", exc)
        yield {"type": "error", "detail": "Postgres недоступен для сводки"}
    except TimeoutError as exc:  # UX2-10.2: сбор фактов завис (БД/пул) — явная ошибка, не hang
        logger.warning("situation: таймаут сбора данных: %s", exc)
        yield {"type": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 — SSE-соединение уже открыто, клиент ждёт кадр
        logger.exception("situation: неожиданная ошибка генерации: %s", exc)
        yield {"type": "error", "detail": "Не удалось сгенерировать сводку"}


@router.post("/situation", response_model=SituationResponse)
async def make_situation(
    request: Request,
    account: AccountContext = Depends(require_account_context),
) -> SituationResponse | StreamingResponse:
    """Сгенерировать свежую сводку (LLM) и сохранить в кэш. `Accept: text/event-stream` → поток."""
    if wants_sse(request.headers.get("accept")):
        return sse_response(_situation_sse_events(account_id=account.account_id))

    logger.info("situation: генерация сводки ситуации")
    try:
        narrative = await generate_situation_narrative(account_id=account.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmError as exc:
        logger.error("situation OpenRouter error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:  # пул PG не поднят — сводке нужны агрегаты из БД
        logger.warning("situation: нет Postgres для агрегатов: %s", exc)
        raise HTTPException(status_code=503, detail="Postgres недоступен для сводки") from exc
    except TimeoutError as exc:  # UX2-10.2: сбор фактов завис (БД/пул) — явная ошибка, не hang
        logger.warning("situation: таймаут сбора данных: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — не оставляем POST висеть без ответа
        logger.exception("situation: неожиданная ошибка генерации: %s", exc)
        raise HTTPException(status_code=503, detail="Не удалось сгенерировать сводку") from exc

    generated_at = await _save_narrative(narrative, account_id=account.account_id)

    return SituationResponse(
        available=True,
        narrative=narrative,
        generated_at=generated_at,
    )
