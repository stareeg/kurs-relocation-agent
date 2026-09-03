"""Парсинг PDF-резюме в структурное ResumeData через LLM (structured output)."""

from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from pydantic import Field

from core.config import get_settings
from core.domains.profile.model import ResumeData, SearchCriteria
from core.domains.profile.search_profile_suggest import (
    EXPERIENCE_INDUSTRY_OPTIONS,
    MARKET_SEGMENT_OPTIONS,
    ROLE_KIND_OPTIONS,
    coerce_experience_industry,
)
from core.kernel import ports
from core.kernel.errors import LlmError

logger = logging.getLogger(__name__)

_MAX_PDF_BYTES = 10 * 1024 * 1024
_MIN_TEXT_LEN = 40
_MAX_TEXT_CHARS = 32_000
_MAX_PDF_PRIORITIES = 6

# LLM иногда отдаёт «Март 2024» / «03.2024» — DatePicker на фронте ждёт ISO.
_MONTH_RU: dict[str, str] = {
    "январ": "01",
    "феврал": "02",
    "март": "03",
    "апрел": "04",
    "ма": "05",  # май / мая
    "июн": "06",
    "июл": "07",
    "август": "08",
    "сентябр": "09",
    "октябр": "10",
    "ноябр": "11",
    "декабр": "12",
}
_RE_ISO = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_RE_RU_MONTH_YEAR = re.compile(
    r"(?i)\b(январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]|июн\w*|июл\w*|"
    r"август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)\s+(\d{4})\b"
)
_RE_DOT_MY = re.compile(r"^(\d{1,2})[./](\d{4})$")
_RE_DOT_DMY = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$")


class ResumePdfParseError(ValueError):
    """PDF не прочитан или текст слишком короткий для парсинга."""


class ResumePdfLlmOut(ResumeData):
    """Схема LLM: ResumeData + черновик приоритетов (не персистится в JSON резюме).

    `priorities` переносятся в `search_criteria.niches` только если niches пуст
    (`finalize_pdf_search_axes`).
    """

    priorities: list[str] = Field(default_factory=list)


def coerce_date_to_iso(raw: str) -> str:
    """Свободную дату → ISO-подстрока для DatePicker; неизвестное оставляем как есть."""
    text = (raw or "").strip()
    if not text or _RE_ISO.match(text):
        return text
    m = _RE_DOT_DMY.match(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y}-{mo:02d}-{d:02d}"
    m = _RE_DOT_MY.match(text)
    if m:
        mo, y = int(m.group(1)), m.group(2)
        if 1 <= mo <= 12:
            return f"{y}-{mo:02d}"
    m = _RE_RU_MONTH_YEAR.search(text)
    if m:
        stem = m.group(1).casefold()
        year = m.group(2)
        for key, num in _MONTH_RU.items():
            if stem.startswith(key):
                return f"{year}-{num}"
    return text


def coerce_resume_dates(data: ResumeData) -> ResumeData:
    """Постпроцессинг дат после LLM — форма резюме понимает только ISO."""
    personal = data.personal.model_copy(
        update={"birth_date": coerce_date_to_iso(data.personal.birth_date)}
    )
    experience = [
        e.model_copy(
            update={
                "start": coerce_date_to_iso(e.start),
                "end": coerce_date_to_iso(e.end),
            }
        )
        for e in data.experience
    ]
    education = [e.model_copy(update={"year": coerce_date_to_iso(e.year)}) for e in data.education]
    return data.model_copy(
        update={"personal": personal, "experience": experience, "education": education}
    )


def coerce_experience_industries(data: ResumeData) -> ResumeData:
    """Отрасль места работы — закрытый список; неизвестное / «Любые» → «Другое»."""
    experience = [
        e.model_copy(update={"industry": coerce_experience_industry(e.industry)})
        for e in data.experience
    ]
    return data.model_copy(update={"experience": experience})


def _canon_role_kind(raw: str) -> str:
    key = (raw or "").strip()
    if not key:
        return ""
    for opt in ROLE_KIND_OPTIONS:
        if key.casefold() == opt.casefold():
            return opt
    return ""


def _canon_market_segment(raw: str) -> str:
    key = (raw or "").strip()
    if not key:
        return ""
    # Мульти-выбор: LLM может вернуть или одно значение, или разделённые запятыми.
    parts = [p.strip() for p in key.split(",")]
    canon: list[str] = []
    seen: set[str] = set()
    for p in parts:
        if not p:
            continue
        matched = next(
            (opt for opt in MARKET_SEGMENT_OPTIONS if p.casefold() == opt.casefold()), None
        )
        c = matched if matched else p[:80]
        if c.casefold() not in seen:
            seen.add(c.casefold())
            canon.append(c)
    # «Любые» соло = пустая строка (без фильтра). В комбинации с другими — убираем.
    if len(canon) == 1 and canon[0].casefold() == "любые":
        return ""
    canon = [c for c in canon if c.casefold() != "любые"]
    return ", ".join(canon) if canon else ""


def finalize_pdf_search_axes(raw: ResumePdfLlmOut) -> ResumeData:
    """Нормализовать оси профиля после PDF; salary_basis не трогать.

    Приоритеты из `priorities` → niches только если niches пуст. Иначе niches как есть (≤6).
    """
    base = ResumeData.model_validate(raw.model_dump(exclude={"priorities"}))
    sc = base.search_criteria
    niches = [n.strip() for n in (sc.niches or []) if n and str(n).strip()]
    if not niches:
        niches = [p.strip() for p in (raw.priorities or []) if p and str(p).strip()]
    niches = niches[:_MAX_PDF_PRIORITIES]

    updated = SearchCriteria(
        niches=niches,
        role_kind=_canon_role_kind(sc.role_kind),
        market_segment=_canon_market_segment(sc.market_segment),
        target_companies=list(sc.target_companies or []),
        avoid_companies=list(sc.avoid_companies or []),
        dealbreakers=list(sc.dealbreakers or []),
        notes=sc.notes or "",
    )
    return base.model_copy(update={"search_criteria": updated})


def _pdf_to_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ResumePdfParseError("для PDF нужен пакет pypdf") from exc
    reader = PdfReader(BytesIO(pdf_bytes))
    parts = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n\n".join(p for p in parts if p)


@lru_cache(maxsize=1)
def _load_prompt(path_str: str) -> str:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Промпт не найден: {path} (CWD={Path.cwd()}). Проверь путь в core.domains.profile.llm."
        )
    return path.read_text(encoding="utf-8")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Извлечь текст из PDF (pypdf / docling)."""
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise ResumePdfParseError(f"PDF больше {_MAX_PDF_BYTES // (1024 * 1024)} МБ")
    if not pdf_bytes.startswith(b"%PDF"):
        raise ResumePdfParseError("файл не похож на PDF")
    try:
        text = _pdf_to_text(pdf_bytes).strip()
    except Exception as exc:
        raise ResumePdfParseError(f"не удалось прочитать PDF: {exc}") from exc
    if len(text) < _MIN_TEXT_LEN:
        raise ResumePdfParseError(
            "не удалось извлечь текст из PDF — возможно, это скан без текстового слоя"
        )
    if len(text) > _MAX_TEXT_CHARS:
        logger.info("resume parse-pdf: текст обрезан до %s символов", _MAX_TEXT_CHARS)
        text = text[:_MAX_TEXT_CHARS]
    return text


async def parse_resume_pdf(pdf_bytes: bytes) -> ResumeData:
    """PDF → ResumeData через extract-тир и structured output."""
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    text = await asyncio.to_thread(extract_pdf_text, pdf_bytes)
    from core.domains.profile.llm import PARSE_PDF

    system = _load_prompt(PARSE_PDF)
    roles = ", ".join(ROLE_KIND_OPTIONS)
    markets = ", ".join(MARKET_SEGMENT_OPTIONS)
    industries = ", ".join(EXPERIENCE_INDUSTRY_OPTIONS)
    user = (
        f"## Текст резюме из PDF\n\n{text}\n\n"
        "Заполни все поля структуры по схеме. Пустые поля — пустые строки/списки.\n"
        f"Канон типа роли (search_criteria.role_kind): {roles}.\n"
        f"Справочник рынков (search_criteria.market_segment): {markets}.\n"
        f"Отрасль места работы (experience[].industry) — одно значение из: {industries}. "
        "Неясно — «Другое». Нет компании в тексте — пустая строка.\n"
    )

    parsed = await ports.llm().structured(
        "resume_parse_pdf",
        system=system,
        user=user,
        schema=ResumePdfLlmOut,
        temperature=0.1,
        max_tokens=8192,
    )
    if not isinstance(parsed, ResumePdfLlmOut):  # pragma: no cover
        raise LlmError(f"parse-pdf вернул неожиданный тип: {type(parsed).__name__}")
    return coerce_experience_industries(coerce_resume_dates(finalize_pdf_search_axes(parsed)))


__all__ = [
    "ResumePdfLlmOut",
    "ResumePdfParseError",
    "coerce_date_to_iso",
    "coerce_experience_industries",
    "coerce_resume_dates",
    "extract_pdf_text",
    "finalize_pdf_search_axes",
    "parse_resume_pdf",
]
