"""google-kit conftest: convert SandboxSkipped to a clean pytest skip."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path, monkeypatch):
    """Keep filesystem side effects hermetic per test.

    Points GOOGLE_KIT_CONFIG_DIR at a per-test tmp dir (backing per-profile
    write-authorization grants and the OAuth refresh file-lock) so no test reads
    the developer's real grants and authz starts empty (default-deny) unless a
    test explicitly grants. Also redirects the audit log: ``_DEFAULT_AUDIT_PATH``
    is resolved at import time (before any env override), so write ops that audit
    via the default path would otherwise append to the developer's real
    ``audit.jsonl`` and hard-fail on a read-only FS — pin it to the tmp dir too.
    A test may still override either itself if needed.
    """
    from google_kit.core import audit as _audit_mod

    monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", str(tmp_path / "gk-config"))
    monkeypatch.delenv("CHAOS_LABS_ROOT", raising=False)
    monkeypatch.setattr(_audit_mod, "_DEFAULT_AUDIT_PATH", tmp_path / "audit.jsonl")


@pytest.fixture(autouse=True)
def _reset_audit_actor():
    """Isolate the audit ``actor`` contextvar per test.

    ``build_service_for_op`` sets the actor contextvar (so audited mutations are
    attributed to the operating profile) and intentionally does not reset it
    — in production each op sets it before running. In the test process the
    contextvar persists across tests on the same thread, so reset it after each
    test to keep order-independence.
    """
    from google_kit.core import audit as _audit

    token = _audit.set_actor(_audit.get_actor())
    try:
        yield
    finally:
        _audit.reset_actor(token)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item):
    """Convert SandboxSkipped to a clean pytest skip."""
    try:
        return (yield)
    except Exception as exc:
        try:
            from kp_mcp_testkit.sandbox import SANDBOX_SKIP_REASON, SandboxSkipped
        except ImportError:
            raise
        if isinstance(exc, SandboxSkipped):
            pytest.skip(str(exc) or SANDBOX_SKIP_REASON)
        raise
