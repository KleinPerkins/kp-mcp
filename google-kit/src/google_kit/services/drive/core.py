"""Core functions for the Drive service (12 ops: 4 cutover-minimum + 8 §7 coverage).

Parity coverage per op:

  drive_fetch         — mock-read DONE (REST paths); Sites path unit-tested via injected seam;
                        sandbox-e2e DEFERRED(P6)
  drive_create        — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  drive_search        — mock-read DONE; sandbox-e2e DEFERRED(P6)
  drive_upload        — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  drive_copy          — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  drive_update        — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  drive_trash         — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  drive_permissions   — mutation-request DONE (create); mock-read DONE (list);
                        sandbox-e2e DEFERRED(E2/E4)
  drive_comments      — mutation-request DONE (create); mock-read DONE (list);
                        sandbox-e2e DEFERRED(E2/E4)
  drive_revisions     — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
  drive_changes       — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
  drive_changes_watch — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)

Legacy quirks preserved:
  - drive_fetch: cascading export fallbacks (HTML→text strip → plain text export).
    Google Sites URL dispatches via injectable ``sites_fetcher`` seam
    (default raises RuntimeError with P6 guidance); Sites path: sandbox-e2e DEFERRED(P6).
  - drive_search: allDrives scope with 403 fallback to 'user' corpora.
  - drive_upload: R18 APPROVED DEVIATION (amended) — legacy ``cmd_upload`` called
    ``build_service(creds, 'drive')`` with positional args inverted (service name
    should be first, credentials second); the command was broken at runtime.
    google-kit implements the documented-correct behavior: a resumable upload that
    streams from disk (``MediaFileUpload`` when ``path`` is given) or from inline
    base64 (``MediaIoBaseUpload`` when ``content_b64`` is given), both
    ``resumable=True``. Sharing is PRIVATE by default; a world-readable
    ``permissions.create(type=anyone, role=reader)`` call is made ONLY when the
    caller opts in with ``share="anyone_reader"``. (The original R18 behavior
    auto-granted anyone/reader on every upload; that default was tightened to
    private-by-default — see docs/DECISIONS.md.)
  - drive_upload: when ``folder_id`` is absent, the upload target folder is found or
    created via a ``files.list`` + conditional ``files.create`` (not atomic with the upload).
"""
from __future__ import annotations

import base64
import binascii
import mimetypes
import os
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable

from google_kit.core.client import execute_api_call
from google_kit.core.errors import Permission, Validation
from google_kit.core.flags import FlagDisabledError, is_flag_enabled
from google_kit.core.normalize import Meta, OutputEnvelope, PageInfo

from .models import (
    DriveChangesData,
    DriveChangesInput,
    DriveChangesOutput,
    DriveChangesWatchData,
    DriveChangesWatchInput,
    DriveChangesWatchOutput,
    DriveCommentsData,
    DriveCommentsInput,
    DriveCommentsOutput,
    DriveCopyData,
    DriveCopyInput,
    DriveCopyOutput,
    DriveCreateData,
    DriveCreateInput,
    DriveCreateOutput,
    DriveFetchData,
    DriveFetchInput,
    DriveFetchOutput,
    DriveFileItem,
    DrivePermissionsData,
    DrivePermissionsInput,
    DrivePermissionsOutput,
    DriveRevisionsData,
    DriveRevisionsInput,
    DriveRevisionsOutput,
    DriveSearchData,
    DriveSearchInput,
    DriveSearchOutput,
    DriveTrashData,
    DriveTrashInput,
    DriveTrashOutput,
    DriveUpdateData,
    DriveUpdateInput,
    DriveUpdateOutput,
    DriveUploadData,
    DriveUploadInput,
    DriveUploadOutput,
)

# ─── MIME constants ───────────────────────────────────────────────────────────

_MIME_DOC = "application/vnd.google-apps.document"
_MIME_SHEET = "application/vnd.google-apps.spreadsheet"
_MIME_SLIDE = "application/vnd.google-apps.presentation"
_MIME_FOLDER = "application/vnd.google-apps.folder"
_MIME_SITE = "application/vnd.google-apps.site"

_MIME_MAP: dict[str, str] = {
    "doc": _MIME_DOC,
    "sheet": _MIME_SHEET,
    "slide": _MIME_SLIDE,
    "folder": _MIME_FOLDER,
}

_PLATFORM_MAP: dict[str, str] = {
    _MIME_DOC: "google_docs",
    _MIME_SHEET: "google_sheets",
    _MIME_SLIDE: "google_slides",
    _MIME_SITE: "google_sites",
    _MIME_FOLDER: "google_drive",
}

_SEARCH_MIME_MAP: dict[str, str] = {
    "doc": _MIME_DOC,
    "sheet": _MIME_SHEET,
    "slide": _MIME_SLIDE,
    "site": _MIME_SITE,
}

_EXT_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_META_FIELDS = (
    "id,name,mimeType,createdTime,modifiedTime,owners,"
    "lastModifyingUser,version,webViewLink,shared"
)

_SEARCH_FIELDS = (
    "files(id,name,mimeType,modifiedTime,owners,webViewLink,shared),nextPageToken"
)

_UPLOAD_FOLDER_NAME = "google-kit-uploads"

# ─── Security gates (audit High #1 / High #2 / Low #8) ────────────────────────

#: Capability gate for permission *mutations* (drive.permissions). Mirrors the
#: ADR F5 ``GOOGLE_KIT_ENABLE_GMAIL_WRITE`` pattern; wired at the adapter layer
#: via ``OpSpec.flag``.
ENABLE_DRIVE_WRITE_FLAG = "GOOGLE_KIT_ENABLE_DRIVE_WRITE"

#: Capability gate for the push-notification watch op (drive.changes_watch).
ENABLE_DRIVE_WATCH_FLAG = "GOOGLE_KIT_ENABLE_DRIVE_WATCH"

#: Distinct opt-in required before ANY world-readable (``type=anyone``) exposure:
#: ``drive.upload share="anyone_reader"`` and ``drive.permissions`` create with
#: ``type=anyone``. Public exposure is arg-specific, so this is enforced in core
#: (not expressible as a per-op ``OpSpec.flag``).
ENABLE_DRIVE_PUBLIC_SHARE_FLAG = "GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE"

#: Env var naming the root directory that ``drive.upload`` ``path`` sources must
#: stay within (after symlink resolution). Defaults to the operator's home.
UPLOAD_ROOT_ENV = "GOOGLE_KIT_UPLOAD_ROOT"

#: Hard cap on decoded ``content_b64`` bytes before buffering into memory.
MAX_INLINE_UPLOAD_BYTES = 10 * 1024 * 1024

_FILE_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]{20,})")
_SITES_URL_RE = re.compile(r"^https?://sites\.google\.com/")
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HTML_BLOCK_TAG_RE = re.compile(r"<(/?(h[1-6]|p|div|br|li|tr|td|th|blockquote|pre|ul|ol|table|hr)[^>]*)>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _wrap(data: Any, op: str, *, page: PageInfo | None = None) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, page=page, meta=Meta(op=op))


def _is_sites_url(url: str) -> bool:
    return bool(_SITES_URL_RE.match(url.strip()))


def _extract_file_id(url_or_id: str) -> str:
    m = _FILE_ID_RE.search(url_or_id.strip())
    return m.group(1) if m else url_or_id.strip()


def _escape_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _drive_datetime(value: str, *, end_of_day: bool = False) -> str:
    """Coerce YYYY-MM-DD or ISO datetime to a Drive query-safe UTC string."""
    raw = (value or "").strip()
    if not raw:
        raise Validation("empty date value", op="drive.search")
    if _DATE_ONLY_RE.match(raw):
        # The regex only proves digit *shape*; reject digit-shaped but invalid
        # calendar dates (e.g. 2026-13-99) before they reach the Drive query.
        try:
            datetime.strptime(raw, "%Y-%m-%d")
        except ValueError as exc:
            raise Validation(
                f"{raw!r} is not a valid calendar date (expected YYYY-MM-DD)",
                op="drive.search",
            ) from exc
        suffix = "23:59:59Z" if end_of_day else "00:00:00Z"
        return f"{raw}T{suffix}"
    parse_val = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(parse_val)
    except ValueError as exc:
        raise Validation(f"{raw!r} must be YYYY-MM-DD or ISO datetime", op="drive.search") from exc
    if parsed.tzinfo is None:
        raise Validation(f"{raw!r} must be timezone-aware", op="drive.search")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_search_query(inp: DriveSearchInput) -> str:
    clauses: list[str] = []
    if inp.query:
        clauses.append(f"fullText contains '{_escape_query_literal(inp.query)}'")
    if inp.name:
        clauses.append(f"name contains '{_escape_query_literal(inp.name)}'")
    if inp.doc_type and inp.doc_type != "all-google":
        mime = _SEARCH_MIME_MAP.get(inp.doc_type)
        if mime:
            clauses.append(f"mimeType = '{mime}'")
    elif inp.doc_type == "all-google":
        mime_clauses = [f"mimeType = '{m}'" for m in _SEARCH_MIME_MAP.values()]
        clauses.append(f"({' or '.join(mime_clauses)})")
    if inp.owner:
        clauses.append(f"'{_escape_query_literal(inp.owner)}' in owners")
    if inp.after:
        clauses.append(f"modifiedTime > '{_drive_datetime(inp.after)}'")
    if inp.before:
        clauses.append(f"modifiedTime < '{_drive_datetime(inp.before, end_of_day=True)}'")
    if inp.created_after:
        clauses.append(f"createdTime > '{_drive_datetime(inp.created_after)}'")
    if inp.created_before:
        clauses.append(f"createdTime < '{_drive_datetime(inp.created_before, end_of_day=True)}'")
    if inp.shared_with_me:
        clauses.append("sharedWithMe = true")
    if inp.starred:
        clauses.append("starred = true")
    clauses.append("trashed = false")
    return " and ".join(clauses)


def _strip_html(html: str) -> str:
    """Strip HTML tags, inserting newlines at block boundaries (no external dep)."""
    text = _HTML_BLOCK_TAG_RE.sub("\n", html)
    text = _HTML_TAG_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fetch_metadata(service: Any, file_id: str) -> dict[str, Any]:
    raw = execute_api_call(
        lambda: service.files().get(fileId=file_id, fields=_META_FIELDS).execute(),
        op="drive.fetch.meta",
        posture="read",
    )
    raw = raw or {}
    return {
        "id": raw.get("id", file_id),
        "title": raw.get("name", ""),
        "mime_type": raw.get("mimeType", ""),
        "platform": _PLATFORM_MAP.get(raw.get("mimeType", ""), "google_drive"),
        "web_url": raw.get("webViewLink"),
    }


def _sites_fetcher_default(url: str) -> tuple[dict[str, Any], str]:
    """Real Google Sites fetcher — requires Chrome + Playwright.

    Sites path: sandbox-e2e DEFERRED(P6). This path uses browser_cookie3 +
    headless Playwright Chromium, which cannot be exercised against MockGoogleService.
    """
    raise NotImplementedError(
        "Sites path: sandbox-e2e DEFERRED(P6). "
        "Real fetcher requires Chrome running with an active Google session, "
        "browser_cookie3, playwright, and Chromium installed."
    )


# ─── drive.fetch ─────────────────────────────────────────────────────────────


def drive_fetch(
    inp: DriveFetchInput,
    *,
    service: Any = None,
    sites_fetcher: Callable[[str], tuple[dict[str, Any], str]] = _sites_fetcher_default,
) -> DriveFetchOutput:
    """Fetch a Drive item's content (Docs/Sheets/Slides export, or Google Sites).

    Dispatch:
      - Google Sites URL → ``sites_fetcher`` seam (injectable; default raises
        NotImplementedError). Sites path: sandbox-e2e DEFERRED(P6).
      - All other Drive URLs/IDs → REST export cascade:
        1. ``files.export(mimeType="text/html")`` → strip tags (markdownify optional)
        2. ``files.export(mimeType="text/plain")`` fallback

    Parity: mock-read DONE (REST paths); Sites path: seam unit-tested with injected
    fake; sandbox-e2e DEFERRED(P6)
    """
    url = inp.url_or_id.strip()

    if _is_sites_url(url):
        meta, content = sites_fetcher(url)
        return _wrap(
            DriveFetchData(
                id=meta.get("id", url),
                title=meta.get("title", ""),
                mime_type=_MIME_SITE,
                platform="google_sites",
                content=content if not inp.metadata_only else None,
                fetch_method=meta.get("fetch_method", "sites_injected"),
                web_url=meta.get("web_url", url),
            ),
            "drive.fetch",
        )

    file_id = _extract_file_id(url)
    meta = _fetch_metadata(service, file_id)

    if inp.metadata_only:
        return _wrap(
            DriveFetchData(**meta, content=None, fetch_method="metadata_only"),
            "drive.fetch",
        )

    mime = meta["mime_type"]
    content: str | None = None
    fetch_method = "unknown"

    html_bytes = execute_api_call(
        lambda: service.files().export(fileId=file_id, mimeType="text/html").execute(),
        op="drive.fetch.export_html",
        posture="read",
    )
    if html_bytes:
        raw_html = html_bytes if isinstance(html_bytes, str) else html_bytes.decode("utf-8", errors="replace")
        try:
            from markdownify import markdownify as _md_convert
            content = re.sub(r"\n{3,}", "\n\n", _md_convert(raw_html, heading_style="ATX", bullets="-", strip=["img"])).strip()
            fetch_method = "drive_export_html_markdownify"
        except ImportError:
            content = _strip_html(raw_html)
            fetch_method = "drive_export_html_stripped"

    if not content:
        plain = execute_api_call(
            lambda: service.files().export(fileId=file_id, mimeType="text/plain").execute(),
            op="drive.fetch.export_text",
            posture="read",
        )
        if plain:
            content = plain if isinstance(plain, str) else plain.decode("utf-8", errors="replace")
            fetch_method = "drive_export_text"

    return _wrap(
        DriveFetchData(
            id=meta["id"],
            title=meta["title"],
            mime_type=mime,
            platform=meta["platform"],
            content=content,
            fetch_method=fetch_method,
            web_url=meta["web_url"],
        ),
        "drive.fetch",
    )


# ─── drive.create ────────────────────────────────────────────────────────────


def drive_create(
    inp: DriveCreateInput,
    *,
    service: Any = None,
) -> DriveCreateOutput:
    """Create a new Google Doc, Sheet, Slide, or folder in Drive.

    For doc/sheet/slide types, uses ``files.create`` with the appropriate
    Google Workspace MIME type (no content uploaded — creates a blank file).
    For ``folder`` type, creates a Drive folder. Optional ``folder_id`` places
    the new item inside that folder.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    mime = _MIME_MAP.get(inp.doc_type, _MIME_DOC)
    body: dict[str, Any] = {"name": inp.title, "mimeType": mime}
    if inp.folder_id:
        body["parents"] = [inp.folder_id]

    raw = execute_api_call(
        lambda: service.files().create(body=body, fields="id,name,webViewLink").execute(),
        op="drive.create",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    created = raw or {}
    file_id = created.get("id", "")
    url = created.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
    return _wrap(
        DriveCreateData(
            id=file_id,
            url=url,
            title=created.get("name", inp.title),
            doc_type=inp.doc_type,
        ),
        "drive.create",
    )


# ─── drive.search ────────────────────────────────────────────────────────────


def drive_search(
    inp: DriveSearchInput,
    *,
    service: Any = None,
) -> DriveSearchOutput:
    """Search Google Drive with rich filtering and pagination.

    Builds a Drive ``q`` query string from the input filters and calls
    ``files.list``. Paginates up to ``limit`` results. Falls back from
    ``allDrives`` corpora to ``user`` on 403 (matches legacy behaviour).

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    q = _build_search_query(inp)
    limit = inp.limit

    all_files: list[dict[str, Any]] = []
    page_token: str | None = None
    truncated = False
    corpora = inp.scope
    warnings: list[str] = []

    while len(all_files) < limit:
        page_size = min(limit - len(all_files), 100)
        # includeItemsFromAllDrives / supportsAllDrives only apply to the shared-
        # drive corpora; on the 'user' fallback they must be dropped (the API
        # rejects them without a shared-drive corpus).
        shared_drive_corpus = corpora != "user"
        list_kwargs: dict[str, Any] = {
            "q": q,
            "fields": _SEARCH_FIELDS,
            "pageSize": page_size,
            "orderBy": inp.sort,
            "corpora": corpora,
            "includeItemsFromAllDrives": shared_drive_corpus,
            "supportsAllDrives": shared_drive_corpus,
        }
        if page_token:
            list_kwargs["pageToken"] = page_token

        try:
            resp = execute_api_call(
                lambda kw=dict(list_kwargs): service.files().list(**kw).execute(),
                op="drive.search",
                posture="read",
            )
        except Permission:
            # Documented legacy parity: a caller without shared-drive access gets
            # a 403 from the 'allDrives' corpora. Fall back ONCE to the 'user'
            # corpora (the caller's own files) rather than surfacing the 403.
            if corpora != "allDrives":
                raise
            corpora = "user"
            warnings.append(
                "drive.search: 'allDrives' corpora returned 403 (no shared-drive "
                "access); fell back to 'user' corpora."
            )
            all_files = []
            page_token = None
            continue

        resp = resp or {}
        files = resp.get("files", [])
        all_files.extend(files)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if page_token and len(all_files) >= limit:
        truncated = True

    items = [
        DriveFileItem(
            id=f["id"],
            title=f.get("name", ""),
            type=_PLATFORM_MAP.get(f.get("mimeType", ""), f.get("mimeType", "unknown")),
            modified=f.get("modifiedTime", "")[:10] if f.get("modifiedTime") else None,
            owners=[
                o.get("displayName", o.get("emailAddress", "?"))
                for o in f.get("owners", [])
            ],
            url=f.get("webViewLink", ""),
            shared=f.get("shared", False),
        )
        for f in all_files[:limit]
    ]

    return OutputEnvelope(
        data=DriveSearchData(
            query=q,
            count=len(items),
            results=items,
            truncated=truncated,
        ),
        warnings=warnings,
        meta=Meta(op="drive.search"),
    )


# ─── drive.upload ────────────────────────────────────────────────────────────


def _resolve_upload_root() -> str:
    """Return the canonical (realpath) directory that ``path`` uploads must stay within."""
    raw = os.environ.get(UPLOAD_ROOT_ENV, "").strip() or os.path.expanduser("~")
    return os.path.realpath(raw)


def _ensure_path_within_root(path: str) -> None:
    """Reject an upload ``path`` that resolves outside the permitted upload root.

    Resolves symlinks (realpath) on BOTH the candidate and the root so a symlink
    planted inside the root cannot be used to read an arbitrary file outside it.
    """
    root = _resolve_upload_root()
    resolved = os.path.realpath(path)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise Validation(
            f"drive.upload path escapes the permitted upload root: {path!r} "
            f"resolves to {resolved!r}, which is outside {root!r}. "
            f"Set {UPLOAD_ROOT_ENV} to widen the allowed root.",
            op="drive.upload",
        )


def _require_public_share_optin(op: str) -> None:
    """Raise unless the operator explicitly opted into world-readable sharing."""
    if not is_flag_enabled(ENABLE_DRIVE_PUBLIC_SHARE_FLAG):
        raise FlagDisabledError(
            f"{op} public sharing (type=anyone) is off by default; "
            f"set {ENABLE_DRIVE_PUBLIC_SHARE_FLAG}=1 to enable it.",
            op=op,
        )


def _detect_mime(filename: str) -> str:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXT_MIME.get(suffix, "application/octet-stream")


def _resolve_upload_mime(mime_type: str | None, path: str | None, filename: str | None) -> str:
    """Resolve upload MIME: explicit wins; else guess from path/filename; else octet-stream."""
    if mime_type:
        return mime_type
    guessed, _ = mimetypes.guess_type(path or filename or "")
    return guessed or "application/octet-stream"


def _get_or_create_folder(service: Any, folder_name: str) -> str:
    """Find or create a Drive folder by name. Returns folder ID."""
    q = (
        f"name = '{_escape_query_literal(folder_name)}' "
        f"and mimeType = '{_MIME_FOLDER}' "
        f"and trashed = false"
    )
    resp = execute_api_call(
        lambda: service.files().list(q=q, spaces="drive", fields="files(id,name)").execute(),
        op="drive.upload.folder_lookup",
        posture="read",
    )
    folders = (resp or {}).get("files", [])
    if folders:
        return folders[0]["id"]

    folder_meta: dict[str, Any] = {"name": folder_name, "mimeType": _MIME_FOLDER}
    created = execute_api_call(
        lambda: service.files().create(body=folder_meta, fields="id").execute(),
        op="drive.upload.folder_create",
        posture="write",
        normalized_request={"folder_name": folder_name, "mimeType": _MIME_FOLDER},
    )
    return (created or {}).get("id", "")


def drive_upload(
    inp: DriveUploadInput,
    *,
    service: Any = None,
) -> DriveUploadOutput:
    """Upload a file to Google Drive via a resumable upload (private by default).

    Content source (exactly one, enforced by the input model):
      - ``path`` → stream from disk with ``MediaFileUpload(resumable=True)``.
        Works for any size and any binary content (no base64 round-trip).
      - ``content_b64`` → inline bytes via ``MediaIoBaseUpload(resumable=True)``.

    Sharing is PRIVATE by default: ``share="private"`` makes NO permissions call,
    so the uploaded file stays owner-private. ``share="anyone_reader"`` grants a
    single world-readable ``permissions.create(type=anyone, role=reader)``, and is
    refused unless the operator opts in with
    ``GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE=1`` (audit High #1).

    Containment (audit High #1): a ``path`` source must resolve (after symlink
    resolution) within ``GOOGLE_KIT_UPLOAD_ROOT`` (default: the operator's home);
    paths escaping that root are rejected before any disk read. An inline
    ``content_b64`` source is capped at ``MAX_INLINE_UPLOAD_BYTES`` decoded bytes
    (audit Low #8) — use ``path`` for larger files.

    History (R18, amended): legacy ``cmd_upload`` was broken at runtime, and the
    initial google-kit port unconditionally granted anyone/reader on every upload.
    That default was tightened — public sharing is now an explicit opt-in. See
    docs/DECISIONS.md.

    When ``folder_id`` is absent, the target folder is found or created via a
    ``files.list`` + conditional ``files.create`` call (not atomic with the upload).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

    if inp.share == "anyone_reader":
        _require_public_share_optin("drive.upload")

    mime = _resolve_upload_mime(inp.mime_type, inp.path, inp.filename)

    if inp.path is not None:
        if not os.path.exists(inp.path):
            raise Validation(f"drive.upload path does not exist: {inp.path!r}", op="drive.upload")
        if not os.path.isfile(inp.path):
            raise Validation(f"drive.upload path is not a regular file: {inp.path!r}", op="drive.upload")
        if not os.access(inp.path, os.R_OK):
            raise Validation(f"drive.upload path is not readable: {inp.path!r}", op="drive.upload")
        _ensure_path_within_root(inp.path)
        media: Any = MediaFileUpload(inp.path, mimetype=mime, resumable=True)
    else:
        try:
            content_bytes = base64.b64decode(inp.content_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise Validation("Invalid base64 content for drive.upload.", op="drive.upload") from exc
        if len(content_bytes) > MAX_INLINE_UPLOAD_BYTES:
            raise Validation(
                f"drive.upload content_b64 decodes to {len(content_bytes)} bytes, "
                f"exceeding the {MAX_INLINE_UPLOAD_BYTES}-byte inline cap; "
                f"use 'path' to stream large files from disk.",
                op="drive.upload",
            )
        media = MediaIoBaseUpload(BytesIO(content_bytes), mimetype=mime, resumable=True)

    display_name = inp.title or inp.filename or "upload"

    folder_id = inp.folder_id
    if not folder_id:
        folder_id = _get_or_create_folder(service, inp.folder_name)

    file_meta: dict[str, Any] = {
        "name": display_name,
        "parents": [folder_id],
    }

    uploaded = execute_api_call(
        lambda: service.files().create(
            body=file_meta, media_body=media, fields="id,name,webViewLink,mimeType"
        ).execute(),
        op="drive.upload",
        posture="write",
        # Exclude content_b64 from the audit record: it can be up to
        # MAX_INLINE_UPLOAD_BYTES of base64 and is payload, not a mutation target.
        normalized_request=inp.model_dump(exclude={"content_b64"}),
    )
    uploaded = uploaded or {}
    file_id = uploaded.get("id", "")
    url = uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")

    shared = False
    if inp.share == "anyone_reader":
        execute_api_call(
            lambda: service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
            ).execute(),
            op="drive.upload.permission",
            posture="write",
            normalized_request={"file_id": file_id, "type": "anyone", "role": "reader"},
            target_ids=[file_id],
        )
        shared = True

    return _wrap(
        DriveUploadData(
            id=file_id,
            url=url,
            name=uploaded.get("name", display_name),
            mime_type=uploaded.get("mimeType", mime),
            shared=shared,
        ),
        "drive.upload",
    )


# ─── drive.copy ───────────────────────────────────────────────────────────────


def drive_copy(
    inp: DriveCopyInput,
    *,
    service: Any = None,
) -> DriveCopyOutput:
    """Copy a Drive file, optionally renaming and/or placing it in a new folder.

    Parity: mutation-request DONE; sandbox-e2e live-PASS 2026-06-17
    """
    body: dict[str, Any] = {}
    if inp.name is not None:
        body["name"] = inp.name
    if inp.folder_id is not None:
        body["parents"] = [inp.folder_id]

    raw = execute_api_call(
        lambda: service.files().copy(
            fileId=inp.file_id, body=body, fields="id,name,webViewLink"
        ).execute(),
        op="drive.copy",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    created = raw or {}
    file_id = created.get("id", "")
    url = created.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
    return _wrap(
        DriveCopyData(
            id=file_id,
            url=url,
            name=created.get("name", inp.name or ""),
        ),
        "drive.copy",
    )


# ─── drive.update ─────────────────────────────────────────────────────────────


def drive_update(
    inp: DriveUpdateInput,
    *,
    service: Any = None,
) -> DriveUpdateOutput:
    """Rename, move, or update metadata on a Drive file (covers rename + MOVE).

    Parity: mutation-request DONE; sandbox-e2e live-PASS 2026-06-17
    """
    body: dict[str, Any] = {}
    if inp.name is not None:
        body["name"] = inp.name
    if inp.description is not None:
        body["description"] = inp.description
    if inp.starred is not None:
        body["starred"] = inp.starred

    kwargs: dict[str, Any] = {
        "fileId": inp.file_id,
        "body": body,
        "fields": "id,name,parents",
    }
    if inp.add_parents:
        kwargs["addParents"] = ",".join(inp.add_parents)
    if inp.remove_parents:
        kwargs["removeParents"] = ",".join(inp.remove_parents)

    raw = execute_api_call(
        lambda kw=dict(kwargs): service.files().update(**kw).execute(),
        op="drive.update",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    updated = raw or {}
    return _wrap(
        DriveUpdateData(
            id=updated.get("id", inp.file_id),
            name=updated.get("name", inp.name or ""),
            parents=updated.get("parents", []),
        ),
        "drive.update",
    )


# ─── drive.trash ──────────────────────────────────────────────────────────────


def drive_trash(
    inp: DriveTrashInput,
    *,
    service: Any = None,
) -> DriveTrashOutput:
    """Trash or untrash a Drive file via files.update (Drive v3 has no files.trash).

    Parity: mutation-request DONE; sandbox-e2e live-PASS 2026-06-17
    """
    body: dict[str, Any] = {"trashed": not inp.untrash}
    raw = execute_api_call(
        lambda: service.files().update(
            fileId=inp.file_id, body=body, fields="id,trashed,name"
        ).execute(),
        op="drive.trash",
        posture="destructive",
        normalized_request=inp.model_dump(),
    )
    updated = raw or {}
    return _wrap(
        DriveTrashData(
            id=updated.get("id", inp.file_id),
            trashed=updated.get("trashed", not inp.untrash),
        ),
        "drive.trash",
    )


# ─── drive.permissions ────────────────────────────────────────────────────────


def drive_permissions(
    inp: DrivePermissionsInput,
    *,
    service: Any = None,
) -> DrivePermissionsOutput:
    """Manage sharing permissions on a Drive file: list, create, or delete.

    Gating (audit High #2): the whole capability is off by default behind
    ``GOOGLE_KIT_ENABLE_DRIVE_WRITE`` (ADR F5 ``OpSpec.flag``, enforced at the
    CLI/MCP boundary) — including ``list``, since enumerating who can access a
    file is part of sharing management. A ``create`` with ``type=anyone``
    additionally requires the world-readable opt-in
    ``GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE`` (enforced here in core).

    Parity: mutation-request DONE (create); mock-read DONE (list); sandbox-e2e live-PASS 2026-06-17
    """
    if inp.action == "list":
        raw = execute_api_call(
            lambda: service.permissions().list(
                fileId=inp.file_id,
                fields="permissions(id,type,role,emailAddress,domain)",
            ).execute(),
            op="drive.permissions",
            posture="read",
        )
        raw = raw or {}
        return _wrap(
            DrivePermissionsData(action="list", permissions=raw.get("permissions", [])),
            "drive.permissions",
        )

    if inp.action == "create":
        if inp.type == "anyone":
            _require_public_share_optin("drive.permissions")
        perm_body: dict[str, Any] = {"type": inp.type, "role": inp.role}
        if inp.email_address:
            perm_body["emailAddress"] = inp.email_address
        if inp.domain:
            perm_body["domain"] = inp.domain
        raw = execute_api_call(
            lambda b=dict(perm_body): service.permissions().create(
                fileId=inp.file_id, body=b, fields="id,type,role,emailAddress"
            ).execute(),
            op="drive.permissions",
            posture="write",
            normalized_request=inp.model_dump(),
        )
        return _wrap(
            DrivePermissionsData(action="create", permission=raw or {}),
            "drive.permissions",
        )

    # action == "delete"
    execute_api_call(
        lambda: service.permissions().delete(
            fileId=inp.file_id, permissionId=inp.permission_id
        ).execute(),
        op="drive.permissions",
        posture="destructive",
        normalized_request=inp.model_dump(),
        target_ids=[inp.file_id],
    )
    return _wrap(
        DrivePermissionsData(action="delete", deleted=True),
        "drive.permissions",
    )


# ─── drive.comments ───────────────────────────────────────────────────────────


def drive_comments(
    inp: DriveCommentsInput,
    *,
    service: Any = None,
) -> DriveCommentsOutput:
    """Create or list comments on a Drive file.

    Parity: mutation-request DONE (create); mock-read DONE (list); sandbox-e2e live-PASS 2026-06-17
    """
    if inp.action == "list":
        raw = execute_api_call(
            lambda: service.comments().list(
                fileId=inp.file_id,
                fields="comments(id,content,author,resolved),nextPageToken",
            ).execute(),
            op="drive.comments",
            posture="read",
        )
        raw = raw or {}
        return _wrap(
            DriveCommentsData(action="list", comments=raw.get("comments", [])),
            "drive.comments",
        )

    # action == "create"
    body: dict[str, Any] = {"content": inp.content}
    raw = execute_api_call(
        lambda: service.comments().create(
            fileId=inp.file_id, body=body, fields="id,content,author,createdTime"
        ).execute(),
        op="drive.comments",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.file_id],
    )
    return _wrap(
        DriveCommentsData(action="create", comment=raw or {}),
        "drive.comments",
    )


# ─── drive.revisions ──────────────────────────────────────────────────────────


def drive_revisions(
    inp: DriveRevisionsInput,
    *,
    service: Any = None,
) -> DriveRevisionsOutput:
    """List or get revisions of a Drive file.

    Parity: mock-read DONE; sandbox-e2e live-PASS 2026-06-17
    """
    if inp.revision_id:
        raw = execute_api_call(
            lambda: service.revisions().get(
                fileId=inp.file_id,
                revisionId=inp.revision_id,
                fields="id,modifiedTime,lastModifyingUser,size",
            ).execute(),
            op="drive.revisions",
            posture="read",
        )
        return _wrap(
            DriveRevisionsData(revision=raw or {}),
            "drive.revisions",
        )

    raw = execute_api_call(
        lambda: service.revisions().list(
            fileId=inp.file_id,
            fields="revisions(id,modifiedTime,lastModifyingUser,size)",
        ).execute(),
        op="drive.revisions",
        posture="read",
    )
    raw = raw or {}
    return _wrap(
        DriveRevisionsData(revisions=raw.get("revisions", [])),
        "drive.revisions",
    )


# ─── drive.changes ────────────────────────────────────────────────────────────


def drive_changes(
    inp: DriveChangesInput,
    *,
    service: Any = None,
) -> DriveChangesOutput:
    """List Drive changes or get the start page token for change tracking.

    Parity: mock-read DONE; sandbox-e2e live-PASS 2026-06-17
    """
    if not inp.page_token:
        raw = execute_api_call(
            lambda: service.changes().getStartPageToken(
                fields="startPageToken"
            ).execute(),
            op="drive.changes",
            posture="read",
        )
        raw = raw or {}
        return _wrap(
            DriveChangesData(changes=[], new_start_page_token=raw.get("startPageToken")),
            "drive.changes",
        )

    raw = execute_api_call(
        lambda: service.changes().list(
            pageToken=inp.page_token,
            spaces="drive",
            fields="changes(fileId,removed,time,file(id,name,mimeType)),newStartPageToken,nextPageToken",
        ).execute(),
        op="drive.changes",
        posture="read",
    )
    raw = raw or {}
    return _wrap(
        DriveChangesData(
            changes=raw.get("changes", []),
            new_start_page_token=raw.get("newStartPageToken"),
        ),
        "drive.changes",
        page=PageInfo(next_page_token=raw.get("nextPageToken")),
    )


# ─── drive.changes_watch ──────────────────────────────────────────────────────


def drive_changes_watch(
    inp: DriveChangesWatchInput,
    *,
    service: Any = None,
) -> DriveChangesWatchOutput:
    """Register a Drive push-notification channel (web_hook) via changes.watch.

    Calls ``service.changes().watch(pageToken=<token>, body=<channel>).execute()``.
    The channel body includes ``id``, ``type="web_hook"``, and ``address``; the
    optional ``expiration`` field (Unix-epoch milliseconds) is included only when
    ``expiration_ms`` is provided.

    Note: Drive push delivers change events to an HTTPS webhook. The endpoint
    and channel identity must be provisioned by the operator before calling this op.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    body: dict[str, Any] = {
        "id": inp.channel_id,
        "type": "web_hook",
        "address": inp.address,
    }
    if inp.expiration_ms is not None:
        body["expiration"] = inp.expiration_ms

    raw = execute_api_call(
        lambda: service.changes().watch(pageToken=inp.page_token, body=body).execute(),
        op="drive.changes_watch",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    raw = raw or {}
    return _wrap(
        DriveChangesWatchData(
            id=raw.get("id", ""),
            resourceId=raw.get("resourceId", ""),
            resourceUri=raw.get("resourceUri", ""),
            expiration=raw.get("expiration"),
        ),
        "drive.changes_watch",
    )
