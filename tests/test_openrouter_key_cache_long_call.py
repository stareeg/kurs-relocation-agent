"""Ключ аккаунта не должен исчезать посреди длинного LLM-вызова.

Прод-баг 2026-08-27..31: TTL кэша (15 с) применялся и на ЧТЕНИИ, поэтому любой вызов дольше
15 с (второй вызов сценария — ремонт сопроводительного — приходится на ~25-ю секунду) уходил
в OpenRouter с пустым ключом и получал `HTTP 401 Missing Authentication header` по всей
цепочке моделей. В журнале это выглядело как «провайдер лежит», хотя ключ был на месте.
"""

from __future__ import annotations

import pytest

from core.platform.config import runtime as rt


@pytest.fixture(autouse=True)
def clean_runtime() -> None:
    rt.reset_runtime_for_tests()


def _with_account(account_id: int):
    return rt.set_current_account_id(account_id)


def test_key_survives_longer_than_refresh_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1_000.0}
    monkeypatch.setattr(rt.time, "monotonic", lambda: clock["now"])

    rt.cache_account_openrouter_key(9, "sk-or-v1-secret")
    token = _with_account(9)
    try:
        assert rt.current_account_openrouter_key() == "sk-or-v1-secret"
        # Прошло больше интервала обновления, но вызов всё ещё идёт — ключ обязан остаться.
        clock["now"] += rt._ACCOUNT_KEY_REFRESH_S + 60
        assert rt.current_account_openrouter_key() == "sk-or-v1-secret"
    finally:
        rt.reset_current_account_id(token)


def test_refresh_interval_still_asks_to_reread(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1_000.0}
    monkeypatch.setattr(rt.time, "monotonic", lambda: clock["now"])

    rt.cache_account_openrouter_key(9, "sk-or-v1-secret")
    assert rt.account_openrouter_key_cache_stale(9) is False
    clock["now"] += rt._ACCOUNT_KEY_REFRESH_S + 1
    assert rt.account_openrouter_key_cache_stale(9) is True


def test_key_dropped_after_retention(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1_000.0}
    monkeypatch.setattr(rt.time, "monotonic", lambda: clock["now"])

    rt.cache_account_openrouter_key(9, "sk-or-v1-secret")
    token = _with_account(9)
    try:
        clock["now"] += rt._ACCOUNT_KEY_RETAIN_S + 1
        assert rt.current_account_openrouter_key() == ""
    finally:
        rt.reset_current_account_id(token)


def test_explicit_rewrite_wins_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отзыв/смена ключа доезжает явной инвалидацией, а не по таймеру — на этом и держится
    решение читать кэш дольше интервала обновления."""
    clock = {"now": 1_000.0}
    monkeypatch.setattr(rt.time, "monotonic", lambda: clock["now"])

    rt.cache_account_openrouter_key(9, "sk-old")
    rt.cache_account_openrouter_key(9, "sk-new")
    token = _with_account(9)
    try:
        assert rt.current_account_openrouter_key() == "sk-new"
    finally:
        rt.reset_current_account_id(token)


def test_no_account_context_means_no_account_key() -> None:
    rt.cache_account_openrouter_key(9, "sk-or-v1-secret")
    assert rt.current_account_openrouter_key() == ""
