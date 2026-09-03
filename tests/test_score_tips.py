"""Формат подсказок в спойлерах балла резюме."""

from __future__ import annotations

from core.domains.profile.gap import WeakBullet
from core.domains.profile.score_tips import (
    format_role_fit_note,
    format_writing_tip,
    normalize_score_tip,
)


def test_normalize_score_tip_strips_slop_prefix() -> None:
    assert normalize_score_tip("Слабый: нет конкретного действия") == "добавьте конкретное действие"
    assert normalize_score_tip("нет результата") == "добавьте результат"
    assert normalize_score_tip("Рекомендуется добавить метрики") == "добавить метрики"


def test_format_writing_tip_one_line() -> None:
    b = WeakBullet(
        section="experience",
        ref="Сбер — Lead",
        text="Занимался развитием команды",
        reason="общая фраза без результата",
    )
    line = format_writing_tip(b)
    assert line.startswith("Сбер — Lead:")
    assert "«Занимался развитием команды»" in line
    assert "общая фраза без результата" in line


def test_format_writing_tip_default_without_reason() -> None:
    b = WeakBullet(section="about", ref="Обо мне", text="Ответственный специалист")
    assert "добавьте действие" in format_writing_tip(b)


def test_format_role_fit_note() -> None:
    assert format_role_fit_note("Рекомендуется добавить RAG в навыки") == "добавить RAG в навыки"
