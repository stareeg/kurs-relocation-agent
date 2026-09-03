"""Опорная дата для event_extract — без LLM."""

from datetime import datetime, timedelta, timezone

from core.domains.pipeline.event_extract import anchor_label

_MSK = timezone(timedelta(hours=3))


def test_anchor_label_russian_weekday_not_locale_a() -> None:
    # 2026-07-13 — понедельник; %A на Windows-ru давал бы другой язык/сдвиг в промпте.
    dt = datetime(2026, 7, 13, 15, 0, tzinfo=_MSK)
    assert anchor_label(dt) == "2026-07-13 (понедельник)"


def test_anchor_label_converts_utc_to_msk_day() -> None:
    # 2026-07-13 22:30 UTC = 2026-07-14 01:30 МСК — вторник
    dt = datetime(2026, 7, 13, 22, 30, tzinfo=timezone.utc)
    assert anchor_label(dt) == "2026-07-14 (вторник)"
