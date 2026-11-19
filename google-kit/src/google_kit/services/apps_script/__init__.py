"""Apps Script service — registers 13 ops (automation escape-hatch surface)."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    script_create,
    script_get_content,
    script_update_content,
    script_deployments,
    script_create_deployment,
    script_get_deployment,
    script_update_deployment,
    script_delete_deployment,
    script_versions,
    script_create_version,
    script_get_version,
    script_metrics,
    script_run,
)
from .models import (
    ScriptCreateInput,
    ScriptCreateOutput,
    ScriptGetContentInput,
    ScriptGetContentOutput,
    ScriptUpdateContentInput,
    ScriptUpdateContentOutput,
    ScriptDeploymentsInput,
    ScriptDeploymentsOutput,
    ScriptCreateDeploymentInput,
    ScriptCreateDeploymentOutput,
    ScriptGetDeploymentInput,
    ScriptGetDeploymentOutput,
    ScriptUpdateDeploymentInput,
    ScriptUpdateDeploymentOutput,
    ScriptDeleteDeploymentInput,
    ScriptDeleteDeploymentOutput,
    ScriptVersionsInput,
    ScriptVersionsOutput,
    ScriptCreateVersionInput,
    ScriptCreateVersionOutput,
    ScriptGetVersionInput,
    ScriptGetVersionOutput,
    ScriptMetricsInput,
    ScriptMetricsOutput,
    ScriptRunInput,
    ScriptRunOutput,
)

_SCRIPT_PROJECTS = "https://www.googleapis.com/auth/script.projects"
_SCRIPT_PROJECTS_READONLY = "https://www.googleapis.com/auth/script.projects.readonly"
_SCRIPT_DEPLOYMENTS = "https://www.googleapis.com/auth/script.deployments"
_SCRIPT_DEPLOYMENTS_READONLY = "https://www.googleapis.com/auth/script.deployments.readonly"
_SCRIPT_EXTERNAL_REQUEST = "https://www.googleapis.com/auth/script.external_request"
# projects.getMetrics authorizes ONLY via the dedicated script.metrics scope —
# script.projects[.readonly] do NOT cover it (live 403 ACCESS_TOKEN_SCOPE_INSUFFICIENT).
_SCRIPT_METRICS = "https://www.googleapis.com/auth/script.metrics"

#: Per-service F5 write gate (off by default) for ALL Apps Script
#: write/destructive ops — including the execution escape-hatch ``script.run``,
#: ``script.update_content``, and ``script.create_version``. Satisfied by the
#: ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. The advanced OAuth scopes that some of
#: these ops require remain a SEPARATE opt-in (off-by-default scope mode) and are
#: NOT part of the shared grant. See core/flags.py.
_SCRIPT_WRITE_FLAG = "GOOGLE_KIT_ENABLE_SCRIPT_WRITE"

register(OpSpec(
    name="script.create",
    fn=script_create,
    input_model=ScriptCreateInput,
    output_model=ScriptCreateOutput,
    posture="write",
    scopes=[_SCRIPT_PROJECTS],
    perf={
        "api": "Apps Script v1",
        "method": "projects.create",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Create a new standalone Apps Script project",
        "input": {"title": "My Automation Script"},
        "cli": "google-kit script create --title 'My Automation Script'",
    }],
    flag=_SCRIPT_WRITE_FLAG,
))

register(OpSpec(
    name="script.get_content",
    fn=script_get_content,
    input_model=ScriptGetContentInput,
    output_model=ScriptGetContentOutput,
    posture="read",
    scopes=[_SCRIPT_PROJECTS_READONLY],
    perf={
        "api": "Apps Script v1",
        "method": "projects.getContent",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Get source files of a script project",
        "input": {"script_id": "<script-id>"},
        "cli": "google-kit script get-content --script-id <script-id>",
    }],
))

register(OpSpec(
    name="script.update_content",
    fn=script_update_content,
    input_model=ScriptUpdateContentInput,
    output_model=ScriptUpdateContentOutput,
    posture="write",
    scopes=[_SCRIPT_PROJECTS],
    perf={
        "api": "Apps Script v1",
        "method": "projects.updateContent",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Replace source files in a script project",
        "input": {
            "script_id": "<script-id>",
            "files": [{"name": "Code", "type": "SERVER_JS", "source": "function main() {}"}],
        },
        "cli": "google-kit script update-content --script-id <script-id> --files '[...]'",
    }],
    flag=_SCRIPT_WRITE_FLAG,
))

register(OpSpec(
    name="script.deployments",
    fn=script_deployments,
    input_model=ScriptDeploymentsInput,
    output_model=ScriptDeploymentsOutput,
    posture="read",
    scopes=[_SCRIPT_PROJECTS_READONLY, _SCRIPT_DEPLOYMENTS_READONLY],
    perf={
        "api": "Apps Script v1",
        "method": "projects.deployments.list",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "List deployments of a script project",
        "input": {"script_id": "<script-id>"},
        "cli": "google-kit script deployments --script-id <script-id>",
    }],
))

register(OpSpec(
    name="script.create_deployment",
    fn=script_create_deployment,
    input_model=ScriptCreateDeploymentInput,
    output_model=ScriptCreateDeploymentOutput,
    posture="write",
    scopes=[_SCRIPT_DEPLOYMENTS],
    perf={
        "api": "Apps Script v1",
        "method": "projects.deployments.create",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Create a deployment for a script project",
        "input": {
            "script_id": "<script-id>",
            "version_number": 3,
            "description": "Production deployment",
        },
        "cli": (
            "google-kit script create-deployment --script-id <script-id> "
            "--version-number 3 --description 'Production deployment'"
        ),
        "notes": "Requires the off-by-default advanced scope mode AND the GOOGLE_KIT_ENABLE_SCRIPT_WRITE write gate (or the GOOGLE_KIT_ENABLE_WRITES umbrella).",
    }],
    flag=_SCRIPT_WRITE_FLAG,
))

register(OpSpec(
    name="script.get_deployment",
    fn=script_get_deployment,
    input_model=ScriptGetDeploymentInput,
    output_model=ScriptGetDeploymentOutput,
    posture="read",
    scopes=[_SCRIPT_PROJECTS_READONLY, _SCRIPT_DEPLOYMENTS_READONLY],
    perf={
        "api": "Apps Script v1",
        "method": "projects.deployments.get",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Get one deployment of a script project",
        "input": {"script_id": "<script-id>", "deployment_id": "<deployment-id>"},
        "cli": "google-kit script get-deployment --script-id <script-id> --deployment-id <deployment-id>",
    }],
))

register(OpSpec(
    name="script.update_deployment",
    fn=script_update_deployment,
    input_model=ScriptUpdateDeploymentInput,
    output_model=ScriptUpdateDeploymentOutput,
    posture="write",
    scopes=[_SCRIPT_DEPLOYMENTS],
    perf={
        "api": "Apps Script v1",
        "method": "projects.deployments.update",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Point an existing deployment at a new script version",
        "input": {
            "script_id": "<script-id>",
            "deployment_id": "<deployment-id>",
            "version_number": 4,
            "description": "Updated production deployment",
        },
        "cli": (
            "google-kit script update-deployment --script-id <script-id> "
            "--deployment-id <deployment-id> --version-number 4 "
            "--description 'Updated production deployment'"
        ),
        "notes": "Requires the off-by-default advanced scope mode AND the GOOGLE_KIT_ENABLE_SCRIPT_WRITE write gate (or the GOOGLE_KIT_ENABLE_WRITES umbrella).",
    }],
    flag=_SCRIPT_WRITE_FLAG,
))

register(OpSpec(
    name="script.delete_deployment",
    fn=script_delete_deployment,
    input_model=ScriptDeleteDeploymentInput,
    output_model=ScriptDeleteDeploymentOutput,
    posture="destructive",
    scopes=[_SCRIPT_DEPLOYMENTS],
    perf={
        "api": "Apps Script v1",
        "method": "projects.deployments.delete",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Delete one deployment of a script project",
        "input": {"script_id": "<script-id>", "deployment_id": "<deployment-id>"},
        "cli": "google-kit script delete-deployment --script-id <script-id> --deployment-id <deployment-id>",
        "notes": "Requires the off-by-default advanced scope mode AND the GOOGLE_KIT_ENABLE_SCRIPT_WRITE write gate (or the GOOGLE_KIT_ENABLE_WRITES umbrella).",
    }],
    flag=_SCRIPT_WRITE_FLAG,
))

register(OpSpec(
    name="script.versions",
    fn=script_versions,
    input_model=ScriptVersionsInput,
    output_model=ScriptVersionsOutput,
    posture="read",
    scopes=[_SCRIPT_PROJECTS_READONLY],
    perf={
        "api": "Apps Script v1",
        "method": "projects.versions.list",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "List versions of a script project",
        "input": {"script_id": "<script-id>"},
        "cli": "google-kit script versions --script-id <script-id>",
    }],
))

register(OpSpec(
    name="script.create_version",
    fn=script_create_version,
    input_model=ScriptCreateVersionInput,
    output_model=ScriptCreateVersionOutput,
    posture="write",
    scopes=[_SCRIPT_PROJECTS],
    perf={
        "api": "Apps Script v1",
        "method": "projects.versions.create",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Create an immutable version of a script project",
        "input": {"script_id": "<script-id>", "description": "Release v1"},
        "cli": "google-kit script create-version --script-id <script-id> --description 'Release v1'",
        "notes": "Requires the off-by-default advanced scope mode AND the GOOGLE_KIT_ENABLE_SCRIPT_WRITE write gate (or the GOOGLE_KIT_ENABLE_WRITES umbrella).",
    }],
    flag=_SCRIPT_WRITE_FLAG,
))

register(OpSpec(
    name="script.get_version",
    fn=script_get_version,
    input_model=ScriptGetVersionInput,
    output_model=ScriptGetVersionOutput,
    posture="read",
    scopes=[_SCRIPT_PROJECTS_READONLY],
    perf={
        "api": "Apps Script v1",
        "method": "projects.versions.get",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Get one immutable version of a script project",
        "input": {"script_id": "<script-id>", "version_number": 3},
        "cli": "google-kit script get-version --script-id <script-id> --version-number 3",
    }],
))

register(OpSpec(
    name="script.run",
    fn=script_run,
    input_model=ScriptRunInput,
    output_model=ScriptRunOutput,
    posture="write",
    scopes=[_SCRIPT_PROJECTS, _SCRIPT_EXTERNAL_REQUEST],
    perf={
        "api": "Apps Script v1",
        "method": "scripts.run",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Execute a function in a deployed Apps Script project",
        "input": {"script_id": "<script-id>", "function": "myFunction"},
        "cli": "google-kit script run --script-id <script-id> --function myFunction",
        "notes": (
            "Escape-hatch only — requires the script deployed as API-executable "
            "in the same Cloud project as the OAuth client. Gated by "
            "GOOGLE_KIT_ENABLE_SCRIPT_WRITE (or the GOOGLE_KIT_ENABLE_WRITES umbrella)."
        ),
    }],
    flag=_SCRIPT_WRITE_FLAG,
))

register(OpSpec(
    name="script.metrics",
    fn=script_metrics,
    input_model=ScriptMetricsInput,
    output_model=ScriptMetricsOutput,
    posture="read",
    scopes=[_SCRIPT_METRICS],
    perf={
        "api": "Apps Script v1",
        "method": "projects.getMetrics",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="automation",
    capability="automation.script",
    examples=[{
        "description": "Get weekly execution metrics for a script project",
        "input": {"script_id": "<script-id>", "metrics_granularity": "WEEKLY"},
        "cli": "google-kit script metrics --script-id <script-id> --metrics-granularity WEEKLY",
    }],
))
