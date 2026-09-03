"""Короткие подсказки для спойлеров «Формулировки» и «Релевантность роли» — без AI-slop."""

from __future__ import annotations

import re

from core.domains.profile.gap import WeakBullet

# Префиксы/мета, которые LLM любит вставлять в reason/notes.
_SLOP_PREFIX_RE = re.compile(
    r"^(?:"
    r"(?:буллет\s+)?(?:слаб(?:ый|ая|ое)|strong|weak)\b[^—\-:]*[:—\-]\s*"
    r"|(?:рекоменду(?:ю|ется)|следует|желательно|стоит|нужно)\s+"
    r"|(?:вердикт|оценка|комментарий)\s*[:—\-]\s*"
    r")+",
    re.IGNORECASE,
)
_META_WORDS_RE = re.compile(
    r"\b(?:слаб(?:ый|ая|ое)|strong|weak|вердикт)\b",
    re.IGNORECASE,
)

_DEFAULT_WRITING_TIP = "добавьте действие, технологии или измеримый результат"


_GENITIVE_TO_NOMINATIVE: dict[str, str] = {
    "результата": "результат",
    "метрик": "метрики",
    "технологий": "технологии",
    "конкретного действия": "конкретное действие",
    "масштаба": "масштаб",
}


def normalize_score_tip(text: str) -> str:
    """Одна строка совета без мета-комментариев LLM."""
    line = " ".join((text or "").split())
    if not line:
        return ""
    line = _SLOP_PREFIX_RE.sub("", line).strip()
    line = _META_WORDS_RE.sub("", line)
    line = re.sub(r"\s{2,}", " ", line).strip(" .—-–")
    m = re.match(r"^нет\s+(.+)$", line, re.IGNORECASE)
    if m:
        rest = m.group(1).strip().casefold()
        fixed = _GENITIVE_TO_NOMINATIVE.get(rest, m.group(1).strip())
        return f"добавьте {fixed}"
    return line


def format_writing_tip(bullet: WeakBullet, *, quote_max: int = 55) -> str:
    """Одна строка: где слабо и что улучшить."""
    ref = (bullet.ref or "").strip()
    quote = (bullet.text or "").strip()
    if len(quote) > quote_max:
        quote = quote[: quote_max - 1].rstrip() + "…"
    reason = normalize_score_tip(bullet.reason or "")
    if not reason:
        reason = _DEFAULT_WRITING_TIP
    if ref:
        return f"{ref}: «{quote}» — {reason}"
    return f"«{quote}» — {reason}"


def format_role_fit_note(note: str) -> str:
    """Нормализованная подсказка role_fit — одно действие в строке."""
    line = normalize_score_tip(note)
    if not line:
        return ""
    # Первая буква строчная, если строка не начинается с кавычки/цифры.
    if line[0].isupper() and not line.startswith(("«", '"', "RAG", "LLM")):
        line = line[0].lower() + line[1:]
    return line


__all__ = ["format_role_fit_note", "format_writing_tip", "normalize_score_tip"]
