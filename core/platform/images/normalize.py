"""Нормализация картинок для вложений в чатах.

Синхронное и CPU-bound (Pillow держит GIL на большой картинке) — вызывающая сторона обязана
оборачивать вызовы в `asyncio.to_thread`, здесь никакого `asyncio` нет намеренно.

Формат сниффится содержимым (Pillow сам разбирает сигнатуру байт при `Image.open`), а не
Content-Type запроса — клиент может соврать заголовком.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

# SVG сюда не входит намеренно — это документ со скриптами, не растровое изображение.
# HEIC/AVIF Pillow без доп. плагинов не откроет — упадут в UnsupportedImageError сами.
_ACCEPTED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}


class UnsupportedImageError(ValueError):
    """Байты не распознаны как изображение принимаемого формата."""


@dataclass(frozen=True, slots=True)
class NormalizedImage:
    """Готово к записи в `attachments.data` / отправке в vision-модель."""

    data: bytes
    mime: str  # всегда "image/webp"
    width: int
    height: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Thumbnail:
    """Готово к записи в `attachments.thumb`."""

    data: bytes
    mime: str  # всегда "image/webp"
    width: int
    height: int


def decode_and_normalize(raw: bytes, *, max_side: int) -> NormalizedImage:
    """raw → EXIF-развёрнутый RGB(A) без метаданных, даунскейл LANCZOS, кодирование в WebP.

    PNG-источник (типичный скриншот) кодируется lossless — текст на скрине не должен
    размываться, его потом распознаёт модель; остальные форматы — lossy q85.

    Raises:
        UnsupportedImageError: битые байты или формат вне `_ACCEPTED_FORMATS`.
    """
    image, source_format = _open(raw)
    image = ImageOps.exif_transpose(image) or image
    image = _drop_metadata(image)
    image = _downscale(image, max_side)
    data = _encode_webp(image, lossless=source_format == "PNG")
    width, height = image.size
    return NormalizedImage(
        data=data,
        mime="image/webp",
        width=width,
        height=height,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def make_thumb(normalized: bytes, *, max_side: int) -> Thumbnail:
    """Превью из уже нормализованных байт. Независимый даунскейл, всегда lossy — это превью."""
    image = _load_normalized(normalized)
    image = _downscale(image, max_side)
    data = _encode_webp(image, lossless=False)
    width, height = image.size
    return Thumbnail(data=data, mime="image/webp", width=width, height=height)


def crop(normalized: bytes, box: tuple[float, float, float, float]) -> NormalizedImage:
    """Вырезает `box = (x, y, w, h)` — доли 0..1 относительно `normalized` — в новую картинку.

    Не мутирует исходник (вызывающая сторона сама решает, что делать со старой строкой —
    см. `derived_from` в §2.1 плана); клампится к границам, чтобы округление долей не вылезло
    за размер изображения.
    """
    image = _load_normalized(normalized)
    width, height = image.size
    x, y, w, h = box
    left = max(0, min(round(x * width), width))
    top = max(0, min(round(y * height), height))
    right = max(0, min(round((x + w) * width), width))
    bottom = max(0, min(round((y + h) * height), height))
    if right <= left or bottom <= top:
        raise ValueError("crop box пуст после клампа к границам изображения")

    cropped = image.crop((left, top, right, bottom))
    data = _encode_webp(cropped, lossless=True)
    cw, ch = cropped.size
    return NormalizedImage(
        data=data,
        mime="image/webp",
        width=cw,
        height=ch,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _open(raw: bytes) -> tuple[Image.Image, str | None]:
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:  # Pillow бросает разные исключения на битых/неизвестных байтах
        raise UnsupportedImageError("не удалось распознать файл как изображение") from exc
    if image.format not in _ACCEPTED_FORMATS:
        raise UnsupportedImageError(f"формат {image.format} не поддерживается")
    return image, image.format


def _load_normalized(normalized: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(normalized))
    image.load()
    return image


def _drop_metadata(image: Image.Image) -> Image.Image:
    # convert() строит новый Image без EXIF/ICC/прочих ключей .info — самый простой способ
    # снять метаданные (в т.ч. GPS), не перечисляя теги руками.
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        return image.convert("RGBA")
    return image.convert("RGB")


def _downscale(image: Image.Image, max_side: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _encode_webp(image: Image.Image, *, lossless: bool) -> bytes:
    buf = io.BytesIO()
    if lossless:
        image.save(buf, format="WEBP", lossless=True, method=6)
    else:
        image.save(buf, format="WEBP", quality=85, method=6)
    return buf.getvalue()
