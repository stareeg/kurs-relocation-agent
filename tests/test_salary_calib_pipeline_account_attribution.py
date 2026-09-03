"""plan local_context_blind_spots_2026_08_12.md §14: `salary_calib_pipeline.process_pending_queue`
резолвит `account_id` владельца (тот же `resolve_default_account_id()`, что уже применяет
`snapshot_refresh.py`) и прокидывает его в лог — очередь остаётся кросс-аккаунтной по данным
(каждая строка несёт свой `account_id`), но сам прогон джобы теперь атрибутирован для будущего
troubleshooting. `salary_extract.py` заодно перестаёт терять контекст батча на ошибке парсинга.
"""

from __future__ import annotations

import logging

import pytest

from core.domains.market import salary_calib_pipeline as pipeline
from core.domains.market.salary_calib import CalibQueueItem
from core.domains.market.salary_calibration.salary_extract import extract_salary_batch
from core.kernel import ports
from core.kernel.errors import LlmError
from tests.fakes import FakeLlm


def _item(item_id: int, *, channel: str = "") -> CalibQueueItem:
    return CalibQueueItem(
        id=item_id,
        account_id=1,
        chat_id=1,
        message_id=item_id,
        raw_text="текст поста",
        forward_channel=channel,
    )


async def test_recovered_from_processing_logs_owner_account_id(monkeypatch, caplog):
    async def _fake_owner_id(**_kw):
        return 42

    async def _fake_requeue(**_kw):
        return 3

    async def _fake_fetch_batch(*_a, **_kw):
        return []

    monkeypatch.setattr(
        "core.platform.repo.accounts.resolve_default_account_id", _fake_owner_id
    )
    monkeypatch.setattr(pipeline, "requeue_processing", _fake_requeue)
    monkeypatch.setattr(pipeline, "fetch_pending_batch", _fake_fetch_batch)

    caplog.set_level(logging.INFO, logger="core.domains.market.salary_calib_pipeline")
    processed, relevant, errors = await pipeline.process_pending_queue()

    assert (processed, relevant, errors) == (0, 0, 0)
    records = [r for r in caplog.records if "возвращено в pending" in r.getMessage()]
    assert len(records) == 1
    assert records[0].account_id == 42


async def test_batch_error_logs_owner_account_id_and_batch_size(monkeypatch, caplog):
    async def _fake_owner_id(**_kw):
        return 7

    async def _fake_requeue(**_kw):
        return 0

    batches = [[_item(1), _item(2)], []]

    async def _fake_fetch_batch(*_a, **_kw):
        return batches.pop(0) if batches else []

    async def _fake_mark_status(*_a, **_kw):
        return None

    async def _fake_extract(_items):
        raise LlmError("boom")

    monkeypatch.setattr(
        "core.platform.repo.accounts.resolve_default_account_id", _fake_owner_id
    )
    monkeypatch.setattr(pipeline, "requeue_processing", _fake_requeue)
    monkeypatch.setattr(pipeline, "fetch_pending_batch", _fake_fetch_batch)
    monkeypatch.setattr(pipeline, "mark_queue_status", _fake_mark_status)
    monkeypatch.setattr(pipeline, "extract_salary_batch", _fake_extract)

    caplog.set_level(logging.WARNING, logger="core.domains.market.salary_calib_pipeline")
    processed, relevant, errors = await pipeline.process_pending_queue()

    assert (processed, relevant, errors) == (0, 0, 2)
    records = [r for r in caplog.records if "Salary calib batch error" in r.getMessage()]
    assert len(records) == 1
    assert records[0].account_id == 7
    assert records[0].batch_size == 2


async def test_parse_error_logs_batch_size_and_channels(caplog):
    items = [_item(1, channel="chan_a"), _item(2, channel="chan_b")]

    caplog.set_level(
        logging.WARNING, logger="core.domains.market.salary_calibration.salary_extract"
    )
    with ports.use_ports(llm=FakeLlm(text="это не json")), pytest.raises(LlmError):
        await extract_salary_batch(items)

    records = [r for r in caplog.records if "Salary calib parse error" in r.getMessage()]
    assert len(records) == 1
    assert records[0].batch_size == 2
    assert records[0].channels == "chan_a,chan_b"
