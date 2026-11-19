"""Core functions for the Docs service (cutover-minimum: 1 op).

Parity coverage per op:

  docs_from_markdown — mutation-request DONE (drive.files.create body + docs.batchUpdate
                       requests); sandbox-e2e awaiting operator creds (P6 gate)

Legacy contract preserved (from ``scripts/packages/md-to-google-doc/md_to_gdoc.py``):

  Two-pass approach:
    1. Markdown → styled HTML → ``drive.files.create`` (resumable ``MediaIoBaseUpload``)
       → creates a Google Doc in Drive. ``folder_id`` places the doc directly.
    2. ``docs.documents.get`` → ``docs.documents.batchUpdate`` in ≤500-request chunks
       for pixel-perfect formatting.

  Formatting contract (exact values from legacy):
    - Document margins: 1 inch (72pt) on all four sides.
    - Headings bold, Arial: H1 20pt, H2 16pt, H3 13pt, H4 12pt.
    - All paragraph styles receive 150% line spacing.
    - Table header row (row 0): cell background #F0F0F0 (RGB 0.9411765 each channel),
      text bold 10pt Arial.
    - Table data rows: 10pt Arial (not bold).
    - Body text: 11pt Arial (line spacing only; font applied via named style).

  OAuth note: the legacy tool used a separate ``token.json`` + client secret.
  google-kit unifies this into the single Keychain SecretStore (Phase 5).

  HTML generation: a built-in minimal converter handles the formatting contract
  cases without requiring the ``markdown`` PyPI library. An injectable
  ``md_converter`` seam accepts a callable ``(text: str, title: str) -> str``
  for richer conversions (Phase 5/6 can supply the full ``markdown`` library).
"""
from __future__ import annotations

import re
from copy import deepcopy
from io import BytesIO
from typing import Any, Callable

from google_kit.core.client import execute_api_call
from google_kit.core.errors import Validation
from google_kit.core.normalize import Meta, OutputEnvelope
from google_kit.core.profiles import (
    DEFAULT_NAME,
    apply_overrides,
    delete_profile,
    describe_applied_profile,
    doctor_profiles,
    list_profiles,
    load_for_selector,
    load_profile,
    profile_path,
    resolve_profile_name,
    save_profile,
    starter_profile,
)

from .models import (
    DocsApplyStylesData,
    DocsApplyStylesInput,
    DocsApplyStylesOutput,
    DocsBatchUpdateData,
    DocsBatchUpdateInput,
    DocsBatchUpdateOutput,
    DocsExtractStylesData,
    DocsExtractStylesInput,
    DocsExtractStylesOutput,
    DocsFromMarkdownData,
    DocsFromMarkdownInput,
    DocsFromMarkdownOutput,
    DocsStylesAddInput,
    DocsStylesAddOutput,
    DocsStylesApplyInput,
    DocsStylesDoctorInput,
    DocsStylesDoctorOutput,
    DocsStylesMutationData,
    DocsStylesRemoveInput,
    DocsStylesRemoveOutput,
    DocsStylesSetDefaultInput,
    DocsStylesSetDefaultOutput,
    DocsStylesUpdateInput,
    DocsStylesUpdateOutput,
    DocsStylesViewData,
    DocsStylesViewInput,
    DocsStylesViewOutput,
)

from .style_profile import (
    StyleProfileError,
    _distill_profile as _pure_distill_profile,
    _profile_to_requests as _pure_profile_to_requests,
    _select_document_tab as _pure_select_document_tab,
)


def _select_document_tab(doc: dict[str, Any], tab_id: str | None = None
                         ) -> tuple[dict[str, Any], str | None]:
    try:
        return _pure_select_document_tab(doc, tab_id)
    except StyleProfileError as exc:
        raise Validation(str(exc), op="docs.extract_styles") from exc


def _distill_profile(doc: dict[str, Any], *, source_doc_id: str,
                     template_doc_id: str | None = None,
                     tab_id: str | None = None) -> dict[str, Any]:
    try:
        return _pure_distill_profile(doc, source_doc_id=source_doc_id,
                                    template_doc_id=template_doc_id, tab_id=tab_id)
    except StyleProfileError as exc:
        raise Validation(str(exc), op="docs.extract_styles") from exc


def _profile_to_requests(profile: dict[str, Any], *, mode: str = "definitions",
                         tab_id: str | None = None, document_id: str | None = None,
                         body_elements: list[dict[str, Any]] | None = None
                         ) -> list[dict[str, Any]]:
    try:
        return _pure_profile_to_requests(profile, mode=mode, tab_id=tab_id,
            document_id=document_id, body_elements=body_elements)
    except StyleProfileError as exc:
        raise Validation(str(exc), op="docs.apply_styles") from exc


# ─── Formatting contract constants ────────────────────────────────────────────

_FONT_FAMILY = "Arial"
_BODY_FONT_SIZE = 11
_TABLE_FONT_SIZE = 10
_LINE_SPACING_PCT = 150
_MARGIN_PT = 72

_HEADING_SIZES: dict[int, int] = {1: 20, 2: 16, 3: 13, 4: 12}
_HEADER_BG_RGB = {"red": 0.9411765, "green": 0.9411765, "blue": 0.9411765}

_MIME_DOC = "application/vnd.google-apps.document"

_HEADING_TAG_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
_HR_RE = re.compile(r"^---+$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"\*(.+?)\*")
_CODE_RE = re.compile(r"`(.+?)`")
_UL_RE = re.compile(r"^[-*]\s+(.+)$", re.MULTILINE)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _pt(magnitude: float) -> dict[str, Any]:
    return {"magnitude": magnitude, "unit": "PT"}


def _wrap(data: Any, op: str) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, meta=Meta(op=op))


def _builtin_md_to_html(text: str, title: str) -> str:
    """Minimal Markdown → HTML converter for the Docs formatting contract.

    Handles: ATX headings (#, ##, ###, ####), paragraphs, bold (**text**),
    italic (*text*), inline code (`code`), unordered lists (- item),
    horizontal rules (---), and simple pipe tables (| col | col |).

    Injectable via ``md_converter`` seam; richer conversions (markdown library
    with tables/fenced-code extensions) can be injected in Phase 5/6.
    """
    lines = text.splitlines()
    html_lines: list[str] = []
    in_list = False
    in_table = False
    table_rows: list[list[str]] = []
    paragraph: list[str] = []

    def _flush_paragraph() -> None:
        if paragraph:
            content = " ".join(paragraph).strip()
            if content:
                content = _BOLD_RE.sub(r"<strong>\1</strong>", content)
                content = _ITALIC_RE.sub(r"<em>\1</em>", content)
                content = _CODE_RE.sub(r"<code>\1</code>", content)
                html_lines.append(f"<p>{content}</p>")
            paragraph.clear()

    def _flush_list() -> None:
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    def _flush_table() -> None:
        nonlocal in_table, table_rows
        if in_table and table_rows:
            html_lines.append('<table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse">')
            for ri, row in enumerate(table_rows):
                html_lines.append("<tr>")
                for cell in row:
                    tag = "th" if ri == 0 else "td"
                    html_lines.append(f"<{tag}>{cell.strip()}</{tag}>")
                html_lines.append("</tr>")
            html_lines.append("</table>")
            table_rows = []
            in_table = False

    for line in lines:
        heading_m = re.match(r"^(#{1,4})\s+(.+)$", line)
        is_table_row = line.startswith("|") and "|" in line[1:]
        is_separator = re.match(r"^\|[\s\-|]+\|$", line) is not None
        is_list_item = re.match(r"^[-*]\s+(.+)$", line)
        is_hr = re.match(r"^---+$", line)
        is_blank = line.strip() == ""

        if heading_m:
            _flush_paragraph()
            _flush_list()
            _flush_table()
            level = len(heading_m.group(1))
            html_lines.append(f"<h{level}>{heading_m.group(2).strip()}</h{level}>")
        elif is_table_row and not is_separator:
            _flush_paragraph()
            _flush_list()
            in_table = True
            cells = [c for c in line.split("|") if c.strip() != ""]
            table_rows.append(cells)
        elif is_separator:
            pass
        elif is_list_item:
            _flush_paragraph()
            _flush_table()
            m = re.match(r"^[-*]\s+(.+)$", line)
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{m.group(1).strip()}</li>")
        elif is_hr:
            _flush_paragraph()
            _flush_list()
            _flush_table()
            html_lines.append("<hr>")
        elif is_blank:
            _flush_paragraph()
            _flush_list()
            _flush_table()
        else:
            in_table = False
            html_lines.append(line)
            paragraph.append(line)
            continue

    _flush_paragraph()
    _flush_list()
    _flush_table()

    body = "\n".join(html_lines)
    css = (
        f"body{{font-family:{_FONT_FAMILY},Helvetica,sans-serif;"
        f"font-size:{_BODY_FONT_SIZE}pt;line-height:{_LINE_SPACING_PCT}%;color:#1a1a1a}}"
        f"h1{{font-size:{_HEADING_SIZES[1]}pt;font-weight:bold}}"
        f"h2{{font-size:{_HEADING_SIZES[2]}pt;font-weight:bold}}"
        f"h3{{font-size:{_HEADING_SIZES[3]}pt;font-weight:bold}}"
        f"h4{{font-size:{_HEADING_SIZES[4]}pt;font-weight:bold}}"
        f"table{{border-collapse:collapse;width:auto;font-size:{_TABLE_FONT_SIZE}pt}}"
        f"th{{background-color:#F0F0F0;font-weight:bold;padding:4pt 6pt}}"
        f"td{{padding:4pt 6pt}}"
    )
    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>{title}</title>"
        f"<style>{css}</style>"
        f"</head><body>{body}</body></html>"
    )


def _build_formatting_requests(body_elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build batchUpdate requests for pixel-perfect formatting (legacy contract).

    Always generates the document margin request first. Then iterates body
    elements for heading styles, normal text line spacing, and table header
    formatting. Preserves the exact request structure from md_to_gdoc.py.
    """
    requests: list[dict[str, Any]] = []

    requests.append({
        "updateDocumentStyle": {
            "documentStyle": {
                "marginTop": _pt(_MARGIN_PT),
                "marginBottom": _pt(_MARGIN_PT),
                "marginLeft": _pt(_MARGIN_PT),
                "marginRight": _pt(_MARGIN_PT),
            },
            "fields": "marginTop,marginBottom,marginLeft,marginRight",
        }
    })

    for el in body_elements:
        if "paragraph" in el:
            p = el["paragraph"]
            named = p.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
            start_idx = el.get("startIndex", 0)
            end_idx = el.get("endIndex", start_idx)

            if named in ("HEADING_1", "HEADING_2", "HEADING_3", "HEADING_4"):
                requests.append({
                    "updateParagraphStyle": {
                        "range": {"startIndex": start_idx, "endIndex": end_idx},
                        "paragraphStyle": {
                            "namedStyleType": named,
                            "lineSpacing": _LINE_SPACING_PCT,
                        },
                        "fields": "namedStyleType,lineSpacing",
                    }
                })
                font_size = _HEADING_SIZES.get(int(named[-1]), _BODY_FONT_SIZE)
                text_end = max(end_idx - 1, start_idx)
                if text_end > start_idx:
                    requests.append({
                        "updateTextStyle": {
                            "range": {"startIndex": start_idx, "endIndex": text_end},
                            "textStyle": {
                                "bold": True,
                                "fontSize": _pt(font_size),
                                "weightedFontFamily": {
                                    "fontFamily": _FONT_FAMILY,
                                    "weight": 400,
                                },
                            },
                            "fields": "bold,fontSize,weightedFontFamily",
                        }
                    })
            elif named == "NORMAL_TEXT":
                requests.append({
                    "updateParagraphStyle": {
                        "range": {"startIndex": start_idx, "endIndex": end_idx},
                        "paragraphStyle": {"lineSpacing": _LINE_SPACING_PCT},
                        "fields": "lineSpacing",
                    }
                })

        if "table" in el:
            table = el["table"]
            rows = table.get("tableRows", [])
            if not rows:
                continue

            header_row = rows[0]
            table_start = el["startIndex"]
            cols = table.get("columns", 1)
            header_done = False

            for cell in header_row.get("tableCells", []):
                cell_start = cell.get("startIndex")
                cell_end = cell.get("endIndex")
                if cell_start is None or cell_end is None:
                    continue

                if not header_done:
                    requests.append({
                        "updateTableCellStyle": {
                            "tableRange": {
                                "tableCellLocation": {
                                    "tableStartLocation": {"index": table_start},
                                    "rowIndex": 0,
                                    "columnIndex": 0,
                                },
                                "rowSpan": 1,
                                "columnSpan": cols,
                            },
                            "tableCellStyle": {
                                "backgroundColor": {
                                    "color": {"rgbColor": _HEADER_BG_RGB}
                                }
                            },
                            "fields": "backgroundColor",
                        }
                    })
                    header_done = True

                for content in cell.get("content", []):
                    if "paragraph" in content:
                        p_start = content.get("startIndex", cell_start)
                        p_end = content.get("endIndex", cell_end)
                        if p_end > p_start + 1:
                            requests.append({
                                "updateTextStyle": {
                                    "range": {
                                        "startIndex": p_start,
                                        "endIndex": p_end - 1,
                                    },
                                    "textStyle": {
                                        "bold": True,
                                        "fontSize": _pt(_TABLE_FONT_SIZE),
                                        "weightedFontFamily": {
                                            "fontFamily": _FONT_FAMILY,
                                            "weight": 400,
                                        },
                                    },
                                    "fields": "bold,fontSize,weightedFontFamily",
                                }
                            })

            for row in rows[1:]:
                for cell in row.get("tableCells", []):
                    for content in cell.get("content", []):
                        if "paragraph" in content:
                            p_start = content.get("startIndex", 0)
                            p_end = content.get("endIndex", 0)
                            if p_end > p_start + 1:
                                requests.append({
                                    "updateTextStyle": {
                                        "range": {
                                            "startIndex": p_start,
                                            "endIndex": p_end - 1,
                                        },
                                        "textStyle": {
                                            "fontSize": _pt(_TABLE_FONT_SIZE),
                                            "weightedFontFamily": {
                                                "fontFamily": _FONT_FAMILY,
                                                "weight": 400,
                                            },
                                        },
                                        "fields": "fontSize,weightedFontFamily",
                                    }
                                })

    return requests


def _markdown_lib_to_html(text: str, title: str) -> str:
    """Full-fidelity Markdown → HTML using the ``markdown`` library (P6).

    Uses ``tables`` and ``fenced_code`` extensions for complete Markdown support:
    headings, unordered/ordered lists, tables, fenced code blocks, bold, italic,
    inline code, links, images, and horizontal rules. Matches the legacy
    md_to_gdoc.py formatting contract CSS (font family, sizes, table header styling).
    """
    import markdown as _md_lib

    extensions = ["tables", "fenced_code"]
    body = _md_lib.markdown(text, extensions=extensions)
    css = (
        f"body{{font-family:{_FONT_FAMILY},Helvetica,sans-serif;"
        f"font-size:{_BODY_FONT_SIZE}pt;line-height:{_LINE_SPACING_PCT}%;color:#1a1a1a}}"
        f"h1{{font-size:{_HEADING_SIZES[1]}pt;font-weight:bold}}"
        f"h2{{font-size:{_HEADING_SIZES[2]}pt;font-weight:bold}}"
        f"h3{{font-size:{_HEADING_SIZES[3]}pt;font-weight:bold}}"
        f"h4{{font-size:{_HEADING_SIZES[4]}pt;font-weight:bold}}"
        f"table{{border-collapse:collapse;width:auto;font-size:{_TABLE_FONT_SIZE}pt}}"
        f"th{{background-color:#F0F0F0;font-weight:bold;padding:4pt 6pt}}"
        f"td{{padding:4pt 6pt}}"
        f"code{{font-family:monospace;background:#f5f5f5;padding:1pt 3pt}}"
        f"pre{{font-family:monospace;background:#f5f5f5;padding:8pt}}"
    )
    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>{title}</title>"
        f"<style>{css}</style>"
        f"</head><body>{body}</body></html>"
    )


def _default_md_to_html(text: str, title: str) -> str:
    """Default converter: uses markdown library (P6 required dep).

    Falls back to built-in converter only if the markdown library is somehow
    unavailable at runtime. The injectable md_converter seam continues to accept
    any callable(text, title) -> str.
    """
    try:
        return _markdown_lib_to_html(text, title)
    except ImportError:
        return _builtin_md_to_html(text, title)


def docs_from_markdown(
    inp: DocsFromMarkdownInput,
    *,
    drive_service: Any = None,
    docs_service: Any = None,
    md_converter: Callable[[str, str], str] = _default_md_to_html,
    _profile_loader: Callable[[str | None], dict[str, Any] | None] | None = None,
) -> DocsFromMarkdownOutput:
    """Convert Markdown to a styled Google Doc using the legacy formatting contract.

    Two-pass approach (mirrors md_to_gdoc.py):
      1. ``md_converter(markdown_content, title)`` → styled HTML →
         ``drive.files.create`` (resumable MediaIoBaseUpload, mimeType=text/html)
         → Google Doc ID. Optional ``folder_id`` places the doc directly.
      2. ``docs.documents.get(documentId=doc_id)`` → iterate body elements →
         generate formatting requests → ``docs.documents.batchUpdate`` in ≤500-
         request chunks.

    Formatting contract (1-inch margins; H1 20/H2 16/H3 13/H4 12pt bold Arial;
    body 11pt; table header #F0F0F0 bold 10pt Arial; 150% line spacing).

    Injectable seams:
      ``drive_service`` — Drive API resource (files.create). Defaults None (Phase 5).
      ``docs_service``  — Docs API resource (documents.get, batchUpdate). Defaults None.
      ``md_converter``  — callable(text, title) -> HTML. Defaults to built-in minimal
                          converter; inject ``markdown`` library in Phase 5/6.

    Parity: mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)
    """
    from googleapiclient.http import MediaIoBaseUpload

    html = md_converter(inp.markdown_content, inp.title)
    file_meta: dict[str, Any] = {
        "name": inp.title,
        "mimeType": _MIME_DOC,
    }
    if inp.folder_id:
        file_meta["parents"] = [inp.folder_id]

    media = MediaIoBaseUpload(
        BytesIO(html.encode("utf-8")),
        mimetype="text/html",
        resumable=True,
    )

    created = execute_api_call(
        lambda: drive_service.files().create(
            body=file_meta, media_body=media, fields="id,webViewLink"
        ).execute(),
        op="docs.from_markdown.create",
        posture="write",
        # markdown_content is document body content, not a mutation target.
        normalized_request=inp.model_dump(exclude={"markdown_content"}),
    )
    created = created or {}
    doc_id = created.get("id", "")
    doc_url = created.get("webViewLink", f"https://docs.google.com/document/d/{doc_id}/edit")

    doc = execute_api_call(
        lambda: docs_service.documents().get(documentId=doc_id).execute(),
        op="docs.from_markdown.get",
        posture="read",
    )
    body_elements = (doc or {}).get("body", {}).get("content", [])
    loader = _profile_loader or (
        lambda name: load_for_selector(name, allow_env=True)
    )
    profile = loader(inp.style_profile)
    if profile is not None or inp.style_overrides:
        profile = apply_overrides(profile, inp.style_overrides)
        formatting_requests = _profile_to_requests(
            profile,
            document_id=doc_id,
        )
    else:
        formatting_requests = _build_formatting_requests(body_elements)

    total_applied = 0
    chunk_size = 500
    for i in range(0, len(formatting_requests), chunk_size):
        chunk = formatting_requests[i: i + chunk_size]
        execute_api_call(
            lambda c=chunk: docs_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": c}
            ).execute(),
            op="docs.from_markdown.format",
            posture="write",
            normalized_request={"document_id": doc_id, "request_count": len(chunk)},
            target_ids=[doc_id],
        )
        total_applied += len(chunk)

    return _wrap(
        DocsFromMarkdownData(
            doc_id=doc_id,
            url=doc_url,
            title=inp.title,
            formatting_requests_applied=total_applied,
        ),
        "docs.from_markdown",
    )


def docs_batch_update(
    inp: DocsBatchUpdateInput,
    *,
    docs_service: Any = None,
    _profile_loader: Callable[[str | None], dict[str, Any] | None] | None = None,
) -> DocsBatchUpdateOutput:
    """Apply a list of Docs API update requests to an existing Google Doc.

    Forwards ``requests`` verbatim to ``documents.batchUpdate``; the caller
    is responsible for constructing well-formed request objects (insertText,
    deleteContentRange, updateTextStyle, insertTable, etc.).

    ``write_control`` is forwarded as-is when provided; omitted otherwise.

    Parity: mutation-request DONE; sandbox-e2e live-PASS 2026-06-17
    """
    requests = list(inp.requests)
    if inp.style_profile is not None or inp.style_overrides:
        loader = _profile_loader or (lambda name: load_for_selector(name, allow_env=True))
        loaded = loader(inp.style_profile)
        if loaded is not None or inp.style_overrides:
            profile = apply_overrides(loaded, inp.style_overrides)
            requests.extend(
                _profile_to_requests(profile, document_id=inp.document_id)
            )
    body: dict[str, Any] = {"requests": requests}
    if inp.write_control is not None:
        body["writeControl"] = inp.write_control

    result = execute_api_call(
        lambda: docs_service.documents().batchUpdate(
            documentId=inp.document_id, body=body
        ).execute(),
        op="docs.batch_update",
        posture="write",
            normalized_request={
                **inp.model_dump(exclude={"requests"}),
                "request_count": len(requests),
            },
        target_ids=[inp.document_id],
    )
    result = result or {}
    return _wrap(
        DocsBatchUpdateData(
            document_id=result.get("documentId", inp.document_id),
            replies=result.get("replies", []),
            write_control=result.get("writeControl"),
        ),
        "docs.batch_update",
    )


def docs_extract_styles(
    inp: DocsExtractStylesInput,
    *,
    docs_service: Any = None,
) -> DocsExtractStylesOutput:
    """Extract named styles and document settings from a Google Doc."""
    doc = execute_api_call(
        lambda: docs_service.documents().get(
            documentId=inp.document_id,
            includeTabsContent=True,
        ).execute(),
        op="docs.extract_styles.get",
        posture="read",
        normalized_request=inp.model_dump(exclude_none=True),
        target_ids=[inp.document_id],
    )
    profile = _distill_profile(
        doc or {},
        source_doc_id=inp.document_id,
        template_doc_id=inp.template_doc_id,
        tab_id=inp.tab_id,
    )
    saved_path: str | None = None
    if inp.style_profile:
        saved_path = str(save_profile(inp.style_profile, profile))
    return _wrap(
        DocsExtractStylesData(
            document_id=inp.document_id,
            style_profile=inp.style_profile,
            profile=profile,
            saved_path=saved_path,
        ),
        "docs.extract_styles",
    )


def docs_apply_styles(
    inp: DocsApplyStylesInput,
    *,
    docs_service: Any = None,
    _profile_loader: Callable[[str | None], dict[str, Any] | None] | None = None,
) -> DocsApplyStylesOutput:
    """Apply a local style profile to an existing Google Doc."""
    loader = _profile_loader or (
        lambda name: load_for_selector(name, allow_env=True)
    )
    resolved_name = resolve_profile_name(inp.style_profile, allow_env=True)
    legacy_explicit = (
        inp.style_profile is not None and inp.style_profile.strip().lower() == "legacy"
    )
    if inp.style_profile is None and inp.style_overrides:
        loaded = None
    elif legacy_explicit:
        loaded = {"schema": 1, "named_styles": {}, "document_style": {}}
    else:
        loaded = loader(inp.style_profile)
        if loaded is None and resolved_name is None and not inp.style_overrides:
            raise Validation(
                "style_profile is required when GOOGLE_KIT_DEFAULT_STYLE_PROFILE is unset",
                op="docs.apply_styles",
            )
    profile = apply_overrides(loaded, inp.style_overrides)
    body_elements: list[dict[str, Any]] | None = None
    if inp.mode == "normalize":
        doc = execute_api_call(
            lambda: docs_service.documents().get(
                documentId=inp.document_id,
                includeTabsContent=True,
            ).execute(),
            op="docs.apply_styles.get",
            posture="read",
            normalized_request=inp.model_dump(exclude_none=True),
            target_ids=[inp.document_id],
        )
        tab_content, _ = _select_document_tab(doc or {}, inp.tab_id)
        body_elements = (tab_content.get("body") or {}).get("content", [])
    requests = _profile_to_requests(
        profile,
        mode=inp.mode,
        tab_id=inp.tab_id,
        document_id=inp.document_id,
        body_elements=body_elements,
    )
    applied_profile_name = describe_applied_profile(
        explicit=inp.style_profile,
        resolved_name=resolved_name,
    )
    replies: list[Any] | None = None
    applied = 0
    if not inp.dry_run:
        out = docs_batch_update(
            DocsBatchUpdateInput(
                document_id=inp.document_id,
                requests=requests,
            ),
            docs_service=docs_service,
        )
        replies = list(out.data.replies or [])
        applied = len(requests)
    return _wrap(
        DocsApplyStylesData(
            document_id=inp.document_id,
            style_profile=applied_profile_name,
            mode=inp.mode,
            dry_run=inp.dry_run,
            requests=requests,
            requests_applied=applied,
            replies=replies,
        ),
        "docs.apply_styles",
    )


def docs_styles_view(inp: DocsStylesViewInput) -> DocsStylesViewOutput:
    """View local Google Docs style profiles."""
    profiles = list_profiles()
    selected = inp.style_profile
    profile = load_profile(selected) if selected else None
    return _wrap(
        DocsStylesViewData(
            profiles=profiles,
            default=DEFAULT_NAME if DEFAULT_NAME in profiles else None,
            selected=selected,
            profile=profile,
        ),
        "docs.styles_view",
    )


def docs_styles_add(
    inp: DocsStylesAddInput,
    *,
    docs_service: Any = None,
) -> DocsStylesAddOutput:
    """Add a local Google Docs style profile."""
    if inp.document_id:
        extracted = docs_extract_styles(
            DocsExtractStylesInput(
                document_id=inp.document_id,
                style_profile=inp.style_profile,
                template_doc_id=inp.template_doc_id,
                tab_id=inp.tab_id,
            ),
            docs_service=docs_service,
        )
        profile = extracted.data.profile
        path = extracted.data.saved_path
    else:
        profile = apply_overrides(starter_profile(), inp.profile_data)
        if inp.template_doc_id:
            profile["template_doc_id"] = inp.template_doc_id
        path = str(save_profile(inp.style_profile, profile))
    return _wrap(
        DocsStylesMutationData(
            style_profile=inp.style_profile,
            path=path,
            profile=profile,
        ),
        "docs.styles_add",
    )


def docs_styles_update(inp: DocsStylesUpdateInput) -> DocsStylesUpdateOutput:
    """Update a local Google Docs style profile."""
    profile = apply_overrides(load_profile(inp.style_profile), inp.updates)
    path = save_profile(inp.style_profile, profile)
    return _wrap(
        DocsStylesMutationData(
            style_profile=inp.style_profile,
            path=str(path),
            profile=profile,
        ),
        "docs.styles_update",
    )


def docs_styles_remove(inp: DocsStylesRemoveInput) -> DocsStylesRemoveOutput:
    """Remove a local Google Docs style profile."""
    deleted = delete_profile(inp.style_profile)
    return _wrap(
        DocsStylesMutationData(style_profile=inp.style_profile, deleted=deleted),
        "docs.styles_remove",
    )


def docs_styles_set_default(inp: DocsStylesSetDefaultInput) -> DocsStylesSetDefaultOutput:
    """Set the default local style profile."""
    profile = load_profile(inp.style_profile)
    path = save_profile(DEFAULT_NAME, profile)
    return _wrap(
        DocsStylesMutationData(
            style_profile=DEFAULT_NAME,
            path=str(path),
            profile=profile,
        ),
        "docs.styles_set_default",
    )


def docs_styles_apply(
    inp: DocsStylesApplyInput,
    *,
    docs_service: Any = None,
) -> DocsApplyStylesOutput:
    """Apply a local style profile to an existing Google Doc."""
    out = docs_apply_styles(
        DocsApplyStylesInput.model_validate(inp.model_dump()),
        docs_service=docs_service,
    )
    out.meta.op = "docs.styles_apply"
    return out


def docs_styles_doctor(inp: DocsStylesDoctorInput) -> DocsStylesDoctorOutput:
    """Validate and repair local Google Docs style profiles."""
    result = doctor_profiles(seed_default=inp.seed_default)
    return _wrap(DocsStylesMutationData(result=result), "docs.styles_doctor")


def docs_styles_repair(inp: DocsStylesDoctorInput) -> DocsStylesDoctorOutput:
    """Repair local Google Docs style profiles."""
    result = doctor_profiles(seed_default=inp.seed_default)
    return _wrap(DocsStylesMutationData(result=result), "docs.styles_repair")
