"""Транспортные схемы API: multiplayer (лобби «Хрюши и Волки»)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from core.domains.multiplayer.models import JoinAs, RoomMode

# RoomOut / RoomSeatView — доменные модели, отдаём как response_model напрямую.


class CreateRoomRequest(BaseModel):
    name: str | None = Field(
        default=None,
        max_length=64,
        description="Имя стола; пусто → авто «Стол №N»",
    )
    slots: int = Field(default=2, ge=2, le=6, description="Число слотов кандидатов (2–6)")
    mode: RoomMode = RoomMode.FRIENDS
    pin: str | None = Field(
        default=None,
        description="Опциональный PIN 4–6 цифр; пусто = без PIN",
    )
    friends_only: bool = Field(
        default=False,
        description="Устарело: столы публичны для всех аккаунтов",
    )
    daily: bool = Field(
        default=False,
        description="Э12: стол дня (solo + seed от даты); игнорирует mode/PIN/friends_only",
    )
    nick: str | None = Field(
        default=None,
        max_length=24,
        description="Ник за столом (не ФИО); пусто → @telegram",
    )

    @field_validator("name")
    @classmethod
    def _name_trim(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @field_validator("nick")
    @classmethod
    def _nick_trim(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @field_validator("pin")
    @classmethod
    def _pin_digits(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not v.isdigit() or not (4 <= len(v) <= 6):
            raise ValueError("PIN — 4–6 цифр")
        return v


class JoinRoomRequest(BaseModel):
    as_: JoinAs = Field(default=JoinAs.PLAYER, alias="as")
    pin: str | None = Field(default=None, description="PIN стола, если has_pin")
    nick: str | None = Field(
        default=None,
        max_length=24,
        description="Ник за столом (не ФИО)",
    )

    model_config = {"populate_by_name": True}

    @field_validator("nick")
    @classmethod
    def _nick_trim(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None
