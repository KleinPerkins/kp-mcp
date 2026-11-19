"""Tests for google_kit.core.redaction."""
import pytest

from google_kit.core.redaction import _DEFAULT_PII_FIELDS, redact_dict, redact_string


class TestRedactString:
    def test_email_redacted(self) -> None:
        result = redact_string("Send to alice@example.com please")
        assert "alice@example.com" not in result
        assert "[REDACTED]" in result

    def test_bearer_token_redacted(self) -> None:
        result = redact_string("Authorization: Bearer abc123xyz456789")
        assert "abc123xyz456789" not in result
        assert "[REDACTED]" in result

    def test_credential_kv_redacted(self) -> None:
        result = redact_string("access_token=mysecrettoken12345")
        assert "mysecrettoken12345" not in result

    def test_plain_text_unchanged(self) -> None:
        text = "hello world no secrets here"
        assert redact_string(text) == text

    def test_multiple_emails_all_redacted(self) -> None:
        text = "from alice@x.com to bob@y.com"
        result = redact_string(text)
        assert "alice@x.com" not in result
        assert "bob@y.com" not in result


class TestRedactDict:
    def test_pii_field_value_replaced(self) -> None:
        d = {"title": "My Secret Document", "count": 5}
        result = redact_dict(d)
        assert result["title"] == "[REDACTED]"
        assert result["count"] == 5

    def test_email_in_string_value_redacted(self) -> None:
        d = {"message": "Sent to alice@example.com", "op": "gmail.send"}
        result = redact_dict(d)
        assert "alice@example.com" not in result["message"]
        assert result["op"] == "gmail.send"

    def test_nested_dict_redacted(self) -> None:
        d = {"outer": {"title": "Secret", "safe": "ok"}}
        result = redact_dict(d)
        assert result["outer"]["title"] == "[REDACTED]"
        assert result["outer"]["safe"] == "ok"

    def test_list_of_emails_redacted(self) -> None:
        d = {"recipients": ["alice@example.com", "bob@y.com"]}
        result = redact_dict(d)
        for item in result["recipients"]:
            assert "@" not in item

    def test_non_string_values_pass_through(self) -> None:
        d = {"count": 42, "flag": True, "pi": 3.14}
        result = redact_dict(d)
        assert result == d

    def test_does_not_mutate_input(self) -> None:
        original = {"title": "Secret", "val": "keep"}
        copy = dict(original)
        redact_dict(original)
        assert original == copy

    def test_depth_limit(self) -> None:
        deep: dict = {}
        cur = deep
        for _ in range(15):
            cur["child"] = {}
            cur = cur["child"]
        cur["title"] = "secret"
        result = redact_dict(deep)
        assert result is not deep

    def test_pii_fields_case_insensitive_key_match(self) -> None:
        d = {"Title": "My Doc"}
        result = redact_dict(d)
        assert result["Title"] == "[REDACTED]"

    def test_bearer_in_nested_string(self) -> None:
        d = {"auth": {"header": "Bearer supersecrettoken123456"}}
        result = redact_dict(d)
        assert "supersecrettoken123456" not in str(result)


class TestRedactionAuditPath:
    """Verify the full audit logging path emits no PII or secrets.

    Exercises representative ops through the core observability + audit pipeline,
    capturing stderr log output and audit JSONL content, asserting no emails,
    tokens, doc-titles, or attendee data leak through.
    """

    _SENSITIVE_TOKENS = [
        "alice@example.com",
        "bob@corp.org",
        "supersecrettoken123456",
        "Bearer abc123xyz",
        "My Secret Document Title",
        "confidential_attendee@domain.com",
    ]

    def test_structured_log_redacts_email_in_extra(self, tmp_path: "pytest.Path") -> None:
        import io
        import sys
        from google_kit.core.observability import StructuredLogger

        capture = io.StringIO()
        logger = StructuredLogger(surface="test", profile="default")

        original_stderr = sys.stderr
        sys.stderr = capture
        try:
            logger.log_op(
                "gmail.get",
                outcome="ok",
                extra={"from": "alice@example.com", "subject": "Secret title"},
            )
        finally:
            sys.stderr = original_stderr

        output = capture.getvalue()
        assert "alice@example.com" not in output
        assert "Secret title" not in output

    def test_audit_jsonl_redacts_pii_fields(self, tmp_path: "pytest.Path") -> None:
        from google_kit.core.audit import write_audit, read_audit

        audit_file = tmp_path / "test_audit.jsonl"
        write_audit(
            actor="test-profile",
            op="gmail.send",
            normalized_request={
                "to": "alice@example.com",
                "subject": "Top Secret Memo",
                "body": "confidential content",
            },
            target_ids=["msg_001"],
            result="ok",
            audit_file=audit_file,
        )

        records = read_audit(audit_file=audit_file)
        assert len(records) == 1
        req = records[0]["normalized_request"]

        assert "alice@example.com" not in str(req)
        assert "Top Secret Memo" not in str(req)
        assert "confidential content" not in str(req)

    def test_observe_op_log_no_secrets(self, tmp_path: "pytest.Path") -> None:
        import io
        import sys
        from google_kit.core.observability import observe_op

        capture = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = capture
        try:
            with observe_op(
                "drive.fetch",
                surface="cli",
                profile="default",
            ):
                pass
        finally:
            sys.stderr = original_stderr

        output = capture.getvalue()
        for token in self._SENSITIVE_TOKENS:
            assert token not in output, f"Sensitive token leaked into log: {token!r}"

    def test_redact_dict_covers_all_pii_field_names(self) -> None:
        pii_fields = list(_DEFAULT_PII_FIELDS)
        for field_name in pii_fields:
            d = {field_name: "sensitive_value_here_xyz123"}
            result = redact_dict(d)
            assert result[field_name] == "[REDACTED]", (
                f"PII field {field_name!r} not redacted"
            )

    def test_metric_attributes_no_pii(self) -> None:
        from google_kit.core.observability import get_metrics

        metrics = get_metrics()
        metrics.reset()
        metrics.record_call("gmail.list")
        metrics.record_error("gmail.list", "Auth")

        snapshot = metrics.snapshot()
        snapshot_str = str(snapshot)
        for token in self._SENSITIVE_TOKENS:
            assert token not in snapshot_str, f"PII in metrics snapshot: {token!r}"

    def test_audit_actor_field_not_secret(self, tmp_path: "pytest.Path") -> None:
        from google_kit.core.audit import write_audit, read_audit

        audit_file = tmp_path / "actor_test.jsonl"
        write_audit(
            actor="default",
            op="tasks.create",
            normalized_request={"title": "My Task", "due": "2025-01-01"},
            target_ids=["task_abc"],
            result="ok",
            audit_file=audit_file,
        )
        records = read_audit(audit_file=audit_file)
        assert records[0]["actor"] == "default"
        assert "My Task" not in str(records[0]["normalized_request"])

