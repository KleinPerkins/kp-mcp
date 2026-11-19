"""Bounded, exact-URI MCP resources for snow-kit."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Iterable, Mapping

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_PARAMS, Annotations, ErrorData, Resource

from snow_kit.context import context_source_status
from snow_kit.core.normalize import stable_json
from snow_kit.mcp.metadata import installed_version

_GUIDANCE_PACKAGE = "snow_kit.data.guidance"
_GUIDANCE_CATALOG = "catalog.json"
_MAX_CATALOG_BYTES = 64 * 1024
_MAX_RESOURCE_BYTES = 16 * 1024
_MAX_STATUS_BYTES = 8 * 1024
_STATIC_URIS = (
    "snow-kit://guidance/query-safety",
    "snow-kit://guidance/analytics-workflow",
    "snow-kit://guidance/permissions-and-recovery",
)
SOURCE_STATUS_URI = "snow-kit://context/sources/status"


@dataclass(frozen=True)
class GuidanceDocument:
    """One validated static resource generated from the packaged catalog."""

    uri: str
    name: str
    title: str
    description: str
    mime_type: str
    audience: tuple[str, ...]
    priority: float
    content: str


def source_status() -> dict[str, Any]:
    """Return bounded, redacted context-source status from the live local profile."""
    status = context_source_status()
    source = status.to_dict()
    return {
        "schema_version": 1,
        "server_version": installed_version(),
        "capability": "authoritative-analytics-context",
        "state": status.state,
        "source_count": 1 if status.configured else 0,
        "sources": [source] if status.configured else [],
        "message": status.message,
    }


def list_catalog_resources() -> list[Resource]:
    """Return the exact resource catalog in deterministic order."""
    static = [
        Resource(
            name=document.name,
            title=document.title,
            uri=document.uri,
            description=document.description,
            mimeType=document.mime_type,
            size=len(document.content.encode("utf-8")),
            annotations=Annotations(
                audience=list(document.audience),
                priority=document.priority,
            ),
        )
        for document in guidance_documents()
    ]
    static.append(
        Resource(
            name="context-sources-status",
            title="Authoritative Context Source Status",
            uri=SOURCE_STATUS_URI,
            description=(
                "Redacted availability state for snow-kit's authoritative analytics context sources."
            ),
            mimeType="application/json",
            annotations=Annotations(audience=["assistant"], priority=0.9),
        )
    )
    return static


def read_catalog_resource(uri: object) -> Iterable[ReadResourceContents]:
    """Read one exact resource URI or raise a protocol InvalidParams error."""
    requested = str(uri)
    for document in guidance_documents():
        if requested == document.uri:
            return [
                ReadResourceContents(
                    content=document.content,
                    mime_type=document.mime_type,
                )
            ]
    if requested == SOURCE_STATUS_URI:
        return [
            ReadResourceContents(
                content=_status_text(),
                mime_type="application/json",
            )
        ]
    raise McpError(
        ErrorData(
            code=INVALID_PARAMS,
            message=(
                f"Unknown snow-kit resource URI: {requested!r}. "
                "Call resources/list for the exact supported URIs."
            ),
        )
    )


def register_resource_handlers(server: Any) -> None:
    """Attach static list/read handlers without subscriptions or templates."""

    @server.list_resources()
    async def _list_resources() -> list[Resource]:
        return list_catalog_resources()

    @server.read_resource()
    async def _read_resource(uri: object) -> Iterable[ReadResourceContents]:
        return read_catalog_resource(uri)


@lru_cache(maxsize=1)
def guidance_documents() -> tuple[GuidanceDocument, ...]:
    """Load and validate the single packaged guidance source."""
    raw = files(_GUIDANCE_PACKAGE).joinpath(_GUIDANCE_CATALOG).read_bytes()
    if len(raw) > _MAX_CATALOG_BYTES:
        raise RuntimeError("snow-kit guidance catalog exceeds its packaged size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("snow-kit guidance catalog is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("snow-kit guidance catalog has an unsupported schema")
    entries = payload.get("resources")
    if not isinstance(entries, list) or len(entries) != len(_STATIC_URIS):
        raise RuntimeError("snow-kit guidance catalog must define exactly three resources")

    documents = tuple(_parse_document(entry) for entry in entries)
    if tuple(document.uri for document in documents) != _STATIC_URIS:
        raise RuntimeError("snow-kit guidance catalog URIs or ordering changed")
    return documents


def _parse_document(entry: object) -> GuidanceDocument:
    if not isinstance(entry, dict):
        raise RuntimeError("snow-kit guidance entries must be objects")
    required = {
        "uri",
        "name",
        "title",
        "description",
        "mime_type",
        "audience",
        "priority",
        "summary",
        "sections",
    }
    if set(entry) != required:
        raise RuntimeError("snow-kit guidance entry keys do not match the schema")
    if entry["mime_type"] != "text/markdown":
        raise RuntimeError("snow-kit static guidance must use text/markdown")
    audience = entry["audience"]
    if (
        not isinstance(audience, list)
        or not audience
        or any(item not in {"user", "assistant"} for item in audience)
    ):
        raise RuntimeError("snow-kit guidance audience is invalid")
    priority = entry["priority"]
    if not isinstance(priority, (int, float)) or isinstance(priority, bool) or not 0 <= priority <= 1:
        raise RuntimeError("snow-kit guidance priority is invalid")
    content = _render_markdown(entry)
    if len(content.encode("utf-8")) > _MAX_RESOURCE_BYTES:
        raise RuntimeError("snow-kit guidance resource exceeds its size limit")
    return GuidanceDocument(
        uri=_required_string(entry, "uri"),
        name=_required_string(entry, "name"),
        title=_required_string(entry, "title"),
        description=_required_string(entry, "description"),
        mime_type="text/markdown",
        audience=tuple(audience),
        priority=float(priority),
        content=content,
    )


def _render_markdown(entry: Mapping[str, Any]) -> str:
    title = _required_string(entry, "title")
    summary = _required_string(entry, "summary")
    sections = entry["sections"]
    if not isinstance(sections, list) or not sections:
        raise RuntimeError("snow-kit guidance sections must be a non-empty list")
    lines = [f"# {title}", "", summary]
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"heading", "items"}:
            raise RuntimeError("snow-kit guidance section is invalid")
        heading = _required_string(section, "heading")
        items = section["items"]
        if not isinstance(items, list) or not items:
            raise RuntimeError("snow-kit guidance section items must be non-empty")
        lines.extend(["", f"## {heading}"])
        for item in items:
            if not isinstance(item, str) or not item.strip():
                raise RuntimeError("snow-kit guidance item must be a non-empty string")
            lines.append(f"- {item.strip()}")
    return "\n".join(lines) + "\n"


def _required_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"snow-kit guidance {key} must be a non-empty string")
    return value.strip()


def _status_text() -> str:
    text = stable_json(source_status())
    if len(text.encode("utf-8")) > _MAX_STATUS_BYTES:
        raise RuntimeError("snow-kit context source status exceeds its size limit")
    return text
