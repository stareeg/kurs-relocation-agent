"""Э17.6: generic-хаб столов не должен знать, во что играют.

`session.py` — комнаты, коннекты, reconnect по seat_token, таймеры фаз, presence, рассылка,
idle-GC. Всё это переиспользуется второй игрой как есть. Чтобы это оставалось правдой, хаб не
имеет права дотягиваться до правил «Хрюш и Волков» напрямую — только через `engine.GameEngine`.

Тест держит границу от размывания: следующая правка в `session.py`, которой «проще» дёрнуть
`rules.apply` или `models.Phase`, упрётся сюда, а не всплывёт через полгода, когда вторую игру
уже нельзя будет подключить без переписывания хаба.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOMAIN = ROOT / "core" / "domains" / "multiplayer"

#: Модули с содержимым конкретной игры: правила, состояние, колода, проекции, её LLM-фичи.
GAME_MODULES = frozenset({"rules", "models", "views", "deck", "wolves_llm", "wolves_engine"})


def _imported_domain_modules(path: Path, *, module_level_only: bool = False) -> set[str]:
    """Какие соседние модули домена импортирует файл.

    `module_level_only` — считать только импорты на верхнем уровне: ленивый импорт внутри
    функции это отдельный, осознанный приём (так реестр в `engine.py` достаёт движок, не
    завязывая на него сам протокол).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    prefix = "core.domains.multiplayer"
    nodes = tree.body if module_level_only else list(ast.walk(tree))
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == prefix:
                found.update(alias.name for alias in node.names)
            elif mod.startswith(f"{prefix}."):
                found.add(mod[len(prefix) + 1 :].split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{prefix}."):
                    found.add(alias.name[len(prefix) + 1 :].split(".")[0])
    return found


def test_session_does_not_import_game_modules() -> None:
    leaked = _imported_domain_modules(DOMAIN / "session.py") & GAME_MODULES
    assert not leaked, (
        f"session.py снова тянет игровые модули: {sorted(leaked)}. "
        "Хаб обязан ходить через engine.GameEngine — иначе вторую игру не подключить, "
        "не переписав session.py (Э17)"
    )


def test_engine_protocol_does_not_import_the_game() -> None:
    """`engine.py` — сам протокол; конкретную игру он достаёт лениво, внутри `get_engine`."""
    imported = _imported_domain_modules(DOMAIN / "engine.py", module_level_only=True)
    forbidden = (imported & GAME_MODULES) - {"models"}
    assert not forbidden, (
        f"engine.py тянет игру на уровне модуля: {sorted(forbidden)}. "
        "Реестр обязан импортировать движок лениво (см. get_engine)"
    )


def test_engine_imports_models_only_for_the_error() -> None:
    """Единственная уступка: `IllegalMove` — часть контракта хаба, живёт в models.py."""
    tree = ast.parse((DOMAIN / "engine.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("multiplayer.models"):
            names.extend(alias.name for alias in node.names)
    assert names == ["IllegalMove"], (
        f"из models.py в engine.py разрешён только IllegalMove, а импортируется {names}"
    )


def test_wolves_engine_registered() -> None:
    from core.domains.multiplayer.engine import get_engine, known_game_ids

    assert "wolves" in known_game_ids()
    engine = get_engine("wolves")
    assert engine.game_id == "wolves"
    assert engine.host_seat_id == "hr"
    # Реестр кеширует — хаб дёргает `session.engine` на каждый чих.
    assert get_engine("wolves") is engine


def test_unknown_game_is_rejected() -> None:
    import pytest

    from core.domains.multiplayer.engine import get_engine

    with pytest.raises(KeyError):
        get_engine("offer-auction")


def test_engine_satisfies_protocol_surface() -> None:
    """Каждый метод протокола реально реализован — Protocol сам этого не проверяет."""
    from core.domains.multiplayer.engine import GameEngine, get_engine

    engine = get_engine("wolves")
    missing = [
        name
        for name in vars(GameEngine)
        if not name.startswith("_") and not hasattr(engine, name)
    ]
    assert not missing, f"WolvesEngine не реализует методы протокола: {missing}"
