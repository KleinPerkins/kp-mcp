"""Append-only JSONL mutation audit log for google-kit core (R24).

Every mutation emits one record:
    {ts, run_id, actor, op, normalized_request, target_ids, result, deviation_flag}

Secrets/PII are redacted before write. Audit-file path accepted by injection
for tests (avoids touching the real path in unit tests).
"""
from __future__ import annotations

import contextvars
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google_kit.core import run_id as _run_id_mod
from google_kit.core.redaction import redact_dict, redact_string

#: Identity (Keychain profile/account) performing the current operation. Set once
#: per CLI invocation / MCP tool call at the adapter boundary — mirroring the
#: ``run_id`` contextvar — so every audit record attributes the mutation to the
#: operating profile instead of a hardcoded ``"default"``.
_ACTOR: contextvars.ContextVar[str] = contextvars.ContextVar(
    "google_kit_actor", default="default"
)


def set_actor(actor: str) -> contextvars.Token[str]:
    """Set the current audit actor in the contextvar. Returns the reset token."""
    return _ACTOR.set(actor)


def get_actor() -> str:
    """Return the current audit actor, or ``'default'`` if none is set."""
    return _ACTOR.get()


def reset_actor(token: contextvars.Token[str]) -> None:
    """Reset the actor contextvar to its previous value using the set_actor token."""
    _ACTOR.reset(token)

_DEFAULT_AUDIT_PATH: Path = Path(
    os.environ.get(
        "GOOGLE_KIT_AUDIT_FILE",
        os.path.join(
            os.environ.get(
                "GOOGLE_KIT_CONFIG_DIR",
                os.path.join(
                    os.path.expanduser("~"),
                    "Library",
                    "Application Support",
                    "google-kit",
                ),
            ),
            "audit.jsonl",
        ),
    )
)

_WRITE_LOCK = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_audit(
    *,
    actor: str,
    op: str,
    normalized_request: dict[str, Any],
    target_ids: list[str],
    result: str,
    deviation_flag: bool = False,
    error: str | None = None,
    audit_file: Path | None = None,
) -> None:
    """Append a redacted mutation record to the audit JSONL file.

    Args:
        actor:              Identity performing the operation (profile/account).
        op:                 Operation name (e.g. 'drive.create').
        normalized_request: Normalised input parameters; PII will be redacted.
        target_ids:         Resource IDs created or mutated by this operation.
        result:             Outcome string — 'ok' | 'error' | 'skipped'.
        deviation_flag:     True if a non-trivial deviation from expected was detected.
        error:              Redacted error summary, recorded ONLY for failed
                            mutations (``result='error'``). The caller is
                            responsible for redacting secrets/PII before passing
                            it; it is additionally scrubbed here via
                            ``redact_string`` as defense-in-depth. Omitted from
                            the record entirely when ``None`` so successful
                            records keep their stable shape.
        audit_file:         Override path for tests; defaults to GOOGLE_KIT_AUDIT_FILE.
    """
    from .personal_runtime import current, held
    runtime = current()
    if runtime is not None:
        if actor != runtime.profile or (audit_file is not None and Path(audit_file) != runtime.directory.path / "personal-audit.jsonl"):
            held("audit_override_refused")
    path = audit_file or _DEFAULT_AUDIT_PATH
    record: dict[str, Any] = {
        "ts": _utc_now_iso(),
        "run_id": _run_id_mod.get_run_id(),
        "actor": actor,
        "op": op,
        "normalized_request": redact_dict(normalized_request),
        "target_ids": target_ids,
        "result": result,
        "deviation_flag": deviation_flag,
    }
    if error is not None:
        record["error"] = redact_string(error)
    if runtime is not None:
        runtime.append_audit(record)
        return
    line = json.dumps(record, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def read_audit(
    *,
    op: str | None = None,
    actor: str | None = None,
    since: str | None = None,
    audit_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Read and optionally filter audit records from the JSONL file.

    Args:
        op:         If set, return only records whose op starts with this prefix.
        actor:      If set, return only records matching this actor.
        since:      ISO-8601 timestamp; return records at or after this time.
        audit_file: Override path (default: GOOGLE_KIT_AUDIT_FILE).

    Returns:
        List of matching record dicts in write order.
    """
    path = audit_file or _DEFAULT_AUDIT_PATH
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if op is not None and not rec.get("op", "").startswith(op):
                continue
            if actor is not None and rec.get("actor") != actor:
                continue
            if since is not None and rec.get("ts", "") < since:
                continue
            records.append(rec)
    return records
