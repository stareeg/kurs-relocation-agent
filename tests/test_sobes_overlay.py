"""Контекст для оверлея sobes.tech: жёсткий потолок символов."""

from core.domains.preparation.interview.prep import SOBES_OVERLAY_MAX_CHARS, fit_sobes_overlay_text


def test_fit_under_limit_unchanged():
    text = "Короткий контекст про теорию и RAG."
    assert fit_sobes_overlay_text(text) == text


def test_fit_respects_hard_limit():
    body = "Тема одна про RAG и агентов.\n\n" * 400
    fitted = fit_sobes_overlay_text(body, limit=3900)
    assert len(fitted) <= 3900
    assert len(fitted) > 2000


def test_default_limit_is_3900():
    assert SOBES_OVERLAY_MAX_CHARS == 3900
    huge = ("Абзац про стек вакансии и метрики. " * 200) + "\n\n" + ("Ещё абзац. " * 200)
    fitted = fit_sobes_overlay_text(huge)
    assert len(fitted) <= 3900
