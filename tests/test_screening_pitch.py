"""План 2026-07-23, шаг 6: устный рассказ под вакансию (`core/screening/pitch.py`)."""

from __future__ import annotations

import json

import pytest

from core.domains.preparation.screening import pitch as pitch_module
from core.domains.preparation.screening.brief import JdBrief, JdRequirement
from core.domains.preparation.screening.pitch import (
    PITCH_LABELS,
    ScreeningPitch,
    generate_screening_pitch,
    parse_pitch,
    pitch_to_plain_text,
)
from core.domains.preparation.screening.style import PitchBlock
from tests.fakes import FakeLlm, use_fake_llm

_FULL_RAW = json.dumps(
    {
        "blocks": [
            {"label": "Финал", "lines": ["Расскажите про следующий шаг"]},
            {
                "label": "Кто я",
                "lines": ["Я инженер, который переводит процессы в понятные сценарии"],
            },
            {
                "label": "Что делал",
                "lines": ["Собрал сервис на Python, который считает отчёт за пятнадцать минут"],
            },
        ],
        "why_company": "Задача близка к тому, что уже делал",
    },
    ensure_ascii=False,
)


def test_parse_pitch_sorts_blocks_into_canonical_order() -> None:
    pitch = parse_pitch(_FULL_RAW)
    assert [b.label for b in pitch.blocks] == ["Кто я", "Что делал", "Финал"]
    assert pitch.why_company == "Задача близка к тому, что уже делал"


def test_parse_pitch_drops_blocks_with_foreign_label() -> None:
    raw = json.dumps(
        {
            "blocks": [
                {"label": "Кто я", "lines": ["Норм строка"]},
                {"label": "Незнакомый блок", "lines": ["Мусор"]},
            ],
            "why_company": "",
        },
        ensure_ascii=False,
    )
    pitch = parse_pitch(raw)
    assert len(pitch.blocks) == 1
    assert pitch.blocks[0].label == "Кто я"


def test_parse_pitch_drops_block_with_no_lines() -> None:
    raw = json.dumps(
        {"blocks": [{"label": "Кто я", "lines": []}], "why_company": ""},
        ensure_ascii=False,
    )
    pitch = parse_pitch(raw)
    assert pitch.blocks == []


def test_parse_pitch_not_json_object_raises() -> None:
    with pytest.raises(ValueError, match="не JSON-объект"):
        parse_pitch("[1, 2, 3]")


def test_pitch_to_plain_text_joins_blocks_with_blank_line() -> None:
    blocks = [
        PitchBlock(label="Кто я", lines=["Строка раз", "Строка два"]),
        PitchBlock(label="Финал", lines=["Передаю ход"]),
    ]
    text = pitch_to_plain_text(blocks)
    assert text == "Строка раз\nСтрока два\n\nПередаю ход"


def test_pitch_to_plain_text_skips_empty_blocks() -> None:
    blocks = [PitchBlock(label="Кто я", lines=[]), PitchBlock(label="Финал", lines=["Ход"])]
    assert pitch_to_plain_text(blocks) == "Ход"


async def _async_result(value):
    return value


def _brief() -> JdBrief:
    return JdBrief(
        role_reality="Строить сервисы автоматизации",
        requirements=[JdRequirement(text="опыт с LLM в проде", quote="LLM в prod", weight="must")],
        jargon=["Python"],
    )


async def test_generate_screening_pitch_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pitch_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": ""})()
    )
    with pytest.raises(Exception, match="OPENROUTER_API_KEY"):
        await generate_screening_pitch(account_id=1, brief=_brief())


async def test_generate_screening_pitch_repairs_once_on_violations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pitch_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": "test"})()
    )
    monkeypatch.setattr(pitch_module, "_load_system_prompt", lambda **_: _async_result("SYSTEM"))

    dirty = json.dumps(
        {
            "blocks": [
                {"label": "Кто я", "lines": ["Мы поставили guardrails здесь: и это провал"]}
            ],
            "why_company": "",
        },
        ensure_ascii=False,
    )
    clean = json.dumps(
        {
            "blocks": [
                {
                    "label": "Кто я",
                    "lines": ["Собираю сервисы автоматизации для команд последние годы"],
                }
            ],
            "why_company": "",
        },
        ensure_ascii=False,
    )

    calls: list[str] = []

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        assert feature == "screening_pitch"
        calls.append(user)
        return dirty if len(calls) == 1 else clean

    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    result = await generate_screening_pitch(account_id=1, brief=_brief())
    assert len(calls) == 2
    assert "Нарушения устного стиля" in calls[1]
    assert result.blocks[0].lines == ["Собираю сервисы автоматизации для команд последние годы"]


async def test_generate_screening_pitch_retries_once_on_broken_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Живой баг 2026-07-23: первый ответ Claude с битым JSON ронял весь рассказ → на Скринингах
    оставались только вопросы. Один повтор с подсказкой про синтаксис."""
    monkeypatch.setattr(
        pitch_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": "test"})()
    )
    monkeypatch.setattr(pitch_module, "_load_system_prompt", lambda **_: _async_result("SYSTEM"))

    # Текст без нарушений устного стиля - иначе после успешного JSON пойдёт ещё и style-repair.
    clean_blocks = [
        {
            "label": "Кто я",
            "lines": [
                "Я инженер, который переводит рабочие процессы в понятные автоматические сценарии",
                "Пять лет собираю системы, которые считают и подсказывают, а не просто хранят "
                "данные",
                "За это время прошёл путь от разработчика до тимлида небольшой команды",
                "Умею объяснять сложные технические решения простым языком команде и заказчику",
                "Особенно нравится доводить решения до реального использования в команде",
            ],
        },
        {
            "label": "Что делал",
            "lines": [
                "В прошлой компании автоматизация отчётности отнимала у команды два дня",
                "Я собрал сервис на Python, который считает отчёт за пятнадцать минут",
                "Команда перестала терять пятницы на сведение таблиц и начала тратить время на "
                "анализ",
                "До этого пробовали закрывать процесс таблицами и ручными напоминаниями, но это "
                "не помогало",
                "После запуска сервиса ошибки в отчётах упали почти до нуля",
            ],
        },
        {
            "label": "Мост к вакансии",
            "lines": [
                "Вижу в вашей вакансии похожую задачу с автоматизацией процессов",
                "Такие сценарии я уже строил на Python и знаю, где обычно теряется время",
                "Также помогаю командам разбираться, где именно теряются часы в текущих процессах",
            ],
        },
        {
            "label": "Почему сюда",
            "lines": [
                "Задача близка к тому, что я уже делал, поэтому интерес предметный, а не общий"
            ],
        },
        {
            "label": "Что ищу",
            "lines": [
                "Хочу работать там, где автоматизация реально освобождает время живых людей",
                "Важна команда, которая сама проверяет цифры, а не верит на слово",
                "Также хочется расти в сторону более сложных технических задач",
                "Комфортнее в командах, где решения обсуждают открыто и по делу",
            ],
        },
        {
            "label": "Финал",
            "lines": ["Расскажите, как у вас устроена работа с отчётностью сегодня"],
        },
    ]
    clean = json.dumps(
        {"blocks": clean_blocks, "why_company": "Подходит по стеку"},
        ensure_ascii=False,
    )
    calls: list[str] = []

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        calls.append(user)
        if len(calls) == 1:
            return '{"blocks": [{"label": "Кто я", "lines": ["текст с "кавычкой"]}],'
        return clean

    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    result = await generate_screening_pitch(account_id=1, brief=JdBrief())
    assert len(calls) == 2
    assert "валидный JSON" in calls[1]
    assert [b.label for b in result.blocks] == list(PITCH_LABELS)


async def test_generate_screening_pitch_broken_json_twice_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pitch_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": "test"})()
    )
    monkeypatch.setattr(pitch_module, "_load_system_prompt", lambda **_: _async_result("SYSTEM"))

    calls = 0

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        nonlocal calls
        calls += 1
        return "не json"

    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    with pytest.raises(Exception, match="некорректный формат"):
        await generate_screening_pitch(account_id=1, brief=_brief())
    assert calls == 2


async def test_generate_screening_pitch_repair_failure_falls_back_to_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Доп. усиление надёжности после живой проверки шага 16: сам ремонтный вызов упал (сеть/битый
    JSON) - возвращаем черновик до ремонта, а не роняем весь рассказ целиком."""
    monkeypatch.setattr(
        pitch_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": "test"})()
    )
    monkeypatch.setattr(pitch_module, "_load_system_prompt", lambda **_: _async_result("SYSTEM"))

    dirty = json.dumps(
        {
            "blocks": [
                {"label": "Кто я", "lines": ["Мы поставили guardrails здесь: и это провал"]}
            ],
            "why_company": "",
        },
        ensure_ascii=False,
    )

    calls: list[str] = []

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        calls.append(user)
        return dirty if len(calls) == 1 else "не json"

    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    result = await generate_screening_pitch(account_id=1, brief=_brief())
    assert len(calls) == 2
    assert result.blocks[0].lines == ["Мы поставили guardrails здесь: и это провал"]


async def test_generate_screening_pitch_no_repair_when_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pitch_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": "test"})()
    )
    monkeypatch.setattr(pitch_module, "_load_system_prompt", lambda **_: _async_result("SYSTEM"))

    clean_blocks = [
        {
            "label": "Кто я",
            "lines": [
                "Я инженер, который переводит рабочие процессы в понятные автоматические сценарии",
                "Пять лет собираю системы, которые считают и подсказывают, а не просто хранят "
                "данные",
                "За это время прошёл путь от разработчика до тимлида небольшой команды",
                "Умею объяснять сложные технические решения простым языком команде и заказчику",
                "Особенно нравится доводить решения до реального использования в команде",
            ],
        },
        {
            "label": "Что делал",
            "lines": [
                "В прошлой компании автоматизация отчётности отнимала у команды два дня",
                "Я собрал сервис на Python, который считает отчёт за пятнадцать минут",
                "Команда перестала терять пятницы на сведение таблиц и начала тратить время на "
                "анализ",
                "До этого пробовали закрывать процесс таблицами и ручными напоминаниями, но это "
                "не помогало",
                "После запуска сервиса ошибки в отчётах упали почти до нуля",
            ],
        },
        {
            "label": "Мост к вакансии",
            "lines": [
                "Вижу в вашей вакансии похожую задачу с автоматизацией процессов",
                "Такие сценарии я уже строил на Python и знаю, где обычно теряется время",
                "Также помогаю командам разбираться, где именно теряются часы в текущих процессах",
            ],
        },
        {
            "label": "Почему сюда",
            "lines": [
                "Задача близка к тому, что я уже делал, поэтому интерес предметный, а не общий"
            ],
        },
        {
            "label": "Что ищу",
            "lines": [
                "Хочу работать там, где автоматизация реально освобождает время живых людей",
                "Важна команда, которая сама проверяет цифры, а не верит на слово",
                "Также хочется расти в сторону более сложных технических задач",
                "Комфортнее в командах, где решения обсуждают открыто и по делу",
            ],
        },
        {
            "label": "Финал",
            "lines": ["Расскажите, как у вас устроена работа с отчётностью сегодня"],
        },
    ]
    clean = json.dumps(
        {"blocks": clean_blocks, "why_company": "Подходит по стеку"},
        ensure_ascii=False,
    )

    calls = 0

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        nonlocal calls
        calls += 1
        return clean

    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    result = await generate_screening_pitch(account_id=1, brief=JdBrief())
    assert calls == 1
    assert [b.label for b in result.blocks] == list(PITCH_LABELS)
    assert isinstance(result, ScreeningPitch)
