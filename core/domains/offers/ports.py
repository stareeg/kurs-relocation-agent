"""Порты репозитория offers.

Сценарии зависят от Protocol; SQL живёт в ``store.py``, класс-адаптер — в ``repo.py``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.domains.offers.store import Offer
from core.kernel.ids import VacancyId


@runtime_checkable
class OffersRepository(Protocol):
    """Персист офферов. Одна реализация — одна ``session`` UoW."""

    async def load(self, vacancy_id: VacancyId | str) -> Offer | None: ...

    async def upsert(self, offer: Offer, *, merge: bool = True) -> Offer: ...

    async def delete(self, vacancy_id: VacancyId | str) -> bool: ...


__all__ = ["OffersRepository"]
