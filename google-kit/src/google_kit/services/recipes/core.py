"""Core functions for the first-class composition recipes (architecture brief §4).

Each recipe composes already-covered single-API ops behind the LIFO saga
executor (:mod:`google_kit.core.saga`). Recipes introduce **no new OAuth
scopes** — a recipe's scope set is the union of the scopes of the ops it
composes. On any mid-recipe failure the saga compensates the completed
mutations in LIFO order and the recipe surfaces the partial outcome
(``status="rolled_back"``, ``warnings`` populated, ``meta.saga_compensated=
True``) rather than raising — an agent gets a structured result either way.

Service injection — a recipe spans multiple APIs, so unlike a 1:1 op its
``service`` argument is a *resolver* that maps an API prefix (``"drive"``,
``"docs"``) to a built API resource. Both forms are accepted:

* a callable ``resolver(prefix) -> resource`` (CLI/MCP inject a Keychain-backed
  one), or
* a plain mapping ``{"drive": <resource>, "docs": <resource>}`` (tests inject a
  dict of mocks).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from google_kit.core.normalize import OutputEnvelope, build_meta, extract_drive_id
from google_kit.core.saga import SagaError, SagaStep, run_saga
from google_kit.services.docs.core import docs_apply_styles, docs_batch_update, docs_from_markdown
from google_kit.services.docs.models import (
    DocsApplyStylesInput,
    DocsBatchUpdateInput,
    DocsFromMarkdownInput,
)
from google_kit.services.drive.core import (
    drive_copy,
    drive_fetch,
    drive_permissions,
    drive_trash,
)
from google_kit.services.drive.models import (
    DriveCopyInput,
    DriveFetchInput,
    DrivePermissionsInput,
    DriveTrashInput,
)

from .models import (
    BuildThenShareData,
    BuildThenShareInput,
    BuildThenShareOutput,
    BuildStyledData,
    BuildStyledInput,
    BuildStyledOutput,
    HydrateThenRefineData,
    HydrateThenRefineInput,
    HydrateThenRefineOutput,
    TemplateMergeData,
    TemplateMergeInput,
    TemplateMergeOutput,
)

# Scope unions (subsets of already-granted scopes — recipes add NO new scopes).
_DRIVE = "https://www.googleapis.com/auth/drive"
_DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
_DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
_DOCUMENTS = "https://www.googleapis.com/auth/documents"

BUILD_THEN_SHARE_SCOPES = [_DOCUMENTS, _DRIVE, _DRIVE_FILE]
TEMPLATE_MERGE_SCOPES = [_DOCUMENTS, _DRIVE_FILE]
HYDRATE_THEN_REFINE_SCOPES = [_DOCUMENTS, _DRIVE_FILE, _DRIVE_READONLY]
BUILD_STYLED_SCOPES = [_DOCUMENTS, _DRIVE, _DRIVE_FILE]

ServiceResolver = Callable[[str], Any] | Mapping[str, Any]


def _resolve(resolver: ServiceResolver | None, prefix: str) -> Any:
    """Resolve the built API resource for ``prefix`` from a callable or mapping."""
    if resolver is None:
        raise ValueError(
            f"recipe requires a service resolver to obtain the {prefix!r} API"
        )
    if callable(resolver):
        return resolver(prefix)
    try:
        return resolver[prefix]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"no service available for API prefix {prefix!r}") from exc


def _bare_id(value: str) -> str:
    """Return a bare Drive/Docs file id, extracting from a URL when needed."""
    return extract_drive_id(value) if value.startswith("http") else value


def _rollback_warning(exc: SagaError) -> str:
    """Render a single human-readable warning describing a saga rollback."""
    parts = [f"recipe rolled back: step {exc.failed_step!r} failed: {exc.original}"]
    if exc.compensated_steps:
        parts.append(f"compensated (LIFO): {', '.join(exc.compensated_steps)}")
    if exc.compensation_errors:
        parts.append(f"compensation errors: {'; '.join(exc.compensation_errors)}")
    return " | ".join(parts)


# ─── recipes.build_then_share ─────────────────────────────────────────────────


def recipe_build_then_share(
    inp: BuildThenShareInput,
    *,
    service: ServiceResolver | None = None,
) -> BuildThenShareOutput:
    """Create a styled Google Doc from Markdown, then share it (saga-guarded).

    Compose: ``docs.from_markdown`` (Drive ``files.create`` + Docs
    ``documents.batchUpdate``) → ``drive.permissions`` (``permissions.create``).
    If sharing fails, the just-created Doc is trashed (LIFO compensation) and the
    partial outcome is surfaced with ``status="rolled_back"``.
    """
    drive = _resolve(service, "drive")
    docs = _resolve(service, "docs")
    state: dict[str, Any] = {}

    def _create_doc() -> Any:
        out = docs_from_markdown(
            DocsFromMarkdownInput(
                markdown_content=inp.markdown_content,
                title=inp.title,
                folder_id=inp.folder_id,
                style_profile=inp.style_profile,
                style_overrides=inp.style_overrides,
            ),
            drive_service=drive,
            docs_service=docs,
        )
        state["doc_id"] = out.data.doc_id
        state["url"] = out.data.url
        return out

    def _trash_doc(_create_result: Any) -> None:
        drive_trash(DriveTrashInput(file_id=state["doc_id"]), service=drive)

    def _share_doc() -> Any:
        return drive_permissions(
            DrivePermissionsInput(
                file_id=state["doc_id"],
                action="create",
                role=inp.role,
                type=inp.type,
                email_address=inp.share_with,
            ),
            service=drive,
        )

    steps = [
        SagaStep("create_doc", _create_doc, _trash_doc),
        SagaStep("share_doc", _share_doc),
    ]

    method = (
        "recipe build-then-share: docs.from_markdown → drive.permissions.create "
        "(compensate: drive.trash)"
    )
    try:
        run_saga(steps)
    except SagaError as exc:
        return OutputEnvelope(
            data=BuildThenShareData(
                status="rolled_back",
                doc_id=state.get("doc_id"),
                url=state.get("url"),
                title=inp.title,
            ),
            warnings=[_rollback_warning(exc)],
            meta=build_meta(
                op="recipes.build_then_share",
                recipe_id="build-then-share",
                saga_compensated=bool(exc.compensated_steps),
                api="Docs v1 + Drive v3",
                method=method,
                scopes_used=BUILD_THEN_SHARE_SCOPES,
                calls=len(steps),
            ),
        )

    return OutputEnvelope(
        data=BuildThenShareData(
            status="completed",
            doc_id=state.get("doc_id"),
            url=state.get("url"),
            title=inp.title,
            shared_with=inp.share_with,
            role=inp.role,
        ),
        meta=build_meta(
            op="recipes.build_then_share",
            recipe_id="build-then-share",
            saga_compensated=False,
            api="Docs v1 + Drive v3",
            method=method,
            scopes_used=BUILD_THEN_SHARE_SCOPES,
            calls=len(steps),
        ),
    )


# ─── recipes.template_merge ───────────────────────────────────────────────────


def recipe_template_merge(
    inp: TemplateMergeInput,
    *,
    service: ServiceResolver | None = None,
) -> TemplateMergeOutput:
    """Copy a template Doc, then merge placeholder fields into the copy (saga-guarded).

    Compose: ``drive.copy`` (``files.copy``) → ``docs.batch_update``
    (``documents.batchUpdate`` of ``replaceAllText`` requests built from
    ``replacements``). If the merge fails, the copy is trashed (LIFO
    compensation) so no half-merged orphan is left behind.
    """
    drive = _resolve(service, "drive")
    docs = _resolve(service, "docs")
    state: dict[str, Any] = {}

    merge_requests = [
        {
            "replaceAllText": {
                "containsText": {"text": placeholder, "matchCase": inp.match_case},
                "replaceText": value,
            }
        }
        for placeholder, value in inp.replacements.items()
    ]

    def _copy_template() -> Any:
        out = drive_copy(
            DriveCopyInput(
                file_id=_bare_id(inp.template_id),
                name=inp.new_name,
                folder_id=inp.folder_id,
            ),
            service=drive,
        )
        state["doc_id"] = out.data.id
        state["url"] = out.data.url
        state["name"] = out.data.name
        return out

    def _trash_copy(_copy_result: Any) -> None:
        drive_trash(DriveTrashInput(file_id=state["doc_id"]), service=drive)

    def _merge_fields() -> Any:
        return docs_batch_update(
            DocsBatchUpdateInput(
                document_id=state["doc_id"],
                requests=merge_requests,
                style_profile=inp.style_profile,
                style_overrides=inp.style_overrides,
            ),
            docs_service=docs,
        )

    steps = [
        SagaStep("copy_template", _copy_template, _trash_copy),
        SagaStep("merge_fields", _merge_fields),
    ]

    method = (
        "recipe template-merge: drive.copy → docs.batchUpdate(replaceAllText) "
        "(compensate: drive.trash)"
    )
    try:
        run_saga(steps)
    except SagaError as exc:
        return OutputEnvelope(
            data=TemplateMergeData(
                status="rolled_back",
                doc_id=state.get("doc_id"),
                url=state.get("url"),
                name=state.get("name"),
                replacements_applied=0,
            ),
            warnings=[_rollback_warning(exc)],
            meta=build_meta(
                op="recipes.template_merge",
                recipe_id="template-merge",
                saga_compensated=bool(exc.compensated_steps),
                api="Drive v3 + Docs v1",
                method=method,
                scopes_used=TEMPLATE_MERGE_SCOPES,
                calls=len(steps),
            ),
        )

    return OutputEnvelope(
        data=TemplateMergeData(
            status="completed",
            doc_id=state.get("doc_id"),
            url=state.get("url"),
            name=state.get("name"),
            replacements_applied=len(merge_requests),
        ),
        meta=build_meta(
            op="recipes.template_merge",
            recipe_id="template-merge",
            saga_compensated=False,
            api="Drive v3 + Docs v1",
            method=method,
            scopes_used=TEMPLATE_MERGE_SCOPES,
            calls=len(steps),
        ),
    )


# ─── recipes.hydrate_then_refine ──────────────────────────────────────────────


def recipe_hydrate_then_refine(
    inp: HydrateThenRefineInput,
    *,
    service: ServiceResolver | None = None,
) -> HydrateThenRefineOutput:
    """Read a Doc to hydrate context, then apply refinement requests (saga-guarded).

    Compose: ``drive.fetch`` (metadata/content read — no compensation) →
    ``docs.batch_update`` (``documents.batchUpdate`` of the caller's refinement
    requests). The hydrate step is read-only, so a refinement failure leaves no
    mutation to roll back; the partial outcome is still surfaced uniformly.
    """
    drive = _resolve(service, "drive")
    docs = _resolve(service, "docs")
    state: dict[str, Any] = {}

    def _hydrate() -> Any:
        out = drive_fetch(
            DriveFetchInput(
                url_or_id=inp.document_id,
                metadata_only=inp.hydrate_metadata_only,
            ),
            service=drive,
        )
        state["doc_id"] = out.data.id
        state["title"] = out.data.title
        state["mime_type"] = out.data.mime_type
        return out

    def _refine() -> Any:
        out = docs_batch_update(
            DocsBatchUpdateInput(
                document_id=_bare_id(inp.document_id),
                requests=inp.requests,
                style_profile=inp.style_profile,
                style_overrides=inp.style_overrides,
            ),
            docs_service=docs,
        )
        state["replies"] = list(out.data.replies or [])
        return out

    steps = [
        SagaStep("hydrate", _hydrate),
        SagaStep("refine", _refine),
    ]

    method = "recipe hydrate-then-refine: drive.fetch → docs.batchUpdate"
    try:
        run_saga(steps)
    except SagaError as exc:
        return OutputEnvelope(
            data=HydrateThenRefineData(
                status="rolled_back",
                doc_id=state.get("doc_id"),
                title=state.get("title"),
                mime_type=state.get("mime_type"),
                requests_applied=0,
            ),
            warnings=[_rollback_warning(exc)],
            meta=build_meta(
                op="recipes.hydrate_then_refine",
                recipe_id="hydrate-then-refine",
                saga_compensated=bool(exc.compensated_steps),
                api="Drive v3 + Docs v1",
                method=method,
                scopes_used=HYDRATE_THEN_REFINE_SCOPES,
                calls=len(steps),
            ),
        )

    return OutputEnvelope(
        data=HydrateThenRefineData(
            status="completed",
            doc_id=state.get("doc_id"),
            title=state.get("title"),
            mime_type=state.get("mime_type"),
            requests_applied=len(inp.requests),
            refine_replies=state.get("replies", []),
        ),
        meta=build_meta(
            op="recipes.hydrate_then_refine",
            recipe_id="hydrate-then-refine",
            saga_compensated=False,
            api="Drive v3 + Docs v1",
            method=method,
            scopes_used=HYDRATE_THEN_REFINE_SCOPES,
            calls=len(steps),
        ),
    )


# ─── recipes.build_styled ─────────────────────────────────────────────────────


def recipe_build_styled(
    inp: BuildStyledInput,
    *,
    service: ServiceResolver | None = None,
) -> BuildStyledOutput:
    """Create a Google Doc from Markdown, then assert a local style profile."""
    drive = _resolve(service, "drive")
    docs = _resolve(service, "docs")
    state: dict[str, Any] = {}

    def _create_doc() -> Any:
        out = docs_from_markdown(
            DocsFromMarkdownInput(
                markdown_content=inp.markdown_content,
                title=inp.title,
                folder_id=inp.folder_id,
                style_profile="legacy",
            ),
            drive_service=drive,
            docs_service=docs,
        )
        state["doc_id"] = out.data.doc_id
        state["url"] = out.data.url
        return out

    def _trash_doc(_create_result: Any) -> None:
        drive_trash(DriveTrashInput(file_id=state["doc_id"]), service=drive)

    def _apply_styles() -> Any:
        out = docs_apply_styles(
            DocsApplyStylesInput(
                document_id=state["doc_id"],
                style_profile=inp.style_profile,
                style_overrides=inp.style_overrides,
            ),
            docs_service=docs,
        )
        state["style_requests_applied"] = out.data.requests_applied
        return out

    steps = [
        SagaStep("create_doc", _create_doc, _trash_doc),
        SagaStep("apply_styles", _apply_styles),
    ]
    method = "recipe build-styled: docs.from_markdown → docs.apply_styles (compensate: drive.trash)"
    try:
        run_saga(steps)
    except SagaError as exc:
        return OutputEnvelope(
            data=BuildStyledData(
                status="rolled_back",
                doc_id=state.get("doc_id"),
                url=state.get("url"),
                title=inp.title,
                style_requests_applied=state.get("style_requests_applied", 0),
            ),
            warnings=[_rollback_warning(exc)],
            meta=build_meta(
                op="recipes.build_styled",
                recipe_id="build-styled",
                saga_compensated=bool(exc.compensated_steps),
                api="Docs v1 + Drive v3",
                method=method,
                scopes_used=BUILD_STYLED_SCOPES,
                calls=len(steps),
            ),
        )

    return OutputEnvelope(
        data=BuildStyledData(
            status="completed",
            doc_id=state.get("doc_id"),
            url=state.get("url"),
            title=inp.title,
            style_requests_applied=state.get("style_requests_applied", 0),
        ),
        meta=build_meta(
            op="recipes.build_styled",
            recipe_id="build-styled",
            saga_compensated=False,
            api="Docs v1 + Drive v3",
            method=method,
            scopes_used=BUILD_STYLED_SCOPES,
            calls=len(steps),
        ),
    )
