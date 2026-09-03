"""Нормализация загруженных изображений (Э0-1 плана вложений-картинок).

Чистая инфраструктура: не знает про вакансии, ленты, LLM. См. `normalize.py`.
"""

from __future__ import annotations

from core.platform.images.normalize import (
    NormalizedImage,
    Thumbnail,
    UnsupportedImageError,
    crop,
    decode_and_normalize,
    make_thumb,
)

__all__ = [
    "NormalizedImage",
    "Thumbnail",
    "UnsupportedImageError",
    "crop",
    "decode_and_normalize",
    "make_thumb",
]
