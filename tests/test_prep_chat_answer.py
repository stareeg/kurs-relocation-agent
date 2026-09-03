"""Unit-тесты парсинга ответа чата подготовки: kind=chat vs kind=questions."""

from __future__ import annotations

import json

from core.domains.preparation.interview.prep import _parse_chat_answer, _parse_questions


def test_parse_chat_answer_questions() -> None:
    raw = json.dumps(
        {
            "kind": "questions",
            "text": "Добавил пачку «Kafka/Flink» - 2 вопроса, они выше в списке.",
            "topic": "Kafka/Flink",
            "questions": [
                {
                    "category": "technical",
                    "text": "Как Kafka гарантирует порядок сообщений в партиции?",
                    "hint": "consumer group, offset",
                    "answer": "Порядок держится внутри одной партиции.",
                },
                {
                    "category": "technical",
                    "text": "Чем Flink отличается от Kafka Streams?",
                    "hint": "",
                    "answer": "Flink - отдельный движок обработки потоков.",
                },
            ],
        }
    )
    result = _parse_chat_answer(raw)
    assert result.kind == "questions"
    assert result.topic == "Kafka/Flink"
    assert len(result.questions) == 2
    assert result.questions[0].category == "technical"
    assert "Добавил пачку" in result.text


def test_parse_chat_answer_chat() -> None:
    raw = json.dumps({"kind": "chat", "text": "GIL - глобальная блокировка интерпретатора.", "topic": None, "questions": []})
    result = _parse_chat_answer(raw)
    assert result.kind == "chat"
    assert result.questions == []
    assert result.text.startswith("GIL")


def test_parse_chat_answer_markdown_fence() -> None:
    payload = json.dumps({"kind": "chat", "text": "Ответ в обёртке", "topic": None, "questions": []})
    raw = f"```json\n{payload}\n```"
    result = _parse_chat_answer(raw)
    assert result.kind == "chat"
    assert result.text == "Ответ в обёртке"


def test_parse_chat_answer_invalid_json_falls_back_to_chat() -> None:
    raw = "Не json, а обычный человеческий ответ про декораторы."
    result = _parse_chat_answer(raw)
    assert result.kind == "chat"
    assert result.text == raw


def test_parse_chat_answer_questions_kind_without_valid_items_falls_back_to_chat() -> None:
    raw = json.dumps({"kind": "questions", "text": "", "topic": "X", "questions": []})
    result = _parse_chat_answer(raw)
    assert result.kind == "chat"
    assert result.questions == []


def test_parse_chat_answer_questions_kind_with_only_broken_items_falls_back_to_chat() -> None:
    raw = json.dumps(
        {
            "kind": "questions",
            "text": "",
            "topic": "X",
            "questions": [{"category": "not-a-real-category", "text": "Q"}],
        }
    )
    result = _parse_chat_answer(raw)
    assert result.kind == "chat"


def test_parse_questions_still_works_after_shared_parser_refactor() -> None:
    """Неизвестная категория не роняет вопрос - `_normalize_prep_category` сводит её к "technical"
    (иначе LLM из внешнего парсинга массово отваливается на валидации, см. `_parse_question_item`)."""
    raw = json.dumps(
        {
            "questions": [
                {"category": "technical", "text": "Как устроен HNSW?", "hint": "", "answer": "..."},
                {"category": "bogus-category", "text": "Вопрос с незнакомой категорией"},
            ]
        }
    )
    questions = _parse_questions(raw)
    assert len(questions) == 2
    assert questions[0].text == "Как устроен HNSW?"
    assert questions[1].text == "Вопрос с незнакомой категорией"
    assert questions[1].category == "technical"
