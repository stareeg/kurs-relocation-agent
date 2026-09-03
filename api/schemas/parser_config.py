"""Транспорт конфига селекторов парсера hh (`GET /api/opportunities/parser-config/hh`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ParserSelectorsConfigOut(BaseModel):
    version: int
    updated_at: datetime
    origin: Literal["db_override", "repo"]
    selectors: dict[str, Any]
    patterns: dict[str, str | bool] = Field(default_factory=dict)


class ExtensionRuntimeConfigOut(BaseModel):
    """`GET /api/opportunities/parser-config/extension` — флаги/тюнинг/селекторы отклика и
    разбора/текстовые сигналы, расширение тянет их вместо хардкода, чтобы фиксы не требовали
    переустановки zip."""

    version: int
    updated_at: datetime
    origin: Literal["db_override", "repo"]
    flags: dict[str, bool]
    tuning: dict[str, Any]
    apply_selectors: dict[str, dict[str, str]] = Field(default_factory=dict)
    parse_selectors: dict[str, dict[str, str]] = Field(default_factory=dict)
    text_signals: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
