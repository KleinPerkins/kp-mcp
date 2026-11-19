"""Tests for google_kit.core.normalize."""
import json
from datetime import date, datetime, timezone

import pytest

from google_kit.core.normalize import (
    Meta,
    OutputEnvelope,
    PageInfo,
    build_meta,
    coerce_enum,
    extract_drive_id,
    parse_datetime,
    parse_email_list,
    stable_json,
    validate_a1_range,
)


class TestExtractDriveId:
    def test_bare_id(self) -> None:
        fid = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
        assert extract_drive_id(fid) == fid

    def test_drive_url(self) -> None:
        url = "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/view"
        assert extract_drive_id(url) == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"

    def test_docs_url(self) -> None:
        url = "https://docs.google.com/document/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit"
        assert extract_drive_id(url) == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Drive ID"):
            extract_drive_id("https://drive.google.com/no-id-here")

    def test_invalid_bare_value_raises(self) -> None:
        with pytest.raises(ValueError, match="Drive ID"):
            extract_drive_id("short")


class TestParseDatetime:
    def test_iso_string_no_tz(self) -> None:
        dt = parse_datetime("2024-01-15T10:30:00")
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2024

    def test_iso_string_with_tz(self) -> None:
        dt = parse_datetime("2024-01-15T10:30:00+05:00")
        assert dt.tzinfo == timezone.utc
        assert dt.hour == 5

    def test_passthrough_datetime(self) -> None:
        orig = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        assert parse_datetime(orig) == orig

    def test_passthrough_date(self) -> None:
        dt = parse_datetime(date(2024, 6, 1))
        assert dt == datetime(2024, 6, 1, tzinfo=timezone.utc)

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="parse"):
            parse_datetime("not-a-date")


class TestValidateA1Range:
    def test_simple(self) -> None:
        assert validate_a1_range("A1:B10") == "A1:B10"

    def test_with_sheet(self) -> None:
        assert validate_a1_range("Sheet1!A1:B10") == "Sheet1!A1:B10"

    def test_column_only(self) -> None:
        assert validate_a1_range("A:B") == "A:B"

    def test_strips_whitespace(self) -> None:
        assert validate_a1_range("  A1:B10  ") == "A1:B10"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="A1 range"):
            validate_a1_range("123:456")


class TestParseEmailList:
    def test_single_email(self) -> None:
        assert parse_email_list("alice@example.com") == ["alice@example.com"]

    def test_csv_string(self) -> None:
        result = parse_email_list("alice@example.com, bob@example.com")
        assert result == ["alice@example.com", "bob@example.com"]

    def test_list_input(self) -> None:
        result = parse_email_list(["alice@example.com", "bob@example.com"])
        assert result == ["alice@example.com", "bob@example.com"]

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="email"):
            parse_email_list("not-an-email")

    def test_empty_string_returns_empty(self) -> None:
        assert parse_email_list("") == []


class TestCoerceEnum:
    def test_exact_match(self) -> None:
        assert coerce_enum("read", ["read", "write", "admin"]) == "read"

    def test_case_insensitive(self) -> None:
        assert coerce_enum("WRITE", ["read", "write", "admin"]) == "write"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="allowed"):
            coerce_enum("delete", ["read", "write"])


class TestOutputEnvelope:
    def test_minimal(self) -> None:
        env = OutputEnvelope(data={"key": "value"})
        assert env.data == {"key": "value"}
        assert env.page is None
        assert env.warnings == []
        assert env.meta.run_id == ""

    def test_with_page(self) -> None:
        env = OutputEnvelope(
            data=[],
            page=PageInfo(next_page_token="abc", total_items=100),
        )
        assert env.page is not None
        assert env.page.next_page_token == "abc"

    def test_model_dump(self) -> None:
        env = OutputEnvelope(data=42, warnings=["partial"])
        d = env.model_dump()
        assert d["data"] == 42
        assert d["warnings"] == ["partial"]

    def test_meta_fields(self) -> None:
        env = OutputEnvelope(data=None, meta=Meta(run_id="abc", op="drive.fetch", latency_ms=12.5))
        assert env.meta.run_id == "abc"
        assert env.meta.latency_ms == 12.5


class TestObservabilityEnvelope:
    """§8 observability envelope fields are additive and default-safe."""

    def test_extended_fields_default(self) -> None:
        m = Meta(op="drive.fetch")
        assert m.api is None
        assert m.method is None
        assert m.scopes_used == []
        assert m.calls is None
        assert m.quota_units_est is None
        assert m.fallback_used is False
        assert m.recipe_id is None
        assert m.saga_compensated is False

    def test_legacy_meta_unaffected(self) -> None:
        # The pre-existing minimal construction still works unchanged.
        m = Meta(op="drive.fetch")
        assert m.run_id == "" and m.op == "drive.fetch" and m.latency_ms is None

    def test_build_meta_populates_envelope(self) -> None:
        m = build_meta(
            "doc.read",
            api="drive.v3",
            method="files.export",
            scopes_used=["https://www.googleapis.com/auth/drive.readonly"],
            calls=1,
            quota_units_est=1,
            fallback_used=True,
            recipe_id="hydrate-then-refine",
            saga_compensated=True,
        )
        assert m.op == "doc.read"
        assert m.api == "drive.v3" and m.method == "files.export"
        assert m.scopes_used == ["https://www.googleapis.com/auth/drive.readonly"]
        assert m.calls == 1 and m.quota_units_est == 1
        assert m.fallback_used is True and m.saga_compensated is True
        assert m.recipe_id == "hydrate-then-refine"

    def test_build_meta_minimal_defaults(self) -> None:
        m = build_meta("drive.fetch")
        assert m.op == "drive.fetch"
        assert m.scopes_used == [] and m.fallback_used is False
        assert m.run_id == "" and m.latency_ms is None


class TestStableJson:
    def test_sorted_keys(self) -> None:
        result = stable_json({"z": 1, "a": 2, "m": 3})
        parsed = json.loads(result)
        assert list(parsed.keys()) == ["a", "m", "z"]

    def test_datetime_serialized(self) -> None:
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = stable_json({"ts": dt})
        assert "2024-01-01" in result

    def test_deterministic(self) -> None:
        obj = {"b": [3, 1, 2], "a": {"z": 9, "a": 1}}
        assert stable_json(obj) == stable_json(obj)
