"""Э4-2 (chat_image_attachments_2026_08_03.md, «Технички · Внешний ИИ»): маршрутизация скринов
в `parse_external`.

`_split_external_attachments` — новая логика этого шага: переписка уходит в текстовый дамп
(тот же приём, что `_build_import_text` в Э4-1), всё остальное — в id для «вложения диалога»
(`send_message`, Э3). `attachments_service.wait_ready` монкейпатчится напрямую, как в
`test_conversations_import_attachments.py`; `parse_external` тестируется на уровне
маршрутизации веток, доменные вызовы (`parse_external_prep_chat`/`send_message`) подменены
заглушками.
"""

from __future__ import annotations

import pytest

from core.app.scenarios import prep_chat
from core.domains.assistant.attachments import service as attachments_service
from core.domains.assistant.attachments.models import (
    AttachmentAnalysis,
    AttachmentMeta,
    AttachmentTurn,
)
from core.domains.preparation.scenarios import VacancyRef
from core.kernel.errors import Unprocessable


def _meta(id_: int, analysis: AttachmentAnalysis | None) -> AttachmentMeta:
    return AttachmentMeta(
        id=id_,
        sha256=f"sha{id_}",
        mime="image/webp",
        width=10,
        height=10,
        bytes=100,
        thumb_width=5,
        thumb_height=5,
        analysis_status="ready" if analysis else "failed",
        analysis=analysis,
    )


def _correspondence(text: str = "дословный текст", turns: list[AttachmentTurn] | None = None):
    return AttachmentAnalysis(
        kind="correspondence", title="t", summary="s", text=text, turns=turns or []
    )


def _material(kind: str = "document"):
    return AttachmentAnalysis(kind=kind, title="Не переписка", summary="документ", text="что-то")


async def test_split_uses_turns_for_correspondence(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = _correspondence(
        turns=[
            AttachmentTurn(speaker="ИИ", text="Что такое GC?"),
            AttachmentTurn(speaker="Я", text="Сборка мусора"),
        ]
    )

    async def fake_wait_ready(ids, **_kwargs):
        assert list(ids) == [1]
        return [_meta(1, analysis)]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, correspondence_ids, material_ids = await prep_chat._split_external_attachments(
        [1], account_id=1
    )

    assert "ИИ: Что такое GC?" in text
    assert "Я: Сборка мусора" in text
    assert correspondence_ids == [1]
    assert material_ids == []


async def test_split_falls_back_to_text_without_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = _correspondence(text="со скрина")

    async def fake_wait_ready(ids, **_kwargs):
        return [_meta(1, analysis)]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, correspondence_ids, material_ids = await prep_chat._split_external_attachments(
        [1], account_id=1
    )

    assert text == "со скрина"
    assert correspondence_ids == [1]
    assert material_ids == []


async def test_split_flags_non_correspondence_as_material(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_wait_ready(ids, **_kwargs):
        return [_meta(2, _material())]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, correspondence_ids, material_ids = await prep_chat._split_external_attachments(
        [2], account_id=1
    )

    assert text == ""
    assert correspondence_ids == []
    assert material_ids == [2]


async def test_split_flags_failed_analysis_as_material(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_wait_ready(ids, **_kwargs):
        return [_meta(3, None)]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, correspondence_ids, material_ids = await prep_chat._split_external_attachments(
        [3], account_id=1
    )

    assert text == ""
    assert correspondence_ids == []
    assert material_ids == [3]


async def test_split_mixes_correspondence_and_material(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_wait_ready(ids, **_kwargs):
        return [_meta(1, _correspondence(text="переписка")), _meta(2, _material())]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, correspondence_ids, material_ids = await prep_chat._split_external_attachments(
        [1, 2], account_id=1
    )

    assert text == "переписка"
    assert correspondence_ids == [1]
    assert material_ids == [2]


async def test_split_no_attachments_returns_empty() -> None:
    text, correspondence_ids, material_ids = await prep_chat._split_external_attachments(
        [], account_id=1
    )

    assert text == ""
    assert correspondence_ids == []
    assert material_ids == []


# --------------------------------------------------------------------------- parse_external


def _ref() -> VacancyRef:
    return VacancyRef(vacancy_id="v1")


async def test_parse_external_material_only_routes_to_dialog_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Скрин, распознанный НЕ как переписка → «вложение диалога» (Э3, send_message), не парсер."""

    async def fake_wait_ready(ids, **_kwargs):
        return [_meta(9, _material(kind="diagram"))]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    calls: list[dict] = []

    async def fake_send_message(ref, **kwargs):
        calls.append(kwargs)
        return prep_chat.PrepChatReply(
            message=prep_chat.PrepChatMessage(
                id=1, vacancy_id=ref.vacancy_id, role="assistant", content="ok"
            )
        )

    monkeypatch.setattr(prep_chat, "send_message", fake_send_message)

    async def fail_parse_external_prep_chat(*_a, **_kw):
        raise AssertionError("parse_external_prep_chat не должен зваться без текста переписки")

    monkeypatch.setattr(prep_chat, "parse_external_prep_chat", fail_parse_external_prep_chat)

    reply = await prep_chat.parse_external(
        _ref(), stage="tech", transcript="", account_id=1, attachment_ids=[9]
    )

    assert reply.message.content == "ok"
    assert len(calls) == 1
    assert calls[0]["attachment_ids"] == [9]
    assert calls[0]["message"] == prep_chat._EXTERNAL_MATERIAL_MESSAGE


async def test_parse_external_nothing_to_parse_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_wait_ready(ids, **_kwargs):
        return []

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    with pytest.raises(Unprocessable):
        await prep_chat.parse_external(
            _ref(), stage="tech", transcript="   ", account_id=1, attachment_ids=[]
        )
