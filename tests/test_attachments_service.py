"""Э0-3: сервис вложений — обязательный персист (нет PG → 503), 404/400 контракты.

`repo.*` монкейпатчится напрямую (без DB-фикстур, CLAUDE.md); нормализация/кроп гоняются по-настоящему
через Pillow на маленьких сгенерированных картинках — это дёшево и проверяет реальную интеграцию
`service` с `core.platform.images`.

M4 (plans/multitenancy_gaps_2026_08_06.md §3.5): все вызовы несут `account_id` — `repo.get_meta`/
`get_data` теперь фильтруют по аккаунту, чужой id неотличим от отсутствующего (`NotFound`).
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from core.domains.assistant.attachments import service
from core.domains.assistant.attachments.models import Attachment, AttachmentAnalysis, AttachmentMeta
from core.kernel.errors import InvalidInput, NotFound, StorageUnavailable, Unprocessable

_ACCOUNT_A = 1


def _png_bytes(size: tuple[int, int] = (20, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _meta_from_upsert_kwargs(assigned_id: int, kwargs: dict[str, Any]) -> AttachmentMeta:
    return AttachmentMeta(
        id=assigned_id,
        sha256=kwargs["sha256"],
        mime=kwargs["mime"],
        width=kwargs["width"],
        height=kwargs["height"],
        bytes=len(kwargs["data"]),
        thumb_width=kwargs["thumb_width"],
        thumb_height=kwargs["thumb_height"],
        derived_from=kwargs.get("derived_from"),
        crop=kwargs.get("crop"),
        analysis_status="pending",
    )


async def test_store_upload_persists_normalized_image(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_upsert(**kwargs: Any) -> AttachmentMeta:
        captured.update(kwargs)
        return _meta_from_upsert_kwargs(1, kwargs)

    monkeypatch.setattr(service.repo, "upsert_attachment", fake_upsert)

    meta = await service.store_upload(_png_bytes((20, 10)), account_id=_ACCOUNT_A)

    assert meta.id == 1
    assert meta.mime == "image/webp"
    assert captured["account_id"] == _ACCOUNT_A
    assert captured["width"] == 20
    assert captured["height"] == 10


async def test_store_upload_raises_storage_unavailable_without_pg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_upsert(**_kwargs: Any) -> AttachmentMeta:
        raise RuntimeError("no pg")

    monkeypatch.setattr(service.repo, "upsert_attachment", fake_upsert)

    with pytest.raises(StorageUnavailable):
        await service.store_upload(_png_bytes(), account_id=_ACCOUNT_A)


async def test_store_upload_routes_text_plain_to_document_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_upsert(**kwargs: Any) -> AttachmentMeta:
        captured.update(kwargs)
        return _meta_from_upsert_kwargs(1, kwargs)

    async def fake_set_analysis(*args: Any, **kwargs: Any) -> None:
        captured["set_analysis_args"] = kwargs

    monkeypatch.setattr(service.repo, "upsert_attachment", fake_upsert)
    monkeypatch.setattr(service.repo, "set_analysis", fake_set_analysis)

    meta = await service.store_upload(
        b"hello world", account_id=_ACCOUNT_A, content_type="text/plain", filename="notes.txt"
    )

    assert captured["mime"] == "text/plain"
    assert captured["width"] == 0
    assert captured["thumb"] == b""
    assert meta.analysis_status == "ready"
    assert meta.analysis is not None
    assert meta.analysis.text == "hello world"
    assert meta.analysis.title == "notes.txt"


async def test_store_upload_routes_md_extension_when_content_type_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """.md часто приходит с generic/пустым content-type — расширение должно подстраховать."""
    captured: dict[str, Any] = {}

    async def fake_upsert(**kwargs: Any) -> AttachmentMeta:
        captured.update(kwargs)
        return _meta_from_upsert_kwargs(1, kwargs)

    async def fake_set_analysis(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr(service.repo, "upsert_attachment", fake_upsert)
    monkeypatch.setattr(service.repo, "set_analysis", fake_set_analysis)

    await service.store_upload(
        b"# heading", account_id=_ACCOUNT_A, content_type="application/octet-stream", filename="readme.md"
    )

    assert captured["mime"] == "text/markdown"


async def test_store_upload_document_extract_error_raises_invalid_input() -> None:
    with pytest.raises(InvalidInput):
        await service.store_upload(
            b"", account_id=_ACCOUNT_A, content_type="text/plain", filename="empty.txt"
        )


async def test_store_upload_document_dedup_skips_reextraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Тот же sha256 уже разобран (дедуп по account_id+sha256) — не зовём set_analysis повторно."""

    async def fake_upsert(**kwargs: Any) -> AttachmentMeta:
        meta = _meta_from_upsert_kwargs(1, kwargs)
        return meta.model_copy(update={"analysis_status": "ready"})

    async def fail_set_analysis(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("set_analysis не должен звать при дедупе")

    monkeypatch.setattr(service.repo, "upsert_attachment", fake_upsert)
    monkeypatch.setattr(service.repo, "set_analysis", fail_set_analysis)

    meta = await service.store_upload(
        b"hello", account_id=_ACCOUNT_A, content_type="text/plain", filename="a.txt"
    )
    assert meta.analysis_status == "ready"


async def test_store_upload_still_routes_images_to_pillow_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """content_type картинки не совпадает ни с одним документным mime — прежний путь Pillow."""
    captured: dict[str, Any] = {}

    async def fake_upsert(**kwargs: Any) -> AttachmentMeta:
        captured.update(kwargs)
        return _meta_from_upsert_kwargs(1, kwargs)

    monkeypatch.setattr(service.repo, "upsert_attachment", fake_upsert)

    meta = await service.store_upload(
        _png_bytes(), account_id=_ACCOUNT_A, content_type="image/png", filename="shot.png"
    )
    assert meta.mime == "image/webp"
    assert captured["width"] == 20


async def test_get_meta_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_meta(_attachment_id: int, *, account_id: int, db: Any = None) -> None:
        return None

    monkeypatch.setattr(service.repo, "get_meta", fake_get_meta)

    with pytest.raises(NotFound):
        await service.get_meta(1, account_id=_ACCOUNT_A)


async def test_get_meta_storage_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_meta(_attachment_id: int, *, account_id: int, db: Any = None) -> None:
        raise RuntimeError("no pg")

    monkeypatch.setattr(service.repo, "get_meta", fake_get_meta)

    with pytest.raises(StorageUnavailable):
        await service.get_meta(1, account_id=_ACCOUNT_A)


async def test_crop_attachment_source_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_data(_attachment_id: int, *, account_id: int, db: Any = None) -> None:
        return None

    monkeypatch.setattr(service.repo, "get_data", fake_get_data)

    with pytest.raises(NotFound):
        await service.crop_attachment(1, (0.0, 0.0, 1.0, 1.0), account_id=_ACCOUNT_A)


async def test_crop_attachment_empty_box_raises_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Attachment(
        id=1,
        sha256="src",
        mime="image/webp",
        width=10,
        height=10,
        bytes=10,
        thumb_width=5,
        thumb_height=5,
        analysis_status="ready",
        data=_png_bytes((10, 10)),
        thumb=b"thumb",
    )

    async def fake_get_data(_attachment_id: int, *, account_id: int, db: Any = None) -> Attachment:
        return source

    monkeypatch.setattr(service.repo, "get_data", fake_get_data)

    # box целиком вне картинки после клампа к границам -> пустой прямоугольник.
    with pytest.raises(InvalidInput):
        await service.crop_attachment(1, (2.0, 2.0, 1.0, 1.0), account_id=_ACCOUNT_A)


async def test_crop_attachment_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Attachment(
        id=7,
        sha256="src",
        mime="image/webp",
        width=20,
        height=20,
        bytes=10,
        thumb_width=5,
        thumb_height=5,
        analysis_status="ready",
        data=_png_bytes((20, 20)),
        thumb=b"thumb",
    )
    captured: dict[str, Any] = {}

    async def fake_get_data(attachment_id: int, *, account_id: int, db: Any = None) -> Attachment:
        assert attachment_id == 7
        assert account_id == _ACCOUNT_A
        return source

    async def fake_upsert(**kwargs: Any) -> AttachmentMeta:
        captured.update(kwargs)
        return _meta_from_upsert_kwargs(8, kwargs)

    monkeypatch.setattr(service.repo, "get_data", fake_get_data)
    monkeypatch.setattr(service.repo, "upsert_attachment", fake_upsert)

    meta = await service.crop_attachment(7, (0.0, 0.0, 0.5, 0.5), account_id=_ACCOUNT_A)

    assert meta.derived_from == 7
    assert meta.crop == {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}
    assert captured["account_id"] == _ACCOUNT_A
    assert captured["derived_from"] == 7
    assert captured["crop"] == {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}


async def test_crop_attachment_raises_storage_unavailable_on_save_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Attachment(
        id=1,
        sha256="src",
        mime="image/webp",
        width=10,
        height=10,
        bytes=10,
        thumb_width=5,
        thumb_height=5,
        analysis_status="ready",
        data=_png_bytes((10, 10)),
        thumb=b"thumb",
    )

    async def fake_get_data(_attachment_id: int, *, account_id: int, db: Any = None) -> Attachment:
        return source

    async def fake_upsert(**_kwargs: Any) -> AttachmentMeta:
        raise RuntimeError("no pg")

    monkeypatch.setattr(service.repo, "get_data", fake_get_data)
    monkeypatch.setattr(service.repo, "upsert_attachment", fake_upsert)

    with pytest.raises(StorageUnavailable):
        await service.crop_attachment(1, (0.0, 0.0, 1.0, 1.0), account_id=_ACCOUNT_A)


async def test_wait_ready_returns_metas_once_not_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    ready = AttachmentMeta(
        id=1,
        sha256="s1",
        mime="image/webp",
        width=1,
        height=1,
        bytes=1,
        thumb_width=1,
        thumb_height=1,
        analysis_status="ready",
    )

    async def fake_get_meta(attachment_id: int, *, account_id: int, db: Any = None) -> AttachmentMeta:
        assert attachment_id == 1
        assert account_id == _ACCOUNT_A
        return ready

    monkeypatch.setattr(service.repo, "get_meta", fake_get_meta)

    metas = await service.wait_ready([1], account_id=_ACCOUNT_A)

    assert metas == [ready]


async def test_wait_ready_polls_until_pending_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def fake_get_meta(attachment_id: int, *, account_id: int, db: Any = None) -> AttachmentMeta:
        calls["n"] += 1
        status = "pending" if calls["n"] < 3 else "ready"
        return AttachmentMeta(
            id=attachment_id,
            sha256="s",
            mime="image/webp",
            width=1,
            height=1,
            bytes=1,
            thumb_width=1,
            thumb_height=1,
            analysis_status=status,
        )

    monkeypatch.setattr(service.repo, "get_meta", fake_get_meta)

    metas = await service.wait_ready([1], account_id=_ACCOUNT_A, poll_interval_s=0)

    assert metas[0].analysis_status == "ready"
    assert calls["n"] == 3


async def test_wait_ready_timeout_raises_unprocessable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_meta(attachment_id: int, *, account_id: int, db: Any = None) -> AttachmentMeta:
        return AttachmentMeta(
            id=attachment_id,
            sha256="s",
            mime="image/webp",
            width=1,
            height=1,
            bytes=1,
            thumb_width=1,
            thumb_height=1,
            analysis_status="pending",
        )

    monkeypatch.setattr(service.repo, "get_meta", fake_get_meta)

    with pytest.raises(Unprocessable):
        await service.wait_ready([1], account_id=_ACCOUNT_A, timeout_s=0, poll_interval_s=0)


async def test_wait_ready_empty_input_short_circuits() -> None:
    assert await service.wait_ready([], account_id=_ACCOUNT_A) == []


async def test_load_llm_context_skips_other_accounts_attachment_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M4: IDOR-попытка (чужой attachment_id в payload чата) не валит ответ и не
    подтверждает существование строки — молча пропускается, как и раньше пропускался
    GC'нутый/устаревший id."""

    async def fake_get_data(_attachment_id: int, *, account_id: int, db: Any = None) -> None:
        return None

    monkeypatch.setattr(service.repo, "get_data", fake_get_data)

    images, doc_text = await service.load_llm_context([999], account_id=_ACCOUNT_A)

    assert images == []
    assert doc_text == ""


async def test_load_llm_context_splits_images_and_document_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Картинка → `images=`, документ с готовым разбором → текстовый блок, документ без
    разбора (analysis_status != 'ready') — молча пропускается (нечего отдать модели)."""

    def fake_meta(id_: int, **overrides: Any) -> AttachmentMeta:
        base = dict(
            id=id_,
            sha256=f"sha-{id_}",
            mime="image/png",
            width=1,
            height=1,
            bytes=1,
            thumb_width=1,
            thumb_height=1,
            analysis_status="pending",
            analysis=None,
        )
        base.update(overrides)
        return AttachmentMeta(**base)

    rows = {
        1: fake_meta(1, mime="image/png"),
        2: fake_meta(
            2,
            mime="text/plain",
            analysis_status="ready",
            analysis=AttachmentAnalysis(
                kind="document", title="notes.txt", summary="", text="важные заметки", confidence=1.0
            ),
        ),
        3: fake_meta(3, mime="application/pdf", analysis_status="pending", analysis=None),
    }

    async def fake_get_data(attachment_id: int, *, account_id: int, db: Any = None) -> Any:
        meta = rows[attachment_id]
        return Attachment(**meta.model_dump(), data=b"bytes", thumb=b"thumb")

    monkeypatch.setattr(service.repo, "get_data", fake_get_data)

    images, doc_text = await service.load_llm_context([1, 2, 3], account_id=_ACCOUNT_A)

    assert len(images) == 1
    assert images[0].sha256 == "sha-1"
    assert "notes.txt" in doc_text
    assert "важные заметки" in doc_text
    assert "sha-3" not in doc_text
