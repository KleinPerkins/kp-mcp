"""Tests for the Apps Script service.

Coverage:
  script_create         — mutation-request parity (projects.create body)
  script_get_content    — mock-read parity (normalized-json)
  script_update_content — mutation-request parity (projects.updateContent body)
  script_deployments    — mock-read parity (deployments.list response)
  script_versions       — mock-read parity (versions.list response)
  script_run            — mutation-request parity (scripts.run body)
  script_metrics        — mock-read parity (getMetrics response)

Parity status per op:
  script_create         — mutation-request DONE; sandbox-e2e DEFERRED
  script_get_content    — mock-read DONE; sandbox-e2e DEFERRED
  script_update_content — mutation-request DONE; sandbox-e2e DEFERRED
  script_deployments    — mock-read DONE; sandbox-e2e DEFERRED
  script_versions       — mock-read DONE; sandbox-e2e DEFERRED
  script_run            — mutation-request DONE; sandbox-e2e DEFERRED
                          (escape-hatch only; requires API-executable deployment)
  script_metrics        — mock-read DONE; sandbox-e2e DEFERRED

Test-local MockAppsScriptService models the Apps Script API's nested resource
chains (projects(), projects().deployments(), projects().versions(), scripts())
that MockGoogleService's flat model does not cover.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.parity import compare

FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "apps_script"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# ─── Test-local mock infrastructure ──────────────────────────────────────────


@dataclass
class _ScriptRecord:
    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> dict[str, Any] | None:
        return self.kwargs.get("body")


class _FakeExec:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _FakeDeploymentsProxy:
    def __init__(self, responses: dict, log: list[_ScriptRecord]) -> None:
        self._responses = responses
        self._log = log

    def list(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_ScriptRecord("deployments", "list", dict(kwargs)))
        return _FakeExec(self._responses.get(("deployments", "list")))


class _FakeVersionsProxy:
    def __init__(self, responses: dict, log: list[_ScriptRecord]) -> None:
        self._responses = responses
        self._log = log

    def list(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_ScriptRecord("versions", "list", dict(kwargs)))
        return _FakeExec(self._responses.get(("versions", "list")))


class _FakeProjectsProxy:
    def __init__(self, responses: dict, log: list[_ScriptRecord]) -> None:
        self._responses = responses
        self._log = log

    def create(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_ScriptRecord("projects", "create", dict(kwargs)))
        return _FakeExec(self._responses.get(("projects", "create")))

    def getContent(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_ScriptRecord("projects", "getContent", dict(kwargs)))
        return _FakeExec(self._responses.get(("projects", "getContent")))

    def updateContent(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_ScriptRecord("projects", "updateContent", dict(kwargs)))
        return _FakeExec(self._responses.get(("projects", "updateContent")))

    def getMetrics(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_ScriptRecord("projects", "getMetrics", dict(kwargs)))
        return _FakeExec(self._responses.get(("projects", "getMetrics")))

    def deployments(self) -> _FakeDeploymentsProxy:
        return _FakeDeploymentsProxy(self._responses, self._log)

    def versions(self) -> _FakeVersionsProxy:
        return _FakeVersionsProxy(self._responses, self._log)


class _FakeScriptsProxy:
    def __init__(self, responses: dict, log: list[_ScriptRecord]) -> None:
        self._responses = responses
        self._log = log

    def run(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_ScriptRecord("scripts", "run", dict(kwargs)))
        return _FakeExec(self._responses.get(("scripts", "run")))


class MockAppsScriptService:
    """Test-local mock for the Google Apps Script API service (script v1)."""

    def __init__(self, responses: dict | None = None) -> None:
        self._responses: dict = responses or {}
        self._log: list[_ScriptRecord] = []

    def projects(self) -> _FakeProjectsProxy:
        return _FakeProjectsProxy(self._responses, self._log)

    def scripts(self) -> _FakeScriptsProxy:
        return _FakeScriptsProxy(self._responses, self._log)

    def last_request_body(self) -> dict[str, Any] | None:
        for rec in reversed(self._log):
            if rec.body is not None:
                return rec.body
        return None

    def requests_for(self, resource: str, method: str) -> list[_ScriptRecord]:
        return [r for r in self._log if r.resource == resource and r.method == method]

    def reset(self) -> None:
        self._log.clear()


# ─── Registry isolation fixture ──────────────────────────────────────────────


@pytest.fixture(autouse=True, scope="module")
def _ensure_apps_script() -> None:
    """Re-register Apps Script ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.apps_script as apps_script_mod

    if "script.create" not in {s.name for s in reg.all_specs()}:
        importlib.reload(apps_script_mod)


# ─── script.create ────────────────────────────────────────────────────────────


class TestScriptCreate:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.apps_script.core import script_create
        from google_kit.services.apps_script.models import ScriptCreateInput

        expected_body = _load("create_expected_body.json")
        canned_resp = {"scriptId": "script001", "title": "My Automation Script"}
        svc = MockAppsScriptService(responses={("projects", "create"): canned_resp})
        script_create(ScriptCreateInput(title="My Automation Script"), service=svc)

        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_parent_id_included_in_body(self) -> None:
        from google_kit.services.apps_script.core import script_create
        from google_kit.services.apps_script.models import ScriptCreateInput

        expected_body = _load("create_with_parent_expected_body.json")
        canned_resp = {"scriptId": "script002", "title": "Bound Script"}
        svc = MockAppsScriptService(responses={("projects", "create"): canned_resp})
        script_create(
            ScriptCreateInput(title="Bound Script", parent_id="doc_parent_id_001"),
            service=svc,
        )

        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_no_parent_id_not_in_body(self) -> None:
        from google_kit.services.apps_script.core import script_create
        from google_kit.services.apps_script.models import ScriptCreateInput

        canned_resp = {"scriptId": "script003", "title": "Standalone"}
        svc = MockAppsScriptService(responses={("projects", "create"): canned_resp})
        script_create(ScriptCreateInput(title="Standalone"), service=svc)

        body = svc.last_request_body()
        assert "parentId" not in (body or {})

    def test_output_envelope(self) -> None:
        from google_kit.services.apps_script.core import script_create
        from google_kit.services.apps_script.models import ScriptCreateInput

        canned_resp = {"scriptId": "script004", "title": "Output Test"}
        svc = MockAppsScriptService(responses={("projects", "create"): canned_resp})
        result = script_create(ScriptCreateInput(title="Output Test"), service=svc)

        assert result.meta.op == "script.create"
        assert result.data.script_id == "script004"
        assert result.data.title == "Output Test"


# ─── script.get_content ───────────────────────────────────────────────────────


class TestScriptGetContent:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.apps_script.core import script_get_content
        from google_kit.services.apps_script.models import ScriptGetContentInput

        mock_resp = _load("get_content_response.json")
        expected = _load("get_content_expected.json")

        svc = MockAppsScriptService(responses={("projects", "getContent"): mock_resp})
        result = script_get_content(ScriptGetContentInput(script_id="script001"), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_version_number_passed_as_kwarg(self) -> None:
        from google_kit.services.apps_script.core import script_get_content
        from google_kit.services.apps_script.models import ScriptGetContentInput

        mock_resp = {"scriptId": "script001", "files": []}
        svc = MockAppsScriptService(responses={("projects", "getContent"): mock_resp})
        script_get_content(
            ScriptGetContentInput(script_id="script001", version_number=3), service=svc
        )

        calls = svc.requests_for("projects", "getContent")
        assert calls
        assert calls[0].kwargs.get("versionNumber") == 3

    def test_no_version_number_omitted(self) -> None:
        from google_kit.services.apps_script.core import script_get_content
        from google_kit.services.apps_script.models import ScriptGetContentInput

        mock_resp = {"scriptId": "script001", "files": []}
        svc = MockAppsScriptService(responses={("projects", "getContent"): mock_resp})
        script_get_content(ScriptGetContentInput(script_id="script001"), service=svc)

        calls = svc.requests_for("projects", "getContent")
        assert "versionNumber" not in calls[0].kwargs

    def test_output_envelope(self) -> None:
        from google_kit.services.apps_script.core import script_get_content
        from google_kit.services.apps_script.models import ScriptGetContentInput

        mock_resp = {"scriptId": "s001", "files": [{"name": "Code", "type": "SERVER_JS", "source": "function f(){}"}]}
        svc = MockAppsScriptService(responses={("projects", "getContent"): mock_resp})
        result = script_get_content(ScriptGetContentInput(script_id="s001"), service=svc)

        assert result.meta.op == "script.get_content"
        assert result.data.script_id == "s001"
        assert len(result.data.files) == 1
        assert result.data.files[0].name == "Code"


# ─── script.update_content ────────────────────────────────────────────────────


class TestScriptUpdateContent:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.apps_script.core import script_update_content
        from google_kit.services.apps_script.models import ScriptFileInput, ScriptUpdateContentInput

        expected_body = _load("update_content_expected_body.json")
        canned_resp = {
            "scriptId": "script001",
            "files": [{"name": "Code", "type": "SERVER_JS", "source": "function main() { Logger.log('Updated'); }"}],
        }
        svc = MockAppsScriptService(responses={("projects", "updateContent"): canned_resp})
        script_update_content(
            ScriptUpdateContentInput(
                script_id="script001",
                files=[ScriptFileInput(name="Code", type="SERVER_JS", source="function main() { Logger.log('Updated'); }")],
            ),
            service=svc,
        )

        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_script_id_passed_as_kwarg(self) -> None:
        from google_kit.services.apps_script.core import script_update_content
        from google_kit.services.apps_script.models import ScriptFileInput, ScriptUpdateContentInput

        canned_resp = {"scriptId": "script_x", "files": []}
        svc = MockAppsScriptService(responses={("projects", "updateContent"): canned_resp})
        script_update_content(
            ScriptUpdateContentInput(
                script_id="script_x",
                files=[ScriptFileInput(name="Code", type="SERVER_JS", source="")],
            ),
            service=svc,
        )

        calls = svc.requests_for("projects", "updateContent")
        assert calls[0].kwargs.get("scriptId") == "script_x"

    def test_output_envelope(self) -> None:
        from google_kit.services.apps_script.core import script_update_content
        from google_kit.services.apps_script.models import ScriptFileInput, ScriptUpdateContentInput

        canned_resp = {
            "scriptId": "s001",
            "files": [{"name": "Code", "type": "SERVER_JS", "source": "fn()"}],
        }
        svc = MockAppsScriptService(responses={("projects", "updateContent"): canned_resp})
        result = script_update_content(
            ScriptUpdateContentInput(
                script_id="s001",
                files=[ScriptFileInput(name="Code", type="SERVER_JS", source="fn()")],
            ),
            service=svc,
        )

        assert result.meta.op == "script.update_content"
        assert result.data.script_id == "s001"
        assert len(result.data.files) == 1


# ─── script.deployments ───────────────────────────────────────────────────────


class TestScriptDeployments:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.apps_script.core import script_deployments
        from google_kit.services.apps_script.models import ScriptDeploymentsInput

        mock_resp = _load("deployments_response.json")
        expected = _load("deployments_expected.json")

        svc = MockAppsScriptService(responses={("deployments", "list"): mock_resp})
        result = script_deployments(ScriptDeploymentsInput(script_id="script001"), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_script_id_in_kwargs(self) -> None:
        from google_kit.services.apps_script.core import script_deployments
        from google_kit.services.apps_script.models import ScriptDeploymentsInput

        svc = MockAppsScriptService(responses={("deployments", "list"): {"deployments": []}})
        script_deployments(ScriptDeploymentsInput(script_id="s_abc"), service=svc)

        calls = svc.requests_for("deployments", "list")
        assert calls[0].kwargs.get("scriptId") == "s_abc"

    def test_page_size_page_token_optional(self) -> None:
        from google_kit.services.apps_script.core import script_deployments
        from google_kit.services.apps_script.models import ScriptDeploymentsInput

        svc = MockAppsScriptService(responses={("deployments", "list"): {"deployments": []}})
        script_deployments(
            ScriptDeploymentsInput(script_id="s1", page_size=5, page_token="tok_abc"),
            service=svc,
        )

        calls = svc.requests_for("deployments", "list")
        assert calls[0].kwargs.get("pageSize") == 5
        assert calls[0].kwargs.get("pageToken") == "tok_abc"

    def test_output_envelope(self) -> None:
        from google_kit.services.apps_script.core import script_deployments
        from google_kit.services.apps_script.models import ScriptDeploymentsInput

        svc = MockAppsScriptService(responses={("deployments", "list"): {"deployments": [], "nextPageToken": "nxt"}})
        result = script_deployments(ScriptDeploymentsInput(script_id="s1"), service=svc)

        assert result.meta.op == "script.deployments"
        assert result.data.deployments == []
        assert result.page is not None
        assert result.page.next_page_token == "nxt"


# ─── script.versions ──────────────────────────────────────────────────────────


class TestScriptVersions:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.apps_script.core import script_versions
        from google_kit.services.apps_script.models import ScriptVersionsInput

        mock_resp = _load("versions_response.json")
        expected = _load("versions_expected.json")

        svc = MockAppsScriptService(responses={("versions", "list"): mock_resp})
        result = script_versions(ScriptVersionsInput(script_id="script001"), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_script_id_in_kwargs(self) -> None:
        from google_kit.services.apps_script.core import script_versions
        from google_kit.services.apps_script.models import ScriptVersionsInput

        svc = MockAppsScriptService(responses={("versions", "list"): {"versions": []}})
        script_versions(ScriptVersionsInput(script_id="s_xyz"), service=svc)

        calls = svc.requests_for("versions", "list")
        assert calls[0].kwargs.get("scriptId") == "s_xyz"

    def test_pagination_kwargs(self) -> None:
        from google_kit.services.apps_script.core import script_versions
        from google_kit.services.apps_script.models import ScriptVersionsInput

        svc = MockAppsScriptService(responses={("versions", "list"): {"versions": []}})
        script_versions(
            ScriptVersionsInput(script_id="s1", page_size=10, page_token="pg_tok"),
            service=svc,
        )

        calls = svc.requests_for("versions", "list")
        assert calls[0].kwargs.get("pageSize") == 10
        assert calls[0].kwargs.get("pageToken") == "pg_tok"

    def test_output_envelope(self) -> None:
        from google_kit.services.apps_script.core import script_versions
        from google_kit.services.apps_script.models import ScriptVersionsInput

        svc = MockAppsScriptService(responses={("versions", "list"): {"versions": [], "nextPageToken": None}})
        result = script_versions(ScriptVersionsInput(script_id="s1"), service=svc)

        assert result.meta.op == "script.versions"
        assert result.data.versions == []
        assert result.page is not None
        assert result.page.next_page_token is None


# ─── script.run ───────────────────────────────────────────────────────────────


class TestScriptRun:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.apps_script.core import script_run
        from google_kit.services.apps_script.models import ScriptRunInput

        expected_body = _load("run_expected_body.json")
        canned_resp = {
            "done": True,
            "response": {"result": "ok"},
        }
        svc = MockAppsScriptService(responses={("scripts", "run"): canned_resp})
        script_run(
            ScriptRunInput(
                script_id="script001",
                function="sendReport",
                parameters=["Q4", True],
                dev_mode=False,
            ),
            service=svc,
        )

        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_minimal_body_no_optional_fields(self) -> None:
        from google_kit.services.apps_script.core import script_run
        from google_kit.services.apps_script.models import ScriptRunInput

        canned_resp = {"done": True}
        svc = MockAppsScriptService(responses={("scripts", "run"): canned_resp})
        script_run(ScriptRunInput(script_id="s1", function="myFn"), service=svc)

        body = svc.last_request_body()
        assert body == {"function": "myFn"}

    def test_script_id_as_kwarg(self) -> None:
        from google_kit.services.apps_script.core import script_run
        from google_kit.services.apps_script.models import ScriptRunInput

        canned_resp = {"done": False}
        svc = MockAppsScriptService(responses={("scripts", "run"): canned_resp})
        script_run(ScriptRunInput(script_id="s_run_001", function="fn"), service=svc)

        calls = svc.requests_for("scripts", "run")
        assert calls[0].kwargs.get("scriptId") == "s_run_001"

    def test_output_envelope_done(self) -> None:
        from google_kit.services.apps_script.core import script_run
        from google_kit.services.apps_script.models import ScriptRunInput

        canned_resp = {"done": True, "response": {"result": 42}}
        svc = MockAppsScriptService(responses={("scripts", "run"): canned_resp})
        result = script_run(ScriptRunInput(script_id="s1", function="fn"), service=svc)

        assert result.meta.op == "script.run"
        assert result.data.done is True
        assert result.data.response == {"result": 42}
        assert result.data.error is None

    def test_output_envelope_error(self) -> None:
        from google_kit.services.apps_script.core import script_run
        from google_kit.services.apps_script.models import ScriptRunInput

        canned_resp = {
            "done": True,
            "error": {"code": 3, "message": "Script error", "status": "INVALID_ARGUMENT"},
        }
        svc = MockAppsScriptService(responses={("scripts", "run"): canned_resp})
        result = script_run(ScriptRunInput(script_id="s1", function="fn"), service=svc)

        assert result.data.done is True
        assert result.data.error is not None
        assert result.data.error["code"] == 3


# ─── script.metrics ───────────────────────────────────────────────────────────


class TestScriptMetrics:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.apps_script.core import script_metrics
        from google_kit.services.apps_script.models import ScriptMetricsInput

        mock_resp = _load("metrics_response.json")
        expected = _load("metrics_expected.json")

        svc = MockAppsScriptService(responses={("projects", "getMetrics"): mock_resp})
        result = script_metrics(
            ScriptMetricsInput(script_id="script001", metrics_granularity="WEEKLY"),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_granularity_in_kwargs(self) -> None:
        from google_kit.services.apps_script.core import script_metrics
        from google_kit.services.apps_script.models import ScriptMetricsInput

        mock_resp = {"activeUsers": [], "totalExecutions": [], "failedExecutions": []}
        svc = MockAppsScriptService(responses={("projects", "getMetrics"): mock_resp})
        script_metrics(
            ScriptMetricsInput(script_id="s1", metrics_granularity="DAILY"),
            service=svc,
        )

        calls = svc.requests_for("projects", "getMetrics")
        assert calls[0].kwargs.get("metricsGranularity") == "DAILY"

    def test_deployment_filter_in_kwargs(self) -> None:
        from google_kit.services.apps_script.core import script_metrics
        from google_kit.services.apps_script.models import ScriptMetricsInput

        mock_resp = {"activeUsers": [], "totalExecutions": [], "failedExecutions": []}
        svc = MockAppsScriptService(responses={("projects", "getMetrics"): mock_resp})
        script_metrics(
            ScriptMetricsInput(
                script_id="s1",
                metrics_granularity="WEEKLY",
                metrics_filter_deployment_id="deploy001",
            ),
            service=svc,
        )

        calls = svc.requests_for("projects", "getMetrics")
        assert calls[0].kwargs.get("metricsFilter.deploymentId") == "deploy001"

    def test_no_deployment_filter_omitted(self) -> None:
        from google_kit.services.apps_script.core import script_metrics
        from google_kit.services.apps_script.models import ScriptMetricsInput

        mock_resp = {"activeUsers": [], "totalExecutions": [], "failedExecutions": []}
        svc = MockAppsScriptService(responses={("projects", "getMetrics"): mock_resp})
        script_metrics(
            ScriptMetricsInput(script_id="s1", metrics_granularity="WEEKLY"),
            service=svc,
        )

        calls = svc.requests_for("projects", "getMetrics")
        assert "metricsFilter.deploymentId" not in calls[0].kwargs

    def test_output_envelope(self) -> None:
        from google_kit.services.apps_script.core import script_metrics
        from google_kit.services.apps_script.models import ScriptMetricsInput

        mock_resp = {
            "activeUsers": [{"value": "5"}],
            "totalExecutions": [{"value": "100"}],
            "failedExecutions": [],
        }
        svc = MockAppsScriptService(responses={("projects", "getMetrics"): mock_resp})
        result = script_metrics(
            ScriptMetricsInput(script_id="s1", metrics_granularity="WEEKLY"),
            service=svc,
        )

        assert result.meta.op == "script.metrics"
        assert len(result.data.active_users) == 1
        assert len(result.data.total_executions) == 1
        assert result.data.failed_executions == []
