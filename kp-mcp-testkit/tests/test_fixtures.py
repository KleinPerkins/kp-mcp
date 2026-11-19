"""Tests for fixtures.py: roundtrip, normalization, compare."""

from pathlib import Path

import pytest

from kp_mcp_testkit.fixtures import compare_normalized, load_fixture, save_fixture


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    fixture_path = tmp_path / "golden" / "test.json"
    data = {"b": 2, "a": 1, "list": [3, 1, 2]}
    save_fixture(fixture_path, data)
    loaded = load_fixture(fixture_path)
    assert loaded == data


def test_compare_normalized_match_ignores_key_order() -> None:
    a = {"z": 1, "a": 2}
    b = {"a": 2, "z": 1}
    match, diff = compare_normalized(a, b)
    assert match is True
    assert diff == ""


def test_compare_normalized_match_ignores_list_order() -> None:
    a = {"items": [3, 1, 2]}
    b = {"items": [1, 2, 3]}
    match, diff = compare_normalized(a, b)
    assert match is True


def test_compare_normalized_detects_mismatch() -> None:
    a = {"x": 1}
    b = {"x": 2}
    match, diff = compare_normalized(a, b)
    assert match is False
    assert diff != ""


def test_compare_normalized_nested() -> None:
    a = {"outer": {"inner": [1, 2]}}
    b = {"outer": {"inner": [2, 1]}}
    match, _ = compare_normalized(a, b)
    assert match is True


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "fixture.json"
    save_fixture(path, {"ok": True})
    assert path.exists()
