"""Э0.2: город → страна/IANA; неизвестный город — None, без угадывания."""

from __future__ import annotations

from datetime import date

from core.kernel.timezones import (
    UNKNOWN_CITY_HINT,
    CityGeo,
    cities_reference,
    city_derived_line,
    city_geo,
    derived_work_countries,
    overlap_hours,
    overlap_map,
    utc_offset_label,
)


def test_moscow_resolves_to_russia_and_moscow_zone() -> None:
    assert city_geo("Москва") == CityGeo("Россия", "Europe/Moscow")
    assert city_geo("moscow") == CityGeo("Россия", "Europe/Moscow")
    assert city_geo("  МОСКВА  ") == CityGeo("Россия", "Europe/Moscow")


def test_tbilisi_resolves() -> None:
    assert city_geo("Тбилиси") == CityGeo("Грузия", "Asia/Tbilisi")
    assert city_geo("Tbilisi") == CityGeo("Грузия", "Asia/Tbilisi")


def test_unknown_city_is_none_without_guessing() -> None:
    assert city_geo("Хогвартс") is None
    assert city_geo("") is None
    assert city_geo("   ") is None
    assert city_geo("Москв") is None  # префикс не угадываем


def test_cities_reference_is_nonempty_and_stable() -> None:
    names = cities_reference()
    assert "Москва" in names
    assert "Тбилиси" in names
    assert names[0] == "Москва"
    assert names == cities_reference()


def test_derived_work_countries_sets_country_and_keeps_second_residency() -> None:
    assert derived_work_countries("Москва", []) == ["Россия"]
    assert derived_work_countries("Москва", ["Россия"]) == ["Россия"]
    assert derived_work_countries("Москва", ["Грузия"]) == ["Россия", "Грузия"]
    assert derived_work_countries("Тбилиси", ["Россия", "Грузия"]) == ["Грузия", "Россия"]


def test_derived_work_countries_unknown_city_does_not_touch_existing() -> None:
    assert derived_work_countries("Хогвартс", ["Россия"]) is None
    assert derived_work_countries("", ["Грузия"]) is None


def test_city_derived_line_known_and_unknown() -> None:
    assert city_derived_line("Москва") == "UTC+3"
    assert city_derived_line("Хогвартс") == UNKNOWN_CITY_HINT
    assert city_derived_line("") == ""


def test_utc_offset_moscow_is_plus_three() -> None:
    assert utc_offset_label("Europe/Moscow") == "UTC+3"


def test_overlap_moscow_emea_positive_us_west_zero() -> None:
    # Фиксируем дату без перехода DST, чтобы число не плясало от сезона.
    winter = date(2026, 1, 15)
    assert overlap_hours("Europe/Moscow", "EMEA", day=winter) == 8
    assert overlap_hours("Europe/Moscow", "US-West", day=winter) == 0
    assert overlap_hours("not-a-zone", "EMEA") == 0
    assert overlap_map("") == {}
    assert overlap_map("Europe/Moscow", day=winter)["EMEA"] == 8


def test_utc_offset_minutes_moscow() -> None:
    from core.kernel.timezones import utc_offset_minutes

    assert utc_offset_minutes("Europe/Moscow") == 3 * 60
    assert utc_offset_minutes("not-a-zone") == 0


def test_apply_city_derived_countries_keeps_second_residency() -> None:
    from core.domains.profile.model import Personal, ResumeData, apply_city_derived_countries

    data = ResumeData(personal=Personal(city="Москва", work_countries=["Грузия"]))
    out = apply_city_derived_countries(data)
    assert out.personal.work_countries == ["Россия", "Грузия"]
    assert data.personal.work_countries == ["Грузия"]

    unknown = ResumeData(personal=Personal(city="Хогвартс", work_countries=["Грузия"]))
    assert apply_city_derived_countries(unknown) is unknown

