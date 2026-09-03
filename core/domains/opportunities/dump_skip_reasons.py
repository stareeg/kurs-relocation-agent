"""Регенерация эталонного JSON-снапшота канона skip-reasons.

Запись: ``core/domains/opportunities/skip_reasons.json`` — читают vitest (frontend)
и extension/tests. Источник правды — ``SELF_SKIP_REASONS`` в ``skip_reasons.py``.

Запуск::

    python -m core.domains.opportunities.dump_skip_reasons
"""

from __future__ import annotations

import json
from pathlib import Path

from core.domains.opportunities.skip_reasons import SELF_SKIP_REASONS
from core.platform.observability.logging import ensure_utf8_console

OUT = Path(__file__).resolve().with_name("skip_reasons.json")


def dump_payload() -> dict[str, list[str]]:
    return {"self_skip_reasons": list(SELF_SKIP_REASONS)}


def main() -> None:
    ensure_utf8_console()
    payload = dump_payload()
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"skip-reasons → {OUT} ({len(payload['self_skip_reasons'])} шт.)")


if __name__ == "__main__":
    main()
