"""Input coercion and uniform output envelope for google-kit core (R23).

Envelope shape: {data, page, warnings, meta} — pydantic model.
Stable/deterministic JSON serialization via stable_json (sorted keys).
Shared by all ops; unit-tested.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

_DRIVE_URL_RE = re.compile(
    r"https://(?:drive|docs)\.google\.com/[^\s?#]*/d/([a-zA-Z0-9_-]{25,})"
)
_DRIVE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{25,}$")
_A1_RANGE_RE = re.compile(r"^[A-Za-z]+\d*(?::[A-Za-z]+\d*)?$")
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
    re.IGNORECASE,
)


def extract_drive_id(value: str) -> str:
    """Extract a Drive file/folder ID from a URL or return the ID if bare.

    Raises:
        ValueError: If value looks like a URL but no valid ID can be found,
                    or if value is neither a recognisable URL nor a bare ID.
    """
    if value.startswith("http"):
        m = _DRIVE_URL_RE.search(value)
        if not m:
            raise ValueError(f"Could not extract Drive ID from URL: {value!r}")
        return m.group(1)
    if _DRIVE_ID_RE.match(value):
        return value
    raise ValueError(f"Value is neither a Drive URL nor a bare Drive ID: {value!r}")


def parse_datetime(value: str | datetime | date) -> datetime:
    """Parse an ISO-8601 string (or pass-through datetime/date) to a UTC datetime.

    Raises:
        ValueError: On unparseable input.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Cannot parse datetime: {value!r}") from exc


def validate_a1_range(value: str) -> str:
    """Validate a Sheets A1-notation range (e.g. 'A1:B10', 'Sheet1!A1:B10').

    Returns:
        The canonical (stripped) value.

    Raises:
        ValueError: If the range part is not valid A1 notation.
    """
    value = value.strip()
    if "!" in value:
        _, range_part = value.split("!", 1)
    else:
        range_part = value
    if not _A1_RANGE_RE.match(range_part):
        raise ValueError(f"Invalid A1 range: {value!r}")
    return value


def parse_email_list(value: str | list[str]) -> list[str]:
    """Parse a comma-separated email string or list, validating each address.

    Raises:
        ValueError: On the first invalid email address found.
    """
    if isinstance(value, list):
        raw = [str(v).strip() for v in value]
    else:
        raw = [v.strip() for v in str(value).split(",")]
    result: list[str] = []
    for addr in raw:
        if not addr:
            continue
        if not _EMAIL_RE.match(addr):
            raise ValueError(f"Invalid email address: {addr!r}")
        result.append(addr)
    return result


def coerce_enum(value: str, allowed: list[str], *, name: str = "value") -> str:
    """Normalise and validate an enum string (case-insensitive).

    Returns:
        The canonical (original-case) member from allowed.

    Raises:
        ValueError: If value is not in the allowed set.
    """
    mapping = {a.lower(): a for a in allowed}
    normalized = value.strip().lower()
    if normalized not in mapping:
        raise ValueError(
            f"Invalid {name} {value!r}; allowed: {', '.join(allowed)}"
        )
    return mapping[normalized]


class PageInfo(BaseModel):
    """Pagination metadata returned in the output envelope."""

    next_page_token: str | None = None
    total_items: int | None = None


class Meta(BaseModel):
    """Operation metadata returned in the output envelope.

    Carries the architecture-brief §8 observability envelope. The base fields
    (``run_id``, ``op``, ``latency_ms``) are populated by every op; the
    routing/composition fields (``api``..``saga_compensated``) are populated by
    capabilities that go through the router (thick reads) or a recipe (saga).
    Legacy 1:1 ops leave the extended fields at their defaults — they are all
    optional and strictly additive (no existing op needs to change).
    """

    run_id: str = ""
    op: str = ""
    latency_ms: float | None = None
    # §8 observability envelope (additive; populated by router/recipe capabilities).
    api: str | None = None
    method: str | None = None
    scopes_used: list[str] = Field(default_factory=list)
    calls: int | None = None
    quota_units_est: int | None = None
    fallback_used: bool = False
    recipe_id: str | None = None
    saga_compensated: bool = False


def build_meta(
    op: str,
    *,
    run_id: str | None = None,
    latency_ms: float | None = None,
    api: str | None = None,
    method: str | None = None,
    scopes_used: list[str] | None = None,
    calls: int | None = None,
    quota_units_est: int | None = None,
    fallback_used: bool = False,
    recipe_id: str | None = None,
    saga_compensated: bool = False,
) -> Meta:
    """Construct a :class:`Meta` populating the §8 observability envelope.

    Convenience for router/recipe capabilities that want to report which API,
    method, scopes, call count, fallback, recipe, and saga state an invocation
    actually used. Legacy ops may keep using ``Meta(op=...)`` directly.
    """
    kwargs: dict[str, Any] = {
        "op": op,
        "api": api,
        "method": method,
        "scopes_used": list(scopes_used or []),
        "calls": calls,
        "quota_units_est": quota_units_est,
        "fallback_used": fallback_used,
        "recipe_id": recipe_id,
        "saga_compensated": saga_compensated,
    }
    if run_id is not None:
        kwargs["run_id"] = run_id
    if latency_ms is not None:
        kwargs["latency_ms"] = latency_ms
    return Meta(**kwargs)


class OutputEnvelope(BaseModel, Generic[T]):
    """Uniform output envelope for all google-kit operations.

    Attributes:
        data:     Primary result payload (typed per operation).
        page:     Pagination info (None for non-paginated ops).
        warnings: Non-fatal warnings (e.g. partial results, deprecated fields).
        meta:     Run metadata (run_id, op, latency_ms).
    """

    data: T
    page: PageInfo | None = None
    warnings: list[str] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def stable_json(obj: Any) -> str:
    """Serialize obj to JSON with sorted keys (deterministic output)."""
    return json.dumps(obj, sort_keys=True, default=_json_default)
