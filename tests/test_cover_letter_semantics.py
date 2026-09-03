"""FR3-65: letter_required ≠ факт наличия текста письма.

Площадка пишет letter_required (расширение / SERP); cover_letter_text — отдельно.
Генерация/сохранение текста не должно выставлять letter_required=True.
"""

from __future__ import annotations

import inspect

from api.routers import cover_letter as cover_letter_router
from core.app.scenarios import cover_letter as cover_letter_scenario


def test_cover_letter_scenario_does_not_set_letter_required_on_generate():
    """Исходник generate_for_job пишет только cover_letter_text (FR3-65/67, логика в scenarios)."""
    src = inspect.getsource(cover_letter_scenario.generate_for_job)
    assert "cover_letter_text=letter" in src
    assert "letter_required=True" not in src
    assert "letter_required=True" not in inspect.getsource(cover_letter_scenario)
    assert "letter_required=True" not in inspect.getsource(cover_letter_router)
