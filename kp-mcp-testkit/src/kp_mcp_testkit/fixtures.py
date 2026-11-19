"""Golden fixture load/save and JSON-normalized comparison.

Concrete, utility-agnostic. No Google deps.
"""

import json
from pathlib import Path
from typing import Any


def _normalize(value: Any) -> Any:
    """Recursively sort dict keys and list elements for stable comparison."""
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        normalized = [_normalize(i) for i in value]
        try:
            return sorted(normalized, key=lambda x: json.dumps(x, sort_keys=True))
        except TypeError:
            return normalized
    return value


def load_fixture(path: Path) -> Any:
    """Load a JSON golden fixture from disk.

    Args:
        path: Path to the fixture JSON file.

    Returns:
        Parsed JSON value (dict, list, str, etc.).
    """
    return json.loads(path.read_text(encoding="utf-8"))


def save_fixture(path: Path, value: Any) -> None:
    """Save a value as a pretty-printed JSON golden fixture.

    Args:
        path: Destination path (parent dirs are created if absent).
        value: JSON-serializable value to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare_normalized(expected: Any, actual: Any) -> tuple[bool, str]:
    """Compare two JSON-serializable values after normalization.

    Normalization: sorts dict keys and lists (by JSON repr) so that
    ordering differences are ignored.

    Args:
        expected: Reference value (e.g. loaded from a golden fixture).
        actual: Candidate value produced by the system under test.

    Returns:
        (match, diff_summary) where diff_summary is empty if match is True.
    """
    norm_expected = _normalize(expected)
    norm_actual = _normalize(actual)

    if norm_expected == norm_actual:
        return True, ""

    exp_str = json.dumps(norm_expected, indent=2, sort_keys=True)
    act_str = json.dumps(norm_actual, indent=2, sort_keys=True)

    exp_lines = exp_str.splitlines()
    act_lines = act_str.splitlines()

    diff_lines: list[str] = []
    for i, (e, a) in enumerate(zip(exp_lines, act_lines)):
        if e != a:
            diff_lines.append(f"  line {i + 1}: expected {e!r}, got {a!r}")
    if len(exp_lines) != len(act_lines):
        diff_lines.append(
            f"  length mismatch: expected {len(exp_lines)} lines, got {len(act_lines)}"
        )

    summary = "\n".join(diff_lines[:20])
    if len(diff_lines) > 20:
        summary += f"\n  ... ({len(diff_lines) - 20} more differences)"
    return False, summary
