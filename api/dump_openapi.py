"""Дамп OpenAPI-схемы FastAPI-приложения в frontend/openapi.json (compact, без indent).

Регенерация типов фронта без живого сервера:
    python -m api.dump_openapi
    cd frontend; npm run gen-api:offline

Compact (separators без пробелов) держит диффы openapi.json маленькими.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.platform.observability.logging import ensure_utf8_console

# FR2-65: до любого print с кириллицей/стрелкой — иначе падение на cp1251/866-консоли.
ensure_utf8_console()

from api.main import app  # noqa: E402 - импорт после ensure_utf8_console() нарочно, см. выше

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "openapi.json"


def main() -> None:
    ensure_utf8_console()
    schema = app.openapi()
    OUT.write_text(json.dumps(schema, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"OpenAPI → {OUT} ({OUT.stat().st_size} байт)")


if __name__ == "__main__":
    main()
