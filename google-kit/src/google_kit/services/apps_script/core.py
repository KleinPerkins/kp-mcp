"""Core functions for the Apps Script service (13 ops).

Parity coverage per op:

  script_create         — mutation-request DONE; sandbox-e2e DEFERRED
  script_get_content    — mock-read DONE; sandbox-e2e DEFERRED
  script_update_content — mutation-request DONE; sandbox-e2e DEFERRED
  script_deployments    — mock-read DONE; sandbox-e2e DEFERRED
  script_create_deployment — mutation-request DONE; sandbox-e2e DEFERRED
  script_get_deployment    — mock-read DONE; sandbox-e2e DEFERRED
  script_update_deployment — mutation-request DONE; sandbox-e2e DEFERRED
  script_delete_deployment — mutation-request DONE; sandbox-e2e DEFERRED
  script_versions       — mock-read DONE; sandbox-e2e DEFERRED
  script_create_version — mutation-request DONE; sandbox-e2e DEFERRED
  script_get_version    — mock-read DONE; sandbox-e2e DEFERRED
  script_run            — mutation-request DONE; sandbox-e2e DEFERRED
                          (escape-hatch only; requires script deployed as API-executable
                          in the same Cloud project as the OAuth client)
  script_metrics        — mock-read DONE; sandbox-e2e DEFERRED
"""
from __future__ import annotations

from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope, PageInfo

from .models import (
    ScriptCreateData,
    ScriptCreateInput,
    ScriptCreateOutput,
    ScriptFileItem,
    ScriptGetContentData,
    ScriptGetContentInput,
    ScriptGetContentOutput,
    ScriptUpdateContentData,
    ScriptUpdateContentInput,
    ScriptUpdateContentOutput,
    ScriptDeploymentsData,
    ScriptDeploymentsInput,
    ScriptDeploymentsOutput,
    ScriptCreateDeploymentData,
    ScriptCreateDeploymentInput,
    ScriptCreateDeploymentOutput,
    ScriptGetDeploymentData,
    ScriptGetDeploymentInput,
    ScriptGetDeploymentOutput,
    ScriptUpdateDeploymentData,
    ScriptUpdateDeploymentInput,
    ScriptUpdateDeploymentOutput,
    ScriptDeleteDeploymentData,
    ScriptDeleteDeploymentInput,
    ScriptDeleteDeploymentOutput,
    ScriptVersionsData,
    ScriptVersionsInput,
    ScriptVersionsOutput,
    ScriptCreateVersionData,
    ScriptCreateVersionInput,
    ScriptCreateVersionOutput,
    ScriptGetVersionData,
    ScriptGetVersionInput,
    ScriptGetVersionOutput,
    ScriptMetricsData,
    ScriptMetricsInput,
    ScriptMetricsOutput,
    ScriptRunData,
    ScriptRunInput,
    ScriptRunOutput,
)


def _wrap(data: Any, op: str, *, page: PageInfo | None = None) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, page=page, meta=Meta(op=op))


def _deployment_config_body(
    *,
    version_number: int | None,
    description: str | None,
    manifest_file_name: str | None,
) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if version_number is not None:
        config["versionNumber"] = version_number
    if description is not None:
        config["description"] = description
    if manifest_file_name is not None:
        config["manifestFileName"] = manifest_file_name
    return {"deploymentConfig": config}


# ─── script.create ────────────────────────────────────────────────────────────


def script_create(
    inp: ScriptCreateInput,
    *,
    service: Any = None,
) -> ScriptCreateOutput:
    """Create a new Apps Script project.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED
    """
    body: dict[str, Any] = {"title": inp.title}
    if inp.parent_id is not None:
        body["parentId"] = inp.parent_id

    raw = execute_api_call(
        lambda: service.projects().create(body=body).execute(),
        op="script.create",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    created = raw or {}
    return _wrap(
        ScriptCreateData(
            script_id=created.get("scriptId", ""),
            title=created.get("title", inp.title),
        ),
        "script.create",
    )


# ─── script.get_content ───────────────────────────────────────────────────────


def script_get_content(
    inp: ScriptGetContentInput,
    *,
    service: Any = None,
) -> ScriptGetContentOutput:
    """Get the source content (files) of a script project.

    Parity: mock-read DONE; sandbox-e2e DEFERRED
    """
    kwargs: dict[str, Any] = {"scriptId": inp.script_id}
    if inp.version_number is not None:
        kwargs["versionNumber"] = inp.version_number

    raw = execute_api_call(
        lambda kw=dict(kwargs): service.projects().getContent(**kw).execute(),
        op="script.get_content",
        posture="read",
    )
    raw = raw or {}
    files = [
        ScriptFileItem(
            name=f.get("name", ""),
            type=f.get("type", ""),
            source=f.get("source"),
        )
        for f in raw.get("files", [])
    ]
    return _wrap(
        ScriptGetContentData(script_id=raw.get("scriptId", inp.script_id), files=files),
        "script.get_content",
    )


# ─── script.update_content ────────────────────────────────────────────────────


def script_update_content(
    inp: ScriptUpdateContentInput,
    *,
    service: Any = None,
) -> ScriptUpdateContentOutput:
    """Replace the source files of a script project.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED
    """
    body: dict[str, Any] = {"files": [f.model_dump() for f in inp.files]}

    raw = execute_api_call(
        lambda: service.projects().updateContent(scriptId=inp.script_id, body=body).execute(),
        op="script.update_content",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.script_id],
    )
    result = raw or {}
    return _wrap(
        ScriptUpdateContentData(
            script_id=result.get("scriptId", inp.script_id),
            files=result.get("files", body["files"]),
        ),
        "script.update_content",
    )


# ─── script.deployments ───────────────────────────────────────────────────────


def script_deployments(
    inp: ScriptDeploymentsInput,
    *,
    service: Any = None,
) -> ScriptDeploymentsOutput:
    """List deployments of a script project.

    Parity: mock-read DONE; sandbox-e2e DEFERRED
    """
    kwargs: dict[str, Any] = {"scriptId": inp.script_id}
    if inp.page_size is not None:
        kwargs["pageSize"] = inp.page_size
    if inp.page_token is not None:
        kwargs["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda kw=dict(kwargs): service.projects().deployments().list(**kw).execute(),
        op="script.deployments",
        posture="read",
    )
    raw = raw or {}
    return _wrap(
        ScriptDeploymentsData(
            deployments=raw.get("deployments", []),
        ),
        "script.deployments",
        page=PageInfo(next_page_token=raw.get("nextPageToken")),
    )


# ─── script.create_deployment ─────────────────────────────────────────────────


def script_create_deployment(
    inp: ScriptCreateDeploymentInput,
    *,
    service: Any = None,
) -> ScriptCreateDeploymentOutput:
    """Create a deployment for a script project.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED
    """
    body = _deployment_config_body(
        version_number=inp.version_number,
        description=inp.description,
        manifest_file_name=inp.manifest_file_name,
    )
    raw = execute_api_call(
        lambda: service.projects().deployments().create(scriptId=inp.script_id, body=body).execute(),
        op="script.create_deployment",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.script_id],
    )
    deployment = raw or {}
    return _wrap(
        ScriptCreateDeploymentData(deployment=deployment),
        "script.create_deployment",
    )


# ─── script.get_deployment ────────────────────────────────────────────────────


def script_get_deployment(
    inp: ScriptGetDeploymentInput,
    *,
    service: Any = None,
) -> ScriptGetDeploymentOutput:
    """Get one deployment for a script project.

    Parity: mock-read DONE; sandbox-e2e DEFERRED
    """
    raw = execute_api_call(
        lambda: service.projects().deployments().get(
            scriptId=inp.script_id,
            deploymentId=inp.deployment_id,
        ).execute(),
        op="script.get_deployment",
        posture="read",
    )
    deployment = raw or {}
    return _wrap(
        ScriptGetDeploymentData(deployment=deployment),
        "script.get_deployment",
    )


# ─── script.update_deployment ─────────────────────────────────────────────────


def script_update_deployment(
    inp: ScriptUpdateDeploymentInput,
    *,
    service: Any = None,
) -> ScriptUpdateDeploymentOutput:
    """Update a deployment for a script project.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED
    """
    body = _deployment_config_body(
        version_number=inp.version_number,
        description=inp.description,
        manifest_file_name=inp.manifest_file_name,
    )
    raw = execute_api_call(
        lambda: service.projects().deployments().update(
            scriptId=inp.script_id,
            deploymentId=inp.deployment_id,
            body=body,
        ).execute(),
        op="script.update_deployment",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.script_id, inp.deployment_id],
    )
    deployment = raw or {}
    return _wrap(
        ScriptUpdateDeploymentData(deployment=deployment),
        "script.update_deployment",
    )


# ─── script.delete_deployment ─────────────────────────────────────────────────


def script_delete_deployment(
    inp: ScriptDeleteDeploymentInput,
    *,
    service: Any = None,
) -> ScriptDeleteDeploymentOutput:
    """Delete a deployment from a script project.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED
    """
    raw = execute_api_call(
        lambda: service.projects().deployments().delete(
            scriptId=inp.script_id,
            deploymentId=inp.deployment_id,
        ).execute(),
        op="script.delete_deployment",
        posture="destructive",
        normalized_request=inp.model_dump(),
        target_ids=[inp.script_id, inp.deployment_id],
    )
    return _wrap(
        ScriptDeleteDeploymentData(deleted=raw in (None, {}), response=raw or {}),
        "script.delete_deployment",
    )


# ─── script.versions ──────────────────────────────────────────────────────────


def script_versions(
    inp: ScriptVersionsInput,
    *,
    service: Any = None,
) -> ScriptVersionsOutput:
    """List versions of a script project.

    Parity: mock-read DONE; sandbox-e2e DEFERRED
    """
    kwargs: dict[str, Any] = {"scriptId": inp.script_id}
    if inp.page_size is not None:
        kwargs["pageSize"] = inp.page_size
    if inp.page_token is not None:
        kwargs["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda kw=dict(kwargs): service.projects().versions().list(**kw).execute(),
        op="script.versions",
        posture="read",
    )
    raw = raw or {}
    return _wrap(
        ScriptVersionsData(
            versions=raw.get("versions", []),
        ),
        "script.versions",
        page=PageInfo(next_page_token=raw.get("nextPageToken")),
    )


# ─── script.create_version ────────────────────────────────────────────────────


def script_create_version(
    inp: ScriptCreateVersionInput,
    *,
    service: Any = None,
) -> ScriptCreateVersionOutput:
    """Create an immutable version of a script project.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED
    """
    body: dict[str, Any] = {}
    if inp.description is not None:
        body["description"] = inp.description

    raw = execute_api_call(
        lambda: service.projects().versions().create(scriptId=inp.script_id, body=body).execute(),
        op="script.create_version",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.script_id],
    )
    version = raw or {}
    return _wrap(
        ScriptCreateVersionData(version=version),
        "script.create_version",
    )


# ─── script.get_version ───────────────────────────────────────────────────────


def script_get_version(
    inp: ScriptGetVersionInput,
    *,
    service: Any = None,
) -> ScriptGetVersionOutput:
    """Get one immutable version of a script project.

    Parity: mock-read DONE; sandbox-e2e DEFERRED
    """
    raw = execute_api_call(
        lambda: service.projects().versions().get(
            scriptId=inp.script_id,
            versionNumber=inp.version_number,
        ).execute(),
        op="script.get_version",
        posture="read",
    )
    version = raw or {}
    return _wrap(
        ScriptGetVersionData(version=version),
        "script.get_version",
    )


# ─── script.run ───────────────────────────────────────────────────────────────


def script_run(
    inp: ScriptRunInput,
    *,
    service: Any = None,
) -> ScriptRunOutput:
    """Execute a function in a deployed Apps Script project.

    Escape-hatch only — requires the script deployed as API-executable in the
    same Cloud project as the OAuth client.
    Parity: mutation-request DONE; sandbox-e2e DEFERRED
    """
    body: dict[str, Any] = {"function": inp.function}
    if inp.parameters is not None:
        body["parameters"] = inp.parameters
    if inp.dev_mode is not None:
        body["devMode"] = inp.dev_mode

    raw = execute_api_call(
        lambda: service.scripts().run(scriptId=inp.script_id, body=body).execute(),
        op="script.run",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.script_id],
    )
    operation = raw or {}
    return _wrap(
        ScriptRunData(
            done=operation.get("done", False),
            response=operation.get("response"),
            error=operation.get("error"),
        ),
        "script.run",
    )


# ─── script.metrics ───────────────────────────────────────────────────────────


def script_metrics(
    inp: ScriptMetricsInput,
    *,
    service: Any = None,
) -> ScriptMetricsOutput:
    """Retrieve execution metrics for a script project.

    Parity: mock-read DONE; sandbox-e2e DEFERRED
    """
    kwargs: dict[str, Any] = {
        "scriptId": inp.script_id,
        "metricsGranularity": inp.metrics_granularity,
    }
    if inp.metrics_filter_deployment_id is not None:
        kwargs["metricsFilter.deploymentId"] = inp.metrics_filter_deployment_id

    raw = execute_api_call(
        lambda kw=dict(kwargs): service.projects().getMetrics(**kw).execute(),
        op="script.metrics",
        posture="read",
    )
    raw = raw or {}
    return _wrap(
        ScriptMetricsData(
            active_users=raw.get("activeUsers", []),
            total_executions=raw.get("totalExecutions", []),
            failed_executions=raw.get("failedExecutions", []),
        ),
        "script.metrics",
    )
