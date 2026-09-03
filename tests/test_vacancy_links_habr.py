"""Тесты habr-ссылок в `core.domains.pipeline.vacancy_links` (S11.2)."""

from __future__ import annotations

from core.domains.pipeline.vacancy_links import (
    extract_job_urls,
    extract_primary_job_url,
    extract_primary_vacancy_id,
    extract_vacancy_ids,
    listing_url_for_vacancy_id,
)


def test_extract_vacancy_ids_hh_unchanged():
    assert extract_vacancy_ids("вакансия https://hh.ru/vacancy/12345678?query=1") == ["12345678"]


def test_extract_vacancy_ids_habr_canonical():
    """Хабр-ссылка → каноничный `habr_{numeric}`."""
    assert extract_vacancy_ids("https://career.habr.com/vacancies/1000164602") == [
        "habr_1000164602"
    ]


def test_extract_vacancy_ids_mixed_and_dedup():
    text = (
        "hh: https://hh.ru/vacancy/111\n"
        "habr: https://career.habr.com/vacancies/222\n"
        "habr dup: career.habr.com/vacancies/222\n"
    )
    assert extract_vacancy_ids(text) == ["111", "habr_222"]


def test_extract_primary_vacancy_id_habr():
    assert extract_primary_vacancy_id("https://career.habr.com/vacancies/1000164602") == (
        "habr_1000164602"
    )


def test_extract_primary_job_url_habr():
    """Прямая ссылка на хабр-вакансию резолвится в career.habr.com URL, а не в hh."""
    url = extract_primary_job_url("https://career.habr.com/vacancies/1000164602")
    assert url == "https://career.habr.com/vacancies/1000164602"


def test_extract_job_urls_catches_habr():
    """_is_job_listing_url уже ловит /vacancies/ — хабр-URL попадает в extract_job_urls."""
    assert "https://career.habr.com/vacancies/1000164602" in extract_job_urls(
        "https://career.habr.com/vacancies/1000164602"
    )


def test_listing_url_for_vacancy_id():
    assert listing_url_for_vacancy_id("12345678") == "https://hh.ru/vacancy/12345678"
    assert (
        listing_url_for_vacancy_id("habr_1000164602")
        == "https://career.habr.com/vacancies/1000164602"
    )
    assert listing_url_for_vacancy_id("gm_42") == "https://getmatch.ru/vacancies/42"
