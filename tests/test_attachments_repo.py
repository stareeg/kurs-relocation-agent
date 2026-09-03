"""Э0-3: репозиторий `attachments` — дедуп по (account_id, sha256), мета/байты, кандидаты GC.

Без реального Postgres (CLAUDE.md: тесты без DB-фикстур) — мини-модель таблицы в памяти,
повторяющая ровно те запросы, что шлёт `core.domains.assistant.attachments.repo` (см. FakeAttachmentsDb).

M4 (plans/multitenancy_gaps_2026_08_06.md §3.5): дедуп стал per-account — тот же sha256 у ДВУХ
разных аккаунтов теперь даёт ДВЕ разные строки (было: одна строка на всю систему, IDOR).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.domains.assistant.attachments import repo
from core.domains.assistant.attachments.models import AttachmentAnalysis

_ACCOUNT_A = 1
_ACCOUNT_B = 2


class FakeAttachmentsDb:
    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._next_id = 1

    @staticmethod
    def _meta_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if k not in ("account_id", "data", "thumb")}

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        sql_l = sql.lower()
        if sql_l.startswith("insert into attachments"):
            (
                account_id,
                sha256,
                mime,
                width,
                height,
                bytes_,
                data,
                thumb,
                thumb_width,
                thumb_height,
                derived_from,
                crop,
            ) = args
            for row in self._rows.values():
                if row["account_id"] == account_id and row["sha256"] == sha256:
                    return self._meta_dict(row)
            row_id = self._next_id
            self._next_id += 1
            row = {
                "id": row_id,
                "account_id": account_id,
                "sha256": sha256,
                "mime": mime,
                "width": width,
                "height": height,
                "bytes": bytes_,
                "data": data,
                "thumb": thumb,
                "thumb_width": thumb_width,
                "thumb_height": thumb_height,
                "derived_from": derived_from,
                "crop": crop,
                "analysis_status": "pending",
                "analysis": None,
                "analyzed_at": None,
                "created_at": datetime.now(timezone.utc),
            }
            self._rows[row_id] = row
            return self._meta_dict(row)
        if "from attachments where id = $1 and account_id = $2" in sql_l:
            attachment_id, account_id = args
            row = self._rows.get(attachment_id)
            if row is None or row["account_id"] != account_id:
                return None
            if "data, thumb" in sql_l:
                return {k: v for k, v in row.items() if k != "account_id"}
            return self._meta_dict(row)
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def execute(self, sql: str, *args: Any) -> str:
        sql_l = sql.lower()
        if sql_l.startswith("delete from attachments"):
            ids = args[0]
            n = sum(1 for i in ids if self._rows.pop(i, None) is not None)
            return f"DELETE {n}"
        if sql_l.startswith("update attachments set analysis_status = $3"):
            attachment_id, account_id, status, analysis = args
            row = self._rows.get(attachment_id)
            if row is not None and row["account_id"] == account_id:
                row["analysis_status"] = status
                row["analysis"] = analysis
                row["analyzed_at"] = datetime.now(timezone.utc)
            return "UPDATE 1"
        if sql_l.startswith("update attachments set analysis_status = 'pending'"):
            attachment_id, account_id = args
            row = self._rows.get(attachment_id)
            if row is not None and row["account_id"] == account_id:
                row["analysis_status"] = "pending"
                row["analysis"] = None
                row["analyzed_at"] = None
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute: {sql}")

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        sql_l = sql.lower()
        if sql_l.startswith("select a.id from attachments a where"):
            older_than, limit = args
            derived_ids = {
                r["derived_from"] for r in self._rows.values() if r["derived_from"] is not None
            }
            out = [
                {"id": row["id"]}
                for row in self._rows.values()
                if row["created_at"] < older_than and row["id"] not in derived_ids
            ]
            return out[:limit]
        raise AssertionError(f"unexpected fetch: {sql}")


def _upload_kwargs(sha256: str = "aaa", *, account_id: int = _ACCOUNT_A) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "sha256": sha256,
        "mime": "image/webp",
        "width": 100,
        "height": 50,
        "data": b"normalized-bytes",
        "thumb": b"thumb-bytes",
        "thumb_width": 50,
        "thumb_height": 25,
    }


async def test_upsert_dedup_by_sha256_within_account() -> None:
    """Тот же аккаунт, тот же sha256 дважды → одна строка, один и тот же id."""
    db = FakeAttachmentsDb()
    first = await repo.upsert_attachment(**_upload_kwargs("same-hash"), db=db)
    second = await repo.upsert_attachment(**_upload_kwargs("same-hash"), db=db)
    assert first.id == second.id
    assert len(db._rows) == 1


async def test_upsert_same_sha256_different_accounts_makes_separate_rows() -> None:
    """M4: одинаковые байты у ДВУХ аккаунтов — ДВЕ разные строки, не общий контент-адрес."""
    db = FakeAttachmentsDb()
    a = await repo.upsert_attachment(**_upload_kwargs("shared-hash", account_id=_ACCOUNT_A), db=db)
    b = await repo.upsert_attachment(**_upload_kwargs("shared-hash", account_id=_ACCOUNT_B), db=db)
    assert a.id != b.id
    assert len(db._rows) == 2


async def test_upsert_different_sha256_makes_new_rows() -> None:
    db = FakeAttachmentsDb()
    first = await repo.upsert_attachment(**_upload_kwargs("hash-1"), db=db)
    second = await repo.upsert_attachment(**_upload_kwargs("hash-2"), db=db)
    assert first.id != second.id
    assert len(db._rows) == 2


async def test_upsert_bytes_field_is_data_length() -> None:
    db = FakeAttachmentsDb()
    meta = await repo.upsert_attachment(**_upload_kwargs(), db=db)
    assert meta.bytes == len(b"normalized-bytes")


async def test_get_meta_missing_returns_none() -> None:
    db = FakeAttachmentsDb()
    assert await repo.get_meta(999, account_id=_ACCOUNT_A, db=db) is None


async def test_get_meta_round_trip() -> None:
    db = FakeAttachmentsDb()
    created = await repo.upsert_attachment(**_upload_kwargs(), db=db)
    fetched = await repo.get_meta(created.id, account_id=_ACCOUNT_A, db=db)
    assert fetched is not None
    assert fetched.sha256 == "aaa"
    assert fetched.width == 100
    assert fetched.analysis_status == "pending"


async def test_get_meta_other_account_returns_none() -> None:
    """M4: чужой id — то же самое, что несуществующий (404 без подтверждения, не 403)."""
    db = FakeAttachmentsDb()
    created = await repo.upsert_attachment(**_upload_kwargs(), db=db)
    assert await repo.get_meta(created.id, account_id=_ACCOUNT_B, db=db) is None


async def test_get_data_round_trip_includes_bytes() -> None:
    db = FakeAttachmentsDb()
    created = await repo.upsert_attachment(**_upload_kwargs(), db=db)
    fetched = await repo.get_data(created.id, account_id=_ACCOUNT_A, db=db)
    assert fetched is not None
    assert fetched.data == b"normalized-bytes"
    assert fetched.thumb == b"thumb-bytes"


async def test_get_data_missing_returns_none() -> None:
    db = FakeAttachmentsDb()
    assert await repo.get_data(999, account_id=_ACCOUNT_A, db=db) is None


async def test_get_data_other_account_returns_none() -> None:
    db = FakeAttachmentsDb()
    created = await repo.upsert_attachment(**_upload_kwargs(), db=db)
    assert await repo.get_data(created.id, account_id=_ACCOUNT_B, db=db) is None


async def test_set_analysis_updates_status_and_payload() -> None:
    db = FakeAttachmentsDb()
    created = await repo.upsert_attachment(**_upload_kwargs(), db=db)
    analysis = AttachmentAnalysis(kind="document", title="Скрин", summary="...", text="текст")
    await repo.set_analysis(created.id, account_id=_ACCOUNT_A, status="ready", analysis=analysis, db=db)
    fetched = await repo.get_meta(created.id, account_id=_ACCOUNT_A, db=db)
    assert fetched is not None
    assert fetched.analysis_status == "ready"
    assert fetched.analysis is not None
    assert fetched.analysis.title == "Скрин"


async def test_reset_pending_clears_analysis() -> None:
    db = FakeAttachmentsDb()
    created = await repo.upsert_attachment(**_upload_kwargs(), db=db)
    analysis = AttachmentAnalysis(kind="document", title="t", summary="s", text="x")
    await repo.set_analysis(created.id, account_id=_ACCOUNT_A, status="ready", analysis=analysis, db=db)
    await repo.reset_pending(created.id, account_id=_ACCOUNT_A, db=db)
    fetched = await repo.get_meta(created.id, account_id=_ACCOUNT_A, db=db)
    assert fetched is not None
    assert fetched.analysis_status == "pending"
    assert fetched.analysis is None


async def test_gc_candidates_respects_cutoff() -> None:
    """Свежая строка (после cutoff) не должна попасть в кандидаты на удаление."""
    db = FakeAttachmentsDb()
    old = await repo.upsert_attachment(**_upload_kwargs("old"), db=db)
    db._rows[old.id]["created_at"] = datetime.now(timezone.utc) - timedelta(days=2)
    fresh = await repo.upsert_attachment(**_upload_kwargs("fresh"), db=db)

    candidates = await repo.gc_candidates(
        older_than=datetime.now(timezone.utc) - timedelta(hours=24), db=db
    )
    assert candidates == [old.id]
    assert fresh.id not in candidates


async def test_gc_candidates_excludes_derived_from_source() -> None:
    """Оригинал, на который ссылается кроп (`derived_from`), не удаляется, даже если он старый."""
    db = FakeAttachmentsDb()
    source = await repo.upsert_attachment(**_upload_kwargs("source"), db=db)
    db._rows[source.id]["created_at"] = datetime.now(timezone.utc) - timedelta(days=2)
    cropped_kwargs = _upload_kwargs("cropped")
    cropped_kwargs["derived_from"] = source.id
    cropped = await repo.upsert_attachment(**cropped_kwargs, db=db)
    db._rows[cropped.id]["created_at"] = datetime.now(timezone.utc) - timedelta(days=2)

    candidates = await repo.gc_candidates(
        older_than=datetime.now(timezone.utc) - timedelta(hours=24), db=db
    )
    assert source.id not in candidates
    assert cropped.id in candidates


async def test_delete_attachments_removes_rows_and_counts() -> None:
    db = FakeAttachmentsDb()
    a = await repo.upsert_attachment(**_upload_kwargs("del-a"), db=db)
    b = await repo.upsert_attachment(**_upload_kwargs("del-b"), db=db)
    deleted = await repo.delete_attachments([a.id, b.id, 9999], db=db)
    assert deleted == 2
    assert await repo.get_meta(a.id, account_id=_ACCOUNT_A, db=db) is None
    assert await repo.get_meta(b.id, account_id=_ACCOUNT_A, db=db) is None


async def test_delete_attachments_empty_list_is_noop() -> None:
    db = FakeAttachmentsDb()
    assert await repo.delete_attachments([], db=db) == 0
