"""TB-7.5: рендер HR-карточки и клавиатуры по фикстурному HrBatchResult (без PG)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bot_app.services import hr_card as card
from core.domains.pipeline.hr_actions import ActionResult
from core.domains.pipeline.hr_orchestrator import HrBatchResult
from core.domains.preparation.models import InterviewStageIn
from core.domains.pipeline.models import HrMessageAnalysis

_WEB = "https://app.example"
_HTTP = "http://localhost:5173"

# Декоративный эмодзи-забор из TB-7.1 — в карточке быть не должен.
_EMOJI_FENCE = "📨💬🏢💼💰💵📊🏠👥🎯👤📱🔗📆🖥"


def _analysis(**kwargs: Any) -> HrMessageAnalysis:
    base: dict[str, Any] = {
        "raw_text": "тест",
        "intent": "follow_up",
        "company": "Неизвестная компания",
        "position": "Неизвестная позиция",
        "summary": "",
    }
    base.update(kwargs)
    return HrMessageAnalysis(**base)


def _batch(
    analysis: HrMessageAnalysis,
    *,
    pending_resolve: str = "",
    notes: list[str] | None = None,
) -> HrBatchResult:
    return HrBatchResult(
        primary=analysis,
        actions=ActionResult(
            pending_resolve_vacancy_id=pending_resolve,
            notes=list(notes or []),
        ),
    )


def _kb_snapshot(markup: Any) -> list[list[tuple[str, str]]] | None:
    if markup is None:
        return None
    rows: list[list[tuple[str, str]]] = []
    for row in markup.inline_keyboard:
        cells: list[tuple[str, str]] = []
        for btn in row:
            cells.append((btn.text, btn.callback_data or btn.url or ""))
        rows.append(cells)
    return rows


def test_format_with_contact_and_vacancy() -> None:
    batch = _batch(
        _analysis(
            intent="interview_scheduled",
            company="Яндекс",
            position="Backend",
            summary="Скрининг в пятницу",
            hr_link="tg:@anna_hr",
            interviewer_name="Анна",
            contact="@anna_hr",
            vacancy_id="12345",
            vacancy_url="https://hh.ru/vacancy/12345",
            salary_text="400-500k",
            salary_match="yes",
            format="online",
            interview_dt=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            stage_type="hr_screening",
        ),
        notes=["воронка: screening"],
    )
    text = card.format_hr_card(batch)

    assert text.startswith("<b>Контакт</b>")
    assert "@anna_hr</a>" in text or ">@anna_hr<" in text
    assert "Анна" in text
    assert "Привязка:" in text
    assert "Яндекс — Backend" in text
    assert "<b>Назначено собеседование</b>" in text
    assert "Скрининг в пятницу" in text
    assert "Зарплата: 400-500k" in text
    assert "Match зарплаты: да" in text
    assert "Когда: 01.08.2026 12:00 (МСК)" in text
    assert "Формат: онлайн" in text
    assert "<b>Действия</b>" in text
    assert "воронка: screening" in text
    assert not any(e in text for e in _EMOJI_FENCE)


def test_format_without_contact() -> None:
    batch = _batch(
        _analysis(
            intent="hr_outreach",
            company="Acme",
            position="PM",
            summary="Написали в Telegram",
            interviewer_name="Мария",  # только имя — не actionable
        )
    )
    text = card.format_hr_card(batch)

    assert "<b>Контакт</b>" in text
    assert "Мария" in text
    assert "Привязка: Acme — PM" in text
    assert "<b>HR написал первым (Telegram)</b>" in text
    assert "Написали в Telegram" in text
    assert "Источник: Telegram (без hh в сообщении)" in text
    assert card.needs_manual_hr_contact(batch.primary) is True
    assert not any(e in text for e in _EMOJI_FENCE)


def test_format_pending_binding() -> None:
    batch = _batch(
        _analysis(company="Acme", position="Dev", summary="ок"),
        pending_resolve="999",
    )
    text = card.format_hr_card(batch)
    assert "предположительно" in text
    assert "999" in text


def test_format_stages_and_debrief() -> None:
    batch = _batch(
        _analysis(
            company="Acme",
            position="Dev",
            vacancy_id="v1",
            vacancy_url="https://hh.ru/vacancy/v1",
            hr_link="mail:hr@acme.test",
            interview_stages=[
                InterviewStageIn(
                    stage_type="live_coding",
                    scheduled_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
                    format="online",
                )
            ],
            debrief_summary="Коротко прошло нормально",
        )
    )
    text = card.format_hr_card(batch)
    assert "<b>Этапы</b>" in text
    assert "05.08.2026 10:00" in text
    assert "<b>Дебриф</b>:" in text
    assert "Коротко прошло нормально" in text
    # Ссылка на вакансию только в Привязке, без дубля внизу.
    assert text.count("hh.ru/vacancy/v1") == 1


def test_keyboard_with_contact_and_vacancy() -> None:
    batch = _batch(
        _analysis(
            hr_link="tg:@anna",
            vacancy_id="123",
            vacancy_url="https://hh.ru/vacancy/123",
            company="Acme",
            position="Dev",
        )
    )
    assert card.needs_manual_hr_contact(batch.primary) is False
    snap = _kb_snapshot(card.build_hr_card_keyboard(batch, web_url=_WEB))
    assert snap == [
        [
            ("Открыть тред", f"{_WEB}/chat?vacancy=123"),
            ("Черновик ответа", f"{_WEB}/chat?vacancy=123"),
        ]
    ]


def test_keyboard_pending_resolve_and_no_contact() -> None:
    batch = _batch(
        _analysis(company="Acme", position="Dev", summary="hi"),
        pending_resolve="999",
    )
    assert card.needs_manual_hr_contact(batch.primary) is True
    snap = _kb_snapshot(
        card.build_hr_card_keyboard(
            batch,
            web_url=_WEB,
            resolve_token="TOK",
            contact_token="TOK",
        )
    )
    assert snap == [
        [
            ("Открыть тред", f"{_WEB}/chat?vacancy=999"),
            ("Черновик ответа", f"{_WEB}/chat?vacancy=999"),
        ],
        [
            ("Это вакансия 999", "hrres:ok:TOK"),
            ("Не та вакансия", "hrres:no:TOK"),
        ],
        [("Указать @HR", f"{card.CB_SET_CONTACT_PREFIX}TOK")],
    ]


def test_keyboard_only_set_contact_when_no_vacancy() -> None:
    batch = _batch(_analysis(summary="hi"))
    snap = _kb_snapshot(card.build_hr_card_keyboard(batch, web_url=_WEB, contact_token="C1"))
    assert snap == [[("Указать @HR", f"{card.CB_SET_CONTACT_PREFIX}C1")]]


def test_keyboard_http_web_skips_url_buttons() -> None:
    batch = _batch(_analysis(hr_link="tg:@a", vacancy_id="1", company="Acme", position="Dev"))
    snap = _kb_snapshot(card.build_hr_card_keyboard(batch, web_url=_HTTP))
    assert snap is None


def test_keyboard_none_without_tokens_when_no_vacancy_no_contact() -> None:
    batch = _batch(_analysis(summary="x"))
    assert card.build_hr_card_keyboard(batch, web_url=_WEB) is None


def test_has_actionable_contact_variants() -> None:
    assert card.has_actionable_hr_contact(_analysis(hr_link="tg:@u")) is True
    assert card.has_actionable_hr_contact(_analysis(hr_link="mail:a@b.c")) is True
    assert card.has_actionable_hr_contact(_analysis(hr_link="tel:+79991234567")) is True
    assert card.has_actionable_hr_contact(_analysis(hr_link="name:Анна")) is False
    assert card.has_actionable_hr_contact(_analysis(contact="@hidden_hr")) is True
    assert card.has_actionable_hr_contact(_analysis()) is False
