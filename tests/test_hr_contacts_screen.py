"""TB-7.4: рендер экрана HR-контактов (без PG)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot_app.services import hr_contacts as hc
from core.domains.pipeline.hr_threads import RecentHrContact

_NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
_WEB = "https://app.example"


def test_format_empty() -> None:
    screen = hc.format_hr_contacts_screen([], web_url=_WEB)
    assert "Пока пусто" in screen.text
    assert screen.reply_markup is None


def test_format_rows_and_buttons() -> None:
    rows = [
        RecentHrContact(
            vacancy_id="v1",
            company="Acme",
            contact_name="",
            hr_link="tg:@anna",
            last_at=_NOW - timedelta(days=2),
        ),
        RecentHrContact(
            vacancy_id="v2",
            company="Beta",
            contact_name="Ира",
            hr_link="",
            last_at=_NOW,
        ),
        RecentHrContact(
            vacancy_id="v3",
            company="",
            contact_name="",
            hr_link="",
            last_at=None,
        ),
    ]
    screen = hc.format_hr_contacts_screen(rows, web_url=_WEB, now=_NOW)
    assert "<b>HR-контакты</b>" in screen.text
    assert "@anna · Acme · 2д" in screen.text
    assert "Ира · Beta · сегодня" in screen.text
    assert "без контакта · без компании · дата ?" in screen.text

    assert screen.reply_markup is not None
    labels = [btn.text for row in screen.reply_markup.inline_keyboard for btn in row]
    urls = [btn.url for row in screen.reply_markup.inline_keyboard for btn in row]
    assert labels == ["Acme", "Beta", "без контакта"]
    assert urls == [
        f"{_WEB}/chat?vacancy=v1",
        f"{_WEB}/chat?vacancy=v2",
        f"{_WEB}/chat?vacancy=v3",
    ]


def test_http_web_url_skips_buttons() -> None:
    rows = [
        RecentHrContact(vacancy_id="v1", company="Acme", hr_link="tg:@a", last_at=_NOW),
    ]
    screen = hc.format_hr_contacts_screen(rows, web_url="http://localhost:5173", now=_NOW)
    assert "@a · Acme · сегодня" in screen.text
    assert screen.reply_markup is None


def test_days_since() -> None:
    assert hc.days_since(None, now=_NOW) is None
    assert hc.days_since(_NOW, now=_NOW) == 0
    assert hc.days_since(_NOW - timedelta(hours=30), now=_NOW) == 1
    assert hc.days_since(_NOW - timedelta(days=5, hours=1), now=_NOW) == 5


def test_contact_label_prefers_name() -> None:
    row = RecentHrContact(
        vacancy_id="v",
        contact_name="Анна",
        hr_link="tg:@anna",
    )
    assert hc.contact_label(row) == "Анна"
    assert hc.contact_label(RecentHrContact(vacancy_id="v", hr_link="mail:a@b.c")) == "a@b.c"
