"""Э2-5 (`plans/chat_image_attachments_2026_08_03.md`): связки вложений с HR-
сообщениями — `repo.link_hr_message_attachments`/`repo.load_hr_message_attachments`.

M4 (plans/multitenancy_gaps_2026_08_06.md §3.5): бывшие surface-агностичные
`link_message_attachments`/`load_message_attachments` заменены парой, специфичной для
`hr_message_attachments` (та же таблица, но теперь несёт `account_id`) — тот же приём, что
`link_debrief_attachments`/`link_prep_chat_attachments` в M3.

Отдельный файл от `test_attachments_repo.py`: здесь нужен join с `attachments`, поэтому фейк
держит обе "таблицы" и умеет параметризованный SQL с именем таблицы связок.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.domains.assistant.attachments import repo
from core.domains.assistant.attachments.models import AttachmentAnalysis

_ACCOUNT_A = 1
_ACCOUNT_B = 2


class FakeLinksDb:
    def __init__(self) -> None:
        self._attachments: dict[int, dict[str, Any]] = {}
        self._links: dict[str, list[dict[str, Any]]] = {}
        self._next_id = 1

    def add_attachment(self, **overrides: Any) -> int:
        row_id = self._next_id
        self._next_id += 1
        row = {
            "id": row_id,
            "sha256": f"sha-{row_id}",
            "mime": "image/webp",
            "width": 100,
            "height": 50,
            "bytes": 10,
            "thumb_width": 50,
            "thumb_height": 25,
            "derived_from": None,
            "crop": None,
            "analysis_status": "pending",
            "analysis": None,
            "analyzed_at": None,
            "created_at": datetime.now(timezone.utc),
        }
        row.update(overrides)
        self._attachments[row_id] = row
        return row_id

    async def executemany(self, sql: str, args_seq: Any) -> None:
        m = re.match(r"insert into (\w+) \(account_id, message_id, attachment_id, position\)", sql)
        assert m, f"unexpected executemany: {sql}"
        rows = self._links.setdefault(m.group(1), [])
        for account_id, message_id, attachment_id, position in args_seq:
            if any(
                r["message_id"] == message_id and r["attachment_id"] == attachment_id for r in rows
            ):
                continue
            rows.append(
                {
                    "account_id": account_id,
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "position": position,
                }
            )

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        m = re.match(r"select m\.message_id, .* from (\w+) m join attachments a", sql)
        assert m, f"unexpected fetch: {sql}"
        message_ids = set(args[0])
        account_id = args[1]
        rows = [
            r
            for r in self._links.get(m.group(1), [])
            if r["message_id"] in message_ids and r["account_id"] == account_id
        ]
        rows.sort(key=lambda r: (r["message_id"], r["position"]))
        out = []
        for r in rows:
            att = dict(self._attachments[r["attachment_id"]])
            att["message_id"] = r["message_id"]
            out.append(att)
        return out


async def test_link_hr_message_attachments_inserts_rows() -> None:
    db = FakeLinksDb()
    a = db.add_attachment()
    b = db.add_attachment()
    await repo.link_hr_message_attachments(42, [a, b], account_id=_ACCOUNT_A, db=db)
    assert len(db._links[repo.HR_SURFACE]) == 2


async def test_link_hr_message_attachments_empty_list_is_noop() -> None:
    db = FakeLinksDb()
    await repo.link_hr_message_attachments(42, [], account_id=_ACCOUNT_A, db=db)
    assert db._links == {}


async def test_load_hr_message_attachments_groups_by_message_and_keeps_position_order() -> None:
    db = FakeLinksDb()
    a = db.add_attachment()
    b = db.add_attachment()
    c = db.add_attachment()
    await repo.link_hr_message_attachments(1, [b, a], account_id=_ACCOUNT_A, db=db)
    await repo.link_hr_message_attachments(2, [c], account_id=_ACCOUNT_A, db=db)

    out = await repo.load_hr_message_attachments([1, 2], account_id=_ACCOUNT_A, db=db)
    assert [m.id for m in out[1]] == [b, a]
    assert [m.id for m in out[2]] == [c]


async def test_load_hr_message_attachments_empty_ids_is_noop() -> None:
    db = FakeLinksDb()
    assert await repo.load_hr_message_attachments([], account_id=_ACCOUNT_A, db=db) == {}


async def test_load_hr_message_attachments_includes_ready_analysis() -> None:
    db = FakeLinksDb()
    a = db.add_attachment(
        analysis_status="ready",
        analysis=AttachmentAnalysis(
            kind="document", title="Скрин", summary="s", text="t"
        ).model_dump(),
    )
    await repo.link_hr_message_attachments(5, [a], account_id=_ACCOUNT_A, db=db)

    out = await repo.load_hr_message_attachments([5], account_id=_ACCOUNT_A, db=db)
    assert out[5][0].analysis is not None
    assert out[5][0].analysis.title == "Скрин"


async def test_link_hr_message_attachments_is_idempotent_on_conflict() -> None:
    """Повторная привязка того же (message_id, attachment_id) не плодит вторую строку."""
    db = FakeLinksDb()
    a = db.add_attachment()
    await repo.link_hr_message_attachments(7, [a], account_id=_ACCOUNT_A, db=db)
    await repo.link_hr_message_attachments(7, [a], account_id=_ACCOUNT_A, db=db)
    assert len(db._links[repo.HR_SURFACE]) == 1


async def test_load_hr_message_attachments_does_not_cross_accounts() -> None:
    """M4: чужой account_id не видит связку, даже зная message_id."""
    db = FakeLinksDb()
    a = db.add_attachment()
    await repo.link_hr_message_attachments(9, [a], account_id=_ACCOUNT_A, db=db)

    out = await repo.load_hr_message_attachments([9], account_id=_ACCOUNT_B, db=db)
    assert out == {}
