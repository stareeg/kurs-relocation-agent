"""Аватар владельца: `GET` байты, `POST` ручная загрузка, `DELETE` — назад на Telegram.

Тот же приём отдачи картинки, что у `/api/attachments/{id}` (ETag/Cache-Control, байты — уже
нормализованный WebP): фронт держит `<img src="/api/profile/avatar">` прямо в сайдбаре.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile

from api.schemas import AvatarMetaOut
from api.security import AccountContext, require_account
from core.domains.profile import avatar
from core.platform.images import UnsupportedImageError

router = APIRouter(prefix="/api/profile/avatar", tags=["profile"])

_IMAGE_HEADERS = {
    "Cache-Control": "private, max-age=300",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'",
    "Content-Disposition": "inline",
}


def _meta_out(record: avatar.AvatarImage) -> AvatarMetaOut:
    return AvatarMetaOut(
        source=record.source, width=record.width, height=record.height, updated_at=record.updated_at
    )


def _image_response(request: Request, record: avatar.AvatarImage) -> Response:
    etag = f'"{record.source}-{int(record.updated_at.timestamp())}"'
    inm = request.headers.get("if-none-match", "")
    if etag in (tag.strip() for tag in inm.split(",") if tag.strip()):
        return Response(status_code=304, headers={"ETag": etag, **_IMAGE_HEADERS})
    return Response(
        content=base64.b64decode(record.data_b64),
        media_type=record.mime,
        headers={"ETag": etag, **_IMAGE_HEADERS},
    )


@router.get("", response_model=AvatarMetaOut | None)
async def get_avatar_meta(
    account: AccountContext | None = Depends(require_account),
) -> AvatarMetaOut | None:
    """Мета без байт — фронт решает, рисовать ли `<img>`, не гоняя картинку впустую."""
    record = await avatar.get_effective_avatar(account_id=account.account_id if account else None)
    return _meta_out(record) if record else None


@router.get("/image")
async def get_avatar_image(
    request: Request, account: AccountContext | None = Depends(require_account)
) -> Response:
    """Сами байты (WebP) — `<img src="/api/profile/avatar/image">`. Нет аватара → 404."""
    record = await avatar.get_effective_avatar(account_id=account.account_id if account else None)
    if record is None:
        raise HTTPException(status_code=404, detail="Аватар не задан")
    return _image_response(request, record)


@router.post("", response_model=AvatarMetaOut)
async def post_avatar(
    file: UploadFile = File(...),
    account: AccountContext | None = Depends(require_account),
) -> AvatarMetaOut:
    """Ручная загрузка — сохраняется как `custom`, приоритет над Telegram-фото."""
    raw = await file.read()
    try:
        record = await avatar.set_custom_avatar(
            raw, account_id=account.account_id if account else None
        )
    except UnsupportedImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _meta_out(record)


@router.delete("", status_code=204, response_model=None)
async def delete_avatar(account: AccountContext | None = Depends(require_account)) -> None:
    """Убрать ручную картинку — назад на Telegram-фото (если есть) или дефолтную иконку."""
    await avatar.clear_custom_avatar(account_id=account.account_id if account else None)
