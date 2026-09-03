"""Э4-1 (chat_image_attachments_2026_08_03.md, «Чаты · HR»): склейка текста дампа.

`_build_import_text` — новая логика этого шага: вручную набранный текст + распознанный текст
скринов-переписок идут в один дамп для существующего `hr_import`, а картинки НЕ распознанные как
переписка возвращаются отдельно (`unrecognized`), чтобы фронт предложил приложить их как вложение
вместо импорта. `attachments_service.wait_ready` монкейпатчится напрямую (репозиторий/БД не
трогаем, тот же приём, что в `test_attachments_service.py`).
"""

from __future__ import annotations

import pytest

from core.app.scenarios import conversations
from core.domains.assistant.attachments import service as attachments_service
from core.domains.assistant.attachments.models import (
    AttachmentAnalysis,
    AttachmentMeta,
    AttachmentTurn,
)


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


async def test_build_import_text_uses_turns_for_correspondence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = AttachmentAnalysis(
        kind="correspondence",
        title="Скрин переписки",
        summary="переписка с HR",
        text="раз текст",
        turns=[
            AttachmentTurn(speaker="HR", text="Добрый день"),
            AttachmentTurn(speaker="Я", text="Здравствуйте"),
        ],
    )

    async def fake_wait_ready(ids, **_kwargs):
        assert list(ids) == [1]
        return [_meta(1, analysis)]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, unrecognized = await conversations._build_import_text("", [1], account_id=1)

    assert unrecognized == []
    assert "HR: Добрый день" in text
    assert "Я: Здравствуйте" in text


async def test_build_import_text_falls_back_to_text_without_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = AttachmentAnalysis(
        kind="correspondence", title="t", summary="s", text="дословный текст со скрина", turns=[]
    )

    async def fake_wait_ready(ids, **_kwargs):
        return [_meta(1, analysis)]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, unrecognized = await conversations._build_import_text("", [1], account_id=1)

    assert unrecognized == []
    assert text == "дословный текст со скрина"


async def test_build_import_text_combines_manual_text_and_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = AttachmentAnalysis(
        kind="correspondence", title="t", summary="s", text="со скрина", turns=[]
    )

    async def fake_wait_ready(ids, **_kwargs):
        return [_meta(1, analysis)]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, unrecognized = await conversations._build_import_text(
        "вручную набранный текст", [1], account_id=1
    )

    assert unrecognized == []
    assert "вручную набранный текст" in text
    assert "со скрина" in text
    assert text.index("вручную набранный текст") < text.index("со скрина")


async def test_build_import_text_flags_non_correspondence_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = AttachmentAnalysis(
        kind="document", title="Не переписка", summary="документ", text="какой-то текст"
    )

    async def fake_wait_ready(ids, **_kwargs):
        return [_meta(2, analysis)]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, unrecognized = await conversations._build_import_text("", [2], account_id=1)

    assert text == ""
    assert unrecognized == [2]


async def test_build_import_text_flags_failed_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_wait_ready(ids, **_kwargs):
        return [_meta(3, None)]

    monkeypatch.setattr(attachments_service, "wait_ready", fake_wait_ready)

    text, unrecognized = await conversations._build_import_text("", [3], account_id=1)

    assert text == ""
    assert unrecognized == [3]


async def test_build_import_text_no_attachments_returns_manual_text_only() -> None:
    text, unrecognized = await conversations._build_import_text("просто текст", [], account_id=1)

    assert text == "просто текст"
    assert unrecognized == []
