"""Парсинг и нормализация буллетов резюме (опыт / «Обо мне»).

`parse_bullets` — только явные маркеры (для скоринга; prose не дробим — иначе ложные срабатывания).
`ensure_bullet_format` — пост-процессор выхода LLM (ATS/strengthen): всегда `- …` построчно.
"""

from __future__ import annotations

import re

# Явный маркер в начале строки: markdown, нумерация, типографские буллеты hh/PDF.
_BULLET_LINE_RE = re.compile(
    r"(?m)^[ \t]*"
    r"(?:"
    r"[-*+•·▪◦]\s+"
    r"|[\u2013\u2014\u2212]\s+"
    r"|\d+[.)]\s+"
    r")"
    r"(.+?\S)[ \t]*$"
)

# Заголовки секций («Обязанности:», «Достижения:») — не буллеты.
_SECTION_HEADER_RE = re.compile(
    r"^[ \t]*[А-ЯA-Za-z0-9][^.\n]{0,48}:\s*$",
    re.UNICODE,
)

# Разбиение prose на предложения (RU/EN начало следующего).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯA-Z0-9«\"(])")


def _strip_marker(line: str) -> str:
    """Снять маркер с одной строки, если он есть."""
    m = _BULLET_LINE_RE.match(line)
    if m:
        return m.group(1).strip()
    # Inline «• item» в начале строки без пробела после маркера
    m2 = re.match(r"^[ \t]*[•·▪◦]\s*(.+?\S)[ \t]*$", line)
    if m2:
        return m2.group(1).strip()
    return line.strip()


def _is_section_header(line: str) -> bool:
    return bool(_SECTION_HEADER_RE.match(line.strip()))


def parse_bullets(text: str) -> list[str]:
    """Строки-буллеты с явным маркером. Prose без маркеров не дробим."""
    out: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if _is_section_header(line):
            continue
        m = _BULLET_LINE_RE.match(line)
        if m:
            out.append(m.group(1).strip())
            continue
        m2 = re.match(r"^[ \t]*[•·▪◦]\s*(.+?\S)[ \t]*$", line)
        if m2:
            out.append(m2.group(1).strip())
    return out


def _split_prose_to_segments(text: str) -> list[str]:
    """Разбить prose на смысловые сегменты для ensure_bullet_format."""
    raw = (text or "").strip()
    if not raw:
        return []

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    non_headers = [ln for ln in lines if not _is_section_header(ln)]
    if len(non_headers) > 1:
        return [_strip_marker(ln) for ln in non_headers if _strip_marker(ln)]

    single = " ".join(non_headers) if non_headers else raw
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(single) if p.strip()]
    if len(parts) > 1:
        return parts

    if ";" in single and len(single) > 80:
        semi = [p.strip() for p in single.split(";") if p.strip()]
        if len(semi) > 1:
            return semi

    return [single.strip()] if single.strip() else []


def ensure_bullet_format(text: str, *, kind: str = "experience") -> str:
    """Привести текст блока к канону «- буллет» построчно (выход strengthen/ATS).

    `kind` зарезервирован под будущие отличия «Обо мне» vs опыт; сейчас правила общие.
    """
    _ = kind
    raw = (text or "").strip()
    if not raw:
        return raw

    bullets = parse_bullets(raw)
    if not bullets:
        bullets = _split_prose_to_segments(raw)
    if not bullets:
        bullets = [raw]

    normalized: list[str] = []
    for b in bullets:
        body = b.strip()
        if not body:
            continue
        # Убираем случайный двойной маркер после parse.
        body = re.sub(r"^[-*+•·▪◦]\s+", "", body).strip()
        normalized.append(body)

    if not normalized:
        return raw

    return "\n".join(f"- {b}" for b in normalized)


__all__ = ["ensure_bullet_format", "parse_bullets"]
