"""Шаг 30 universal profile: общий анти-slop линтер `core.kernel.text.style_lint`."""

from __future__ import annotations

from core.kernel.text.style_lint import (
    StyleIssue,
    check_anglicisms,
    check_cliches,
    check_line_length,
    check_monotony,
    check_officialese,
    check_punctuation,
    lint,
)

# Слоп-образец из части 0 `plans/2026-07-23_screening_antislop.md` (oral_pitch AIT.LAB).
_SLOP_SAMPLE = """
Я Lead LLM Engineer из Сбера, два года строил production multi-agent систему Data Copilot.
Оркестрировал агентов на LangGraph по supervisor-паттерну - researcher, planner, coder,
reviewer с self-correction петлями. Закрывал весь цикл: от прототипа через eval-инфру и
LLMOps до эксплуатации на ПРОДЕ с Langfuse и MLflow. Строил observability и guardrails.
Оптимизировал инференс на 40%. Работал с enterprise harness и SOTA reliability.
В AIT.LAB вижу возможность масштабировать эти подходы на уровне платформы.
"""

_HUMAN_SAMPLE = """
Я пять лет собираю сервисы, которые считают отчёты за людей.
В прошлой компании сведение таблиц отнимало у команды два дня.
Собрал сервис на Python - отчёт готов за пятнадцать минут.
Команда перестала терять пятницы и занялась анализом.
"""


def test_slop_sample_yields_at_least_four_distinct_codes() -> None:
    issues = lint(_SLOP_SAMPLE, allowed_terms={"LangGraph", "Langfuse", "MLflow", "Python"})
    codes = {iss.code for iss in issues}
    assert len(codes) >= 4, f"ожидали ≥4 разных code, получили {sorted(codes)}: {issues}"


def test_human_paragraph_is_clean() -> None:
    assert lint(_HUMAN_SAMPLE, allowed_terms={"Python"}) == []


def test_check_anglicisms_respects_density_threshold() -> None:
    # Мало латиницы относительно длины - не флагируем.
    short = "Я собрал сервис на Python для команды отчётности за две недели работы."
    assert check_anglicisms(short, {"python"}) == []

    dense = "production multi-agent supervisor eval LLMOps observability reliability harness SOTA"
    hits = check_anglicisms(dense, set())
    assert hits and hits[0].code == "anglicism"


def test_check_officialese() -> None:
    text = "В рамках проекта осуществлял внедрение и реализовывал улучшения."
    issues = check_officialese(text)
    assert any(iss.code == "officialese" for iss in issues)


def test_check_punctuation_emdash_and_colon() -> None:
    text = "Закрывал весь цикл: от прототипа до сдачи — быстро."
    codes = {iss.code for iss in check_punctuation(text)}
    assert codes == {"punctuation"}
    assert len(check_punctuation(text)) >= 2


def test_check_monotony_past_tense_run() -> None:
    text = (
        "Собрал сервис для команды за две недели. "
        "Оптимизировал отчёт так, чтобы он считался быстрее. "
        "Запустил сервис в работу без единого отката."
    )
    assert any(iss.code == "monotony" for iss in check_monotony(text))


def test_check_cliches() -> None:
    assert check_cliches("В AIT.LAB вижу возможность масштабировать подходы.") != []


def test_check_line_length() -> None:
    long_line = " ".join(["слово"] * 20)
    issues = check_line_length(long_line, max_words=18)
    assert issues and issues[0].code == "line_length"


def test_lint_selects_checks() -> None:
    text = "В рамках проекта вижу возможность расти."
    only_cliche = lint(text, checks=("cliches",))
    assert all(iss.code == "cliche" for iss in only_cliche)
    assert only_cliche


def test_style_issue_shape() -> None:
    iss = StyleIssue(code="cliche", message="тест", sample="вижу возможность")
    assert iss.code == "cliche"
    assert iss.sample == "вижу возможность"
