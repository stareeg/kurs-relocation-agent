"""FR2-69: cap spool + chunked replay в PgLogSink."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from core.platform.observability.pg_sink import PgLogSink, trim_spool_bytes


def _line(msg: str) -> bytes:
    return (json.dumps({"msg": msg}, ensure_ascii=False) + "\n").encode("utf-8")


def test_trim_spool_bytes_keeps_tail_on_line_boundary() -> None:
    data = b"".join(_line(f"old-{i}") for i in range(10)) + b"".join(
        _line(f"new-{i}") for i in range(5)
    )
    # Окно меньше целого файла — должны остаться только «new-*» (или хвост с полной строкой).
    trimmed = trim_spool_bytes(data, max_bytes=len(b"".join(_line(f"new-{i}") for i in range(5))) + 3)
    text = trimmed.decode("utf-8")
    assert "old-0" not in text
    assert "new-4" in text
    for raw in text.splitlines():
        json.loads(raw)  # только целые JSON-строки


def test_trim_spool_bytes_noop_when_under_cap() -> None:
    data = _line("only")
    assert trim_spool_bytes(data, max_bytes=10_000) == data


@pytest.mark.asyncio
async def test_spool_cap_drops_old_lines_with_one_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    spool = tmp_path / "_pg_spool.jsonl"
    sink = PgLogSink(pool=None, spool_path=spool, spool_max_bytes=400)

    # Набьём больше лимита несколькими батчами.
    with caplog.at_level(logging.WARNING, logger="core.observability.pg_sink"):
        for i in range(40):
            sink._spool_rows([{"msg": f"row-{i}", "level": "INFO"}])

    assert spool.exists()
    assert spool.stat().st_size <= 400
    msgs = [r.get("msg") for r in (json.loads(line) for line in spool.read_text(encoding="utf-8").splitlines() if line.strip())]
    assert msgs
    assert msgs[-1] == "row-39"
    # Старые ушли.
    assert "row-0" not in msgs

    warnings = [r for r in caplog.records if "превысил" in r.getMessage()]
    assert len(warnings) == 1  # одна WARNING на эпизод, не на каждый батч


@pytest.mark.asyncio
async def test_replay_spool_reads_in_chunks(tmp_path: Path) -> None:
    spool = tmp_path / "_pg_spool.jsonl"
    rows = [{"msg": f"m-{i}", "level": "INFO"} for i in range(5)]
    spool.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )

    inserted: list[list[dict]] = []

    class FakePool:
        async def executemany(self, _sql: str, args: list) -> None:
            inserted.append(list(args))

    sink = PgLogSink(
        pool=FakePool(),
        spool_path=spool,
        batch_size=2,
        spool_max_bytes=10_000_000,
    )
    await sink._replay_spool()

    # 5 строк / batch_size=2 → 3 чанка (2+2+1), не один гигантский insert.
    assert len(inserted) == 3
    assert sum(len(c) for c in inserted) == 5
    assert not spool.exists()
    assert not sink._replaying_path().exists()


@pytest.mark.asyncio
async def test_replay_failure_restores_remainder(tmp_path: Path) -> None:
    spool = tmp_path / "_pg_spool.jsonl"
    rows = [{"msg": f"m-{i}", "level": "INFO"} for i in range(4)]
    spool.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )

    class FlakyPool:
        def __init__(self) -> None:
            self.calls = 0

        async def executemany(self, _sql: str, args: list) -> None:
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("pg down")

    pool = FlakyPool()
    sink = PgLogSink(pool=pool, spool_path=spool, batch_size=2)
    await sink._replay_spool()

    # Первый чанк (2) прошёл, второй упал → в spool остались failed chunk + хвост.
    assert spool.exists()
    left = [json.loads(line)["msg"] for line in spool.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert left == ["m-2", "m-3"]
    assert not sink._replaying_path().exists()
