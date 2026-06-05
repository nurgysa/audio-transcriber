"""WS-5: tasks.doc_context must cap input size before handing a document to
markitdown.

markitdown parses fully-untrusted PDF/DOCX/PPTX/XLSX (zip+XML containers via
pdfminer/lxml/openpyxl). Without an input ceiling, a huge attachment OOMs the
extraction worker (and on the shared MCP server, a DoS). The existing 16k
OUTPUT cap is applied AFTER conversion, so it does nothing for the parse-time
blowup. This guards the obvious huge-file case before convert() is called.
(A crafted small-file zip-bomb that expands at parse time still needs a
wall-clock timeout / subprocess isolation — tracked as a follow-up.)
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

from tasks.doc_context import MAX_DOC_BYTES, convert_documents


def test_oversized_document_skipped_before_convert(monkeypatch, tmp_path):
    """A document over MAX_DOC_BYTES is skipped — convert() is never called on
    it, so the parser can't blow up."""
    big = tmp_path / "huge.pdf"
    big.write_bytes(b"x")  # real tiny file; we fake its reported size below
    monkeypatch.setattr(os.path, "getsize", lambda _p: MAX_DOC_BYTES + 1)

    fake_instance = MagicMock()
    monkeypatch.setattr("tasks.doc_context.MarkItDown", MagicMock(return_value=fake_instance))

    result = convert_documents([str(big)])

    fake_instance.convert.assert_not_called()
    assert result == ""  # nothing converted → empty context block


def test_normal_document_is_converted(monkeypatch, tmp_path):
    """A normal-size document still converts (regression guard — the cap must
    not break the happy path)."""
    doc = tmp_path / "brief.pdf"
    doc.write_bytes(b"realish content")  # well under the cap

    fake_instance = MagicMock()
    fake_instance.convert.return_value = MagicMock(text_content="Hello brief")
    monkeypatch.setattr("tasks.doc_context.MarkItDown", MagicMock(return_value=fake_instance))

    result = convert_documents([str(doc)])

    fake_instance.convert.assert_called_once()
    assert "Hello brief" in result
