"""Мелкие хелперы бота."""

from __future__ import annotations

import html


def esc(text: str) -> str:
    """HTML-экранирование для parse_mode=HTML (телеграм требует & < >)."""
    return html.escape(str(text), quote=False)


__all__ = ["esc"]
