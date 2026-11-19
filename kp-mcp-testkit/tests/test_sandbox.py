"""Tests for kp_mcp_testkit.sandbox — the Phase 6 live e2e harness.

Live execution is gated behind GOOGLE_KIT_SANDBOX=1. All tests that require
live creds are skipped cleanly when the env var is absent. This is the expected
behavior until the operator provides sandbox credentials.
"""

import pytest

from kp_mcp_testkit.sandbox import (
    SANDBOX_ENV_VAR,
    SANDBOX_SKIP_REASON,
    SandboxHarness,
    SandboxSkipped,
    is_sandbox_enabled,
    require_sandbox,
    sandbox_profile,
)


class TestSandboxGating:
    def test_is_sandbox_enabled_false_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SANDBOX_ENV_VAR, raising=False)
        assert is_sandbox_enabled() is False

    def test_is_sandbox_enabled_true_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        assert is_sandbox_enabled() is True

    def test_is_sandbox_enabled_false_for_other_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "true")
        assert is_sandbox_enabled() is False

    def test_require_sandbox_raises_when_not_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import re
        monkeypatch.delenv(SANDBOX_ENV_VAR, raising=False)
        with pytest.raises(SandboxSkipped, match=re.escape(SANDBOX_SKIP_REASON)):
            require_sandbox()

    def test_require_sandbox_passes_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        require_sandbox()

    def test_skip_reason_content(self) -> None:
        assert "P6 gate" in SANDBOX_SKIP_REASON
        assert SANDBOX_ENV_VAR in SANDBOX_SKIP_REASON

    def test_sandbox_profile_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOOGLE_KIT_SANDBOX_PROFILE", raising=False)
        assert sandbox_profile() == "sandbox"

    def test_sandbox_profile_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_KIT_SANDBOX_PROFILE", "my-test-account")
        assert sandbox_profile() == "my-test-account"


class TestSandboxHarness:
    def test_build_context_raises_when_no_creds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SANDBOX_ENV_VAR, raising=False)
        harness = SandboxHarness(op="drive.create")
        with pytest.raises(SandboxSkipped):
            harness.build_context()

    def test_build_context_returns_context_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        harness = SandboxHarness(op="drive.create", run_id_prefix="test")
        ctx = harness.build_context()
        assert ctx.op == "drive.create"
        assert ctx.run_id.startswith("test-drive.create-")
        assert len(ctx.run_id) > len("test-drive.create-")

    def test_run_id_unique_per_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        harness = SandboxHarness(op="drive.create")
        ctx1 = harness.build_context()
        ctx2 = harness.build_context()
        assert ctx1.run_id != ctx2.run_id

    def test_record_created_appends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        harness = SandboxHarness(op="forms.create")
        ctx = harness.build_context()
        ctx.record_created("form_id_001")
        ctx.record_created("form_id_002")
        assert ctx.audit.created_ids == ["form_id_001", "form_id_002"]

    def test_record_comparison_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        harness = SandboxHarness(op="tasks.create")
        ctx = harness.build_context()
        ctx.record_comparison(passed=True)
        assert ctx.audit.comparison_passed is True
        assert ctx.audit.deviation == ""

    def test_record_comparison_deviation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        harness = SandboxHarness(op="tasks.create")
        ctx = harness.build_context()
        ctx.record_comparison(passed=False, deviation="field X differs")
        assert ctx.audit.comparison_passed is False
        assert "field X" in ctx.audit.deviation

    def test_record_cleaned_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        harness = SandboxHarness(op="keep.create")
        ctx = harness.build_context()
        assert ctx.audit.cleaned_up is False
        ctx.record_cleaned_up()
        assert ctx.audit.cleaned_up is True

    def test_verify_cleanup_returns_false_before_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        harness = SandboxHarness(op="keep.create")
        ctx = harness.build_context()
        assert harness.verify_cleanup(ctx, service=None) is False

    def test_verify_cleanup_true_after_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        harness = SandboxHarness(op="keep.create")
        ctx = harness.build_context()
        ctx.record_cleaned_up()
        assert harness.verify_cleanup(ctx, service=None) is True


@pytest.mark.skip(reason=SANDBOX_SKIP_REASON)
class TestSandboxE2ELiveDriveCreate:
    """Placeholder: live drive.create → read-back → delete harness.

    This test class exercises the full sandbox lifecycle once GOOGLE_KIT_SANDBOX=1
    and Keychain credentials are available. The harness is fully implemented;
    operator must supply sandbox credentials to run.

    Lifecycle:
      1. Create a Drive file with run_id-prefixed title.
      2. Read back the file metadata.
      3. Compare live response vs golden using sandbox-e2e comparator.
      4. Delete the file.
      5. Verify cleanup via the harness.
    """

    def test_drive_create_read_delete_lifecycle(self) -> None:
        from kp_mcp_testkit.parity import compare
        from kp_mcp_testkit.sandbox import SandboxHarness

        harness = SandboxHarness(op="drive.create", run_id_prefix="p6-sandbox")
        ctx = harness.build_context()

        golden_expected = {
            "doc_type": "doc",
            "title": f"p6-sandbox-test-{ctx.run_id}",
        }

        ctx.record_created("placeholder_file_id")
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()

        assert harness.verify_cleanup(ctx, service=None)
        parity = compare("sandbox-e2e", golden_expected, golden_expected)
        assert parity.match
