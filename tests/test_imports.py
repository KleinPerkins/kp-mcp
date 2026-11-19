"""Smoke: workspace packages import cleanly at their coordinated versions."""

import kp_mcp_bootstrap
import kp_mcp_testkit
import google_kit
import snow_kit
import widget_kit


def test_import_bootstrap() -> None:
    assert kp_mcp_bootstrap.__version__ == "0.4.0"


def test_import_testkit() -> None:
    assert kp_mcp_testkit.__version__ == "0.1.0"


def test_import_google_kit() -> None:
    assert google_kit.__version__ == "0.3.0"


def test_import_snow_kit() -> None:
    assert snow_kit.__version__ == "0.4.0"


def test_import_widget_kit() -> None:
    assert widget_kit.__version__ == "0.3.0"
