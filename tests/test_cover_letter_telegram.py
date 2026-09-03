"""Нормализация Telegram-ника и префикс в сопроводительном."""

from core.domains.pipeline.cover_letter import normalize_telegram_handle, prepend_telegram_handle


def test_normalize_at_prefix() -> None:
    assert normalize_telegram_handle("@MyNick_1") == "@MyNick_1"


def test_normalize_bare_and_tme() -> None:
    assert normalize_telegram_handle("MyNick_1") == "@MyNick_1"
    assert normalize_telegram_handle("t.me/MyNick_1") == "@MyNick_1"
    assert normalize_telegram_handle("https://t.me/MyNick_1") == "@MyNick_1"


def test_normalize_empty_and_junk() -> None:
    assert normalize_telegram_handle("") == ""
    assert normalize_telegram_handle("   ") == ""
    assert normalize_telegram_handle("ab") == ""  # слишком короткий
    assert normalize_telegram_handle("not a handle!!!") == ""


def test_prepend_adds_first_line() -> None:
    assert prepend_telegram_handle("Делал X.\nГотов обсудить.", "@nick_ok") == (
        "@nick_ok\nДелал X.\nГотов обсудить."
    )


def test_prepend_no_duplicate() -> None:
    letter = "@nick_ok\nДелал X."
    assert prepend_telegram_handle(letter, "@nick_ok") == letter


def test_prepend_skips_without_handle() -> None:
    assert prepend_telegram_handle("Текст", "") == "Текст"
