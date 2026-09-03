"""Добавление компании в список «Избегать» резюме (K-связка с skip по причине
«Избегать компанию» — раньше причина называлась «Сомнительная компания»).

Канонизация — через `core.domains.opportunities.companies.normalize.normalize_company`
(детерминизм: оргформы/кавычки/алиасы; LLM-тир — только если результат всё ещё похож
на мусор/слоган, т.е. редко). При недоступном LLM кладём детерминированный канон —
лучше сырой дубль, чем потерянный сигнал.
"""

from __future__ import annotations

import logging

from core.domains.opportunities.companies.normalize import normalize_company

logger = logging.getLogger(__name__)

# Причина skip, при которой компания попадает в «Избегать» (sync: extension SKIP_REASONS).
# После переименования 2026-08-10 канон — «Избегать компанию» (legacy «Сомнительная компания»
# матчится в канон через canonical_skip_reason, но здесь держим новый канон для прямого сравнения
# в POST /skip — расширение/бот шлют уже канонический лейбл).
SKIP_REASON_DODGY_COMPANY = "Избегать компанию"


async def add_company_to_avoid(
    company_raw: str,
    *,
    account_id: int,
    normalize=normalize_company,
) -> str | None:
    """Добавить компанию в `search_criteria.avoid_companies` резюме аккаунта.

    Возвращает итоговое имя, попавшее в список (уже в списке / пустой вход → None).
    Импорты store — ленивые, чтобы домен opportunities не тянул profile на старте.
    """
    if not (company_raw or "").strip():
        return None

    from core.domains.profile.structured_store import (
        read_resume_data_for_account,
        save_resume_data,
    )

    name = await normalize(company_raw)
    if not name:
        return None

    data = await read_resume_data_for_account(account_id)
    sc = data.search_criteria
    existing = list(sc.avoid_companies or [])
    if any(e.casefold() == name.casefold() for e in existing):
        return None

    updated = sc.model_copy(update={"avoid_companies": [*existing, name]})
    merged = data.model_copy(update={"search_criteria": updated})
    await save_resume_data(merged, source="company_avoid_skip", account_id=account_id)
    logger.info("Компания добавлена в «Избегать» (skip): %s (account_id=%s)", name, account_id)
    return name
