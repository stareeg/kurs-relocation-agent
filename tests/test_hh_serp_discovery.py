"""Этап 6 §6.1 (plans/scoring_precision_2026_08_17.md): SERP embedded-JSON парсинг hh.ru.

Живая проверка hh.ru 2026-08-18 (Playwright, реальные страницы) нашла два наложившихся дефекта,
из-за которых `extract_vacancies_from_html` молча проваливался в regex-фолбэк (только
vacancy_id, без total_responses/salary/work_format/letter_required) на 100% прод-трафика:
1. Блок `vacancies` теперь HTML-entity-encoded (`&#34;` вместо `"`).
2. У части карточек `mapData` несёт продублированный экранирующий бэкслеш перед внутренними
   кавычками, что по правилам JSON законно обрывает разбор всего массива на первом элементе.
"""

from __future__ import annotations

import json

from core.domains.opportunities.sources.hh import extract_vacancies_from_html


def _sample_vacancy(vacancy_id: int = 111, **overrides: object) -> dict:
    base: dict[str, object] = {
        "vacancyId": vacancy_id,
        "name": "Backend Developer",
        "company": {"name": "Acme"},
        "area": {"name": "Москва"},
        "compensation": {"from": 300000, "to": 400000, "currencyCode": "RUR"},
        "workFormats": [{"workFormatsElement": ["REMOTE"]}],
        "@responseLetterRequired": False,
        "totalResponsesCount": 42,
        "links": {"desktop": f"https://hh.ru/vacancy/{vacancy_id}"},
    }
    base.update(overrides)
    return base


def _encode_serp_payload(vacancies: list[dict]) -> str:
    """Как реально отдаёт SERP hh.ru: компактный JSON, кавычки → `&#34;`."""
    payload = json.dumps({"vacancies": vacancies}, separators=(",", ":"))
    return payload.replace('"', "&#34;")


def _wrap_page(body: str) -> str:
    return f'<html><body><div data-params="{body}"></div></body></html>'


def test_html_entity_encoded_serp_parses_full_fields():
    """Основной баг: маркер/JSON не матчились на encoded-виде → фолбэк терял всё, кроме id."""
    html = _wrap_page(_encode_serp_payload([_sample_vacancy(vacancy_id=111)]))
    out = extract_vacancies_from_html(html)
    assert len(out) == 1
    v = out[0]
    assert v.vacancy_id == "111"
    assert v.total_responses == 42
    assert v.letter_required is False
    assert v.work_format == "удалённо"
    assert "300000" in v.salary_text and "400000" in v.salary_text
    assert v.source == "search_batch"


def test_legacy_unescaped_script_json_still_parses():
    """Легаси-случай (`<script>` с сырым JSON, без HTML-энкодинга) не должен ломаться."""
    payload = json.dumps({"vacancies": [_sample_vacancy(vacancy_id=222)]}, separators=(",", ":"))
    html = f"<html><body><script>window.__STATE__ = {payload}</script></body></html>"
    out = extract_vacancies_from_html(html)
    assert len(out) == 1
    assert out[0].vacancy_id == "222"
    assert out[0].total_responses == 42


def test_double_escaped_map_data_does_not_sink_the_batch():
    """Второй баг: продублированный бэкслеш перед закодированной кавычкой в `mapData` (реальный
    прод-паттерн 2026-08-18) не должен ронять разбор всего массива."""
    good = _sample_vacancy(vacancy_id=333, totalResponsesCount=7)
    broken = _sample_vacancy(
        vacancy_id=444,
        totalResponsesCount=9,
        mapData=json.dumps({"points": {"lng": 1, "lat": 2}}),
    )
    encoded_correct = _encode_serp_payload([good, broken])
    # Симулируем прод-баг hh: удваиваем экранирующий бэкслеш перед `&#34;` — обратная операция
    # тому, что делает collapse-фикс в extract_vacancies_from_html.
    encoded_buggy = encoded_correct.replace("\\&#34;", "\\\\&#34;")

    out = extract_vacancies_from_html(_wrap_page(encoded_buggy))

    by_id = {v.vacancy_id: v for v in out}
    assert by_id["333"].total_responses == 7
    assert by_id["444"].total_responses == 9


def test_no_vacancies_marker_falls_back_to_id_regex():
    html = '<html><body><a href="/vacancy/999888">карточка</a></body></html>'
    out = extract_vacancies_from_html(html)
    assert len(out) == 1
    assert out[0].vacancy_id == "999888"
    assert out[0].source == "search_batch_fallback"
    assert out[0].total_responses is None
