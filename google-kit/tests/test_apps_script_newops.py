"""Tests for Apps Script deployment and version operations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


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
    def __init__(self, responses: dict[tuple[str, str], Any], log: list[_ScriptRecord]) -> None:
        self._responses = responses
        self._log = log

    def _exec(self, method: str, kwargs: dict[str, Any]) -> _FakeExec:
        key = ("deployments", method)
        self._log.append(_ScriptRecord("deployments", method, dict(kwargs)))
        return _FakeExec(self._responses[key])

    def create(self, **kwargs: Any) -> _FakeExec:
        return self._exec("create", kwargs)

    def get(self, **kwargs: Any) -> _FakeExec:
        return self._exec("get", kwargs)

    def update(self, **kwargs: Any) -> _FakeExec:
        return self._exec("update", kwargs)

    def delete(self, **kwargs: Any) -> _FakeExec:
        return self._exec("delete", kwargs)


class _FakeVersionsProxy:
    def __init__(self, responses: dict[tuple[str, str], Any], log: list[_ScriptRecord]) -> None:
        self._responses = responses
        self._log = log

    def _exec(self, method: str, kwargs: dict[str, Any]) -> _FakeExec:
        key = ("versions", method)
        self._log.append(_ScriptRecord("versions", method, dict(kwargs)))
        return _FakeExec(self._responses[key])

    def create(self, **kwargs: Any) -> _FakeExec:
        return self._exec("create", kwargs)

    def get(self, **kwargs: Any) -> _FakeExec:
        return self._exec("get", kwargs)


class _FakeProjectsProxy:
    def __init__(self, responses: dict[tuple[str, str], Any], log: list[_ScriptRecord]) -> None:
        self._responses = responses
        self._log = log

    def deployments(self) -> _FakeDeploymentsProxy:
        return _FakeDeploymentsProxy(self._responses, self._log)

    def versions(self) -> _FakeVersionsProxy:
        return _FakeVersionsProxy(self._responses, self._log)


class _FakeAppsScriptService:
    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self._responses = responses or {}
        self._log: list[_ScriptRecord] = []

    def projects(self) -> _FakeProjectsProxy:
        return _FakeProjectsProxy(self._responses, self._log)

    def requests_for(self, resource: str, method: str) -> list[_ScriptRecord]:
        return [r for r in self._log if r.resource == resource and r.method == method]


class TestScriptDeploymentOps:
    def test_create_deployment_happy_path(self) -> None:
        from google_kit.services.apps_script.core import script_create_deployment
        from google_kit.services.apps_script.models import ScriptCreateDeploymentInput

        deployment = {
            "deploymentId": "dep_1",
            "deploymentConfig": {
                "versionNumber": 3,
                "description": "Production deployment",
                "manifestFileName": "appsscript",
            },
            "updateTime": "2026-01-01T00:00:00Z",
        }
        svc = _FakeAppsScriptService({("deployments", "create"): deployment})

        result = script_create_deployment(
            ScriptCreateDeploymentInput(
                script_id="script_1",
                version_number=3,
                description="Production deployment",
                manifest_file_name="appsscript",
            ),
            service=svc,
        )

        calls = svc.requests_for("deployments", "create")
        assert calls[0].kwargs["scriptId"] == "script_1"
        assert calls[0].body == {
            "deploymentConfig": {
                "versionNumber": 3,
                "description": "Production deployment",
                "manifestFileName": "appsscript",
            }
        }
        assert result.meta.op == "script.create_deployment"
        assert result.data.deployment == deployment

    def test_get_deployment_happy_path(self) -> None:
        from google_kit.services.apps_script.core import script_get_deployment
        from google_kit.services.apps_script.models import ScriptGetDeploymentInput

        deployment = {"deploymentId": "dep_1", "deploymentConfig": {"versionNumber": 3}}
        svc = _FakeAppsScriptService({("deployments", "get"): deployment})

        result = script_get_deployment(
            ScriptGetDeploymentInput(script_id="script_1", deployment_id="dep_1"),
            service=svc,
        )

        calls = svc.requests_for("deployments", "get")
        assert calls[0].kwargs == {"scriptId": "script_1", "deploymentId": "dep_1"}
        assert result.meta.op == "script.get_deployment"
        assert result.data.deployment == deployment

    def test_update_deployment_happy_path(self) -> None:
        from google_kit.services.apps_script.core import script_update_deployment
        from google_kit.services.apps_script.models import ScriptUpdateDeploymentInput

        deployment = {"deploymentId": "dep_1", "deploymentConfig": {"versionNumber": 4}}
        svc = _FakeAppsScriptService({("deployments", "update"): deployment})

        result = script_update_deployment(
            ScriptUpdateDeploymentInput(
                script_id="script_1",
                deployment_id="dep_1",
                version_number=4,
                description="Updated production deployment",
            ),
            service=svc,
        )

        calls = svc.requests_for("deployments", "update")
        assert calls[0].kwargs["scriptId"] == "script_1"
        assert calls[0].kwargs["deploymentId"] == "dep_1"
        assert calls[0].body == {
            "deploymentConfig": {
                "versionNumber": 4,
                "description": "Updated production deployment",
            }
        }
        assert result.meta.op == "script.update_deployment"
        assert result.data.deployment == deployment

    def test_delete_deployment_happy_path(self) -> None:
        from google_kit.services.apps_script.core import script_delete_deployment
        from google_kit.services.apps_script.models import ScriptDeleteDeploymentInput

        svc = _FakeAppsScriptService({("deployments", "delete"): {}})

        result = script_delete_deployment(
            ScriptDeleteDeploymentInput(script_id="script_1", deployment_id="dep_1"),
            service=svc,
        )

        calls = svc.requests_for("deployments", "delete")
        assert calls[0].kwargs == {"scriptId": "script_1", "deploymentId": "dep_1"}
        assert result.meta.op == "script.delete_deployment"
        assert result.data.deleted is True
        assert result.data.response == {}


class TestScriptVersionOps:
    def test_create_version_happy_path(self) -> None:
        from google_kit.services.apps_script.core import script_create_version
        from google_kit.services.apps_script.models import ScriptCreateVersionInput

        version = {
            "scriptId": "script_1",
            "versionNumber": 5,
            "description": "Release v5",
        }
        svc = _FakeAppsScriptService({("versions", "create"): version})

        result = script_create_version(
            ScriptCreateVersionInput(script_id="script_1", description="Release v5"),
            service=svc,
        )

        calls = svc.requests_for("versions", "create")
        assert calls[0].kwargs == {
            "scriptId": "script_1",
            "body": {"description": "Release v5"},
        }
        assert result.meta.op == "script.create_version"
        assert result.data.version == version

    def test_get_version_happy_path(self) -> None:
        from google_kit.services.apps_script.core import script_get_version
        from google_kit.services.apps_script.models import ScriptGetVersionInput

        version = {"scriptId": "script_1", "versionNumber": 5}
        svc = _FakeAppsScriptService({("versions", "get"): version})

        result = script_get_version(
            ScriptGetVersionInput(script_id="script_1", version_number=5),
            service=svc,
        )

        calls = svc.requests_for("versions", "get")
        assert calls[0].kwargs == {"scriptId": "script_1", "versionNumber": 5}
        assert result.meta.op == "script.get_version"
        assert result.data.version == version


def test_new_ops_handle_sparse_responses() -> None:
    from google_kit.services.apps_script.core import (
        script_create_deployment,
        script_create_version,
        script_delete_deployment,
        script_get_deployment,
        script_get_version,
        script_update_deployment,
    )
    from google_kit.services.apps_script.models import (
        ScriptCreateDeploymentInput,
        ScriptCreateVersionInput,
        ScriptDeleteDeploymentInput,
        ScriptGetDeploymentInput,
        ScriptGetVersionInput,
        ScriptUpdateDeploymentInput,
    )

    svc = _FakeAppsScriptService({
        ("deployments", "create"): {},
        ("deployments", "get"): {},
        ("deployments", "update"): {},
        ("deployments", "delete"): None,
        ("versions", "create"): {},
        ("versions", "get"): {},
    })

    assert script_create_deployment(
        ScriptCreateDeploymentInput(script_id="script_1"), service=svc
    ).data.deployment == {}
    assert script_get_deployment(
        ScriptGetDeploymentInput(script_id="script_1", deployment_id="dep_1"), service=svc
    ).data.deployment == {}
    assert script_update_deployment(
        ScriptUpdateDeploymentInput(script_id="script_1", deployment_id="dep_1"), service=svc
    ).data.deployment == {}
    assert script_delete_deployment(
        ScriptDeleteDeploymentInput(script_id="script_1", deployment_id="dep_1"), service=svc
    ).data.deleted is True
    assert script_create_version(
        ScriptCreateVersionInput(script_id="script_1"), service=svc
    ).data.version == {}
    assert script_get_version(
        ScriptGetVersionInput(script_id="script_1", version_number=1), service=svc
    ).data.version == {}


def test_new_ops_propagate_missing_fake_response_key() -> None:
    from google_kit.services.apps_script.core import script_get_deployment
    from google_kit.services.apps_script.models import ScriptGetDeploymentInput

    svc = _FakeAppsScriptService()

    with pytest.raises(KeyError) as excinfo:
        script_get_deployment(
            ScriptGetDeploymentInput(script_id="script_1", deployment_id="dep_1"),
            service=svc,
        )

    assert excinfo.value.args == (("deployments", "get"),)
