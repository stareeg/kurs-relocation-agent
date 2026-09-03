"""offer_confidence — confidence «Оффера»: устно / письмом / подписан (без данных → None)."""

from core.domains.offers.models import OfferRecord, offer_confidence


def test_verbal_reached_stage_no_offer_record() -> None:
    assert offer_confidence(True, None) == "verbal"


def test_verbal_reached_stage_offer_record_without_raw_text() -> None:
    offer = OfferRecord(vacancy_id="1", status="thinking", raw_text="")
    assert offer_confidence(True, offer) == "verbal"


def test_written_offer_record_with_raw_text() -> None:
    offer = OfferRecord(vacancy_id="1", status="thinking", raw_text="оффер от HR: ...")
    assert offer_confidence(False, offer) == "written"
    assert offer_confidence(True, offer) == "written"


def test_signed_accepted_status_wins_over_written() -> None:
    offer = OfferRecord(vacancy_id="1", status="accepted", raw_text="оффер от HR: ...")
    assert offer_confidence(True, offer) == "signed"


def test_signed_accepted_status_without_raw_text() -> None:
    offer = OfferRecord(vacancy_id="1", status="accepted", raw_text="")
    assert offer_confidence(False, offer) == "signed"


def test_none_when_nothing_reached_and_no_offer() -> None:
    assert offer_confidence(False, None) is None
