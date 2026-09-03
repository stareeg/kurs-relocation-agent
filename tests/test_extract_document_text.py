"""Извлечение текста из вложений-документов (не картинок): txt/md/pdf/docx."""

from __future__ import annotations

from io import BytesIO

import pytest

from core.kernel.text.extract import (
    MAX_DOCUMENT_BYTES,
    DocumentExtractError,
    extract_document_text,
    extract_docx_text,
    extract_pdf_text,
    extract_plain_text,
)


def _build_docx(paragraphs: list[str]) -> bytes:
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestExtractPlainText:
    def test_utf8_happy_path(self) -> None:
        assert extract_plain_text("Привет, мир".encode()) == "Привет, мир"

    def test_strips_whitespace(self) -> None:
        assert extract_plain_text(b"  hello  \n\n") == "hello"

    def test_empty_raises(self) -> None:
        with pytest.raises(DocumentExtractError, match="пуст"):
            extract_plain_text(b"")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(DocumentExtractError, match="пуст"):
            extract_plain_text(b"   \n  ")

    def test_invalid_utf8_falls_back_to_latin1_instead_of_raising(self) -> None:
        # Битые UTF-8 байты не должны ронять вложение — падаем на latin-1.
        text = extract_plain_text(b"\xff\xfehello")
        assert "hello" in text

    def test_truncates_to_max_chars(self) -> None:
        long_text = "a" * 100_000
        result = extract_plain_text(long_text.encode())
        assert len(result) == 60_000


class TestExtractDocxText:
    def test_happy_path_paragraphs(self) -> None:
        raw = _build_docx(["Первый абзац.", "Второй абзац."])
        text = extract_docx_text(raw)
        assert "Первый абзац." in text
        assert "Второй абзац." in text

    def test_empty_docx_raises(self) -> None:
        raw = _build_docx([])
        with pytest.raises(DocumentExtractError, match="пуст"):
            extract_docx_text(raw)

    def test_garbage_bytes_raise(self) -> None:
        with pytest.raises(DocumentExtractError, match="не удалось прочитать DOCX"):
            extract_docx_text(b"not a docx file at all")


class TestExtractPdfText:
    def test_rejects_non_pdf_magic_bytes(self) -> None:
        with pytest.raises(DocumentExtractError, match="не похож на PDF"):
            extract_pdf_text(b"not a pdf")

    def test_rejects_textless_pdf(self) -> None:
        with pytest.raises(DocumentExtractError):
            extract_pdf_text(b"%PDF-1.4\n")


class TestExtractDocumentTextDispatch:
    def test_routes_plain_text_mime(self) -> None:
        assert extract_document_text(b"hello", "text/plain") == "hello"

    def test_routes_markdown_mime(self) -> None:
        assert extract_document_text(b"# heading", "text/markdown") == "# heading"

    def test_unsupported_mime_raises(self) -> None:
        with pytest.raises(DocumentExtractError, match="неподдерживаемый тип"):
            extract_document_text(b"data", "application/zip")

    def test_oversized_file_raises_before_extraction(self) -> None:
        oversized = b"a" * (MAX_DOCUMENT_BYTES + 1)
        with pytest.raises(DocumentExtractError, match="больше"):
            extract_document_text(oversized, "text/plain")
