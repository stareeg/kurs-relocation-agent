"""Парсинг ответа чата подготовки: конверт kind/text не должен утекать в UI."""

from core.domains.preparation.interview.prep import (
    _parse_chat_answer,
    _parse_question_item,
    extract_external_transcript,
    format_external_transcript_message,
)


def test_parse_valid_chat_envelope():
    raw = '{"kind": "chat", "text": "Разберём trade-off по RAG.", "topic": null, "questions": []}'
    ans = _parse_chat_answer(raw)
    assert ans.kind == "chat"
    assert ans.text == "Разберём trade-off по RAG."
    assert '{"kind"' not in ans.text


def test_parse_broken_envelope_extracts_text():
    raw = '{"kind": "chat", "text": "Короткий ответ про агентов.", "topic": null, "questions":'
    ans = _parse_chat_answer(raw)
    assert ans.kind == "chat"
    assert "агентов" in ans.text
    assert '"kind"' not in ans.text


def test_parse_envelope_without_text_not_leaked():
    raw = '{"kind": "chat", "topic": null, "questions": []}'
    ans = _parse_chat_answer(raw)
    assert ans.kind == "chat"
    assert '"kind"' not in ans.text
    assert "разобрать" in ans.text.lower() or "ещё раз" in ans.text.lower()


def test_parse_plain_text_passthrough():
    raw = "Обычный ответ без JSON"
    ans = _parse_chat_answer(raw)
    assert ans.text == raw


def test_parse_questions_pack():
    raw = """{
      "kind": "questions",
      "text": "Добавил пачку",
      "topic": "RAG",
      "questions": [
        {"category": "technical", "text": "Что такое hybrid RAG?", "hint": "", "answer": "Два слоя поиска"}
      ]
    }"""
    ans = _parse_chat_answer(raw)
    assert ans.kind == "questions"
    assert len(ans.questions) == 1
    assert ans.questions[0].topic == "RAG"


def test_theory_category_normalized_to_technical():
    q = _parse_question_item(
        {
            "category": "theory",
            "text": "Как работает attention?",
            "hint": "",
            "answer": "QKV и softmax",
        }
    )
    assert q is not None
    assert q.category == "technical"


def test_system_design_category_normalized_to_case():
    q = _parse_question_item(
        {
            "category": "system_design",
            "text": "Спроектируй RAG на 1M docs",
            "hint": "",
            "answer": "ingest → index → retrieve",
        }
    )
    assert q is not None
    assert q.category == "case"


def test_external_transcript_roundtrip_no_truncate():
    big = "Q: вопрос\nA: ответ\n" * 5000
    stored = format_external_transcript_message(big)
    assert stored.startswith("Внешняя переписка (парсинг)")
    assert extract_external_transcript(stored) == big.strip()
    assert extract_external_transcript("обычное сообщение") is None
