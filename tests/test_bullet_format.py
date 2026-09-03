"""Парсинг и нормализация буллетов (этап 2 resume score)."""

from __future__ import annotations

from core.domains.profile.bullet_format import ensure_bullet_format, parse_bullets
from core.domains.profile.gap import _bullets, count_bullets
from core.domains.profile.model import Experience, ResumeData


def test_parse_bullets_unicode_marker():
    text = "Обязанности:\n• Спроектировал API на FastAPI\n• Сократил p95 latency в 3 раза"
    assert parse_bullets(text) == [
        "Спроектировал API на FastAPI",
        "Сократил p95 latency в 3 раза",
    ]


def test_parse_bullets_em_dash_marker():
    text = "— Внедрил CI/CD в GitLab\n— Настроил мониторинг в Grafana"
    assert len(parse_bullets(text)) == 2


def test_parse_bullets_skips_section_header():
    text = "Достижения:\n1. Поднял NPS до 72\n2. Сократил churn на 15%"
    assert parse_bullets(text) == ["Поднял NPS до 72", "Сократил churn на 15%"]


def test_parse_bullets_does_not_split_plain_prose():
    """Scoring path: prose без маркеров не считаем буллетами."""
    prose = "Просто абзац текста без маркеров и цифр."
    assert parse_bullets(prose) == []
    assert _bullets(prose) == []


def test_ensure_bullet_format_from_prose_paragraph():
    prose = "Спроектировал API. Сократил latency. Внедрил CI."
    out = ensure_bullet_format(prose)
    assert out.startswith("- Спроектировал API.")
    assert out.count("\n") == 2
    assert parse_bullets(out) == [
        "Спроектировал API.",
        "Сократил latency.",
        "Внедрил CI.",
    ]


def test_ensure_bullet_format_from_numbered_llm_output():
    numbered = "1. Первый пункт\n2. Второй пункт"
    out = ensure_bullet_format(numbered)
    assert out == "- Первый пункт\n- Второй пункт"


def test_ensure_bullet_format_single_line_gets_marker():
    out = ensure_bullet_format("Lead LLM Engineer с фокусом на RAG")
    assert out == "- Lead LLM Engineer с фокусом на RAG"
    data = ResumeData(about=out)
    assert count_bullets(data) == 1


def test_ensure_bullet_format_preserves_existing_dash_bullets():
    dashed = "- Уже в формате\n- Второй пункт"
    out = ensure_bullet_format(dashed)
    assert out == dashed
    data = ResumeData(
        experience=[Experience(company="X", position="Y", description=out)],
    )
    assert count_bullets(data) == 2
