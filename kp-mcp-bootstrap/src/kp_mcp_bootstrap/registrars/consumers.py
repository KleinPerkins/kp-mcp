"""Kit-facing coordination over the existing registrar transaction engine.

No authority, preparation or approval is manufactured here. The engine preflights
all supplied operations and returns every target's exact partial outcome.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from . import (
    Action, Approval, BatchApplyRequest, RegistrationContext, RegistrationDefinition,
    PreparedOperation, ReasonCode, RegistrarError, Result, SourceIdentity,
    apply_batch, preflight_apply_batch,
)
from .base import BaseRegistrar, ServerEntry


def kit_definition(name: str, revision: str, entry: ServerEntry) -> RegistrationDefinition:
    """Bind a reviewed launch entry to the kit's stable source identity."""
    return RegistrationDefinition.from_server_entry(
        SourceIdentity(
            source_owner="KleinPerkins/kp-mcp",
            connection_id=f"kp-mcp:{name}",
            source_revision=revision,
            native_name=name,
        ),
        entry,
    )


def require_contexts(
    platforms: Mapping[str, BaseRegistrar],
    contexts: Mapping[str, RegistrationContext] | None,
) -> Mapping[str, RegistrationContext]:
    """Refuse before reading config when any target lacks explicit context."""
    if contexts is None or set(contexts) != set(platforms):
        raise RegistrarError(ReasonCode.CONTEXT_REQUIRED)
    if any(not isinstance(context, RegistrationContext) for context in contexts.values()):
        raise RegistrarError(ReasonCode.CONTEXT_REQUIRED)
    return contexts


def registration_batch(
    name: str,
    platforms: Mapping[str, BaseRegistrar],
    paths: Mapping[str, Path],
    entry: ServerEntry,
    *,
    contexts: Mapping[str, RegistrationContext] | None = None,
    prepared: Mapping[str, PreparedOperation] | None = None,
    approvals: Mapping[str, Approval] | None = None,
    dry_run: bool = False,
    remove: bool = False,
    validate_only: bool = False,
) -> dict[str, Result | str]:
    """Apply an explicitly prepared batch, or return a read-only preview."""
    contexts = require_contexts(platforms, contexts)
    if set(paths) != set(platforms):
        raise RegistrarError(ReasonCode.CONTEXT_REQUIRED)
    definitions = {
        host: kit_definition(name, contexts[host].source_revision, entry)
        for host in platforms
    }
    for host, definition in definitions.items():
        context = contexts[host]
        if (
            context.source_owner != "KleinPerkins/kp-mcp"
            or context.connection_id != f"kp-mcp:{name}"
            or context.definition_digest != definition.digest
        ):
            raise RegistrarError(ReasonCode.OWNER_CONFLICT)
    if dry_run:
        results: dict[str, Result | str] = {}
        for host, registrar in platforms.items():
            preview = (
                registrar.preview_unregister(paths[host], context=contexts[host])
                if remove else registrar.preview(paths[host], definitions[host], context=contexts[host])
            )
            if preview.conflicts:
                raise RegistrarError(preview.conflicts[0], reason_codes=preview.conflicts)
            if preview.config_changed:
                results[host] = "would-remove" if remove else "would-change"
            elif preview.state_changed:
                results[host] = "would-retire-receipt" if remove else "would-update-ownership"
            else:
                results[host] = "already-absent" if remove else "already-up-to-date"
        return results
    if prepared is None or set(prepared) != set(platforms):
        raise RegistrarError(ReasonCode.PREPARED_RECORD_REQUIRED)
    if approvals is None or set(approvals) != set(platforms):
        raise RegistrarError(ReasonCode.APPROVAL_INVALID)
    requests = tuple(
        BatchApplyRequest(
            registrar=registrar, path=paths[host], definition=None if remove else definitions[host],
            context=contexts[host], prepared=prepared[host], approval=approvals[host],
            action=Action.UNREGISTER if remove else Action.REGISTER,
        )
        for host, registrar in platforms.items()
    )
    if validate_only:
        preflight_apply_batch(requests)
        return {host: "ready" for host in platforms}
    return dict(zip(platforms, apply_batch(requests), strict=True))
