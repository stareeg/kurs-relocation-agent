"""Э4.3 dual_employment_and_contracting_2026.md: анти-slop для английского в style_lint."""

from __future__ import annotations

from core.kernel.text.style_lint import EN_CHECKS, lint

_EN_SLOP_SAMPLE = """
I am excited to apply for this position - I have a proven track record of delivering results.
I am truly passionate about building highly scalable systems, and I believe I would be a great fit.
I think this role leverages my expertise perfectly: it is a fast-paced environment.
"""

_EN_HUMAN_SAMPLE = """
I shipped a data pipeline that cut a two-day manual reconciliation down to fifteen minutes.
The finance team stopped losing Fridays to spreadsheets and moved on to actual analysis.
I have three years of remote contract work across US and EU teams, four hours of daily overlap.
"""

_RU_HUMAN_SAMPLE = """
Я пять лет собираю сервисы, которые считают отчёты за людей.
В прошлой компании сведение таблиц отнимало у команды два дня.
Собрал сервис на Python - отчёт готов за пятнадцать минут.
"""


def test_en_slop_sample_yields_multiple_codes() -> None:
    issues = lint(_EN_SLOP_SAMPLE, checks=EN_CHECKS)
    codes = {iss.code for iss in issues}
    assert "en_cliche" in codes
    assert "en_padding" in codes


def test_en_clean_paragraph_has_no_en_issues() -> None:
    issues = lint(_EN_HUMAN_SAMPLE, checks=EN_CHECKS)
    codes = {iss.code for iss in issues}
    assert "en_cliche" not in codes
    assert "en_padding" not in codes
    assert "en_punctuation" not in codes


def test_ru_text_ru_checks_unaffected_by_en_checks_existing() -> None:
    """Регресс: RU-путь (DEFAULT_CHECKS) не задет добавлением EN_CHECKS."""
    from core.kernel.text.style_lint import DEFAULT_CHECKS

    assert "en_cliches" not in DEFAULT_CHECKS
    assert "en_padding" not in DEFAULT_CHECKS
    assert "en_punctuation" not in DEFAULT_CHECKS
    issues = lint(_RU_HUMAN_SAMPLE)
    assert issues == []
