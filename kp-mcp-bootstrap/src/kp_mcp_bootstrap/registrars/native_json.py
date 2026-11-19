"""Native-config JSON codec, separate from canonical operation-record encoding.

Numbers retain their exact JSON token instead of passing through binary floats.
Only the config serializer emits those tokens; canonical records reject them.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


@dataclass(frozen=True, slots=True)
class _NativeNumber:
    token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.token, str) or not _NUMBER.fullmatch(self.token):
            raise ValueError("invalid native JSON number")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Any:
    raise ValueError("non-finite JSON number")


def loads(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                      parse_int=_NativeNumber, parse_float=_NativeNumber,
                      parse_constant=_reject_constant)


def _quoted(value: str) -> str:
    # Escaped surrogate code units are legal JSON input but cannot be encoded
    # directly as UTF-8. Preserve their escaped form without exposing values.
    escaped = any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    return json.dumps(value, ensure_ascii=escaped)


def _render(value: Any, level: int) -> str:
    if isinstance(value, _NativeNumber):
        return value.token
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _quoted(value)
    if isinstance(value, int):
        return str(value)
    indent = "  " * (level + 1)
    close_indent = "  " * level
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("native JSON object keys must be strings")
        if not value:
            return "{}"
        contents = (indent + _quoted(key) + ": " + _render(item, level + 1)
                    for key, item in value.items())
        return "{\n" + ",\n".join(contents) + "\n" + close_indent + "}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        return "[\n" + ",\n".join(indent + _render(item, level + 1) for item in value) + "\n" + close_indent + "]"
    raise ValueError("unsupported native JSON value")


def dumps(value: Any) -> bytes:
    return (_render(value, 0) + "\n").encode("utf-8")


def native_number_digest(value: Any) -> str | None:
    """Type-separated digest for unexpected numbers on source/auth-owned paths.

    Ordinary values keep the existing canonical digest. A parsed number cannot
    compare equal to a source string containing the same characters. The digest
    is the only value exposed to ownership records; native tokens stay private.
    """
    found = False

    def tagged(item: Any) -> Any:
        nonlocal found
        if isinstance(item, _NativeNumber):
            found = True
            return ["number", item.token]
        if isinstance(item, Mapping):
            return ["object", [[key, tagged(child)] for key, child in sorted(item.items())]]
        if isinstance(item, (list, tuple)):
            return ["array", [tagged(child) for child in item]]
        if item is None:
            return ["null"]
        if isinstance(item, bool):
            return ["boolean", item]
        if isinstance(item, str):
            return ["string", item]
        if isinstance(item, int):
            return ["integer", str(item)]
        return ["other"]

    tree = tagged(value)
    if not found:
        return None
    payload = json.dumps(tree, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(("kp-mcp/native-json-number/v1\0" + payload).encode("utf-8")).hexdigest()
