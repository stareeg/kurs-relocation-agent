"""Извлечение текста из вложений-документов (не картинок): .txt/.md как есть, .pdf/.docx —
текстовый слой. Кросс-доменная утилита (используется `core.domains.assistant.attachments`,
может пригодиться другим доменам) — поэтому в kernel, не в attachments.

Не переиспользует `core.domains.profile.parse_pdf.extract_pdf_text` — тот заточен под резюме
(свои лимиты/ошибка `ResumePdfParseError`/magic-byte guard под конкретный сценарий загрузки
резюме), это отдельная генерическая утилита для произвольных вложений диалога.
"""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO

# Тот же порядок, что и лимит картинки в композере (`_MAX_SIDE_PX`-эквивалент по духу) — большой
# документ всё равно урежется до MAX_EXTRACTED_CHARS, но приём терабайтного файла отсекаем раньше.
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
# Текст инлайнится в промпт LLM — не даём одному вложению съесть весь контекст диалога.
MAX_EXTRACTED_CHARS = 60_000


class DocumentExtractError(ValueError):
    """Текст не извлёкся — битый/пустой/нечитаемый файл."""


def extract_plain_text(raw: bytes) -> str:
    """.txt/.md — UTF-8, с fallback на latin-1 для битых байт (не роняем вложение из-за кодировки)."""  # noqa: E501
    if not raw:
        raise DocumentExtractError("файл пуст")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    text = text.strip()
    if not text:
        raise DocumentExtractError("файл пуст")
    return text[:MAX_EXTRACTED_CHARS]


def extract_pdf_text(raw: bytes) -> str:
    """PDF → текстовый слой (pypdf). Скан без текстового слоя — честная ошибка, не пустая строка."""
    if not raw.startswith(b"%PDF"):
        raise DocumentExtractError("файл не похож на PDF")
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw))
        parts = [(page.extract_text() or "").strip() for page in reader.pages]
        text = "\n\n".join(p for p in parts if p).strip()
    except DocumentExtractError:
        raise
    except Exception as exc:  # noqa: BLE001 — битый PDF/неожиданный формат, не только pypdf-исключения
        raise DocumentExtractError(f"не удалось прочитать PDF: {exc}") from exc
    if not text:
        raise DocumentExtractError(
            "не удалось извлечь текст из PDF — возможно, это скан без текстового слоя"
        )
    return text[:MAX_EXTRACTED_CHARS]


def extract_docx_text(raw: bytes) -> str:
    """DOCX → текст абзацев + таблиц (python-docx)."""
    try:
        from docx import Document

        doc = Document(BytesIO(raw))
        parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        text = "\n".join(parts).strip()
    except Exception as exc:  # noqa: BLE001 — битый DOCX/неожиданный формат
        raise DocumentExtractError(f"не удалось прочитать DOCX: {exc}") from exc
    if not text:
        raise DocumentExtractError("не удалось извлечь текст из DOCX — файл пуст")
    return text[:MAX_EXTRACTED_CHARS]


DOCUMENT_MIME_EXTRACTORS: dict[str, Callable[[bytes], str]] = {
    "text/plain": extract_plain_text,
    "text/markdown": extract_plain_text,
    "application/pdf": extract_pdf_text,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": extract_docx_text,
}


def extract_document_text(raw: bytes, mime: str) -> str:
    """Диспетчер по MIME. Неизвестный mime → `DocumentExtractError` (defensive — вызывающий
    должен был отсеять его раньше по allowlist)."""
    extractor = DOCUMENT_MIME_EXTRACTORS.get(mime)
    if extractor is None:
        raise DocumentExtractError(f"неподдерживаемый тип документа: {mime}")
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise DocumentExtractError(f"файл больше {MAX_DOCUMENT_BYTES // (1024 * 1024)} МБ")
    return extractor(raw)


__all__ = [
    "DOCUMENT_MIME_EXTRACTORS",
    "MAX_DOCUMENT_BYTES",
    "MAX_EXTRACTED_CHARS",
    "DocumentExtractError",
    "extract_docx_text",
    "extract_document_text",
    "extract_pdf_text",
    "extract_plain_text",
]
