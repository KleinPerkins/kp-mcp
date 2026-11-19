"""Pure Google Docs style extraction and request planning.

No account, filesystem, subprocess, network, registration or model operations.
The service core and native-provider callers share this implementation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any


class StyleProfileError(ValueError):
    """The supplied style snapshot is not safe to plan against."""


_CANONICAL_NAMED_STYLE_ORDER = (
    "TITLE",
    "SUBTITLE",
    "HEADING_1",
    "HEADING_2",
    "HEADING_3",
    "HEADING_4",
    "HEADING_5",
    "HEADING_6",
    "NORMAL_TEXT",
)

_TEXT_STYLE_FIELDS = {
    "weightedFontFamily",
    "fontSize",
    "bold",
    "italic",
    "underline",
    "strikethrough",
    "smallCaps",
    "foregroundColor",
    "backgroundColor",
    "baselineOffset",
}

_PARAGRAPH_STYLE_FIELDS = {
    "alignment",
    "lineSpacing",
    "spaceAbove",
    "spaceBelow",
    "indentStart",
    "indentEnd",
    "indentFirstLine",
    "direction",
    "spacingMode",
    "keepWithNext",
    "keepLinesTogether",
    "avoidWidowAndOrphan",
    "pageBreakBefore",
    "borderBetween",
    "borderTop",
    "borderBottom",
    "borderLeft",
    "borderRight",
    "shading",
}

_DOCUMENT_STYLE_FIELDS = {
    "documentFormat",
    "background",
    "marginTop",
    "marginBottom",
    "marginLeft",
    "marginRight",
    "pageSize",
}

def _round_floats(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, list):
        return [_round_floats(v) for v in value]
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in sorted(value.items())}
    return value

def _pick_fields(value: dict[str, Any] | None, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {k: _round_floats(value[k]) for k in sorted(allowed) if k in value}

def _style_from_named_style(named_style: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    text_style = _pick_fields(named_style.get("textStyle"), _TEXT_STYLE_FIELDS)
    paragraph_style = _pick_fields(named_style.get("paragraphStyle"), _PARAGRAPH_STYLE_FIELDS)
    if text_style:
        out["textStyle"] = text_style
    if paragraph_style:
        out["paragraphStyle"] = paragraph_style
    return out

def _select_document_tab(doc: dict[str, Any], tab_id: str | None = None) -> tuple[dict[str, Any], str | None]:
    tabs = doc.get("tabs")
    if not tabs:
        return doc, None
    if tab_id:
        for tab in tabs:
            if tab.get("tabProperties", {}).get("tabId") == tab_id:
                return tab.get("documentTab") or {}, tab_id
        raise StyleProfileError(f"tab_id {tab_id!r} was not found in document")
    if len(tabs) > 1:
        raise StyleProfileError(
            "documents with multiple tabs require an explicit tab_id",
        )
    tab = tabs[0]
    return tab.get("documentTab") or {}, tab.get("tabProperties", {}).get("tabId")

def _distill_profile(
    doc: dict[str, Any],
    *,
    source_doc_id: str,
    template_doc_id: str | None = None,
    tab_id: str | None = None,
) -> dict[str, Any]:
    selected, selected_tab_id = _select_document_tab(doc, tab_id)
    raw_named = selected.get("namedStyles", {}).get("styles", [])
    named_by_type = {
        style.get("namedStyleType"): _style_from_named_style(style)
        for style in raw_named
        if style.get("namedStyleType")
    }
    named_styles = {
        style_type: named_by_type[style_type]
        for style_type in _CANONICAL_NAMED_STYLE_ORDER
        if named_by_type.get(style_type)
    }
    document_style = _pick_fields(selected.get("documentStyle"), _DOCUMENT_STYLE_FIELDS)
    profile: dict[str, Any] = {
        "schema": 1,
        "named_styles": named_styles,
        "document_style": document_style,
        "source_doc_id": source_doc_id,
        "template_doc_id": template_doc_id,
    }
    if selected_tab_id:
        profile["tab_id"] = selected_tab_id
    return profile

def _leaf_field_paths(value: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key in sorted(value):
        child = value[key]
        child_prefix = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict) and child:
            paths.extend(_leaf_field_paths(child, child_prefix))
        else:
            paths.append(child_prefix)
    return paths

def _named_style_requests(profile: dict[str, Any], *, tab_id: str | None = None) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    named_styles = profile.get("named_styles") or {}
    for style_type in _CANONICAL_NAMED_STYLE_ORDER:
        style = named_styles.get(style_type)
        if not isinstance(style, dict) or not style:
            continue
        named_style = deepcopy(style)
        if not named_style:
            continue
        named_style["namedStyleType"] = style_type
        field_parts = ["namedStyleType"]
        if named_style.get("paragraphStyle"):
            field_parts.append("paragraphStyle")
        if named_style.get("textStyle"):
            field_parts.append("textStyle")
        request: dict[str, Any] = {
            "updateNamedStyle": {
                "namedStyle": named_style,
                "fields": ",".join(field_parts),
            }
        }
        if tab_id:
            request["updateNamedStyle"]["tabId"] = tab_id
        requests.append(request)
    return requests


def _canonical_bytes(value: Any) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise StyleProfileError("snapshot must contain finite JSON values") from exc
    if len(raw) > 2**20:
        raise StyleProfileError("snapshot exceeds the 1 MiB bound")
    return raw


def _native_snapshot(document: dict[str, Any], document_id: str,
                     tab_id: str | None) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    _canonical_bytes(document)
    if not isinstance(document_id, str) or not document_id or not isinstance(document, dict):
        raise StyleProfileError("an exact document ID and object are required")
    if document.get("documentId") != document_id:
        raise StyleProfileError("document identity does not match")
    if tab_id is not None and (not isinstance(tab_id, str) or not tab_id):
        raise StyleProfileError("tab ID must be a nonempty string when supplied")
    flattened: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(tabs, depth=0):
        if not isinstance(tabs, list) or depth > 8:
            raise StyleProfileError("invalid or excessively nested tabs")
        for tab in tabs:
            if not isinstance(tab, dict):
                raise StyleProfileError("tab must be an object")
            raw_shape = "tabProperties" in tab or "documentTab" in tab
            flat_shape = "tabId" in tab
            if raw_shape and flat_shape:
                raise StyleProfileError("ambiguous mixed raw and flattened tab shapes")
            if flat_shape:
                if tab.get("documentId", document_id) != document_id:
                    raise StyleProfileError("flattened tab document identity does not match")
                properties = {"tabId": tab["tabId"]}
                projected = {"tabProperties": properties, "documentTab": {
                    key: tab.get(key) for key in ("body", "namedStyles", "documentStyle")
                }}
            else:
                properties = tab.get("tabProperties")
                projected = tab
            ident = properties.get("tabId") if isinstance(properties, dict) else None
            if not isinstance(ident, str) or not ident or ident in seen:
                raise StyleProfileError("every tab needs a distinct nonempty ID")
            seen.add(ident)
            if len(seen) > 64:
                raise StyleProfileError("too many tabs")
            flattened.append(projected)
            if "childTabs" in tab:
                visit(tab["childTabs"], depth + 1)

    snapshot = dict(document)
    if "tabs" in document:
        visit(document["tabs"])
        if not flattened:
            raise StyleProfileError("empty tabs response is incomplete")
        snapshot["tabs"] = flattened
    elif tab_id is not None:
        raise StyleProfileError("tab ID cannot be verified from a legacy response")
    selected, selected_id = _select_document_tab(snapshot, tab_id)
    if not isinstance(selected, dict) or not all(
        isinstance(selected.get(key), dict) for key in ("body", "namedStyles", "documentStyle")
    ):
        raise StyleProfileError("complete body, named styles and document style are required")
    if not isinstance(selected["body"].get("content"), list) or not isinstance(
        selected["namedStyles"].get("styles"), list
    ):
        raise StyleProfileError("body or named styles response is incomplete")
    return snapshot, selected, selected_id


def _check_native_profile(profile: dict[str, Any]) -> None:
    _canonical_bytes(profile)
    allowed = {"schema", "name", "description", "named_styles", "document_style",
               "source_doc_id", "template_doc_id", "tab_id", "updated_at"}
    if not isinstance(profile, dict) or type(profile.get("schema")) is not int or profile["schema"] != 1:
        raise StyleProfileError("style profile must use integer schema 1")
    if set(profile) - allowed:
        raise StyleProfileError("unknown profile fields")
    named, doc_style = profile.get("named_styles"), profile.get("document_style")
    if not isinstance(named, dict) or not isinstance(doc_style, dict):
        raise StyleProfileError("named_styles and document_style must be objects")
    if set(named) - set(_CANONICAL_NAMED_STYLE_ORDER) or set(doc_style) - _DOCUMENT_STYLE_FIELDS:
        raise StyleProfileError("unknown named style or document style field")
    for style in named.values():
        if not isinstance(style, dict) or set(style) - {"textStyle", "paragraphStyle"}:
            raise StyleProfileError("unknown named style component")
        for key, permitted in (("textStyle", _TEXT_STYLE_FIELDS),
                               ("paragraphStyle", _PARAGRAPH_STYLE_FIELDS)):
            if key in style and (not isinstance(style[key], dict) or set(style[key]) - permitted):
                raise StyleProfileError("unknown text or paragraph style field")


def capture_native_profile(document: dict[str, Any], *, document_id: str,
                           tab_id: str | None = None) -> dict[str, Any]:
    """Extract canonical schema-1 profile data from an exact native readback.

    This returns data only. Saving it, accessing an account and approving any
    provider operation remain the caller's responsibilities.
    """
    snapshot, _, selected_id = _native_snapshot(document, document_id, tab_id)
    return _distill_profile(snapshot, source_doc_id=document_id, tab_id=selected_id)


def prepare_native_update(document: dict[str, Any], profile: dict[str, Any], *,
                          document_id: str, revision_id: str,
                          mode: str = "definitions", tab_id: str | None = None) -> dict[str, Any]:
    """Plan an exact, revision-guarded native-provider update without applying it.

    This is not authorization, authentication, registration, retention or whole
    Google Kit provider equivalence. An empty starter can produce no requests.
    """
    snapshot, selected, selected_id = _native_snapshot(document, document_id, tab_id)
    if not isinstance(revision_id, str) or not revision_id or document.get("revisionId") != revision_id:
        raise StyleProfileError("current exact revision ID is required")
    _check_native_profile(profile)
    requests = _profile_to_requests(profile, mode=mode, tab_id=selected_id,
        document_id=document_id, body_elements=selected["body"]["content"])
    return {
        "schema": "google-kit/native-style-plan/v1", "document_id": document_id,
        "tab_id": selected_id, "mode": mode,
        "write_control": {"requiredRevisionId": revision_id}, "requests": requests,
        "profile_sha256": hashlib.sha256(_canonical_bytes(profile)).hexdigest(),
        "document_sha256": hashlib.sha256(_canonical_bytes(document)).hexdigest(),
        "requests_sha256": hashlib.sha256(_canonical_bytes(requests)).hexdigest(),
    }

def _document_style_requests(profile: dict[str, Any], *, tab_id: str | None = None) -> list[dict[str, Any]]:
    raw = profile.get("document_style") or {}
    if not isinstance(raw, dict) or not raw:
        return []
    requests: list[dict[str, Any]] = []
    document_mode = (raw.get("documentFormat") or {}).get("documentMode")
    if document_mode:
        req: dict[str, Any] = {
            "updateDocumentStyle": {
                "documentStyle": {"documentFormat": {"documentMode": document_mode}},
                "fields": "documentFormat.documentMode",
            }
        }
        if tab_id:
            req["updateDocumentStyle"]["tabId"] = tab_id
        requests.append(req)

    page_fields = {"marginTop", "marginBottom", "marginLeft", "marginRight", "pageSize"}
    carry = {"background"}
    if document_mode != "PAGELESS":
        carry |= page_fields
    rest = {k: deepcopy(v) for k, v in raw.items() if k in carry}
    if rest:
        req = {
            "updateDocumentStyle": {
                "documentStyle": rest,
                "fields": ",".join(_leaf_field_paths(rest)),
            }
        }
        if tab_id:
            req["updateDocumentStyle"]["tabId"] = tab_id
        requests.append(req)
    return requests

def _resolve_apply_tab_id(
    *,
    caller_tab_id: str | None,
    profile: dict[str, Any],
    document_id: str,
) -> str | None:
    """Include tabId only when caller supplies it or profile was extracted from this doc."""
    if caller_tab_id:
        return caller_tab_id
    if profile.get("source_doc_id") == document_id:
        return profile.get("tab_id")
    return None

def _normalize_content_requests(
    body_elements: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    tab_id: str | None = None,
) -> list[dict[str, Any]]:
    """Map existing paragraph ranges to profile named-style definitions."""
    requests: list[dict[str, Any]] = []
    named_styles = profile.get("named_styles") or {}
    for el in body_elements:
        if "paragraph" not in el:
            continue
        paragraph = el["paragraph"]
        named = paragraph.get("paragraphStyle", {}).get("namedStyleType")
        if not named or named not in named_styles:
            continue
        style = named_styles[named]
        start_idx = el.get("startIndex", 0)
        end_idx = el.get("endIndex", start_idx)
        if end_idx <= start_idx:
            continue

        paragraph_style = style.get("paragraphStyle")
        if isinstance(paragraph_style, dict) and paragraph_style:
            req: dict[str, Any] = {
                "updateParagraphStyle": {
                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                    "paragraphStyle": deepcopy(paragraph_style),
                    "fields": ",".join(sorted(paragraph_style.keys())),
                }
            }
            if tab_id:
                req["updateParagraphStyle"]["range"]["tabId"] = tab_id
            requests.append(req)

        text_style = style.get("textStyle")
        if isinstance(text_style, dict) and text_style and end_idx > start_idx + 1:
            text_end = end_idx - 1
            req = {
                "updateTextStyle": {
                    "range": {"startIndex": start_idx, "endIndex": text_end},
                    "textStyle": deepcopy(text_style),
                    "fields": ",".join(_leaf_field_paths(text_style)),
                }
            }
            if tab_id:
                req["updateTextStyle"]["range"]["tabId"] = tab_id
            requests.append(req)
    return requests

def _profile_to_requests(
    profile: dict[str, Any],
    *,
    mode: str = "definitions",
    tab_id: str | None = None,
    document_id: str | None = None,
    body_elements: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert a style profile into Docs API batchUpdate requests."""
    if mode not in {"definitions", "normalize"}:
        raise StyleProfileError("mode must be 'definitions' or 'normalize'")
    effective_tab_id = _resolve_apply_tab_id(
        caller_tab_id=tab_id,
        profile=profile,
        document_id=document_id or "",
    )
    requests = (
        _named_style_requests(profile, tab_id=effective_tab_id)
        + _document_style_requests(profile, tab_id=effective_tab_id)
    )
    if mode == "normalize":
        if body_elements is None:
            raise StyleProfileError(
                "normalize mode requires document body content",
            )
        requests.extend(
            _normalize_content_requests(
                body_elements,
                profile,
                tab_id=effective_tab_id,
            )
        )
    return requests
