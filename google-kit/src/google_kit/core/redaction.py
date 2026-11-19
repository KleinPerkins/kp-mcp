"""Redaction rules for google-kit core (R24).

Pure, unit-tested. Used by observability and audit.
Applies to log/metric/span attributes, audit JSONL, and MCP payloads.
"""
from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_CREDENTIAL_RE = re.compile(
    r"""(?ix)
    (?:token|secret|key|credential|password|passwd|pwd
       |api_key|access_token|refresh_token|client_secret|auth_token)
    (\s*[=:]\s*)
    (['"]?)([A-Za-z0-9\-._~+/]{8,})\2
    """,
)

_REDACTED = "[REDACTED]"

_DEFAULT_PII_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "name",
        "subject",
        "summary",
        "attendees",
        "to",
        "cc",
        "bcc",
        "description",
        "body",
        "snippet",
    }
)


def redact_string(text: str, *, pii_fields: frozenset[str] = _DEFAULT_PII_FIELDS) -> str:
    """Redact emails, bearer tokens, and credential key=value patterns from a string."""
    text = _BEARER_RE.sub(_REDACTED, text)
    # Preserve the closing quote (group 2 backreference) so the substitution
    # cannot drop it and malform the surrounding string / JSON.
    text = _CREDENTIAL_RE.sub(
        lambda m: m.group(0)[: m.start(3) - m.start()] + _REDACTED + m.group(2),
        text,
    )
    text = _EMAIL_RE.sub(_REDACTED, text)
    return text


def _redact_list(
    items: list[Any],
    *,
    pii_fields: frozenset[str],
    depth: int,
) -> list[Any]:
    if depth > 10:
        return ["[truncated]"]
    result: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            result.append(redact_dict(item, pii_fields=pii_fields, _depth=depth + 1))
        elif isinstance(item, str):
            result.append(redact_string(item, pii_fields=pii_fields))
        elif isinstance(item, list):
            result.append(_redact_list(item, pii_fields=pii_fields, depth=depth + 1))
        else:
            result.append(item)
    return result


def redact_dict(
    data: dict[str, Any],
    *,
    pii_fields: frozenset[str] = _DEFAULT_PII_FIELDS,
    _depth: int = 0,
) -> dict[str, Any]:
    """Recursively redact a dict (returns a new dict; does not mutate input).

    Field names in pii_fields have their values replaced wholesale.
    String values are scrubbed with redact_string.
    Recursion depth is capped at 10.
    """
    if _depth > 10:
        return {"[truncated]": True}
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(k, str) and k.lower() in pii_fields:
            out[k] = _REDACTED
        elif isinstance(v, str):
            out[k] = redact_string(v, pii_fields=pii_fields)
        elif isinstance(v, dict):
            out[k] = redact_dict(v, pii_fields=pii_fields, _depth=_depth + 1)
        elif isinstance(v, list):
            out[k] = _redact_list(v, pii_fields=pii_fields, depth=_depth + 1)
        else:
            out[k] = v
    return out
