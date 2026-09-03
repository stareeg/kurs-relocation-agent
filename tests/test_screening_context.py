"""FR3-54: форматтер кэша пакета скрининга для hr_draft / чата / письма."""

from __future__ import annotations

from core.domains.preparation.screening.context import (
    format_self_pres_context,
    format_self_pres_for_cover_letter,
    saved_from_mapping,
)


def test_format_empty_none() -> None:
    assert format_self_pres_context(None) == ""
    assert format_self_pres_for_cover_letter(None) == ""


def test_format_empty_saved() -> None:
    saved = saved_from_mapping({}, vacancy_id="x")
    assert format_self_pres_context(saved) == ""


def test_format_full_pack_includes_defense_not_groups() -> None:
    saved = saved_from_mapping(
        {
            "oral_pitch": "Lead LLM.\\nТащил GraphRAG.",
            "why_company": "Стек близкий",
                "hr_questions": [
                    {
                        "question": "Почему Ops?",
                        "requirement": "Опыт с RAG",
                        "intent": "проверяют мотивацию",
                        "draft_answer": "Тащил observability.",
                    },
                    {"question": "Опыт с RAG?", "draft_answer": "Гибрид двух слоёв."},
                    {"question": "Третий?", "draft_answer": "ещё один."},
                    {"question": "Лишняя?", "draft_answer": "не должна попасть"},
                ],
            "groups": [
                {
                    "title": "Роль",
                    "questions": [{"question": "Чем заменяете?", "probe": "текучка"}],
                }
            ],
        },
        vacancy_id="gm_1",
    )
    text = format_self_pres_context(saved)
    assert "Устный рассказ" in text
    assert "Тащил GraphRAG" in text
    assert "Стек близкий" in text
    assert "Почему Ops?" in text
    assert "Опыт с RAG" in text
    assert "проверяют мотивацию" in text
    assert "Опыт с RAG?" in text
    assert "Третий?" in text
    # лимит 3 Q&A - четвёртый не попадает
    assert "Лишняя?" not in text
    # нападение не тащим
    assert "Чем заменяете?" not in text
    assert "текучка" not in text


def test_format_cover_letter_omits_hr_questions() -> None:
    saved = saved_from_mapping(
        {
            "oral_pitch": "Короткий питч",
            "why_company": "Домен",
            "hr_questions": [{"question": "Стек?", "draft_answer": "LangGraph."}],
        }
    )
    text = format_self_pres_for_cover_letter(saved)
    assert "Короткий питч" in text
    assert "Домен" in text
    assert "Стек?" not in text
    assert "LangGraph" not in text


def test_format_only_hr_questions_with_requirement() -> None:
    saved = saved_from_mapping(
        {
            "hr_questions": [
                {
                    "question": "Опыт с RAG?",
                    "requirement": "Опыт с RAG",
                    "draft_answer": "Гибрид двух слоёв.",
                }
            ]
        }
    )
    text = format_self_pres_context(saved)
    assert "Опыт с RAG?" in text
    assert "Требование" in text
    assert "Устный рассказ" not in text
