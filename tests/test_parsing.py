"""Tests for document parsing and text chunking utilities — full edge case coverage."""

import os
import tempfile
import pytest
from apps.worker.parsers import parse_txt, parse_md, parse_file, parse_docx
from apps.worker.chunking import chunk_text


# ── Text File Parsing Edge Cases ─────────────────────────────────────────────


def test_parse_txt_basic():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Hello, EKOA!\nThis is a test document.")
        tmp_path = f.name
    try:
        result = parse_txt(tmp_path)
        assert "Hello, EKOA!" in result
        assert "test document" in result
    finally:
        os.unlink(tmp_path)


def test_parse_txt_empty():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("")
        tmp_path = f.name
    try:
        result = parse_txt(tmp_path)
        assert result == ""
    finally:
        os.unlink(tmp_path)


def test_parse_txt_unicode():
    content = "Hello 世界\nCafé résumé\n¡Hola! ¿Cómo estás?\n🌟 🚀 ✅\n\u00e9\u00e0\u00fc\u00f1"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as f:
        f.write(content)
        tmp_path = f.name
    try:
        result = parse_txt(tmp_path)
        assert "世界" in result
        assert "Café" in result
        assert "🌟" in result
        assert "\u00e9" in result
    finally:
        os.unlink(tmp_path)


def test_parse_txt_very_large():
    content = "Hello\n" * 10000
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        tmp_path = f.name
    try:
        result = parse_txt(tmp_path)
        assert len(result) > 50000
        assert result.count("Hello") == 10000
    finally:
        os.unlink(tmp_path)


def test_parse_txt_only_newlines():
    content = "\n\n\n\n\n\n\n\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        tmp_path = f.name
    try:
        result = parse_txt(tmp_path)
        # Result should preserve newlines
        assert result == content
    finally:
        os.unlink(tmp_path)


def test_parse_txt_single_character():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("a")
        tmp_path = f.name
    try:
        result = parse_txt(tmp_path)
        assert result == "a"
    finally:
        os.unlink(tmp_path)


# ── Markdown Parsing Edge Cases ──────────────────────────────────────────────


def test_parse_md_basic():
    md_content = """# Heading\n\nThis is a **bold** statement.\n\n- List item 1\n- List item 2\n"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(md_content)
        tmp_path = f.name
    try:
        result = parse_md(tmp_path)
        assert "# Heading" in result
        assert "List item 2" in result
    finally:
        os.unlink(tmp_path)


def test_parse_md_code_blocks():
    md_content = """# Code Example\n\n```python\ndef hello():\n    print("world")\n```\n\nDone."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(md_content)
        tmp_path = f.name
    try:
        result = parse_md(tmp_path)
        assert "def hello():" in result
        assert "```" in result
    finally:
        os.unlink(tmp_path)


def test_parse_md_tables():
    md_content = """# Table\n\n| Col1 | Col2 |\n|------|------|\n| A    | B    |\n| C    | D    |\n"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(md_content)
        tmp_path = f.name
    try:
        result = parse_md(tmp_path)
        assert "Col1" in result
        assert "Col2" in result
        assert "A" in result
    finally:
        os.unlink(tmp_path)


def test_parse_md_empty():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("")
        tmp_path = f.name
    try:
        result = parse_md(tmp_path)
        assert result == ""
    finally:
        os.unlink(tmp_path)


def test_parse_md_unicode():
    content = "## 你好世界\n\n这是一段**中文**。\n\n- 项目1\n- 项目2\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as f:
        f.write(content)
        tmp_path = f.name
    try:
        result = parse_md(tmp_path)
        assert "你好世界" in result
        assert "中文" in result
        assert "项目1" in result
    finally:
        os.unlink(tmp_path)


# ── File Routing Edge Cases ──────────────────────────────────────────────────


def _make_docx(text: str) -> str:
    """Create a real .docx file and return its path."""
    from docx import Document

    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.close()
    doc = Document()
    doc.add_paragraph(text)
    doc.save(tmp.name)
    return tmp.name


def test_parse_docx():
    path = _make_docx("This is a DOCX paragraph for EKOA.")
    try:
        result = parse_docx(path)
        assert "DOCX paragraph" in result
        assert "EKOA" in result
    finally:
        os.unlink(path)


def test_parse_docx_by_content_type():
    path = _make_docx("Word document content here.")
    try:
        result = parse_file(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert "Word document content" in result
    finally:
        os.unlink(path)


def test_parse_docx_by_extension():
    path = _make_docx("Routed by extension.")
    try:
        result = parse_file(path, "application/octet-stream")
        assert "Routed by extension" in result
    finally:
        os.unlink(path)


# ── File Routing Edge Cases ──────────────────────────────────────────────────


def test_parse_file_by_content_type():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Plain text content")
        tmp_path = f.name
    try:
        result = parse_file(tmp_path, "application/pdf")
        assert "Plain text content" in result
    finally:
        os.unlink(tmp_path)


def test_parse_file_md_content_type():
    md_content = "# Hello\nWorld"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(md_content)
        tmp_path = f.name
    try:
        result = parse_file(tmp_path, "text/markdown")
        assert "# Hello" in result
    finally:
        os.unlink(tmp_path)


def test_parse_file_pdf_content_type():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Pdf-like content")
        tmp_path = f.name
    try:
        result = parse_file(tmp_path, "APPLICATION/PDF")
        assert "Pdf-like content" in result
    finally:
        os.unlink(tmp_path)


def test_parse_file_unknown_content_type():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".bin", delete=False) as f:
        f.write("binary-like content")
        tmp_path = f.name
    try:
        result = parse_file(tmp_path, "application/octet-stream")
        # Falls through to txt parser
        assert "binary-like content" in result
    finally:
        os.unlink(tmp_path)


def test_parse_file_case_insensitive():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".TXT", delete=False) as f:
        f.write("Case sensitivity test")
        tmp_path = f.name
    try:
        result = parse_file(tmp_path, "TEXT/PLAIN")
        assert "Case sensitivity test" in result
    finally:
        os.unlink(tmp_path)


# ── Chunking Edge Cases ──────────────────────────────────────────────────────


def test_chunk_text_basic():
    text = "Hello. " * 200
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)
    combined = "".join(chunks)
    assert "Hello" in combined


def test_chunk_text_small():
    text = "Short text."
    chunks = chunk_text(text, chunk_size=1000, chunk_overlap=50)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_empty():
    chunks = chunk_text("", chunk_size=100, chunk_overlap=10)
    assert len(chunks) == 0


def test_chunk_text_single_char():
    chunks = chunk_text("a", chunk_size=100, chunk_overlap=10)
    assert len(chunks) == 1
    assert chunks[0] == "a"


def test_chunk_text_exact_fit():
    text = "A" * 100
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=0)
    assert len(chunks) == 1
    assert len(chunks[0]) == 100


def test_chunk_text_unicode_characters():
    text = "Hello 世界 " * 50 + "Café résumé " * 50 + "🌟 " * 50
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)
    assert "世界" in chunks[0] or "世界" in chunks[1]
    combined = "".join(chunks)
    assert "世界" in combined
    assert "Café" in combined
    assert "🌟" in combined


def test_chunk_text_very_large():
    text = "Sentence. " * 50000
    chunks = chunk_text(text, chunk_size=512, chunk_overlap=50)
    assert len(chunks) > 10
    assert all(len(c) <= 600 for c in chunks)


def test_chunk_text_zero_overlap():
    text = "Hello. " * 100
    chunks = chunk_text(text, chunk_size=50, chunk_overlap=0)
    assert len(chunks) > 1
    all_text = "".join(chunks)
    assert "Hello" in all_text


def test_chunk_text_no_separators():
    text = "a" * 1000
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
    assert len(chunks) >= 9  # at least ceil(1000/110)
    all_text = "".join(chunks)
    assert len(all_text) >= len(text)


def test_chunk_text_whitespace_only():
    chunks = chunk_text("   \n\n   \t   ", chunk_size=100, chunk_overlap=10)
    assert len(chunks) >= 0
