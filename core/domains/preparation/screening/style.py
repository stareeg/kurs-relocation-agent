"""Реэкспорт устного анти-slop линтера из `core.kernel.text.style_lint` (шаг 30 universal profile).

Реализация перенесена в общий модуль; импорты `core.domains.preparation.screening.style` сохраняются без изменений.
"""

from __future__ import annotations

from core.kernel.text.style_lint import (
    ALLOWED_NAMES,
    BANNED_TERMS,
    CLICHES,
    PitchBlock,
    StyleViolation,
    lint_pitch,
    lint_spoken_text,
    speak_seconds,
    violations_to_prompt,
)

__all__ = [
    "ALLOWED_NAMES",
    "BANNED_TERMS",
    "CLICHES",
    "PitchBlock",
    "StyleViolation",
    "lint_pitch",
    "lint_spoken_text",
    "speak_seconds",
    "violations_to_prompt",
]
