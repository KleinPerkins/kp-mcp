"""Keep service — registers 4 cutover-minimum ops in the google-kit registry."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import keep_create, keep_delete, keep_get, keep_list
from .models import (
    KeepCreateInput,
    KeepCreateOutput,
    KeepDeleteInput,
    KeepDeleteOutput,
    KeepGetInput,
    KeepGetOutput,
    KeepListInput,
    KeepListOutput,
)

_KEEP_SCOPE = "https://www.googleapis.com/auth/keep"
_KEEP_READONLY_SCOPE = "https://www.googleapis.com/auth/keep.readonly"

#: Per-service F5 write gate (off by default). Satisfied by the
#: ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. See core/flags.py.
_KEEP_WRITE_FLAG = "GOOGLE_KIT_ENABLE_KEEP_WRITE"

register(OpSpec(
    name="keep.list",
    fn=keep_list,
    input_model=KeepListInput,
    output_model=KeepListOutput,
    posture="read",
    scopes=[_KEEP_READONLY_SCOPE],
    perf={"api": "Keep v1", "method": "notes.list", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List up to 50 notes",
        "input": {"page_size": 50},
        "cli": "google-kit keep list",
    }],
))

register(OpSpec(
    name="keep.get",
    fn=keep_get,
    input_model=KeepGetInput,
    output_model=KeepGetOutput,
    posture="read",
    scopes=[_KEEP_READONLY_SCOPE],
    perf={"api": "Keep v1", "method": "notes.get", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get a note by resource name",
        "input": {"note_id": "notes/abc123"},
        "cli": "google-kit keep get notes/abc123",
    }],
))

register(OpSpec(
    name="keep.create",
    fn=keep_create,
    input_model=KeepCreateInput,
    output_model=KeepCreateOutput,
    posture="write",
    scopes=[_KEEP_SCOPE],
    perf={"api": "Keep v1", "method": "notes.create", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a text note (BD-6: Keep API requires allowlist approval)",
        "input": {"title": "Meeting notes", "body_text": "Q1 planning session"},
        "cli": "google-kit keep create --title 'Meeting notes' --body-text 'Q1 planning session'",
        "notes": "BD-6: The Google Keep API is restricted and requires explicit allowlist approval from Google. The keep.* scope is NOT included in the default OAuth consent screen — a separate Workspace consent approval is required before Keep ops will succeed.",
    }],
    flag=_KEEP_WRITE_FLAG,
))

register(OpSpec(
    name="keep.delete",
    fn=keep_delete,
    input_model=KeepDeleteInput,
    output_model=KeepDeleteOutput,
    posture="destructive",
    scopes=[_KEEP_SCOPE],
    perf={"api": "Keep v1", "method": "notes.delete", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Trash a note by resource name (BD-6: Keep API requires allowlist approval)",
        "input": {"note_id": "notes/abc123"},
        "cli": "google-kit keep delete --note-id notes/abc123",
        "notes": "BD-6: The Google Keep API is restricted and requires explicit allowlist approval from Google. The keep.* scope is NOT included in the default OAuth consent screen — a separate Workspace consent approval is required before Keep ops will succeed.",
    }],
    flag=_KEEP_WRITE_FLAG,
))
