"""Drive service — registers 12 ops (4 cutover-minimum + 8 §7 coverage)."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    ENABLE_DRIVE_WATCH_FLAG,
    ENABLE_DRIVE_WRITE_FLAG,
    drive_changes,
    drive_changes_watch,
    drive_comments,
    drive_copy,
    drive_create,
    drive_fetch,
    drive_permissions,
    drive_revisions,
    drive_search,
    drive_trash,
    drive_update,
    drive_upload,
)
from .models import (
    DriveChangesInput,
    DriveChangesOutput,
    DriveChangesWatchInput,
    DriveChangesWatchOutput,
    DriveCommentsInput,
    DriveCommentsOutput,
    DriveCopyInput,
    DriveCopyOutput,
    DriveCreateInput,
    DriveCreateOutput,
    DriveFetchInput,
    DriveFetchOutput,
    DrivePermissionsInput,
    DrivePermissionsOutput,
    DriveRevisionsInput,
    DriveRevisionsOutput,
    DriveSearchInput,
    DriveSearchOutput,
    DriveTrashInput,
    DriveTrashOutput,
    DriveUpdateInput,
    DriveUpdateOutput,
    DriveUploadInput,
    DriveUploadOutput,
)

_DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
_DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
_DOCUMENTS = "https://www.googleapis.com/auth/documents"

register(OpSpec(
    name="drive.fetch",
    fn=drive_fetch,
    input_model=DriveFetchInput,
    output_model=DriveFetchOutput,
    posture="read",
    scopes=[_DRIVE_READONLY, _DRIVE_FILE, _DOCUMENTS],
    perf={
        "api": "Drive v3 + Docs v1",
        "method": "files.get + files.export",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Fetch a Google Doc as text",
        "input": {"url_or_id": "https://docs.google.com/document/d/<id>/edit"},
        "cli": "google-kit drive fetch --url-or-id 'https://docs.google.com/document/d/<id>/edit'",
        "notes": "Google Sites URLs (https://sites.google.com/...) are routed to the Sites path. Prerequisites: Chrome + browser_cookie3 + Playwright installed (see QUICKSTART.md#google-sites-prerequisites). (sandbox-e2e DEFERRED P6 is a dev parity-maturity tag for sandbox e2e test coverage, not a capability limitation.)",
    }],
))

register(OpSpec(
    name="drive.create",
    fn=drive_create,
    input_model=DriveCreateInput,
    output_model=DriveCreateOutput,
    posture="write",
    scopes=[_DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "files.create",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a blank Google Doc in a folder",
        "input": {"title": "My Doc", "doc_type": "doc", "folder_id": "<folder-id>"},
        "cli": "google-kit drive create 'My Doc' --type doc --folder-id <folder-id>",
    }],
    keywords=["blank"],
    flag=ENABLE_DRIVE_WRITE_FLAG,
))

register(OpSpec(
    name="drive.search",
    fn=drive_search,
    input_model=DriveSearchInput,
    output_model=DriveSearchOutput,
    posture="read",
    scopes=[_DRIVE_READONLY, _DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "files.list",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Search by name (title) for a specific file",
        "input": {"name": "Q1 Report", "doc_type": "doc", "limit": 10},
        "cli": "google-kit drive search --name 'Q1 Report' --doc-type doc --limit 10",
    }],
    keywords=["where", "look"],
))

register(OpSpec(
    name="drive.upload",
    fn=drive_upload,
    input_model=DriveUploadInput,
    output_model=DriveUploadOutput,
    posture="write",
    scopes=[_DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "files.create (resumable) [+ permissions.create when share=anyone_reader]",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Upload a local file by path (streamed from disk; private by default)",
        "input": {
            "path": "/tmp/clip.mp4",
            "folder_id": "<folder-id>",
        },
        "cli": "google-kit drive upload --path /tmp/clip.mp4 --folder-id <folder-id>",
        "notes": (
            "Provide exactly one of 'path' (streamed from disk via resumable "
            "MediaFileUpload — any size/binary) or 'content_b64' (inline base64, "
            "small files only). 'filename' defaults to the path basename; MIME is "
            "guessed from the extension when 'mime_type' is omitted. Sharing is "
            "PRIVATE by default (no permissions call); pass share='anyone_reader' to "
            "explicitly grant type=anyone, role=reader. Output data: "
            "{id, url, name, mime_type, shared}."
        ),
    }],
    flag=ENABLE_DRIVE_WRITE_FLAG,
))

register(OpSpec(
    name="drive.copy",
    fn=drive_copy,
    input_model=DriveCopyInput,
    output_model=DriveCopyOutput,
    posture="write",
    scopes=[_DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "files.copy",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Copy a file into a folder with a new name",
        "input": {"file_id": "<file-id>", "name": "Copy of Report", "folder_id": "<folder-id>"},
        "cli": "google-kit drive copy --file-id <file-id> --name 'Copy of Report' --folder-id <folder-id>",
    }],
    keywords=["clone"],
    plane="container",
    capability="file.copy",
    flag=ENABLE_DRIVE_WRITE_FLAG,
))

register(OpSpec(
    name="drive.update",
    fn=drive_update,
    input_model=DriveUpdateInput,
    output_model=DriveUpdateOutput,
    posture="write",
    scopes=[_DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "files.update",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Rename a file",
        "input": {"file_id": "<file-id>", "name": "New Name"},
        "cli": "google-kit drive update --file-id <file-id> --name 'New Name'",
    }],
    aliases=["rename a file", "change a file name"],
    keywords=["rename", "metadata"],
    plane="container",
    capability="file.update",
    flag=ENABLE_DRIVE_WRITE_FLAG,
))

register(OpSpec(
    name="drive.trash",
    fn=drive_trash,
    input_model=DriveTrashInput,
    output_model=DriveTrashOutput,
    posture="destructive",
    scopes=[_DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "files.update (trashed=true/false)",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Trash a file",
        "input": {"file_id": "<file-id>"},
        "cli": "google-kit drive trash --file-id <file-id>",
    }],
    keywords=["remove"],
    plane="container",
    capability="file.trash",
    flag=ENABLE_DRIVE_WRITE_FLAG,
))

register(OpSpec(
    name="drive.permissions",
    fn=drive_permissions,
    input_model=DrivePermissionsInput,
    output_model=DrivePermissionsOutput,
    posture="write",
    scopes=[_DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "permissions.create|list|delete",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Share a file with a specific user",
        "input": {"file_id": "<file-id>", "action": "create", "type": "user", "role": "reader", "email_address": "user@example.com"},
        "cli": "google-kit drive permissions --file-id <file-id> --action create --type user --role reader --email-address user@example.com",
    }],
    keywords=["user"],
    plane="container",
    capability="file.share",
    flag=ENABLE_DRIVE_WRITE_FLAG,
))

register(OpSpec(
    name="drive.comments",
    fn=drive_comments,
    input_model=DriveCommentsInput,
    output_model=DriveCommentsOutput,
    posture="write",
    scopes=[_DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "comments.create|list",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Add a comment to a file",
        "input": {"file_id": "<file-id>", "action": "create", "content": "Please review section 2."},
        "cli": "google-kit drive comments --file-id <file-id> --action create --content 'Please review section 2.'",
    }],
    plane="container",
    capability="comment.create",
    flag=ENABLE_DRIVE_WRITE_FLAG,
))

register(OpSpec(
    name="drive.revisions",
    fn=drive_revisions,
    input_model=DriveRevisionsInput,
    output_model=DriveRevisionsOutput,
    posture="read",
    scopes=[_DRIVE_READONLY, _DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "revisions.list|get",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List revisions of a file",
        "input": {"file_id": "<file-id>"},
        "cli": "google-kit drive revisions --file-id <file-id>",
    }],
    plane="container",
    capability="revision.read",
))

register(OpSpec(
    name="drive.changes",
    fn=drive_changes,
    input_model=DriveChangesInput,
    output_model=DriveChangesOutput,
    posture="read",
    scopes=[_DRIVE_READONLY, _DRIVE_FILE],
    perf={
        "api": "Drive v3",
        "method": "changes.list|getStartPageToken",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get a start page token for change tracking",
        "input": {},
        "cli": "google-kit drive changes",
    }],
    plane="container",
    capability="changes.read",
))

register(OpSpec(
    name="drive.changes_watch",
    fn=drive_changes_watch,
    input_model=DriveChangesWatchInput,
    output_model=DriveChangesWatchOutput,
    posture="write",
    scopes=[_DRIVE_READONLY],
    perf={
        "api": "Drive v3",
        "method": "changes.watch",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Register an HTTPS push-notification channel for Drive changes",
        "input": {
            "page_token": "<start-page-token>",
            "channel_id": "<uuid>",
            "address": "https://example.com/webhook/drive",
            "expiration_ms": 1735689600000,
        },
        "cli": "google-kit drive changes-watch --page-token <token> --channel-id <uuid> --address https://example.com/webhook/drive",
        "notes": "Drive push delivers change events to an HTTPS webhook channel; the endpoint and channel identity must be provisioned by the operator.",
    }],
    plane="eventing",
    capability="eventing.watch",
    flag=ENABLE_DRIVE_WATCH_FLAG,
))
