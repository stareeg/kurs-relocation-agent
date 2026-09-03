"""Текстовые примитивы kernel: анти-slop линтер (проза + устный слой), спотлайтинг недоверенного
ввода, извлечение текста из вложений-документов."""

from core.kernel.text.extract import (
    DOCUMENT_MIME_EXTRACTORS,
    DocumentExtractError,
    extract_document_text,
    extract_docx_text,
    extract_pdf_text,
    extract_plain_text,
)
from core.kernel.text.style_lint import (
    PitchBlock,
    StyleIssue,
    StyleViolation,
    lint,
    lint_pitch,
    lint_spoken_text,
)
from core.kernel.text.untrusted import SPOTLIGHT_RULE, wrap_untrusted

__all__ = [
    "DOCUMENT_MIME_EXTRACTORS",
    "SPOTLIGHT_RULE",
    "DocumentExtractError",
    "PitchBlock",
    "StyleIssue",
    "StyleViolation",
    "extract_docx_text",
    "extract_document_text",
    "extract_pdf_text",
    "extract_plain_text",
    "lint",
    "lint_pitch",
    "lint_spoken_text",
    "wrap_untrusted",
]
