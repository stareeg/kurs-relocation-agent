"""FR3-74: честность атрибуции при разборе HR-дампа."""

from __future__ import annotations

import inspect

from core.domains.pipeline import funnel_suggest
from core.domains.pipeline import hr_import
from core.domains.pipeline.hr_import import DumpMessage, SplitReplica, dedupe_against_existing


def test_prompt_no_silent_hr_fallback():
    """Промпт больше не велит молча ставить hr при неясном авторе."""
    src = hr_import._SPLIT_SYSTEM_TEMPLATE
    assert "author_uncertain: true" in src
    assert 'НЕ сбрасывай молча на "hr"' in src
    assert "МОЖЕТ начинаться с кандидата" in src
    assert "Несколько реплик подряд от одной стороны" in src
    assert "Не помечай так всю переписку оптом" in src
    # Старый silent-fallback убран (негативная формулировка в новом промпте допустима).
    assert 'Если автора реально не понять — ставь "hr"' not in src


def test_dump_message_has_author_uncertain_field():
    msg = DumpMessage(sender="me", body="Привет", author_uncertain=True)
    assert msg.author_uncertain is True
    assert DumpMessage(sender="hr", body="Ок").author_uncertain is False


def test_dedupe_keeps_author_uncertain_flag():
    existing = [("hr_in", "старое")]
    parsed = [
        SplitReplica(kind="hr_in", body="старое", author_uncertain=False),
        SplitReplica(kind="me", body="новое", author_uncertain=True),
    ]
    out = dedupe_against_existing(existing, parsed)
    assert len(out) == 1
    assert out[0].body == "новое"
    assert out[0].author_uncertain is True


def test_relax_blanket_uncertainty_when_both_sides_present():
    """Магнит/Ирина: все реплики uncertain, но стороны уже различены → флаг снимаем."""
    parsed = [
        hr_import.SplitReplica(kind="hr_out", body="Добрый день", author_uncertain=True),
        hr_import.SplitReplica(kind="hr_in", body="Если в понедельник?", author_uncertain=True),
        hr_import.SplitReplica(kind="hr_out", body="Могу", author_uncertain=True),
    ]
    out = hr_import._relax_blanket_uncertainty(parsed)
    assert [p.kind for p in out] == ["hr_out", "hr_in", "hr_out"]
    assert all(not p.author_uncertain for p in out)


def test_relax_blanket_keeps_flag_when_only_one_side():
    parsed = [
        hr_import.SplitReplica(kind="hr_in", body="а", author_uncertain=True),
        hr_import.SplitReplica(kind="hr_in", body="б", author_uncertain=True),
    ]
    out = hr_import._relax_blanket_uncertainty(parsed)
    assert all(p.author_uncertain for p in out)


def test_relax_blanket_keeps_mixed_flags():
    parsed = [
        hr_import.SplitReplica(kind="hr_in", body="а", author_uncertain=True),
        hr_import.SplitReplica(kind="hr_out", body="б", author_uncertain=False),
    ]
    out = hr_import._relax_blanket_uncertainty(parsed)
    assert out[0].author_uncertain is True
    assert out[1].author_uncertain is False


def test_funnel_suggest_skips_uncertain_hr_in():
    """Исходник suggest_funnel_from_dialog фильтрует author_uncertain."""
    src = inspect.getsource(funnel_suggest.suggest_funnel_from_dialog)
    assert "author_uncertain" in src
    assert "not m.author_uncertain" in src
