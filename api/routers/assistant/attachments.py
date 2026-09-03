"""Вложения: приём файла, отдача байт/превью, кроп (Э0-4). Картинки — Э0-3; текстовые
документы (txt/md/pdf/docx, 2026-08-11) — свой путь без Pillow, см. `service.py`.

Байты картинки в ответе — уже нормализованный WebP (Pillow перекодировал на приёме,
`core.platform.images`); исходный файл наружу никогда не отдаётся. Документ отдаётся как есть
(raw bytes, свой mime) — нормализовать текстовый файл нечем и незачем
(см. `core/domains/assistant/attachments/service.py`).
`ETag` строится из `sha256` нормализованных байт (контент-адрес, плана) — стабилен, пока
строка не изменилась, поэтому `If-None-Match` даёт дешёвый 304.

Распознавание (`attachment_read`, фоновая задача) сюда не входит — это Этап 1 плана; до тех пор
`analysis_status` каждого вложения остаётся `pending`, и это ожидаемо.

M4 (plans/multitenancy_gaps_2026_08_06.md §3.5): весь роутер — за `require_account_context`.
Чужой/несуществующий `attachment_id` неотличим (оба дают 404 через `service.get_meta`/
`get_attachment` → `NotFound`) — так перебор id не подтверждает существование чужой строки.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile

from api.errors import to_http
from api.schemas.attachments import AttachmentCropRequest, AttachmentOut, attachment_meta_out
from api.security import AccountContext, require_account_context
from core.domains.assistant.attachments import service
from core.domains.assistant.attachments.models import Attachment
from core.kernel.errors import DomainError
from core.platform.images import UnsupportedImageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

_IMAGE_HEADERS = {
    "Cache-Control": "private, max-age=31536000, immutable",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'",
    "Content-Disposition": "inline",
}


def _etag_for(sha256: str, *, suffix: str = "") -> str:
    return f'"{sha256}{suffix}"'


def _not_modified(request: Request, etag: str) -> Response | None:
    inm = request.headers.get("if-none-match", "")
    if etag in (tag.strip() for tag in inm.split(",") if tag.strip()):
        return Response(status_code=304, headers={"ETag": etag, **_IMAGE_HEADERS})
    return None


def _bytes_response(request: Request, attachment: Attachment, *, thumb: bool) -> Response:
    etag = _etag_for(attachment.sha256, suffix="-thumb" if thumb else "")
    hit = _not_modified(request, etag)
    if hit is not None:
        return hit
    return Response(
        content=attachment.thumb if thumb else attachment.data,
        media_type=attachment.mime,
        headers={"ETag": etag, **_IMAGE_HEADERS},
    )


async def _store_one_upload(file: UploadFile, *, account_id: int) -> AttachmentOut:
    raw = await file.read()
    try:
        meta = await service.store_upload(
            raw, account_id=account_id, content_type=file.content_type, filename=file.filename
        )
    except UnsupportedImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DomainError as exc:
        raise to_http(exc) from exc
    return attachment_meta_out(meta)


@router.post("", response_model=list[AttachmentOut])
async def post_attachments(
    files: list[UploadFile] = File(...),
    account: AccountContext = Depends(require_account_context),
) -> list[AttachmentOut]:
    """Multipart, 1..N файлов → по одному `AttachmentOut` на файл; идемпотентно по (аккаунт,
    sha256)."""
    if not files:
        raise HTTPException(status_code=400, detail="нужен хотя бы один файл")
    return [await _store_one_upload(f, account_id=account.account_id) for f in files]


@router.get("/{attachment_id}/meta", response_model=AttachmentOut)
async def get_attachment_meta(
    attachment_id: int, account: AccountContext = Depends(require_account_context)
) -> AttachmentOut:
    try:
        meta = await service.get_meta(attachment_id, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return attachment_meta_out(meta)


@router.get("/{attachment_id}/thumb")
async def get_attachment_thumb(
    attachment_id: int, request: Request, account: AccountContext = Depends(require_account_context)
) -> Response:
    try:
        attachment = await service.get_attachment(attachment_id, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return _bytes_response(request, attachment, thumb=True)


@router.get("/{attachment_id}")
async def get_attachment_bytes(
    attachment_id: int, request: Request, account: AccountContext = Depends(require_account_context)
) -> Response:
    try:
        attachment = await service.get_attachment(attachment_id, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return _bytes_response(request, attachment, thumb=False)


@router.post("/{attachment_id}/crop", response_model=AttachmentOut)
async def post_attachment_crop(
    attachment_id: int,
    body: AttachmentCropRequest,
    account: AccountContext = Depends(require_account_context),
) -> AttachmentOut:
    try:
        meta = await service.crop_attachment(
            attachment_id, (body.x, body.y, body.w, body.h), account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return attachment_meta_out(meta)
