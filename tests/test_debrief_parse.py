"""Unit-тесты парсинга ответа debrief и нормализации транскрипта."""

from __future__ import annotations

import asyncio

import pytest

import core.domains.preparation.interview.debrief as debrief
from core.domains.preparation.asker import record_from_request_fallback
from core.domains.preparation.interview.debrief import (
    _parse_response,
    analyze_debrief,
    extract_sobes_transcript,
    normalize_transcript,
)
from core.kernel import ports
from tests.fakes import FakeLlm

SAMPLE_JSON = """{
  "questions_asked": ["Как устроен RAG?"],
  "weak_answers": [],
  "strong_answers": ["Хорошо описал пайплайн"],
  "topics_to_study": ["eval для RAG"],
  "competency_map": [
    {"topic": "RAG", "level": "medium", "evidence": "базово"}
  ],
  "honest_notes": [],
  "interview_format": "technical",
  "next_steps_signal": "next_stage_likely",
  "overall_impression": 7,
  "summary": "Неплохо для бизнес-кейса"
}"""

SOBES_EXPORT = """rshb tech
Экспортировано: 08.07.2026, 15:01:38
---
💬 Вопрос (12:56)
Сейчас будет этап технического собеседования.
Мы ищем AI/LMM Engineer уровня лида.
🎙️ Расшифровка аудио
🔊 13:07: добрый день калине добрый день снофтбанк возник вопрос о том как все это делать
"""

# Репродукция бага Далкоса (vacancy_id=136134777): sobes.tech-экспорт с двумя вопросами,
# каждый со своей «Расшифровкой аудио» и служебными блоками «💬 Вопрос» / «📷 скриншот» /
# «---» между ними. extract_sobes_transcript должен вырезать служебку и схлопнуть повторные
# шапки «Расшифровка аудио», оставив только склейку реплик — иначе LLM-сегментация ломается
# (33 реплики вместо полного разговора) и в транскрипт утекают шапки/разделители.
SOBES_MULTI_QUESTION_EXPORT = """dalkos tech

Экспортировано: 13.08.2026, 22:04:06

---

### 💬 Вопрос (*10:58*)

Сейчас будет техническое собеседование на эту вакансию - ML Engineer / AI Engineer (LLM)
Компания: ООО ДАЛКОС

### 🎙️ Расшифровка аудио

🔊 *11:08*: Егор, пока мы ждем подключения Владимира, хотела, что удалось ознакомиться...

🎤 *11:08*: Да, я посмотрел презентацию, всталом понял профиль компании...

🔊 *11:46*: Спасибо. Продолжение следует...

---

### 💬 Вопрос (*11:46*)

...

📷 *1 скриншот*

### 🎙️ Расшифровка аудио

🔊 *11:47*: есть фронт есть backend для которой обслуживает фронт...

🎤 *11:48*: так вот, допустим, так, мы это соединим стрелкой и...

🔊 *12:02*: хорошо а что вот из ближайших там задач проектов хотелось бы реализовать...

🎤 *12:02*: например мы взяли здесь постгресс учитывая сколько у нас будет документов...

---

### 💬 Вопрос (*12:03*)

ну что оцени как оно прошло? адекватно вообще?

### 💬 Вопрос (*12:06*)

а че он так к бэкенду прикопался, раз мы обсуждаем высокие материи - типа агентов и llm
"""


def test_normalize_transcript_strips_zero_width() -> None:
    raw = "Python\u200b:\u200c уверенное\u2060 владение"
    assert "\u200b" not in normalize_transcript(raw)
    assert normalize_transcript(raw).startswith("Python:")


def test_extract_sobes_transcript_keeps_audio_block() -> None:
    extracted = extract_sobes_transcript(SOBES_EXPORT)
    # Шапку «🎙️ Расшифровка аудио» вырезаем — остаётся только таймкод-реплика.
    assert "🔊" in extracted
    assert "🎙️" not in extracted
    assert "Расшифровка аудио" not in extracted
    assert "💬" not in extracted
    assert "AI/LMM Engineer" not in extracted
    assert "снофтбанк" in extracted


def test_extract_sobes_transcript_strips_multi_question_scaffolding() -> None:
    """Два вопроса → одна склейка реплик без служебных блоков и повторных шапок."""
    extracted = extract_sobes_transcript(SOBES_MULTI_QUESTION_EXPORT)
    # Служебные блоки sobes.tech вырезаны полностью.
    assert "💬" not in extracted
    assert "📷" not in extracted
    assert "Экспортировано" not in extracted
    assert "Расшифровка аудио" not in extracted
    assert "🎙️" not in extracted
    # Реплики обоих аудио-блоков сохранились и идут подряд (склейка без разделителя-дубля).
    assert "Егор, пока мы ждем" in extracted
    assert "есть фронт есть backend" in extracted
    # Содержимое шапки вопроса (не реплика) не утекло в транскрипт.
    assert "ML Engineer / AI Engineer (LLM)" not in extracted
    # Разделитель «---» между блоками не должен оставлять рваных пустых секций.
    assert "\n---\n" not in extracted
    # Третий «вопрос» без расшифровки — служебная болтовня, не должна попадать в транскрипт.
    assert "ну что оцени как оно прошло" not in extracted


def test_parse_response_from_markdown_fence() -> None:
    wrapped = f"```json\n{SAMPLE_JSON}\n```"
    result = _parse_response(wrapped)
    assert result.overall_impression == 7
    assert result.next_steps_signal == "next_stage_likely"
    assert result.competency_map[0].topic == "RAG"


def test_parse_response_with_preamble_and_emojis() -> None:
    wrapped = f"💬 Вот разбор:\n```json\n{SAMPLE_JSON}\n```\n🎙️ готово"
    result = _parse_response(wrapped)
    assert "RAG" in result.topics_to_study[0]


def test_parse_response_clamps_invalid_fields() -> None:
    broken = """{
      "questions_asked": ["Q"],
      "weak_answers": [],
      "strong_answers": [],
      "topics_to_study": [],
      "competency_map": [{"topic": "X", "level": "bogus", "evidence": null}],
      "honest_notes": [],
      "interview_format": "nope",
      "next_steps_signal": "???",
      "overall_impression": 99,
      "summary": "ok"
    }"""
    result = _parse_response(broken)
    assert result.competency_map[0].level == "medium"
    assert result.competency_map[0].evidence == ""
    assert result.interview_format == "other"
    assert result.next_steps_signal == "unknown"
    assert result.overall_impression == 10


def test_parse_response_transcript_turns() -> None:
    with_turns = SAMPLE_JSON.replace(
        '"summary": "Неплохо для бизнес-кейса"',
        '"summary": "ok", "transcript_turns": ['
        '{"speaker": "interviewer", "text": "Как устроен RAG?"}, '
        '{"speaker": "candidate", "text": "Через ретривер и реранкер"}, '
        '{"speaker": "bogus", "text": "мусорный говорящий"}, '
        '{"speaker": "candidate", "text": ""}'
        "]",
    )
    result = _parse_response(with_turns)
    assert len(result.transcript_turns) == 2
    assert result.transcript_turns[0].speaker == "interviewer"
    assert result.transcript_turns[1].speaker == "candidate"


def test_parse_response_transcript_turns_missing_defaults_empty() -> None:
    result = _parse_response(SAMPLE_JSON)
    assert result.transcript_turns == []


def test_parse_response_transcript_turns_capped() -> None:
    turns = ", ".join(f'{{"speaker": "candidate", "text": "реплика {i}"}}' for i in range(80))
    with_many = SAMPLE_JSON.replace(
        '"summary": "Неплохо для бизнес-кейса"',
        f'"summary": "ok", "transcript_turns": [{turns}]',
    )
    result = _parse_response(with_many)
    assert len(result.transcript_turns) == 60


def test_parse_response_trailing_comma() -> None:
    broken = SAMPLE_JSON.replace('"summary": "Неплохо для бизнес-кейса"', '"summary": "ok",')
    result = _parse_response(broken)
    assert result.summary == "ok"


def test_parse_response_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="невалидный JSON"):
        _parse_response("💬 не json вообще")


def test_parse_response_truncated_json_recovers() -> None:
    """LLM обрезала ответ по max_tokens посередине JSON (открытый fence, незакрытые
    объекты/массивы) — recovery должен закрыть скобки и вернуть то, что успело сгенерироваться,
    а не падать с «no JSON object». Частый случай на reasoning-тире с длинными транскриптами
    (8к токенов, 60 transcript_turns)."""
    truncated = (
        '```json\n'
        '{\n'
        '  "questions_asked": ["Как устроен RAG?"],\n'
        '  "weak_answers": [],\n'
        '  "strong_answers": ["Хорошо описал пайплайн"],\n'
        '  "topics_to_study": ["eval для RAG"],\n'
        '  "competency_map": [\n'
        '    {"topic": "RAG", "level": "medium", "evidence": "базово'
    )
    result = _parse_response(truncated)
    assert "eval для RAG" in result.topics_to_study
    assert result.questions_asked == ["Как устроен RAG?"]


def test_parse_response_truncated_inside_array_value() -> None:
    """Обрезка внутри массива строк — recovery закрывает и массив, и объект."""
    truncated = (
        '```json\n'
        '{\n'
        '  "questions_asked": ["Первый вопрос", "Второй вопро'
    )
    result = _parse_response(truncated)
    assert "Первый вопрос" in result.questions_asked


def test_parse_response_truncated_in_string_value() -> None:
    """Обрезка внутри значения строки (незакрытая кавычка) — recovery отбрасывает
    незаконченную пару и закрывает объект."""
    truncated = (
        '```json\n'
        '{\n'
        '  "questions_asked": ["Q"],\n'
        '  "summary": "Неплохо, но обрыв'
    )
    result = _parse_response(truncated)
    assert result.questions_asked == ["Q"]
    assert result.summary == ""


async def test_analyze_debrief_hang_raises_timeout_not_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DBR-1: зависший LLM-вызов должен падать по потолку времени, а не висеть неопределённо
    (диагноз плана — «3+ минуты и ничего»)."""

    async def hangs_forever(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        await asyncio.sleep(3600)

    monkeypatch.setattr(debrief, "_LLM_TIMEOUT_S", 0.05)
    monkeypatch.setattr(
        debrief, "get_settings", lambda: type("S", (), {"openrouter_api_key": "x"})()
    )

    record = record_from_request_fallback(
        "vac-1", vacancy_text="Пример вакансии для теста", title="ML Engineer", company="Acme"
    )

    with (
        ports.use_ports(llm=FakeLlm(on_complete=lambda *a, **kw: hangs_forever())),
        pytest.raises(TimeoutError, match="долго думает"),
    ):
        await analyze_debrief(
            record, "достаточно длинный транскрипт для прохождения проверки", account_id=1
        )


async def test_run_llm_uses_text_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    """DBR-7: живые прогоны показали, что `complete_structured` для этой схемы ненадёжен —
    у primary-модели иногда падает 400 "Schema is too complex", и тогда её собственный
    авто-fallback на более слабую модель возвращает schema-валидный, но фактически ПУСТОЙ объект
    (не исключение — слой structured-output проблемы не видит), либо генерация просто занимает
    больше отведённого потолка без единой ошибки. `_run_llm` больше не трогает structured вообще —
    только `complete_text` с уже проверенным JSON-парсингом, что на живых прогонах стабильно
    укладывалось в 15-30с с полным корректным разбором."""

    with ports.use_ports(llm=FakeLlm(text=SAMPLE_JSON)):
        result = await debrief._run_llm("sys", "usr")
    assert result.summary == "Неплохо для бизнес-кейса"
    assert result.overall_impression == 7


async def test_run_llm_raises_when_text_result_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустой (но валидный JSON) ответ модели — явная ошибка с «попробуй ещё раз», а не тихо
    сохранённая пустая карточка разбора в истории."""

    empty = FakeLlm(text='{"summary": "", "questions_asked": []}')
    with ports.use_ports(llm=empty), pytest.raises(ValueError, match="пустой разбор"):
        await debrief._run_llm("sys", "usr")
