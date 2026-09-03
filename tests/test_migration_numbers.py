"""FR2-66: номера SQL-миграций уникальны (кроме исторической пары 0020).

Раннер (`core/platform/db/migrate.py`) ключует применённые файлы по полному имени в
`schema_migrations`, поэтому два файла с одним префиксом `NNNN_` на живой БД уже
записаны как есть. Переименовывать исторические дубли нельзя — сломает учёт.
Тест держит allowlist только для этой пары и запрещает любые новые коллизии.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "core" / "platform" / "db" / "migrations"

# Единственный разрешённый дубль. Файлы НЕ переименовывать.
ALLOWED_DUPLICATE_NUMBERS: dict[str, frozenset[str]] = {
    "0020": frozenset(
        {
            "0020_stage_outcomes.sql",
            "0020_conversation_kind.sql",
        }
    ),
}

_PREFIX_RE = re.compile(r"^(\d{4})_.+\.sql$")


def _files_by_number() -> dict[str, list[str]]:
    by_num: dict[str, list[str]] = defaultdict(list)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = _PREFIX_RE.match(path.name)
        assert m, (
            f"Миграция с неверным именем: {path.name!r} "
            "(ожидается NNNN_description.sql, ровно 4 цифры)"
        )
        by_num[m.group(1)].append(path.name)
    return dict(by_num)


def test_migration_numbers_unique_except_allowlisted_0020() -> None:
    by_num = _files_by_number()
    assert by_num, f"нет миграций в {MIGRATIONS_DIR}"

    # Allowlist не протух: оба исторических файла на месте.
    for number, expected in ALLOWED_DUPLICATE_NUMBERS.items():
        actual = set(by_num.get(number, []))
        assert actual == set(expected), (
            f"Allowlist для {number} рассинхронен с диском: "
            f"ожидалось {sorted(expected)}, есть {sorted(actual)}. "
            "Не переименовывать 0020_* — обновить allowlist только если пара "
            "осознанно менялась (почти никогда)."
        )

    offenders: list[str] = []
    for number, names in sorted(by_num.items()):
        if len(names) < 2:
            continue
        allowed = ALLOWED_DUPLICATE_NUMBERS.get(number)
        if allowed is not None and set(names) == set(allowed):
            continue
        offenders.append(f"{number}: {sorted(names)}")

    assert not offenders, (
        "Дубли номеров миграций (новые запрещены; историческая пара 0020 уже в "
        f"allowlist):\n  - " + "\n  - ".join(offenders) + "\n"
        "Возьми следующий свободный NNNN_ после max(существующих), не копируй номер."
    )
