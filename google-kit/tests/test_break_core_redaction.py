"""Adversarial edge-case tests for google_kit.core.redaction.

Each test encodes a concrete leak/crash that motivated a fix in redaction.py.
"""
from __future__ import annotations

from google_kit.core.redaction import redact_dict, redact_string


class TestNestedListLeak:
    """SEEDED: _redact_list recursed into dict/str items but NOT nested lists,
    leaking PII/secrets buried in list-within-list structures."""

    def test_email_in_list_within_list_redacted(self) -> None:
        d = {"x": [["alice@example.com"]]}
        result = redact_dict(d)
        assert "alice@example.com" not in str(result)

    def test_pii_dict_in_list_within_list_redacted(self) -> None:
        d = {"y": [[{"title": "Secret Doc"}]]}
        result = redact_dict(d)
        assert result["y"][0][0]["title"] == "[REDACTED]"

    def test_deeply_nested_lists_redacted(self) -> None:
        d = {"z": [[[["bob@corp.org"]]]]}
        result = redact_dict(d)
        assert "bob@corp.org" not in str(result)

    def test_bearer_token_in_nested_list(self) -> None:
        d = {"hdrs": [["Authorization: Bearer supersecrettoken123456"]]}
        result = redact_dict(d)
        assert "supersecrettoken123456" not in str(result)

    def test_nested_list_does_not_recurse_forever(self) -> None:
        # Self-referential list must hit the depth cap, not recurse to RecursionError.
        loop: list = []
        loop.append(loop)
        d = {"loop": loop}
        result = redact_dict(d)
        assert "[truncated]" in str(result)


class TestClosingQuotePreserved:
    """The credential substitution dropped the closing quote captured by \\2."""

    def test_double_quoted_credential_keeps_closing_quote(self) -> None:
        result = redact_string('access_token="mysecrettoken12345"')
        assert "mysecrettoken12345" not in result
        assert result == 'access_token="[REDACTED]"'

    def test_single_quoted_credential_keeps_closing_quote(self) -> None:
        result = redact_string("api_key='abcd1234efgh5678'")
        assert "abcd1234efgh5678" not in result
        assert result == "api_key='[REDACTED]'"

    def test_unquoted_credential_unchanged_shape(self) -> None:
        result = redact_string("password=plaintextpw123")
        assert "plaintextpw123" not in result
        assert result == "password=[REDACTED]"


class TestNonStringKeys:
    """redact_dict crashed on non-str keys via k.lower()."""

    def test_int_keys_do_not_crash(self) -> None:
        result = redact_dict({1: "x", 2: "alice@example.com"})
        assert "alice@example.com" not in str(result)
        assert result[1] == "x"

    def test_mixed_key_types(self) -> None:
        result = redact_dict({1: {"title": "secret"}, "title": "also secret"})
        assert result[1]["title"] == "[REDACTED]"
        assert result["title"] == "[REDACTED]"

    def test_none_and_float_keys(self) -> None:
        result = redact_dict({None: "v", 3.5: {"body": "x"}})
        assert result[3.5]["body"] == "[REDACTED]"
