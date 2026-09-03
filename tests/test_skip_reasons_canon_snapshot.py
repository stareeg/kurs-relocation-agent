"""FR2-78: committed JSON-снапшот ≡ SELF_SKIP_REASONS.

Frontend/extension сверяют чипы с ``core/domains/opportunities/skip_reasons.json``.
Если поменять канон в Python и забыть ``python -m core.domains.opportunities.dump_skip_reasons`` —
этот тест красный; если править JSON руками мимо Python — тоже.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.domains.opportunities.dump_skip_reasons import OUT, dump_payload
from core.domains.opportunities.skip_reasons import SELF_SKIP_REASONS


def test_skip_reasons_json_matches_python_canon():
    assert OUT.is_file(), f"Нет снапшота {OUT}; запусти python -m core.domains.opportunities.dump_skip_reasons"
    on_disk = json.loads(OUT.read_text(encoding="utf-8"))
    expected = dump_payload()
    assert on_disk == expected, (
        "skip_reasons.json разошёлся с SELF_SKIP_REASONS — "
        "перегенерируй: python -m core.domains.opportunities.dump_skip_reasons"
    )
    assert on_disk["self_skip_reasons"] == list(SELF_SKIP_REASONS)


def test_skip_reasons_json_is_stable_path():
    """Путь снапшота — рядом с модулем, чтобы FE/ext находили его от корня репо."""
    assert OUT == Path(__file__).resolve().parents[1] / "core" / "domains" / "opportunities" / "skip_reasons.json"
