"""События домена offers: что публикует и на что подписан (шина — A-11)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.kernel import ports
from core.kernel.events import OfferReceived
from core.kernel.ids import OfferId, VacancyId

PUBLISHES: tuple[type, ...] = (OfferReceived,)
SUBSCRIPTIONS: tuple[tuple[type, Callable[[Any], Any]], ...] = ()
SUBSCRIBES: tuple[type, ...] = ()


def publish_offer_received(
    *,
    vacancy_id: str,
    account_id: int,
    company: str = "",
    status: str = "",
) -> None:
    """Оффер появился впервые (правки существующего оффера событием не считаем)."""
    vid = VacancyId(vacancy_id)
    ports.events().publish(
        OfferReceived(
            offer_id=OfferId(vacancy_id),
            vacancy_id=vid,
            company=company,
            status=status,
            account_id=account_id,
        )
    )


__all__ = [
    "OfferReceived",
    "PUBLISHES",
    "SUBSCRIBES",
    "SUBSCRIPTIONS",
    "publish_offer_received",
]
