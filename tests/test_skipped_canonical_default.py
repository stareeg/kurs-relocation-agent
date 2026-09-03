"""Этап 7 §7.1: `save_skipped` больше не пишет `canonical_reason = NULL` (D17).

До фикса пути без явного `canonical_reason` (kanban `skip_job`, `_apply_archive_disposition`)
оставляли колонку пустой навсегда. Теперь `save_skipped` сама выводит канон через
`canonical_skip_reason`, когда каллер его не передал.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.domains.opportunities.skipped import save_skipped


class _FakeDb:
    def __init__(self) -> None:
        self.last_args: tuple[object, ...] | None = None

    async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
        self.last_args = args
        (
            vacancy_id,
            url,
            title,
            company,
            overall_score,
            recommendation,
            skip_reason,
            canonical_reason,
            scored_at,
            account_id,
        ) = args
        return {
            "id": 1,
            "vacancy_id": vacancy_id,
            "url": url,
            "title": title,
            "company": company,
            "overall_score": overall_score,
            "recommendation": recommendation,
            "skip_reason": skip_reason,
            "canonical_reason": canonical_reason,
            "scored_at": scored_at,
            "created_at": datetime.now(UTC),
        }


async def test_save_skipped_defaults_canonical_reason_when_omitted():
    """Kanban skip_job / _apply_archive_disposition не передают canonical_reason явно."""
    db = _FakeDb()
    record = await save_skipped(
        "123",
        "Диалог закрыт",
        account_id=1,
        db=db,
    )
    assert record.canonical_reason == "Избегать компанию"


async def test_save_skipped_defaults_via_legacy_label():
    db = _FakeDb()
    record = await save_skipped(
        "124",
        "Риск выгорания",
        account_id=1,
        db=db,
    )
    assert record.canonical_reason == "Не та роль (IC vs рук)"


async def test_save_skipped_keeps_explicit_canonical_reason():
    """POST /skip уже канонизирует сам (может отличаться от каскада по skip_reason, напр.
    LLM-чип текст не входит в regex-каскад) — явное значение не должно перезаписываться."""
    db = _FakeDb()
    record = await save_skipped(
        "125",
        "Слишком много переработок по отзывам",
        account_id=1,
        canonical_reason="Не та роль (IC vs рук)",
        db=db,
    )
    assert record.canonical_reason == "Не та роль (IC vs рук)"
