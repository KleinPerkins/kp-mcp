"""Pydantic input / output models for all Apps Script service operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope


# ─── script.create ────────────────────────────────────────────────────────────


class ScriptCreateInput(BaseModel):
    """Input for ``script.create``: create a new Apps Script project."""

    title: str = Field(description="Title for the new script project.")
    parent_id: str | None = Field(default=None, description="Drive item ID of the parent (e.g. a Google Doc). Optional.")


class ScriptCreateData(BaseModel):
    """Data payload for ``script.create``."""

    script_id: str
    title: str


ScriptCreateOutput = OutputEnvelope[ScriptCreateData]


# ─── script.get_content ───────────────────────────────────────────────────────


class ScriptGetContentInput(BaseModel):
    """Input for ``script.get_content``: get a script project's source content."""

    script_id: str
    version_number: int | None = Field(default=None, description="Version number to retrieve. Omit for HEAD.")


class ScriptFileItem(BaseModel):
    """One file in a script project's content."""

    name: str
    type: str
    source: str | None = None


class ScriptGetContentData(BaseModel):
    """Data payload for ``script.get_content``."""

    script_id: str
    files: list[ScriptFileItem]


ScriptGetContentOutput = OutputEnvelope[ScriptGetContentData]


# ─── script.update_content ────────────────────────────────────────────────────


class ScriptFileInput(BaseModel):
    """One file to upload in ``script.update_content``."""

    name: str
    type: str
    source: str


class ScriptUpdateContentInput(BaseModel):
    """Input for ``script.update_content``: replace a project's source files."""

    script_id: str
    files: list[ScriptFileInput]


class ScriptUpdateContentData(BaseModel):
    """Data payload for ``script.update_content``."""

    script_id: str
    files: list[dict[str, Any]]


ScriptUpdateContentOutput = OutputEnvelope[ScriptUpdateContentData]


# ─── script.deployments ───────────────────────────────────────────────────────


class ScriptDeploymentsInput(BaseModel):
    """Input for ``script.deployments``: list deployments of a script project."""

    script_id: str
    page_size: int | None = Field(default=None, description="Max deployments per page.")
    page_token: str | None = None


class ScriptDeploymentsData(BaseModel):
    """Data payload for ``script.deployments``."""

    deployments: list[dict[str, Any]]


ScriptDeploymentsOutput = OutputEnvelope[ScriptDeploymentsData]


# ─── script.create_deployment ─────────────────────────────────────────────────


class ScriptCreateDeploymentInput(BaseModel):
    """Input for ``script.create_deployment``: create a script deployment."""

    script_id: str = Field(description="Apps Script project ID.")
    version_number: int | None = Field(
        default=None,
        description="Script version to deploy. Omit to use the Apps Script API default.",
    )
    description: str | None = Field(default=None, description="Human-readable deployment description.")
    manifest_file_name: str | None = Field(
        default=None,
        description="Manifest file name for the deployment, typically appsscript.",
    )


class ScriptCreateDeploymentData(BaseModel):
    """Data payload for ``script.create_deployment``."""

    deployment: dict[str, Any]


ScriptCreateDeploymentOutput = OutputEnvelope[ScriptCreateDeploymentData]


# ─── script.get_deployment ────────────────────────────────────────────────────


class ScriptGetDeploymentInput(BaseModel):
    """Input for ``script.get_deployment``: get a script deployment."""

    script_id: str = Field(description="Apps Script project ID.")
    deployment_id: str = Field(description="Deployment ID to retrieve.")


class ScriptGetDeploymentData(BaseModel):
    """Data payload for ``script.get_deployment``."""

    deployment: dict[str, Any]


ScriptGetDeploymentOutput = OutputEnvelope[ScriptGetDeploymentData]


# ─── script.update_deployment ─────────────────────────────────────────────────


class ScriptUpdateDeploymentInput(BaseModel):
    """Input for ``script.update_deployment``: update a script deployment."""

    script_id: str = Field(description="Apps Script project ID.")
    deployment_id: str = Field(description="Deployment ID to update.")
    version_number: int | None = Field(
        default=None,
        description="Script version to assign to this deployment. Omit to leave unset.",
    )
    description: str | None = Field(default=None, description="Human-readable deployment description.")
    manifest_file_name: str | None = Field(
        default=None,
        description="Manifest file name for the deployment, typically appsscript.",
    )


class ScriptUpdateDeploymentData(BaseModel):
    """Data payload for ``script.update_deployment``."""

    deployment: dict[str, Any]


ScriptUpdateDeploymentOutput = OutputEnvelope[ScriptUpdateDeploymentData]


# ─── script.delete_deployment ─────────────────────────────────────────────────


class ScriptDeleteDeploymentInput(BaseModel):
    """Input for ``script.delete_deployment``: delete a script deployment."""

    script_id: str = Field(description="Apps Script project ID.")
    deployment_id: str = Field(description="Deployment ID to delete.")


class ScriptDeleteDeploymentData(BaseModel):
    """Data payload for ``script.delete_deployment``."""

    deleted: bool
    response: dict[str, Any]


ScriptDeleteDeploymentOutput = OutputEnvelope[ScriptDeleteDeploymentData]


# ─── script.versions ──────────────────────────────────────────────────────────


class ScriptVersionsInput(BaseModel):
    """Input for ``script.versions``: list versions of a script project."""

    script_id: str
    page_size: int | None = Field(default=None, description="Max versions per page.")
    page_token: str | None = None


class ScriptVersionsData(BaseModel):
    """Data payload for ``script.versions``."""

    versions: list[dict[str, Any]]


ScriptVersionsOutput = OutputEnvelope[ScriptVersionsData]


# ─── script.create_version ────────────────────────────────────────────────────


class ScriptCreateVersionInput(BaseModel):
    """Input for ``script.create_version``: create an immutable script version."""

    script_id: str = Field(description="Apps Script project ID.")
    description: str | None = Field(default=None, description="Description to store on the version.")


class ScriptCreateVersionData(BaseModel):
    """Data payload for ``script.create_version``."""

    version: dict[str, Any]


ScriptCreateVersionOutput = OutputEnvelope[ScriptCreateVersionData]


# ─── script.get_version ───────────────────────────────────────────────────────


class ScriptGetVersionInput(BaseModel):
    """Input for ``script.get_version``: get an immutable script version."""

    script_id: str = Field(description="Apps Script project ID.")
    version_number: int = Field(description="Version number to retrieve.")


class ScriptGetVersionData(BaseModel):
    """Data payload for ``script.get_version``."""

    version: dict[str, Any]


ScriptGetVersionOutput = OutputEnvelope[ScriptGetVersionData]


# ─── script.run ───────────────────────────────────────────────────────────────


class ScriptRunInput(BaseModel):
    """Input for ``script.run``: execute a function in a deployed script.

    Escape-hatch only — requires the script deployed as API-executable in the
    same Cloud project as the OAuth client.
    """

    script_id: str
    function: str = Field(description="Name of the function to run.")
    parameters: list[Any] | None = Field(default=None, description="Arguments to pass to the function.")
    dev_mode: bool | None = Field(default=None, description="Run the head deployment instead of the latest. Optional.")


class ScriptRunData(BaseModel):
    """Data payload for ``script.run``: the returned Operation."""

    done: bool
    response: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


ScriptRunOutput = OutputEnvelope[ScriptRunData]


# ─── script.metrics ───────────────────────────────────────────────────────────


class ScriptMetricsInput(BaseModel):
    """Input for ``script.metrics``: retrieve execution metrics for a script."""

    script_id: str
    metrics_granularity: str = Field(description="Granularity of returned metrics: WEEKLY or DAILY.")
    metrics_filter_deployment_id: str | None = Field(default=None, description="Limit metrics to a specific deployment ID. Optional.")


class ScriptMetricsData(BaseModel):
    """Data payload for ``script.metrics``."""

    active_users: list[dict[str, Any]]
    total_executions: list[dict[str, Any]]
    failed_executions: list[dict[str, Any]]


ScriptMetricsOutput = OutputEnvelope[ScriptMetricsData]
