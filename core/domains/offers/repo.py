"""Доступ к данным offers: Protocol + Pg-реализация и re-export SQL-фасада."""

from __future__ import annotations

from core.domains.offers.ports import OffersRepository
from core.domains.offers.store import (
    Offer,
    delete_offer,
    load_active_offers,
    load_all_offers,
    load_offer,
    load_offer_comparison_cache,
    load_offers_by_ids,
    reorder_offers,
    save_offer_bonus_estimate,
    save_offer_comparison_cache,
    save_offer_negotiation,
    upsert_offer,
)
from core.kernel.ids import VacancyId
from core.platform.db.pool import Executor


class PgOffersRepository:
    """``OffersRepository`` поверх ``store.py``; ``db`` — session UoW или пул.

    ``account_id`` фиксирован на весь сценарий UoW (план §6) — тот же приём, что
    ``PgJobsRepository`` (opportunities/repo.py, Этап 3): один запрос = один аккаунт, личность
    живёт в конструкторе, не ломает сигнатуры ``OffersRepository``.
    """

    def __init__(self, db: Executor, *, account_id: int) -> None:
        self._db = db
        self._account_id = account_id

    async def load(self, vacancy_id: VacancyId | str) -> Offer | None:
        return await load_offer(str(vacancy_id), account_id=self._account_id, db=self._db)

    async def upsert(self, offer: Offer, *, merge: bool = True) -> Offer:
        return await upsert_offer(offer, account_id=self._account_id, merge=merge, db=self._db)

    async def delete(self, vacancy_id: VacancyId | str) -> bool:
        return await delete_offer(str(vacancy_id), account_id=self._account_id, db=self._db)


__all__ = [
    "Offer",
    "OffersRepository",
    "PgOffersRepository",
    "delete_offer",
    "load_active_offers",
    "load_all_offers",
    "load_offer",
    "load_offer_comparison_cache",
    "load_offers_by_ids",
    "reorder_offers",
    "save_offer_bonus_estimate",
    "save_offer_comparison_cache",
    "save_offer_negotiation",
    "upsert_offer",
]
