"""FR2-87: детерминированное предложение привязки дампа к вакансии (без LLM/БД)."""

from __future__ import annotations

from core.domains.pipeline.vacancy_attach_suggest import _guess_company_names_in_text, _label


def test_guess_company_sber_alias():
    names = _guess_company_names_in_text("Привет! Пишу из Сбера по вакансии Lead LLM")
    assert "Сбербанк" in names


def test_guess_company_yandex():
    names = _guess_company_names_in_text("Коллеги из Яндекса приглашают на созвон")
    assert "Яндекс" in names


def test_guess_company_empty():
    assert _guess_company_names_in_text("спасибо, жду ответа") == []


def test_label_company_title():
    assert _label("Яндекс", "Lead LLM", "123") == "Яндекс · Lead LLM"


def test_label_fallback_id():
    assert _label("", None, "gm_42") == "Вакансия gm_42"
