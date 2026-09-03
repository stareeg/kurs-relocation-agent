"""Тесты сборки скачиваемого архива расширения.

Проверяют два инварианта build_extension_zip: allowlist (в архиве нет src/node_modules/tests)
и полноту шип-набора (все корневые файлы + dist/icons попадают в архив, если есть на диске).
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

from core.platform.repo.extension_bundle import (
    _SHIP_DIRS,
    _SHIP_ROOT_FILES,
    build_extension_zip,
)

_EXT_DIR = Path(__file__).resolve().parents[1] / "extension"


def _zip_names(data: bytes) -> set[str]:
    with zipfile.ZipFile(BytesIO(data)) as zf:
        return set(zf.namelist())


def test_extension_zip_contains_only_ship_allowlist() -> None:
    names = _zip_names(build_extension_zip())
    assert names, "архив не должен быть пустым"
    for name in names:
        top = name.split("/", 1)[0]
        assert top in {*_SHIP_ROOT_FILES, *_SHIP_DIRS}, f"лишний файл в архиве: {name}"


def test_extension_zip_contains_all_ship_files_present_on_disk() -> None:
    names = _zip_names(build_extension_zip())
    for name in _SHIP_ROOT_FILES:
        if (_EXT_DIR / name).is_file():
            assert name in names
    for dirname in _SHIP_DIRS:
        for path in (_EXT_DIR / dirname).rglob("*"):
            if path.is_file():
                # as_posix(): в zip-архиве слэши прямые даже на Windows.
                assert path.relative_to(_EXT_DIR).as_posix() in names
