"""Comparator-dispatch parity harness.

Registered comparators:
  byte              — CONCRETE: exact bytes equality
  normalized-json   — CONCRETE: JSON equality after normalization (see fixtures.py)
  mutation-request  — CONCRETE (Phase 4): normalized-json comparison of API request bodies
  semantic          — CONCRETE (Phase 6): Google-API-aware semantic normalization
  sandbox-e2e       — CONCRETE (Phase 6): semantic normalization for live sandbox results

Semantic normalization rules (each is NAMED and unit-tested):
  RULE_IGNORE_GENERATED_IDS   — strip objectId/pageObjectId/layoutObjectId/masterObjectId
  RULE_NORMALIZE_REVISION_ETAG — strip revisionId/revision_id/etag/eTag
  RULE_NORMALIZE_TIMESTAMPS   — strip createTime/modifiedTime/etc. timestamp fields
  RULE_NORMALIZE_PAGINATION_TOKENS — strip nextPageToken/pageToken pagination fields
  RULE_NORMALIZE_RESPONDER_URI — strip responderUri/responder_uri
  RULE_ADDITIVE_OPTIONAL_FIELDS — ignore fields present in actual but absent in expected
  RULE_NORMALIZE_DOC_STRUCTURE  — normalize whitespace in text content fields
  RULE_NORMALIZE_BODY_TRUNCATION — for body fields, only compare the first 500 chars
"""

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

from .fixtures import compare_normalized

ComparatorType = Literal[
    "byte", "normalized-json", "semantic", "mutation-request", "sandbox-e2e"
]

RULE_IGNORE_GENERATED_IDS = "ignore_generated_ids"
RULE_NORMALIZE_REVISION_ETAG = "normalize_revision_etag"
RULE_NORMALIZE_TIMESTAMPS = "normalize_timestamps"
RULE_NORMALIZE_PAGINATION_TOKENS = "normalize_pagination_tokens"
RULE_NORMALIZE_RESPONDER_URI = "normalize_responder_uri"
RULE_ADDITIVE_OPTIONAL_FIELDS = "additive_optional_fields"
RULE_NORMALIZE_DOC_STRUCTURE = "normalize_doc_structure"
RULE_NORMALIZE_BODY_TRUNCATION = "normalize_body_truncation"

_GENERATED_ID_FIELDS: frozenset[str] = frozenset({
    "objectId", "object_id",
    "pageObjectId", "page_object_id",
    "layoutObjectId", "layout_object_id",
    "masterObjectId", "master_object_id",
})

_REVISION_ETAG_FIELDS: frozenset[str] = frozenset({
    "revisionId", "revision_id",
    "etag", "eTag", "ETag",
})

_TIMESTAMP_FIELDS: frozenset[str] = frozenset({
    "createTime", "create_time",
    "modifiedTime", "modified_time",
    "lastModifiedTime", "last_modified_time",
    "createdTime", "created_time",
    "updateTime", "update_time",
    "lastEditedTime", "last_edited_time",
})

_PAGINATION_FIELDS: frozenset[str] = frozenset({
    "nextPageToken", "next_page_token",
    "pageToken", "page_token",
})

_RESPONDER_URI_FIELDS: frozenset[str] = frozenset({
    "responderUri", "responder_uri",
})

_BODY_TRUNCATION_FIELDS: frozenset[str] = frozenset({"body"})
_BODY_MAX_CHARS = 500

_STRIP_FIELDS: frozenset[str] = (
    _GENERATED_ID_FIELDS
    | _REVISION_ETAG_FIELDS
    | _TIMESTAMP_FIELDS
    | _PAGINATION_FIELDS
    | _RESPONDER_URI_FIELDS
)


def _apply_strip_fields(obj: Any) -> Any:
    """Recursively remove all STRIP_FIELDS from a JSON-like structure.

    Applies RULE_IGNORE_GENERATED_IDS, RULE_NORMALIZE_REVISION_ETAG,
    RULE_NORMALIZE_TIMESTAMPS, RULE_NORMALIZE_PAGINATION_TOKENS, and
    RULE_NORMALIZE_RESPONDER_URI.
    """
    if isinstance(obj, dict):
        return {
            k: _apply_strip_fields(v)
            for k, v in obj.items()
            if k not in _STRIP_FIELDS
        }
    if isinstance(obj, list):
        return [_apply_strip_fields(item) for item in obj]
    return obj


def _apply_body_truncation(obj: Any) -> Any:
    """Truncate string values for RULE_NORMALIZE_BODY_TRUNCATION fields.

    Only truncates ``body`` fields to _BODY_MAX_CHARS chars, matching the
    gmail core function's output contract (body[:500] + '...').
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in _BODY_TRUNCATION_FIELDS and isinstance(v, str):
                out[k] = v[:_BODY_MAX_CHARS]
            else:
                out[k] = _apply_body_truncation(v)
        return out
    if isinstance(obj, list):
        return [_apply_body_truncation(item) for item in obj]
    return obj


def _normalize_doc_structure(obj: Any) -> Any:
    """Normalize whitespace in text content fields (RULE_NORMALIZE_DOC_STRUCTURE).

    Collapses runs of whitespace in string values so that formatting-equivalent
    doc/slide structures compare equal even when the Google API returns slight
    whitespace variants across calls.
    """
    if isinstance(obj, dict):
        return {k: _normalize_doc_structure(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_doc_structure(item) for item in obj]
    if isinstance(obj, str):
        import re as _re
        return _re.sub(r"\s+", " ", obj).strip()
    return obj


def _apply_additive_optional_fields(expected: Any, actual: Any) -> Any:
    """Remove from actual any keys absent in expected (RULE_ADDITIVE_OPTIONAL_FIELDS).

    This allows the API to add new optional fields without breaking parity.
    Only removes keys at every level where expected is a dict.
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        return {
            k: _apply_additive_optional_fields(expected.get(k), v)
            for k, v in actual.items()
            if k in expected
        }
    if isinstance(expected, list) and isinstance(actual, list):
        if not expected:
            return actual
        return [
            _apply_additive_optional_fields(
                expected[min(i, len(expected) - 1)], item
            )
            for i, item in enumerate(actual)
        ]
    return actual


def _semantic_normalize(expected: Any, actual: Any) -> tuple[Any, Any]:
    """Apply all semantic normalization rules to (expected, actual).

    Returns the normalized pair ready for normalized-json comparison.
    """
    norm_e = _apply_strip_fields(expected)
    norm_a = _apply_strip_fields(actual)

    norm_e = _apply_body_truncation(norm_e)
    norm_a = _apply_body_truncation(norm_a)

    norm_e = _normalize_doc_structure(norm_e)
    norm_a = _normalize_doc_structure(norm_a)

    norm_a = _apply_additive_optional_fields(norm_e, norm_a)

    return norm_e, norm_a


@dataclass
class ParityResult:
    """Result of a parity comparison."""

    match: bool
    comparator: ComparatorType
    diff: str = ""


def _compare_byte(a: Any, b: Any) -> ParityResult:
    """Exact bytes or str equality."""
    if isinstance(a, str) and isinstance(b, str):
        match = a == b
        diff = "" if match else f"strings differ\n  expected: {a!r}\n  got:      {b!r}"
    elif isinstance(a, bytes) and isinstance(b, bytes):
        match = a == b
        diff = "" if match else f"byte sequences differ (lengths {len(a)} vs {len(b)})"
    else:
        match = a == b
        diff = "" if match else f"values differ: {a!r} != {b!r}"
    return ParityResult(match=match, comparator="byte", diff=diff)


def _compare_normalized_json(a: Any, b: Any) -> ParityResult:
    """JSON equality after key-sort and list-sort normalization."""
    match, diff = compare_normalized(a, b)
    return ParityResult(match=match, comparator="normalized-json", diff=diff)


def _normalize_key_order(value: Any) -> Any:
    """Recursively sort mapping keys without reordering list elements."""
    if isinstance(value, dict):
        return {k: _normalize_key_order(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize_key_order(item) for item in value]
    return value


def _compare_ordered_json(a: Any, b: Any, comparator: ComparatorType) -> ParityResult:
    """Compare JSON-like values while preserving list order."""
    norm_a = _normalize_key_order(a)
    norm_b = _normalize_key_order(b)
    if norm_a == norm_b:
        return ParityResult(match=True, comparator=comparator)

    exp_lines = json.dumps(norm_a, indent=2, sort_keys=True).splitlines()
    act_lines = json.dumps(norm_b, indent=2, sort_keys=True).splitlines()
    diff_lines: list[str] = []
    for i, (expected_line, actual_line) in enumerate(zip(exp_lines, act_lines), start=1):
        if expected_line != actual_line:
            diff_lines.append(
                f"  line {i}: expected {expected_line!r}, got {actual_line!r}"
            )
    if len(exp_lines) != len(act_lines):
        diff_lines.append(
            f"  length mismatch: expected {len(exp_lines)} lines, got {len(act_lines)}"
        )
    return ParityResult(match=False, comparator=comparator, diff="\n".join(diff_lines[:20]))


def _compare_semantic(a: Any, b: Any) -> ParityResult:
    """Semantic comparison with Google-API-aware normalizations.

    Rules applied (all named and individually unit-tested in test_parity.py):
      RULE_IGNORE_GENERATED_IDS      — strip objectId/pageObjectId/layoutObjectId/masterObjectId
      RULE_NORMALIZE_REVISION_ETAG   — strip revisionId/revision_id/etag/eTag
      RULE_NORMALIZE_TIMESTAMPS      — strip createTime/modifiedTime/etc.
      RULE_NORMALIZE_PAGINATION_TOKENS — strip nextPageToken/pageToken
      RULE_NORMALIZE_RESPONDER_URI   — strip responderUri/responder_uri
      RULE_ADDITIVE_OPTIONAL_FIELDS  — ignore fields present in actual but absent in expected
      RULE_NORMALIZE_DOC_STRUCTURE   — collapse whitespace in text content
      RULE_NORMALIZE_BODY_TRUNCATION — compare only first 500 chars of body fields
    """
    norm_a, norm_b = _semantic_normalize(a, b)
    match, diff = compare_normalized(norm_a, norm_b)
    return ParityResult(match=match, comparator="semantic", diff=diff)


def _compare_mutation_request(a: Any, b: Any) -> ParityResult:
    """API-request-body equivalence for mutation parity.

    Compares two request body dicts with sorted mapping keys but order-sensitive
    lists, since Google batch/mutation request arrays are executed in order.
    ``a`` is the expected (legacy-equivalent) body; ``b`` is the body captured
    from the mock-Google recorder.
    """
    return _compare_ordered_json(a, b, "mutation-request")


def _compare_sandbox_e2e(a: Any, b: Any) -> ParityResult:
    """End-to-end sandbox comparison for live API round-trip results.

    Applies the same semantic normalization rules as _compare_semantic since
    live API responses contain all nondeterministic fields (generated IDs,
    timestamps, revision IDs, etc.). The sandbox harness (sandbox.py) gates
    live execution behind GOOGLE_KIT_SANDBOX=1; this comparator is invoked
    once real responses are available.
    """
    norm_a, norm_b = _semantic_normalize(a, b)
    match, diff = compare_normalized(norm_a, norm_b)
    return ParityResult(match=match, comparator="sandbox-e2e", diff=diff)


_REGISTRY: dict[ComparatorType, Callable[[Any, Any], ParityResult]] = {
    "byte": _compare_byte,
    "normalized-json": _compare_normalized_json,
    "semantic": _compare_semantic,
    "mutation-request": _compare_mutation_request,
    "sandbox-e2e": _compare_sandbox_e2e,
}


def compare(comparator: ComparatorType, expected: Any, actual: Any) -> ParityResult:
    """Dispatch to the named comparator.

    Args:
        comparator: One of the registered ComparatorType values.
        expected: Reference / golden value.
        actual: Candidate value produced by the system under test.

    Returns:
        ParityResult with match flag and diff summary.
    """
    fn = _REGISTRY.get(comparator)
    if fn is None:
        raise ValueError(f"Unknown comparator: {comparator!r}. Valid: {list(_REGISTRY)}")
    return fn(expected, actual)
