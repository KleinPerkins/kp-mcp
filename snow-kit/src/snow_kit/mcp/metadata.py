"""Native MCP metadata derived from the snow-kit operation registry."""
from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from mcp.types import ToolAnnotations

from snow_kit import __version__
from snow_kit.core.intents import safety_hints

SERVER_INSTRUCTIONS = """Call help first with the complete plain-English request when tool choice is ambiguous or the task requires multiple analytics steps. Help ranking and configured workflow recommendations are deterministic server-side; whether Cursor or another model initially selects help remains model-dependent.
Use authoritative analytics context before analytical SQL when it is available; MCP resources are optional references, not safety gates.
Use context_search to find governed definitions, then context_get for a bounded section and pass document_id/revision through query context_refs.
Reference validity proves approved provenance, not semantic relevance; confirm the selected context supports the proposed metric, segment, date window, timezone, grain, and SQL.
Inspect relevant catalog metadata before querying and never guess table or column names. Require a known database plus schema or table candidate before column discovery. Do not replace missing context with broad INFORMATION_SCHEMA exploration.
query_execute is read-only, but USE changes session context. Its max_rows caps returned rows only: it does not add SQL LIMIT or reduce warehouse scanning.
catalog_preview_table can expose sensitive row values; describe the table first and request the smallest useful limit.
Writes are hidden by default. query_execute_write additionally requires explicit enablement, confirmation, justification, policy validation, and a grant preflight.
Snow-kit returns data rows and does not render charts; hand chart-ready rows to a caller-provided visualization surface.
Separate context evidence, observed Snowflake metadata, query results, and inference in conclusions.
Read warnings in every result; they carry truncation and completeness guidance. Auth requires sign-in, permission requires access correction, and timeout requires a narrower request rather than an unchanged retry."""

HELP_TOOL_DESCRIPTION = (
    "Call this first for an ambiguous or multi-step plain-English analytics "
    "request. Deterministically ranks visible snow-kit operations and conditional "
    "context-first workflows; performs no Snowflake query or context retrieval."
)

_MAX_DISCOVERY_CUES = 6
_MAX_DISCOVERY_SUFFIX_CHARS = 240


@lru_cache(maxsize=1)
def installed_version() -> str:
    """Return installed distribution metadata, with a source-tree fallback."""
    try:
        return version("snow-kit")
    except PackageNotFoundError:
        return __version__


def tool_description(spec: Any) -> str:
    """Build a concise description with operation-specific safety prerequisites."""
    base = _first_line(spec.fn.__doc__)
    notes: list[str] = []
    cue_suffix = discovery_cue_suffix(spec)

    if spec.name in {"query.execute", "query.analyze"}:
        notes.append(
            "For analytical SQL, consult approved analytics context when available and inspect "
            "relevant catalog metadata first; do not guess schema."
        )
    if spec.name == "context.search":
        notes.append(
            "Reads only configured Markdown blobs from one exact local Git commit; no fetch, "
            "working-tree content, sandbox, or unrestricted repository search."
        )
    elif spec.name == "context.get":
        notes.append(
            "Requires the opaque document_id and exact revision returned by context.search; "
            "content and sections are bounded and redacted."
        )
    if spec.name == "query.execute":
        notes.append(
            "max_rows caps rows returned to the client only; it does not add SQL LIMIT or reduce "
            "warehouse scanning. USE statements change session context."
        )
    elif "max_rows" in getattr(spec.input_model, "model_fields", {}):
        notes.append("max_rows limits returned rows, not upstream API work.")

    if spec.name == "catalog.preview_table":
        notes.append(
            "This can return sensitive row values; call catalog_describe_table first and use the "
            "smallest useful limit."
        )
    elif spec.name.startswith("catalog.") and spec.name not in {
        "catalog.list_tables",
        "catalog.describe_table",
        "catalog.search_columns",
    }:
        notes.append("Inspect table metadata before requesting data or derived statistics.")

    if spec.posture in {"write", "destructive"}:
        flag = getattr(spec, "flag", None)
        gate = f"{flag}=1, " if flag else ""
        notes.append(
            f"Write-gated: requires {gate}explicit confirmation and all server-side policy and "
            "permission checks."
        )

    return " ".join(part for part in (base, cue_suffix, *notes) if part)


def discovery_cues(spec: Any) -> tuple[str, ...]:
    """Return every approved alias/keyword in deterministic registry order."""
    cues: list[str] = []
    seen: set[str] = set()
    for raw in (
        *(getattr(spec, "aliases", ()) or ()),
        *(getattr(spec, "keywords", ()) or ()),
    ):
        cue = str(raw).strip()
        key = cue.casefold()
        if cue and key not in seen:
            seen.add(key)
            cues.append(cue)
    if len(cues) > _MAX_DISCOVERY_CUES:
        raise ValueError(
            f"{spec.name} declares {len(cues)} discovery cues; "
            f"the live description budget is {_MAX_DISCOVERY_CUES}."
        )
    return tuple(cues)


def discovery_cue_suffix(spec: Any) -> str:
    """Render the bounded live-discovery suffix or fail rather than truncate."""
    cues = discovery_cues(spec)
    if not cues:
        return ""
    suffix = "Use this for: " + "; ".join(cues) + "."
    if len(suffix) > _MAX_DISCOVERY_SUFFIX_CHARS:
        raise ValueError(
            f"{spec.name} discovery suffix is {len(suffix)} characters; "
            f"the budget is {_MAX_DISCOVERY_SUFFIX_CHARS}."
        )
    return suffix


def tool_annotations(spec: Any) -> ToolAnnotations:
    """Return conservative MCP hints; annotations never replace server-side gates."""
    hints = safety_hints(spec)
    return ToolAnnotations(
        title=_title(spec.name),
        readOnlyHint=bool(hints["read_only"]),
        destructiveHint=bool(hints["destructive"]),
        idempotentHint=hints["idempotent"],
        openWorldHint=bool(hints["open_world"]),
    )


def _first_line(doc: str | None) -> str:
    return doc.strip().splitlines()[0] if doc else ""


def _title(name: str) -> str:
    return " ".join(part.replace("_", " ").title() for part in name.split("."))
