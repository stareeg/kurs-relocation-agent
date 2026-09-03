"""План 2026-07-23, шаг 5 + доп. усиление надёжности (после живой проверки шага 16):
детерминированный анти-slop линтер (`core/screening/style.py`) - без сети и без БД."""

from __future__ import annotations

from pathlib import Path

from core.domains.preparation.screening.style import (
    BANNED_TERMS,
    PitchBlock,
    lint_pitch,
    lint_spoken_text,
    speak_seconds,
    violations_to_prompt,
)

_ORAL_STYLE_PATH = Path("prompts/preparation/screening/oral_style.md")

_CLEAN_BLOCKS = [
    PitchBlock(
        label="Кто я",
        lines=[
            "Я инженер, который переводит рабочие процессы в понятные автоматические сценарии",
            "Пять лет собираю системы, которые считают и подсказывают, а не просто хранят данные",
            "За это время прошёл путь от разработчика до тимлида небольшой команды",
            "Умею объяснять сложные технические решения простым языком команде и заказчику",
            "Особенно нравится доводить решения до реального использования в команде",
        ],
    ),
    PitchBlock(
        label="Что делал",
        lines=[
            "В прошлой компании автоматизация отчётности отнимала у команды два дня",
            "Я собрал сервис на Python, который считает отчёт за пятнадцать минут",
            "Команда перестала терять пятницы на сведение таблиц и начала тратить время на анализ",
            "До этого пробовали закрывать процесс таблицами и ручными напоминаниями, но это не "
            "помогало",
            "После запуска сервиса ошибки в отчётах упали почти до нуля",
        ],
    ),
    PitchBlock(
        label="Мост к вакансии",
        lines=[
            "Вижу в вашей вакансии похожую задачу с автоматизацией процессов",
            "Такие сценарии я уже строил на Python и знаю, где обычно теряется время",
            "Также помогаю командам разбираться, где именно теряются часы в текущих процессах",
        ],
    ),
    PitchBlock(
        label="Почему сюда",
        lines=["Задача близка к тому, что я уже делал, поэтому интерес предметный, а не общий"],
    ),
    PitchBlock(
        label="Что ищу",
        lines=[
            "Хочу работать там, где автоматизация реально освобождает время живых людей",
            "Важна команда, которая сама проверяет цифры, а не верит на слово",
            "Также хочется расти в сторону более сложных технических задач",
            "Комфортнее в командах, где решения обсуждают открыто и по делу",
        ],
    ),
    PitchBlock(
        label="Финал", lines=["Расскажите, как у вас устроена работа с отчётностью сегодня"]
    ),
]

_CLEAN_ANCHORS = ["автоматизация отчётности", "Python"]


def test_lint_pitch_clean_text_gives_empty_list() -> None:
    assert lint_pitch(_CLEAN_BLOCKS, anchors=_CLEAN_ANCHORS) == []


def test_lint_pitch_banned_term() -> None:
    blocks = [
        PitchBlock(label="Что делал", lines=["Мы поставили guardrails, чтобы модель не ошибалась"])
    ]
    violations = lint_pitch(blocks, anchors=[])
    hit = [v for v in violations if v.rule == "banned_term" and "guardrails" in v.detail]
    assert hit
    assert "ограничители" in hit[0].detail


def test_lint_pitch_allowed_name_overuse_in_line() -> None:
    blocks = [
        PitchBlock(label="Что делал", lines=["Мы использовали LangGraph и Langfuse в одном месяце"])
    ]
    violations = lint_pitch(blocks, anchors=[])
    assert any(
        v.rule == "banned_term" and "больше одного технического имени" in v.detail
        for v in violations
    )


def test_lint_pitch_allowed_name_overuse_in_text() -> None:
    names = ["LangGraph", "Langfuse", "MLflow", "vLLM", "RAG", "SQL", "Postgres"]
    blocks = [
        PitchBlock(label="Что делал", lines=[f"Использовал {name} в проекте" for name in names])
    ]
    violations = lint_pitch(blocks, anchors=[])
    assert any(v.rule == "banned_term" and "не больше шести" in v.detail for v in violations)


def test_lint_pitch_punctuation_colon_and_dash() -> None:
    blocks = [
        PitchBlock(
            label="Что делал",
            lines=["Стек: LangGraph, Python", "Сделал это — быстро и без правок"],
        )
    ]
    violations = lint_pitch(blocks, anchors=[])
    rules = [v for v in violations if v.rule == "punctuation"]
    assert len(rules) == 2


def test_lint_pitch_punctuation_markdown_marker() -> None:
    blocks = [PitchBlock(label="Что делал", lines=["- собрал сервис на Python за неделю"])]
    violations = lint_pitch(blocks, anchors=[])
    assert any(v.rule == "punctuation" and "markdown" in v.detail for v in violations)


def test_lint_pitch_long_line() -> None:
    long_line = " ".join(["слово"] * 20)
    blocks = [PitchBlock(label="Что делал", lines=[long_line])]
    violations = lint_pitch(blocks, anchors=[])
    hit = [v for v in violations if v.rule == "long_line"]
    assert hit
    assert "20 слов" in hit[0].detail


def test_lint_pitch_monotony_past_tense_run() -> None:
    blocks = [
        PitchBlock(
            label="Что делал",
            lines=[
                "Собрал сервис для команды за две недели",
                "Оптимизировал отчёт так, чтобы он считался быстрее",
                "Запустил сервис в работу без единого отката",
            ],
        )
    ]
    violations = lint_pitch(blocks, anchors=[])
    assert any(v.rule == "monotony" and "глагола прошедшего" in v.detail for v in violations)


def test_lint_pitch_monotony_same_first_word() -> None:
    blocks = [
        PitchBlock(
            label="Что ищу",
            lines=[
                "Важно расти в команде, которая сама проверяет цифры",
                "Важно видеть, как решение доходит до реальных людей",
                "Важно понимать, зачем именно эта задача существует",
            ],
        )
    ]
    violations = lint_pitch(blocks, anchors=[])
    assert any(v.rule == "monotony" and 'слово "важно"' in v.detail for v in violations)


def test_lint_pitch_cliche() -> None:
    blocks = [
        PitchBlock(label="Почему сюда", lines=["Вижу возможность масштабировать эти подходы у вас"])
    ]
    violations = lint_pitch(blocks, anchors=[])
    assert any(v.rule == "cliche" for v in violations)


# Живые примеры с прода (2026-08-13): «готов рассказать подробнее» в CLICHES ловился только
# дословно - модель обходила его перестановкой слов. Регрессия на реордеринг.
def test_lint_pitch_ready_to_discuss_catches_reordered_variant() -> None:
    blocks = [
        PitchBlock(
            label="Финал",
            lines=["Готов подробнее рассказать про архитектуру и цифры на следующем шаге"],
        )
    ]
    violations = lint_pitch(blocks, anchors=[])
    assert any(v.rule == "cliche" for v in violations)


def test_lint_pitch_ready_to_discuss_catches_original_phrase() -> None:
    blocks = [
        PitchBlock(
            label="Финал", lines=["Готов рассказать подробнее, как я строил систему в Сбере"]
        )
    ]
    violations = lint_pitch(blocks, anchors=[])
    assert any(v.rule == "cliche" for v in violations)


# «Мост к вакансии» с прода (2026-08-13): 3 строки подряд в шаблоне «Нужен X - у меня Y», который
# инструкция явно запрещает повторять по кругу.
def test_lint_pitch_bridge_template_repeated() -> None:
    blocks = [
        PitchBlock(
            label="Мост к вакансии",
            lines=[
                "Нужен реальный опыт внедрения ИИ-агентов, а не разговоры про модели",
                "Нужна архитектура хранения данных и конвейеры - я строил витрины руками",
                "Python для автоматизации у меня рабочий инструмент, а не факультативный навык",
            ],
        )
    ]
    violations = lint_pitch(blocks, anchors=[])
    assert any(v.rule == "cliche" and "Мост к вакансии" in v.detail for v in violations)


def test_lint_pitch_bridge_template_single_line_is_fine() -> None:
    blocks = [
        PitchBlock(
            label="Мост к вакансии",
            lines=[
                "Нужен реальный опыт внедрения ИИ-агентов - это стержень последних двух лет",
                "Ещё нужна архитектура хранения данных, но не отдельным пунктом, а как факт",
            ],
        )
    ]
    violations = lint_pitch(blocks, anchors=[])
    assert not any("Мост к вакансии" in v.detail for v in violations)


def test_lint_pitch_no_anchor() -> None:
    blocks = [
        PitchBlock(
            label="Что делал",
            lines=[
                "Собрал отчёт для команды за две недели без лишних задержек",
                "Помог коллегам разобраться в новом процессе быстрее обычного",
            ],
        )
    ]
    violations = lint_pitch(blocks, anchors=["распределённые вычисления", "Kubernetes"])
    assert any(v.rule == "no_anchor" for v in violations)


def test_lint_pitch_no_anchor_skipped_when_no_anchors_given() -> None:
    blocks = [PitchBlock(label="Что делал", lines=["Собрал отчёт для команды за две недели"])]
    violations = lint_pitch(blocks, anchors=[])
    assert not any(v.rule == "no_anchor" for v in violations)


def test_lint_pitch_length_too_short() -> None:
    blocks = [PitchBlock(label="Кто я", lines=["Коротко о себе в двух словах"])]
    violations = lint_pitch(blocks, anchors=[])
    assert any(v.rule == "length" and "слов" in v.detail for v in violations)


def test_lint_pitch_length_too_long() -> None:
    long_text = " ".join(["слово"] * 270)
    blocks = [PitchBlock(label="Кто я", lines=[long_text])]
    violations = lint_pitch(blocks, anchors=[])
    # длинная строка сама по себе даёт ещё и long_line - проверяем именно length
    assert any(v.rule == "length" for v in violations)


def test_violations_to_prompt_numbers_claims() -> None:
    blocks = [PitchBlock(label="Что делал", lines=["Мы поставили guardrails здесь"])]
    violations = lint_pitch(blocks, anchors=[])
    prompt = violations_to_prompt(violations)
    assert prompt.startswith("1. ")
    assert prompt.count("\n") == len(violations) - 1


def test_violations_to_prompt_empty() -> None:
    assert violations_to_prompt([]) == ""


def test_speak_seconds() -> None:
    text = " ".join(["слово"] * 150)
    assert speak_seconds(text) == 68


def test_speak_seconds_empty() -> None:
    assert speak_seconds("") == 0


def test_banned_terms_all_present_in_oral_style_prompt() -> None:
    content = _ORAL_STYLE_PATH.read_text(encoding="utf-8").lower()
    missing = [term for term in BANNED_TERMS if term.lower() not in content]
    assert missing == []


# `lint_spoken_text` - тот же словарь правил, но для короткого устного текста (черновик ответа
# на HR-вопрос), без правил длины/привязки к вакансии, рассчитанных на целый монолог легенды.


def test_lint_spoken_text_catches_banned_term() -> None:
    violations = lint_spoken_text("Строил observability и guardrails для агентов.")
    assert any(v.rule == "banned_term" for v in violations)


def test_lint_spoken_text_catches_punctuation() -> None:
    violations = lint_spoken_text("Отвечаю честно — это моя основная зона.")
    assert any(v.rule == "punctuation" for v in violations)


def test_lint_spoken_text_catches_cliche() -> None:
    violations = lint_spoken_text("Закрывал весь цикл в прошлой компании.")
    assert any(v.rule == "cliche" for v in violations)


def test_lint_spoken_text_clean_is_empty() -> None:
    text = "Собирал сервис, который считает отчёт за пятнадцать минут.\nКоманда была довольна."
    assert lint_spoken_text(text) == []


def test_lint_spoken_text_ignores_length_and_anchor_rules() -> None:
    """Короткий ответ (пара предложений) не должен получать length/no_anchor - эти правила
    рассчитаны на 110-200-словный монолог легенды, а не на 2-4 фразы черновика ответа."""
    short_clean = "Собирал сервис на Python."
    violations = lint_spoken_text(short_clean)
    assert not any(v.rule in ("length", "no_anchor") for v in violations)
