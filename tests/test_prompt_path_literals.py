"""Литералы путей к промптам в коде указывают на существующие файлы.

`tests/test_settings_paths_exist.py` проверяет только декларации (`domains/*/llm.PROMPT_PATHS`
и `LlmFeature.prompt`). Но часть промптов грузится литералом прямо в модуле домена
(`Path("prompts/…")` + `_load_prompt_file`), и такие пути рефактор R не переехал: четыре
константы в `core/domains/preparation/interview/prep.py` продолжали смотреть на
`prompts/interview/*.md` после переезда в `prompts/preparation/interview/*.md`. Наружу это
выходило как 500 на «Контекст для sobes.tech»/«Импорт» и 503 на «Собрать темы» — ошибка
вылезала только в рантайме, на живом клике.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SCANNED_PACKAGES = ("core", "api", "bot_app")
#: `"prompts/foo/bar.md"` или `'prompts\\foo\\bar.md'` в любом строковом литерале.
_PROMPT_LITERAL_RE = re.compile(r"""["'](prompts[/\\][^"'\n]+\.md)["']""")


def _iter_prompt_literals():
    for package in _SCANNED_PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for match in _PROMPT_LITERAL_RE.finditer(source):
                yield path.relative_to(ROOT).as_posix(), match.group(1)


def test_prompt_path_literals_point_to_existing_files():
    """Каждый `prompts/*.md` литерал в core/api/bot_app — существующий файл."""
    missing = [
        f"{rel}: {raw!r}"
        for rel, raw in _iter_prompt_literals()
        if not (ROOT / raw.replace("\\", "/")).is_file()
    ]
    assert not missing, (
        "Литерал пути к промпту не указывает на файл (переименовали/перенесли промпт "
        "и забыли поправить код?):\n" + "\n".join(missing)
    )


def test_scan_actually_finds_prompt_literals():
    """Страховка от «зелёного» теста при сломанном сканере."""
    found = list(_iter_prompt_literals())
    assert len(found) >= 4, f"ожидали найти литералы промптов, получили {found}"
