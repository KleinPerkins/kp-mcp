"""Tests for parity.py comparators (all concrete as of Phase 6)."""

import pytest

from kp_mcp_testkit.parity import (
    RULE_ADDITIVE_OPTIONAL_FIELDS,
    RULE_IGNORE_GENERATED_IDS,
    RULE_NORMALIZE_BODY_TRUNCATION,
    RULE_NORMALIZE_DOC_STRUCTURE,
    RULE_NORMALIZE_PAGINATION_TOKENS,
    RULE_NORMALIZE_RESPONDER_URI,
    RULE_NORMALIZE_REVISION_ETAG,
    RULE_NORMALIZE_TIMESTAMPS,
    _apply_additive_optional_fields,
    _apply_body_truncation,
    _apply_strip_fields,
    _normalize_doc_structure,
    compare,
)


class TestByteComparator:
    def test_match_str(self) -> None:
        result = compare("byte", "hello", "hello")
        assert result.match is True
        assert result.diff == ""

    def test_mismatch_str(self) -> None:
        result = compare("byte", "hello", "world")
        assert result.match is False
        assert result.diff != ""

    def test_match_bytes(self) -> None:
        result = compare("byte", b"\x00\x01", b"\x00\x01")
        assert result.match is True

    def test_mismatch_bytes(self) -> None:
        result = compare("byte", b"\x00", b"\x01")
        assert result.match is False


class TestNormalizedJsonComparator:
    def test_match_key_order_independent(self) -> None:
        result = compare("normalized-json", {"a": 1, "b": 2}, {"b": 2, "a": 1})
        assert result.match is True

    def test_mismatch(self) -> None:
        result = compare("normalized-json", {"a": 1}, {"a": 99})
        assert result.match is False
        assert result.diff != ""


class TestMutationRequestComparator:
    def test_match(self) -> None:
        result = compare(
            "mutation-request",
            {"title": "t", "status": "needsAction"},
            {"status": "needsAction", "title": "t"},
        )
        assert result.match is True
        assert result.comparator == "mutation-request"

    def test_mismatch(self) -> None:
        result = compare("mutation-request", {"title": "expected"}, {"title": "actual"})
        assert result.match is False
        assert result.diff != ""


class TestSemanticRuleIgnoreGeneratedIds:
    """RULE_IGNORE_GENERATED_IDS: strip objectId/pageObjectId/layoutObjectId/masterObjectId."""

    def test_rule_name_defined(self) -> None:
        assert RULE_IGNORE_GENERATED_IDS == "ignore_generated_ids"

    def test_object_id_stripped_from_both(self) -> None:
        expected = {"title": "My Slide", "objectId": "expected_id"}
        actual = {"title": "My Slide", "objectId": "different_generated_id"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_layout_object_id_stripped(self) -> None:
        expected = {"title": "t", "layoutObjectId": "layout_abc"}
        actual = {"title": "t", "layoutObjectId": "layout_xyz"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_master_object_id_stripped(self) -> None:
        expected = {"count": 2, "masterObjectId": "master_abc"}
        actual = {"count": 2, "masterObjectId": "master_def"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_snake_case_object_id_stripped(self) -> None:
        expected = {"slide_count": 1, "object_id": "exp_id", "layout_object_id": "lo1"}
        actual = {"slide_count": 1, "object_id": "act_id", "layout_object_id": "lo2"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_non_id_fields_still_compared(self) -> None:
        expected = {"slide_count": 2}
        actual = {"slide_count": 3}
        result = compare("semantic", expected, actual)
        assert result.match is False


class TestSemanticRuleNormalizeRevisionEtag:
    """RULE_NORMALIZE_REVISION_ETAG: strip revisionId/revision_id/etag/eTag."""

    def test_rule_name_defined(self) -> None:
        assert RULE_NORMALIZE_REVISION_ETAG == "normalize_revision_etag"

    def test_revision_id_camel_case_stripped(self) -> None:
        expected = {"title": "Doc", "revisionId": "rev-abc"}
        actual = {"title": "Doc", "revisionId": "rev-xyz-different"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_revision_id_snake_case_stripped(self) -> None:
        expected = {"title": "t", "revision_id": "r1"}
        actual = {"title": "t", "revision_id": "r99"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_etag_stripped(self) -> None:
        expected = {"count": 1, "etag": "abc123"}
        actual = {"count": 1, "etag": "xyz789"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff


class TestSemanticRuleNormalizeTimestamps:
    """RULE_NORMALIZE_TIMESTAMPS: strip createTime/modifiedTime/etc."""

    def test_rule_name_defined(self) -> None:
        assert RULE_NORMALIZE_TIMESTAMPS == "normalize_timestamps"

    def test_create_time_stripped(self) -> None:
        expected = {"id": "abc", "createTime": "2024-01-01T00:00:00Z"}
        actual = {"id": "abc", "createTime": "2025-06-15T12:00:00Z"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_modified_time_stripped(self) -> None:
        expected = {"name": "x", "modifiedTime": "2024-01-01"}
        actual = {"name": "x", "modifiedTime": "2025-12-31"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_snake_case_timestamps_stripped(self) -> None:
        expected = {"count": 5, "created_time": "t1", "modified_time": "t2"}
        actual = {"count": 5, "created_time": "t3", "modified_time": "t4"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff


class TestSemanticRuleNormalizePaginationTokens:
    """RULE_NORMALIZE_PAGINATION_TOKENS: strip nextPageToken/pageToken."""

    def test_rule_name_defined(self) -> None:
        assert RULE_NORMALIZE_PAGINATION_TOKENS == "normalize_pagination_tokens"

    def test_next_page_token_stripped(self) -> None:
        expected = {"count": 3, "nextPageToken": "token_abc"}
        actual = {"count": 3, "nextPageToken": "token_xyz"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_snake_page_token_stripped(self) -> None:
        expected = {"count": 2, "next_page_token": "t1"}
        actual = {"count": 2, "next_page_token": "t2"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff


class TestSemanticRuleNormalizeResponderUri:
    """RULE_NORMALIZE_RESPONDER_URI: strip responderUri/responder_uri."""

    def test_rule_name_defined(self) -> None:
        assert RULE_NORMALIZE_RESPONDER_URI == "normalize_responder_uri"

    def test_responder_uri_camel_stripped(self) -> None:
        expected = {"title": "Form", "responderUri": "https://forms.google.com/abc"}
        actual = {"title": "Form", "responderUri": "https://forms.google.com/xyz"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_responder_uri_snake_stripped(self) -> None:
        expected = {"title": "Form", "responder_uri": "https://forms/abc"}
        actual = {"title": "Form", "responder_uri": "https://forms/xyz"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff


class TestSemanticRuleAdditiveOptionalFields:
    """RULE_ADDITIVE_OPTIONAL_FIELDS: ignore extra fields in actual not in expected."""

    def test_rule_name_defined(self) -> None:
        assert RULE_ADDITIVE_OPTIONAL_FIELDS == "additive_optional_fields"

    def test_extra_field_in_actual_ignored(self) -> None:
        expected = {"title": "t", "count": 1}
        actual = {"title": "t", "count": 1, "new_optional_field": "future_addition"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_missing_field_in_actual_fails(self) -> None:
        expected = {"title": "t", "count": 1, "required_field": "value"}
        actual = {"title": "t", "count": 1}
        result = compare("semantic", expected, actual)
        assert result.match is False

    def test_apply_additive_direct_empty_expected_list(self) -> None:
        result = _apply_additive_optional_fields([], [1, 2, 3])
        assert result == [1, 2, 3]

    def test_nested_additive_field_ignored(self) -> None:
        expected = {"data": {"title": "t"}}
        actual = {"data": {"title": "t", "extra_nested": "x"}}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff


class TestSemanticRuleNormalizeDocStructure:
    """RULE_NORMALIZE_DOC_STRUCTURE: normalize whitespace in text content."""

    def test_rule_name_defined(self) -> None:
        assert RULE_NORMALIZE_DOC_STRUCTURE == "normalize_doc_structure"

    def test_whitespace_collapsed(self) -> None:
        expected = {"body": "Hello   World"}
        actual = {"body": "Hello World"}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_leading_trailing_stripped(self) -> None:
        normalized = _normalize_doc_structure("  hello  ")
        assert normalized == "hello"

    def test_numbers_unchanged(self) -> None:
        assert _normalize_doc_structure(42) == 42

    def test_nested_strings_normalized(self) -> None:
        obj = {"outer": {"text": "a  b"}, "list": ["  x  ", "y"]}
        result = _normalize_doc_structure(obj)
        assert result["outer"]["text"] == "a b"
        assert result["list"][0] == "x"


class TestSemanticRuleNormalizeBodyTruncation:
    """RULE_NORMALIZE_BODY_TRUNCATION: compare only first 500 chars of body fields."""

    def test_rule_name_defined(self) -> None:
        assert RULE_NORMALIZE_BODY_TRUNCATION == "normalize_body_truncation"

    def test_body_truncated_to_500(self) -> None:
        long_body = "x" * 1000
        result = _apply_body_truncation({"body": long_body})
        assert len(result["body"]) == 500

    def test_short_body_unchanged(self) -> None:
        result = _apply_body_truncation({"body": "short"})
        assert result["body"] == "short"

    def test_non_body_field_not_truncated(self) -> None:
        result = _apply_body_truncation({"title": "x" * 1000})
        assert len(result["title"]) == 1000

    def test_long_bodies_compare_equal_when_content_matches(self) -> None:
        long_body = "a" * 600
        expected = {"body": long_body[:500]}
        actual = {"body": long_body}
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff


class TestSemanticComparatorIntegration:
    """Integration: semantic comparator for realistic op output shapes."""

    def test_slides_get_output(self) -> None:
        expected = {
            "presentation_id": "pres001",
            "title": "My Presentation",
            "revision_id": "rev-golden",
            "url": "https://docs.google.com/presentation/d/pres001/edit",
            "slide_count": 2,
            "slides": [
                {"object_id": "golden_id", "element_count": 2, "layout_object_id": "lo1"},
                {"object_id": "golden_id2", "element_count": 0, "layout_object_id": "lo2"},
            ],
        }
        actual = {
            "presentation_id": "pres001",
            "title": "My Presentation",
            "revision_id": "rev-live-different",
            "url": "https://docs.google.com/presentation/d/pres001/edit",
            "slide_count": 2,
            "slides": [
                {"object_id": "live_id_a", "element_count": 2, "layout_object_id": "lo_live1"},
                {"object_id": "live_id_b", "element_count": 0, "layout_object_id": "lo_live2"},
            ],
        }
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_forms_get_output(self) -> None:
        expected = {
            "title": "Survey",
            "description": "Please fill out",
            "item_count": 1,
            "items": [{"title": "Q1", "item_type": "short_text", "required": False}],
        }
        actual = {
            "title": "Survey",
            "description": "Please fill out",
            "item_count": 1,
            "items": [{"title": "Q1", "item_type": "short_text", "required": False}],
        }
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_gmail_get_output_body_truncation_compatible(self) -> None:
        expected = {
            "id": "msg001",
            "thread_id": "thread001",
            "snippet": "Hello",
            "subject": "Test",
            "from_": "sender@example.com",
            "date": "Mon, 15 Jan 2024",
            "body": "Hello Gmail test body content.",
            "label_ids": ["INBOX"],
        }
        actual = dict(expected)
        result = compare("semantic", expected, actual)
        assert result.match is True, result.diff

    def test_content_mismatch_still_fails(self) -> None:
        expected = {"title": "Presentation A", "slide_count": 2}
        actual = {"title": "Presentation B", "slide_count": 2}
        result = compare("semantic", expected, actual)
        assert result.match is False


class TestSandboxE2EComparator:
    """sandbox-e2e comparator: same semantic normalization as semantic."""

    def test_matches_with_nondeterministic_fields(self) -> None:
        expected = {"title": "Resource", "count": 3}
        actual = {
            "title": "Resource",
            "count": 3,
            "createTime": "2025-06-15T00:00:00Z",
            "revisionId": "rev-live",
        }
        result = compare("sandbox-e2e", expected, actual)
        assert result.match is True, result.diff

    def test_comparator_name_in_result(self) -> None:
        result = compare("sandbox-e2e", {"a": 1}, {"a": 1})
        assert result.comparator == "sandbox-e2e"

    def test_content_mismatch_fails(self) -> None:
        result = compare("sandbox-e2e", {"title": "A"}, {"title": "B"})
        assert result.match is False


class TestApplyStripFieldsDirect:
    def test_nested_strip(self) -> None:
        obj = {
            "slides": [
                {"objectId": "x", "element_count": 2},
                {"objectId": "y", "element_count": 0},
            ]
        }
        result = _apply_strip_fields(obj)
        for slide in result["slides"]:
            assert "objectId" not in slide
        assert result["slides"][0]["element_count"] == 2


class TestUnknownComparator:
    def test_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown comparator"):
            compare("no-such-comparator", {}, {})
