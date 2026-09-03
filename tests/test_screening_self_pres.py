"""План 2026-07-23, шаг 7 + доп. усиление надёжности: вопросы под вакансию
(`core/screening/questions.py`) - раздельные парсеры части A (вероятные вопросы HR→кандидату) и
части B (вопросы кандидат→HR по группам), генерируемые двумя независимыми LLM-вызовами."""

from __future__ import annotations

import pytest

from core.domains.preparation.screening.questions import parse_groups_response, parse_hr_questions_response


def test_parse_hr_questions_response_full() -> None:
    raw = """
    {
      "hr_questions": [
        {
          "question": "Почему LLM Ops?",
          "intent": "проверяют мотивацию",
          "draft_answer": "Тащил observability.\\nРежет стоимость."
        }
      ]
    }
    """
    hr_questions = parse_hr_questions_response(raw)
    assert len(hr_questions) == 1
    assert hr_questions[0].question.startswith("Почему")
    assert hr_questions[0].intent == "проверяют мотивацию"
    assert "observability" in hr_questions[0].draft_answer


def test_parse_hr_questions_response_accepts_legacy_questions_key() -> None:
    """Старый self_pres-формат: questions вместо hr_questions (до разделения на части A/B)."""
    raw = '{"questions": [{"question": "Опыт с LangGraph?", "draft_answer": "Крутил графы."}]}'
    hr_questions = parse_hr_questions_response(raw)
    assert len(hr_questions) == 1
    assert hr_questions[0].question.startswith("Опыт")


def test_parse_hr_questions_response_skips_broken_items() -> None:
    raw = """
    {
      "hr_questions": [
        {"question": "Норм?", "draft_answer": "Да"},
        {"question": "Без ответа"},
        "мусор"
      ]
    }
    """
    hr_questions = parse_hr_questions_response(raw)
    assert len(hr_questions) == 1
    assert hr_questions[0].question == "Норм?"


def test_parse_hr_questions_response_empty_raises() -> None:
    with pytest.raises(ValueError, match="пустой"):
        parse_hr_questions_response('{"hr_questions": []}')


def test_parse_hr_questions_response_not_json_object_raises() -> None:
    with pytest.raises(ValueError, match="не JSON-объект"):
        parse_hr_questions_response("[1, 2, 3]")


def test_parse_groups_response_full() -> None:
    raw = """
    {
      "groups": [
        {
          "title": "Размытые границы роли",
          "hook": "работа в режиме многозадачности",
          "questions": [
            {
              "question": "Чем заменяете предыдущего?",
              "probe": "скрытая текучка",
              "expect": "конкретика - хорошо, общие слова - плохо"
            }
          ]
        }
      ]
    }
    """
    groups = parse_groups_response(raw)
    assert groups[0].title == "Размытые границы роли"
    assert groups[0].hook == "работа в режиме многозадачности"
    assert groups[0].questions[0].probe == "скрытая текучка"
    assert groups[0].questions[0].expect.startswith("конкретика")


def test_parse_groups_response_skips_broken_groups() -> None:
    """Пустая группа и вопрос без `question`/`probe` отбрасываются; probe-only
    поднимается в question (см. `_parse_screening_question`)."""
    raw = """
    {
      "groups": [
        {"title": "Пустая", "questions": []},
        {"title": "Битая", "questions": [{"expect": "нет question и probe"}]},
        {
          "title": "Ок",
          "hook": "зацепка",
          "questions": [{"question": "Вилка?", "probe": "потолок"}]
        }
      ]
    }
    """
    groups = parse_groups_response(raw)
    assert len(groups) == 1
    assert groups[0].title == "Ок"
    assert groups[0].hook == "зацепка"


def test_parse_groups_response_empty_raises() -> None:
    with pytest.raises(ValueError, match="пустой"):
        parse_groups_response('{"groups": []}')


def test_parse_groups_response_not_json_object_raises() -> None:
    with pytest.raises(ValueError, match="не JSON-объект"):
        parse_groups_response("[1, 2, 3]")
