"""Сборка скачиваемого архива расширения: страница «Расширение» больше не отдаёт
абсолютный путь на диске сервера (бессмысленно, когда бэкенд — на VM, а не на машине
пользователя) — вместо этого пользователь скачивает готовый .zip и распаковывает сам.

Архив собирается по явному allowlist (`_SHIP_ROOT_FILES`/`_SHIP_DIRS`), а не «всё из папки» —
иначе в архив попадут `src/`/`node_modules/`/`tests/` (раздутый файл и утечка исходников на
клиента). Содержимое — ровно то, что нужно Chrome для «Загрузить распакованное».
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

_SHIP_ROOT_FILES = ("manifest.json", "options.html", "popup.html")
_SHIP_DIRS = ("dist", "icons")  # только собранное + иконки — не src/, node_modules/, tests/


def build_extension_zip() -> bytes:
    """Собрать архив расширения в памяти и вернуть готовые байты zip-архива."""
    ext_dir = Path(__file__).resolve().parents[3] / "extension"
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in _SHIP_ROOT_FILES:
            path = ext_dir / name
            if path.is_file():
                zf.writestr(name, path.read_bytes())
        for dirname in _SHIP_DIRS:
            for path in sorted((ext_dir / dirname).rglob("*")):
                if path.is_file():
                    zf.writestr(str(path.relative_to(ext_dir)), path.read_bytes())
    return buf.getvalue()
