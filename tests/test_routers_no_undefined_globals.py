"""Ни одна ручка API не должна звать имя, которого в её модуле нет.

Прод-инцидент 2026-08-31: `api/routers/pipeline/auto_apply.py` звал `event(...)` в трёх
местах, забыв импорт. Ручки `/preview`, `/manual-send` и `/clear-manual-send` падали с
`NameError` в рантайме — 500 на каждый опрос страницы «Расширение», раннер расширения
переставал работать, а снять залипший флаг было нечем (ручка снятия падала так же).

Ruff (F821) это ловит, но в тот момент CI не запускался (кончился биллинг GitHub Actions,
деплой шёл руками) — поэтому держим ту же проверку и в тестах, которые владелец гоняет
локально перед деплоем. `symtable` даёт ровно нужное: имена, которые тело функции читает
как ГЛОБАЛЬНЫЕ (локальные, аргументы и переменные comprehension сюда не попадают).
"""

from __future__ import annotations

import builtins
import importlib
import pkgutil
import symtable
from pathlib import Path

import pytest

import api.routers

_ROUTERS_DIR = Path(api.routers.__file__).parent


def _router_modules() -> list[str]:
    names = []
    for info in pkgutil.walk_packages([str(_ROUTERS_DIR)], prefix="api.routers."):
        if not info.ispkg:
            names.append(info.name)
    return sorted(names)


def _global_reads(table: symtable.SymbolTable) -> set[str]:
    """Имена, читаемые как глобальные, во всех вложенных блоках таблицы."""
    found: set[str] = set()
    for symbol in table.get_symbols():
        if symbol.is_global() and symbol.is_referenced():
            found.add(symbol.get_name())
    for child in table.get_children():
        found |= _global_reads(child)
    return found


@pytest.mark.parametrize("module_name", _router_modules())
def test_router_module_defines_every_global_it_reads(module_name: str) -> None:
    module = importlib.import_module(module_name)
    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    table = symtable.symtable(source, module.__file__ or module_name, "exec")

    missing = sorted(
        name
        for name in _global_reads(table)
        if not hasattr(module, name) and not hasattr(builtins, name)
    )
    assert not missing, f"{module_name}: имена без определения/импорта — {missing}"
