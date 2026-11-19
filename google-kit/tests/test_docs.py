"""Tests for the Docs service.

Coverage:
  docs_from_markdown — mutation-request parity:
    1. drive.files.create body (mimeType, name, optional parents)
    2. docs.documents.batchUpdate body (the full requests array matching the
       formatting contract: margins, heading styles, line spacing, table headers)

Parity status per op:
  docs_from_markdown — mutation-request DONE; sandbox-e2e DEFERRED(P6)

Test-local mock classes (MockDocsService, MockDriveService) model the separate
Drive and Docs API service resources used by docs_from_markdown's two-pass approach.

Formatting contract verified:
  - Document margins: 72pt (1 inch) all sides.
  - HEADING_1: lineSpacing=150, bold, 20pt Arial weight=400.
  - NORMAL_TEXT: lineSpacing=150 only.
  - batchUpdate requests sent in ≤500-request chunks.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.parity import compare

FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "docs"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# ─── Test-local mock infrastructure ──────────────────────────────────────────


@dataclass
class _Record:
    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> dict[str, Any] | None:
        return self.kwargs.get("body")


class _FakeExec:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _FakeDriveFilesProxy:
    def __init__(self, responses: dict, log: list[_Record]) -> None:
        self._responses = responses
        self._log = log

    def create(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_Record("files", "create", dict(kwargs)))
        return _FakeExec(self._responses.get(("files", "create")))


class MockDriveServiceForDocs:
    """Test-local mock for the Drive API used by docs_from_markdown (files.create only)."""

    def __init__(self, responses: dict | None = None) -> None:
        self._responses: dict = responses or {}
        self._log: list[_Record] = []

    def files(self) -> _FakeDriveFilesProxy:
        return _FakeDriveFilesProxy(self._responses, self._log)

    def last_request_body(self) -> dict[str, Any] | None:
        for rec in reversed(self._log):
            if rec.body is not None:
                return rec.body
        return None

    def requests_for(self, resource: str, method: str) -> list[_Record]:
        return [r for r in self._log if r.resource == resource and r.method == method]


class _FakeDocsProxy:
    def __init__(self, responses: dict, log: list[_Record]) -> None:
        self._responses = responses
        self._log = log

    def get(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_Record("documents", "get", dict(kwargs)))
        return _FakeExec(self._responses.get(("documents", "get")))

    def batchUpdate(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_Record("documents", "batchUpdate", dict(kwargs)))
        return _FakeExec(self._responses.get(("documents", "batchUpdate")))


class MockDocsService:
    """Test-local mock for the Google Docs API service (documents.get + batchUpdate)."""

    def __init__(self, responses: dict | None = None) -> None:
        self._responses: dict = responses or {}
        self._log: list[_Record] = []

    def documents(self) -> _FakeDocsProxy:
        return _FakeDocsProxy(self._responses, self._log)

    def last_request_body(self) -> dict[str, Any] | None:
        for rec in reversed(self._log):
            if rec.body is not None:
                return rec.body
        return None

    def requests_for(self, resource: str, method: str) -> list[_Record]:
        return [r for r in self._log if r.resource == resource and r.method == method]


# ─── Registry isolation fixture ──────────────────────────────────────────────


@pytest.fixture(autouse=True, scope="module")
def _ensure_docs() -> None:
    """Re-register Docs ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.docs as docs_mod

    if "docs.from_markdown" not in {s.name for s in reg.all_specs()}:
        importlib.reload(docs_mod)


# ─── docs.from_markdown ───────────────────────────────────────────────────────


class TestDocsFromMarkdown:
    def _make_services(self, doc_response: dict | None = None) -> tuple[MockDriveServiceForDocs, MockDocsService]:
        doc_resp = doc_response or _load("from_markdown_doc_response.json")
        drive_svc = MockDriveServiceForDocs(responses={
            ("files", "create"): {
                "id": "doc001",
                "webViewLink": "https://docs.google.com/document/d/doc001/edit",
            }
        })
        docs_svc = MockDocsService(responses={
            ("documents", "get"): doc_resp,
            ("documents", "batchUpdate"): {"replies": []},
        })
        return drive_svc, docs_svc

    def test_mutation_request_parity_create_body(self) -> None:
        from google_kit.services.docs.core import docs_from_markdown
        from google_kit.services.docs.models import DocsFromMarkdownInput

        expected_body = _load("from_markdown_create_expected_body.json")
        drive_svc, docs_svc = self._make_services()

        docs_from_markdown(
            DocsFromMarkdownInput(markdown_content="# Hello\n\nWorld.", title="Test Doc"),
            drive_service=drive_svc,
            docs_service=docs_svc,
        )

        actual_body = drive_svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"files.create body mismatch:\n{parity.diff}"

    def test_mutation_request_parity_batchupdate_body(self) -> None:
        from google_kit.services.docs.core import docs_from_markdown
        from google_kit.services.docs.models import DocsFromMarkdownInput

        expected_batch = _load("from_markdown_batchupdate_expected.json")
        drive_svc, docs_svc = self._make_services()

        docs_from_markdown(
            DocsFromMarkdownInput(markdown_content="# Hello\n\nBody text.", title="Test Doc"),
            drive_service=drive_svc,
            docs_service=docs_svc,
        )

        batch_calls = docs_svc.requests_for("documents", "batchUpdate")
        assert batch_calls, "Expected at least one documents.batchUpdate call"
        actual_body = batch_calls[0].body
        parity = compare("mutation-request", expected_batch, actual_body)
        assert parity.match, f"batchUpdate body mismatch:\n{parity.diff}"

    def test_folder_id_sets_parents_in_create(self) -> None:
        from google_kit.services.docs.core import docs_from_markdown
        from google_kit.services.docs.models import DocsFromMarkdownInput

        drive_svc, docs_svc = self._make_services()

        docs_from_markdown(
            DocsFromMarkdownInput(markdown_content="Hello", title="Test", folder_id="folder999"),
            drive_service=drive_svc,
            docs_service=docs_svc,
        )

        create_body = drive_svc.last_request_body()
        assert create_body is not None
        assert create_body.get("parents") == ["folder999"]

    def test_no_folder_id_no_parents(self) -> None:
        from google_kit.services.docs.core import docs_from_markdown
        from google_kit.services.docs.models import DocsFromMarkdownInput

        drive_svc, docs_svc = self._make_services()

        docs_from_markdown(
            DocsFromMarkdownInput(markdown_content="Hello", title="Test"),
            drive_service=drive_svc,
            docs_service=docs_svc,
        )

        create_body = drive_svc.last_request_body()
        assert create_body is not None
        assert "parents" not in create_body

    def test_create_mime_type_is_google_doc(self) -> None:
        from google_kit.services.docs.core import docs_from_markdown
        from google_kit.services.docs.models import DocsFromMarkdownInput

        drive_svc, docs_svc = self._make_services()
        docs_from_markdown(
            DocsFromMarkdownInput(markdown_content="x", title="x"),
            drive_service=drive_svc,
            docs_service=docs_svc,
        )

        body = drive_svc.last_request_body()
        assert body is not None
        assert body["mimeType"] == "application/vnd.google-apps.document"

    def test_output_envelope(self) -> None:
        from google_kit.services.docs.core import docs_from_markdown
        from google_kit.services.docs.models import DocsFromMarkdownInput

        drive_svc, docs_svc = self._make_services()
        result = docs_from_markdown(
            DocsFromMarkdownInput(markdown_content="# Hello", title="My Doc"),
            drive_service=drive_svc,
            docs_service=docs_svc,
        )

        assert result.meta.op == "docs.from_markdown"
        assert result.data.doc_id == "doc001"
        assert "doc001" in result.data.url
        assert result.data.title == "My Doc"
        assert result.data.formatting_requests_applied > 0

    def test_batch_chunks_respected(self) -> None:
        """Verify batchUpdate is called once per ≤500-request chunk."""
        from google_kit.services.docs.core import docs_from_markdown, _build_formatting_requests
        from google_kit.services.docs.models import DocsFromMarkdownInput

        drive_svc, docs_svc = self._make_services()
        docs_from_markdown(
            DocsFromMarkdownInput(markdown_content="# A\n\nB", title="T"),
            drive_service=drive_svc,
            docs_service=docs_svc,
        )

        batch_calls = docs_svc.requests_for("documents", "batchUpdate")
        assert batch_calls
        for call in batch_calls:
            assert len(call.body["requests"]) <= 500

    def test_documents_get_called_with_doc_id(self) -> None:
        from google_kit.services.docs.core import docs_from_markdown
        from google_kit.services.docs.models import DocsFromMarkdownInput

        drive_svc, docs_svc = self._make_services()
        docs_from_markdown(
            DocsFromMarkdownInput(markdown_content="x", title="x"),
            drive_service=drive_svc,
            docs_service=docs_svc,
        )

        get_calls = docs_svc.requests_for("documents", "get")
        assert get_calls
        assert get_calls[0].kwargs.get("documentId") == "doc001"

    def test_formatting_contract_margin_request(self) -> None:
        from google_kit.services.docs.core import _build_formatting_requests

        requests = _build_formatting_requests([])
        assert requests, "Expected at least the margin request"
        margin_req = requests[0]
        assert "updateDocumentStyle" in margin_req
        style = margin_req["updateDocumentStyle"]["documentStyle"]
        assert style["marginTop"] == {"magnitude": 72, "unit": "PT"}
        assert style["marginBottom"] == {"magnitude": 72, "unit": "PT"}
        assert style["marginLeft"] == {"magnitude": 72, "unit": "PT"}
        assert style["marginRight"] == {"magnitude": 72, "unit": "PT"}

    def test_formatting_contract_heading_sizes(self) -> None:
        from google_kit.services.docs.core import _build_formatting_requests, _HEADING_SIZES

        for level, expected_size in _HEADING_SIZES.items():
            named = f"HEADING_{level}"
            elements = [{
                "startIndex": 1,
                "endIndex": 10,
                "paragraph": {"paragraphStyle": {"namedStyleType": named}},
            }]
            requests = _build_formatting_requests(elements)
            text_style_reqs = [r for r in requests if "updateTextStyle" in r]
            assert text_style_reqs, f"No updateTextStyle for {named}"
            font_size = text_style_reqs[0]["updateTextStyle"]["textStyle"]["fontSize"]
            assert font_size == {"magnitude": expected_size, "unit": "PT"}, (
                f"{named}: expected {expected_size}pt, got {font_size}"
            )

    def test_formatting_contract_table_header_bg(self) -> None:
        from google_kit.services.docs.core import _build_formatting_requests, _HEADER_BG_RGB

        elements = [{
            "startIndex": 5,
            "endIndex": 50,
            "table": {
                "columns": 2,
                "tableRows": [
                    {
                        "tableCells": [
                            {
                                "startIndex": 6,
                                "endIndex": 15,
                                "content": [{
                                    "startIndex": 6,
                                    "endIndex": 14,
                                    "paragraph": {},
                                }],
                            }
                        ]
                    }
                ],
            },
        }]
        requests = _build_formatting_requests(elements)
        cell_style_reqs = [r for r in requests if "updateTableCellStyle" in r]
        assert cell_style_reqs, "Expected updateTableCellStyle for table header"
        bg = cell_style_reqs[0]["updateTableCellStyle"]["tableCellStyle"]["backgroundColor"]
        assert bg == {"color": {"rgbColor": _HEADER_BG_RGB}}

    def test_injectable_md_converter(self) -> None:
        from google_kit.services.docs.core import docs_from_markdown
        from google_kit.services.docs.models import DocsFromMarkdownInput
        from googleapiclient.http import MediaIoBaseUpload

        html_captured: list[str] = []

        def _custom_converter(text: str, title: str) -> str:
            html_captured.append(text)
            return f"<html><body><p>{text}</p></body></html>"

        drive_svc, docs_svc = self._make_services()
        docs_from_markdown(
            DocsFromMarkdownInput(markdown_content="custom markdown", title="T"),
            drive_service=drive_svc,
            docs_service=docs_svc,
            md_converter=_custom_converter,
        )

        assert html_captured == ["custom markdown"]
        file_creates = drive_svc.requests_for("files", "create")
        assert file_creates
        media = file_creates[0].kwargs.get("media_body")
        assert isinstance(media, MediaIoBaseUpload)


# ─── _build_formatting_requests unit tests ────────────────────────────────────


class TestBuildFormattingRequests:
    def test_empty_body_only_margin(self) -> None:
        from google_kit.services.docs.core import _build_formatting_requests

        reqs = _build_formatting_requests([])
        assert len(reqs) == 1
        assert "updateDocumentStyle" in reqs[0]

    def test_normal_text_gets_line_spacing_only(self) -> None:
        from google_kit.services.docs.core import _build_formatting_requests

        elements = [{
            "startIndex": 1,
            "endIndex": 10,
            "paragraph": {"paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}},
        }]
        reqs = _build_formatting_requests(elements)
        para_reqs = [r for r in reqs if "updateParagraphStyle" in r]
        assert para_reqs
        para = para_reqs[0]["updateParagraphStyle"]
        assert para["paragraphStyle"] == {"lineSpacing": 150}
        assert para["fields"] == "lineSpacing"

    def test_heading_bold_flag(self) -> None:
        from google_kit.services.docs.core import _build_formatting_requests

        elements = [{
            "startIndex": 1,
            "endIndex": 10,
            "paragraph": {"paragraphStyle": {"namedStyleType": "HEADING_2"}},
        }]
        reqs = _build_formatting_requests(elements)
        text_reqs = [r for r in reqs if "updateTextStyle" in r]
        assert text_reqs
        assert text_reqs[0]["updateTextStyle"]["textStyle"]["bold"] is True

    def test_section_break_ignored(self) -> None:
        from google_kit.services.docs.core import _build_formatting_requests

        elements = [{"startIndex": 0, "endIndex": 1, "sectionBreak": {}}]
        reqs = _build_formatting_requests(elements)
        assert len(reqs) == 1
        assert "updateDocumentStyle" in reqs[0]


class TestDocsBatchUpdate:
    """Happy-path + mutation-request parity for docs_batch_update."""

    def _make_docs_service(self, response: dict | None = None) -> MockDocsService:
        return MockDocsService(responses={
            ("documents", "batchUpdate"): response or {
                "documentId": "doc123",
                "replies": [{}],
            }
        })

    def test_happy_path(self) -> None:
        from google_kit.services.docs.core import docs_batch_update
        from google_kit.services.docs.models import DocsBatchUpdateInput

        docs_svc = self._make_docs_service()
        result = docs_batch_update(
            DocsBatchUpdateInput(
                document_id="doc123",
                requests=[{"insertText": {"location": {"index": 1}, "text": "Hello\n"}}],
            ),
            docs_service=docs_svc,
        )

        assert result.meta.op == "docs.batch_update"
        assert result.data.document_id == "doc123"
        assert isinstance(result.data.replies, list)

    def test_mutation_request_parity_body(self) -> None:
        from google_kit.services.docs.core import docs_batch_update
        from google_kit.services.docs.models import DocsBatchUpdateInput

        expected = _load("batch_update_expected_body.json")
        docs_svc = self._make_docs_service()

        docs_batch_update(
            DocsBatchUpdateInput(
                document_id="doc123",
                requests=expected["requests"],
            ),
            docs_service=docs_svc,
        )

        batch_calls = docs_svc.requests_for("documents", "batchUpdate")
        assert batch_calls, "Expected at least one documents.batchUpdate call"
        actual_body = batch_calls[0].body
        parity = compare("mutation-request", expected, actual_body)
        assert parity.match, f"batchUpdate body mismatch:\n{parity.diff}"

    def test_write_control_forwarded(self) -> None:
        from google_kit.services.docs.core import docs_batch_update
        from google_kit.services.docs.models import DocsBatchUpdateInput

        docs_svc = self._make_docs_service()
        wc = {"requiredRevisionId": "rev42"}

        docs_batch_update(
            DocsBatchUpdateInput(
                document_id="doc123",
                requests=[{"insertText": {"location": {"index": 1}, "text": "X"}}],
                write_control=wc,
            ),
            docs_service=docs_svc,
        )

        batch_calls = docs_svc.requests_for("documents", "batchUpdate")
        assert batch_calls
        assert batch_calls[0].body.get("writeControl") == wc

    def test_no_write_control_omitted(self) -> None:
        from google_kit.services.docs.core import docs_batch_update
        from google_kit.services.docs.models import DocsBatchUpdateInput

        docs_svc = self._make_docs_service()

        docs_batch_update(
            DocsBatchUpdateInput(
                document_id="doc123",
                requests=[{"insertText": {"location": {"index": 1}, "text": "X"}}],
            ),
            docs_service=docs_svc,
        )

        batch_calls = docs_svc.requests_for("documents", "batchUpdate")
        assert batch_calls
        assert "writeControl" not in batch_calls[0].body

    def test_document_id_passed_to_api(self) -> None:
        from google_kit.services.docs.core import docs_batch_update
        from google_kit.services.docs.models import DocsBatchUpdateInput

        docs_svc = self._make_docs_service()

        docs_batch_update(
            DocsBatchUpdateInput(
                document_id="my-target-doc",
                requests=[],
            ),
            docs_service=docs_svc,
        )

        batch_calls = docs_svc.requests_for("documents", "batchUpdate")
        assert batch_calls
        assert batch_calls[0].kwargs.get("documentId") == "my-target-doc"


class TestComplexMarkdownFidelity:
    """Golden parity for complex Markdown elements (P6 markdown-lib fidelity).

    Verifies that headings, lists, tables, fenced code blocks, bold, italic,
    inline code, and links all produce non-empty HTML output through the
    markdown-library-backed converter, matching the legacy formatting contract.
    """

    _COMPLEX_MD = """# Heading One

## Heading Two

### Heading Three

Paragraph with **bold text**, *italic text*, and `inline code`.

- List item one
- List item two
- List item three

| Column A | Column B | Column C |
|----------|----------|----------|
| Row 1 A  | Row 1 B  | Row 1 C  |
| Row 2 A  | Row 2 B  | Row 2 C  |

```python
def hello(name: str) -> str:
    return f"hello {name}"
```

[A link](https://example.com)

---

Final paragraph.
"""

    def test_markdown_lib_produces_headings(self) -> None:
        from google_kit.services.docs.core import _markdown_lib_to_html

        html = _markdown_lib_to_html(self._COMPLEX_MD, "Complex Doc")
        assert "<h1>" in html
        assert "<h2>" in html
        assert "<h3>" in html

    def test_markdown_lib_produces_table(self) -> None:
        from google_kit.services.docs.core import _markdown_lib_to_html

        html = _markdown_lib_to_html(self._COMPLEX_MD, "Complex Doc")
        assert "<table" in html
        assert "<th>" in html

    def test_markdown_lib_produces_code_block(self) -> None:
        from google_kit.services.docs.core import _markdown_lib_to_html

        html = _markdown_lib_to_html(self._COMPLEX_MD, "Complex Doc")
        assert "<code>" in html

    def test_markdown_lib_produces_list(self) -> None:
        from google_kit.services.docs.core import _markdown_lib_to_html

        html = _markdown_lib_to_html(self._COMPLEX_MD, "Complex Doc")
        assert "<ul>" in html
        assert "<li>" in html

    def test_markdown_lib_produces_bold_italic(self) -> None:
        from google_kit.services.docs.core import _markdown_lib_to_html

        html = _markdown_lib_to_html(self._COMPLEX_MD, "Complex Doc")
        assert "<strong>" in html
        assert "<em>" in html

    def test_markdown_lib_produces_link(self) -> None:
        from google_kit.services.docs.core import _markdown_lib_to_html

        html = _markdown_lib_to_html(self._COMPLEX_MD, "Complex Doc")
        assert "<a " in html
        assert "https://example.com" in html

    def test_default_converter_uses_markdown_lib(self) -> None:
        from google_kit.services.docs.core import _default_md_to_html

        html = _default_md_to_html("# Hello\n\n| A | B |\n|---|---|\n| 1 | 2 |", "T")
        assert "<h1>" in html
        assert "<table" in html

    def test_mutation_request_parity_complex_md(self) -> None:
        from google_kit.services.docs.core import docs_from_markdown
        from google_kit.services.docs.models import DocsFromMarkdownInput

        expected_body = _load("from_markdown_complex_create_expected_body.json")

        drive_svc = MockDriveServiceForDocs(responses={
            ("files", "create"): {
                "id": "complexdoc001",
                "webViewLink": "https://docs.google.com/document/d/complexdoc001/edit",
            }
        })
        docs_svc = MockDocsService(responses={
            ("documents", "get"): {"body": {"content": []}},
            ("documents", "batchUpdate"): {"replies": []},
        })

        docs_from_markdown(
            DocsFromMarkdownInput(markdown_content=self._COMPLEX_MD, title="Complex Markdown Doc"),
            drive_service=drive_svc,
            docs_service=docs_svc,
        )

        actual_body = drive_svc.last_request_body()
        assert actual_body is not None
        assert actual_body["name"] == "Complex Markdown Doc"
        assert actual_body["mimeType"] == "application/vnd.google-apps.document"
        from kp_mcp_testkit.parity import compare
        parity = compare("mutation-request", expected_body, {
            "mimeType": actual_body["mimeType"],
            "name": actual_body["name"],
        })
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"
