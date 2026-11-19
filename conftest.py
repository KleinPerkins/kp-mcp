"""Root conftest: workspace-level pytest configuration."""

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item) -> None:
    """Convert SandboxSkipped to a clean pytest skip."""
    outcome = yield
    try:
        from kp_mcp_testkit.sandbox import SANDBOX_SKIP_REASON, SandboxSkipped
    except ImportError:
        return
    if outcome.excinfo is not None and isinstance(outcome.excinfo[1], SandboxSkipped):
        pytest.skip(str(outcome.excinfo[1]) or SANDBOX_SKIP_REASON)
