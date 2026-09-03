"""План 2026-07-23, шаг 4: разбор вакансии (`JdBrief`) - парсер, без сети."""

from __future__ import annotations

import json

from core.domains.preparation.screening.brief import parse_jd_brief


def test_parse_jd_brief_full_pack() -> None:
    raw = """
    {
      "role_reality": "Собирать пайплайны разметки данных для рекомендаций",
      "product_context": "Внутренний сервис рекомендаций маркетплейса",
      "requirements": [
        {"text": "опыт с LLM в проде", "quote": "опыт эксплуатации LLM в prod", "weight": "must"},
        {"text": "Python", "quote": "уверенное знание Python", "weight": "nice"}
      ],
      "unknowns": ["не сказано про размер команды", "не сказано про вилку"],
      "hooks": ["работа в режиме многозадачности"],
      "jargon": ["LangGraph", "vLLM"]
    }
    """
    brief = parse_jd_brief(raw)
    assert "пайплайны" in brief.role_reality
    assert "маркетплейса" in brief.product_context
    assert len(brief.requirements) == 2
    assert brief.requirements[0].weight == "must"
    assert brief.requirements[1].weight == "nice"
    assert brief.requirements[0].quote == "опыт эксплуатации LLM в prod"
    assert brief.unknowns == ["не сказано про размер команды", "не сказано про вилку"]
    assert brief.hooks == ["работа в режиме многозадачности"]
    assert brief.jargon == ["LangGraph", "vLLM"]


def test_parse_jd_brief_truncates_requirements_to_seven() -> None:
    requirements = [{"text": f"требование {i}", "quote": "", "weight": "must"} for i in range(12)]
    raw = json.dumps({"requirements": requirements}, ensure_ascii=False)
    brief = parse_jd_brief(raw)
    assert len(brief.requirements) == 7
    assert brief.requirements[0].text == "требование 0"
    assert brief.requirements[-1].text == "требование 6"


def test_parse_jd_brief_degrades_on_garbage() -> None:
    assert parse_jd_brief("это не json вообще") == parse_jd_brief("{}")
    assert parse_jd_brief("[1, 2, 3]").requirements == []
    assert parse_jd_brief("").role_reality == ""


def test_parse_jd_brief_skips_broken_requirements_and_bad_weight() -> None:
    raw = """
    {
      "requirements": [
        {"text": "  ", "quote": "пустой текст"},
        {"quote": "нет text"},
        "мусор",
        {"text": "норм требование", "weight": "unexpected"}
      ]
    }
    """
    brief = parse_jd_brief(raw)
    assert len(brief.requirements) == 1
    assert brief.requirements[0].text == "норм требование"
    assert brief.requirements[0].weight == "must"
