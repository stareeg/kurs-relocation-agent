"""UX6-13: аватар владельца (`core.domains.profile.avatar`) — без PG, реальный Pillow-конвейер.

`get_setting`/`set_setting` монкейпатчатся in-memory (стиль `test_telegram_link.py`);
нормализация гоняется по-настоящему через `core.platform.images` на маленьких сгенерированных
картинках (стиль `test_attachments_service.py`) — дёшево и проверяет реальную интеграцию.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from core.domains.profile import avatar


def _png_bytes(
    size: tuple[int, int] = (20, 10), color: tuple[int, int, int] = (10, 20, 30)
) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def settings_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    store: dict[str, Any] = {}

    async def fake_get(key: str, default: Any = None, *, account_id: Any = None, db: Any = None) -> Any:
        _ = account_id, db
        return store.get(key, default)

    async def fake_set(key: str, value: Any, *, account_id: Any = None, db: Any = None) -> None:
        _ = account_id, db
        if value is None:
            store.pop(key, None)
            return
        store[key] = value

    monkeypatch.setattr(avatar, "get_setting", fake_get)
    monkeypatch.setattr(avatar, "set_setting", fake_set)
    return store


async def test_no_avatar_by_default(settings_store: dict[str, Any]) -> None:
    assert await avatar.get_effective_avatar(account_id=1) is None


async def test_set_custom_avatar_normalizes_and_becomes_effective(
    settings_store: dict[str, Any],
) -> None:
    record = await avatar.set_custom_avatar(_png_bytes((30, 20)), account_id=1)

    assert record.source == "custom"
    assert record.mime == "image/webp"
    assert record.width == 30
    assert record.height == 20
    assert avatar.KEY_CUSTOM in settings_store
    assert avatar.KEY_TELEGRAM not in settings_store

    effective = await avatar.get_effective_avatar(account_id=1)
    assert effective is not None
    assert effective.source == "custom"


async def test_telegram_avatar_used_when_no_custom(settings_store: dict[str, Any]) -> None:
    record = await avatar.set_telegram_avatar(_png_bytes((16, 16)), account_id=1)

    assert record is not None
    assert record.source == "telegram"
    effective = await avatar.get_effective_avatar(account_id=1)
    assert effective is not None
    assert effective.source == "telegram"


async def test_telegram_avatar_does_not_override_custom(settings_store: dict[str, Any]) -> None:
    await avatar.set_custom_avatar(_png_bytes((10, 10), color=(1, 2, 3)), account_id=1)

    result = await avatar.set_telegram_avatar(_png_bytes((10, 10), color=(4, 5, 6)), account_id=1)

    assert result is None  # тихо ничего не сделал — не перетёр ручную картинку
    effective = await avatar.get_effective_avatar(account_id=1)
    assert effective is not None
    assert effective.source == "custom"


async def test_clear_custom_avatar_falls_back_to_telegram(settings_store: dict[str, Any]) -> None:
    await avatar.set_telegram_avatar(_png_bytes(), account_id=1)
    await avatar.set_custom_avatar(_png_bytes(), account_id=1)

    await avatar.clear_custom_avatar(account_id=1)

    effective = await avatar.get_effective_avatar(account_id=1)
    assert effective is not None
    assert effective.source == "telegram"


async def test_clear_custom_avatar_without_telegram_leaves_none(
    settings_store: dict[str, Any],
) -> None:
    await avatar.set_custom_avatar(_png_bytes(), account_id=1)

    await avatar.clear_custom_avatar(account_id=1)

    assert await avatar.get_effective_avatar(account_id=1) is None
