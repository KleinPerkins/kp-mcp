"""Pre-mortem / adversarial E2E suite (QA workstream #6).

Deliberately feeds google-kit malformed, missing, contradictory, oversized, and
permission-denied inputs across both surfaces (CLI + MCP) and the core/model
layer, and asserts the kit ALWAYS degrades into a *structured* signal —
``pydantic.ValidationError`` at the model boundary, a ``GoogleKitError`` subclass
(``Validation`` / ``Permission`` / ``NotFound`` / ``FlagDisabledError``) through
the core, a non-zero CLI exit code with a redacted stderr message, or a
structured MCP error payload. Never a silent success, and never a raw traceback
escaping to the CLI stdout/stderr or the MCP transport.

Attack categories (see module-level test classes):
  1. Malformed parameters        — wrong types, invalid enums, empty strings.
  2. Missing required parameters  — required field omitted.
  3. Mutually exclusive params    — drive.upload path AND/NEITHER content_b64.
  4. Writes when flag disabled    — per-service write gate (registry + CLI + MCP).
  5. Invalid chars in queries     — bad dates; query-literal injection escaping.
  6. File sizes exceeding limits  — content_b64 > 10 MiB; path outside UPLOAD_ROOT.
  7. Permission-denied responses  — 403 -> Permission, 404 -> NotFound fakes.
  8. Pagination edge cases        — empty page, truncated token.
  9. Oversized batch arrays       — gmail.batch_modify > 1000 IDs.

All Google I/O is faked in-process (no Keychain, no network).
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Callable

import pytest
from pydantic import ValidationError

import google_kit  # noqa: F401 — triggers service auto-registration
from google_kit.cli import main as cli_main
from google_kit.core.errors import GoogleKitError, NotFound, Permission, Validation
from google_kit.core.flags import ENABLE_WRITES_FLAG, FlagDisabledError, ensure_enabled
from google_kit.mcp import build_mcp_server
from google_kit.registry import all_specs

_MUTATING = {"write", "destructive"}
_TRACEBACK_MARKER = "Traceback (most recent call last)"


# ─────────────────────────────────────────────────────────────────────────────
# In-process fake Google service (chainable; raises on demand for 403/404 fakes)
# ─────────────────────────────────────────────────────────────────────────────

#: Terminal API verbs; every other accessor is treated as a (recursing) resource.
_VERBS = {
    "list", "get", "create", "update", "delete", "patch", "insert", "copy",
    "export", "batchModify", "getBatchGet", "send", "watch", "getStartPageToken",
    "renew", "batchUpdate", "searchDirectoryPeople", "listDirectoryPeople",
}


def _http_error(status: int, message: str = "denied") -> Exception:
    """Build a real ``googleapiclient`` HttpError for a given status code."""
    import httplib2
    from googleapiclient.errors import HttpError

    resp = httplib2.Response({"status": status})
    content = json.dumps({"error": {"message": message}}).encode("utf-8")
    return HttpError(resp, content)


class _Exec:
    def __init__(self, producer: Callable[[], Any]) -> None:
        self._producer = producer

    def execute(self) -> Any:
        return self._producer()


class _Node:
    def __init__(self, root: "FakeService", path: list[str]) -> None:
        self._root = root
        self._path = path

    def __getattr__(self, name: str) -> Any:
        def _method(**kwargs: Any) -> Any:
            if name not in _VERBS:
                return _Node(self._root, [*self._path, name])
            resource = ".".join(self._path)
            self._root.calls.append((resource, name, kwargs))
            return _Exec(lambda: self._root.handler(resource, name, kwargs))

        return _method


class FakeService(_Node):
    """Chainable fake ``googleapiclient`` service.

    ``handler(resource, method, kwargs)`` returns the canned response or raises
    (e.g. an injected ``HttpError``). ``calls`` records every dispatched verb so
    tests can assert that a guard fired *before* any API round-trip.
    """

    def __init__(self, handler: Callable[[str, str, dict[str, Any]], Any] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._handler = handler or (lambda *_: {})
        super().__init__(self, [])

    def handler(self, resource: str, method: str, kwargs: dict[str, Any]) -> Any:
        return self._handler(resource, method, kwargs)


def _factory_for(svc: FakeService) -> Callable[..., FakeService]:
    def factory(op_name: str, *, profile: str | None = None) -> FakeService:
        del op_name, profile
        return svc

    return factory


def _clear_write_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every GOOGLE_KIT_ENABLE_* opt-in so write gates are all closed."""
    import os

    for key in list(os.environ):
        if key.startswith("GOOGLE_KIT_ENABLE"):
            monkeypatch.delenv(key, raising=False)


def _call_mcp(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Drive a tool call through the registered MCP CallToolRequest handler."""
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=arguments),
        )
        return await handler(req)

    result = asyncio.run(_run())
    return getattr(result, "root", result)


def _mcp_text(root: Any) -> str:
    assert root.content, "MCP result carried no content"
    return root.content[0].text


def _assert_structured_mcp_error(text: str) -> dict[str, Any]:
    """A structured MCP error: parseable JSON with error+message, no traceback, no data."""
    assert _TRACEBACK_MARKER not in text, f"raw traceback leaked to MCP transport: {text!r}"
    payload = json.loads(text)  # must be valid JSON, not a bare string dump
    assert "error" in payload and payload["error"], f"no error class in payload: {payload}"
    assert payload.get("message"), f"no message in payload: {payload}"
    assert "data" not in payload, f"error payload masqueraded as a success envelope: {payload}"
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# 1. Malformed parameters — wrong types, invalid enums, empty strings
# ─────────────────────────────────────────────────────────────────────────────


def _malformed_cases() -> list[tuple[str, Callable[[], Any]]]:
    from google_kit.services.drive.models import (
        DriveCreateInput,
        DrivePermissionsInput,
        DriveSearchInput,
    )
    from google_kit.services.gmail.models import GmailListInput, GmailSearchInput
    from google_kit.services.tasks.models import TasksListListsInput

    return [
        # invalid enum value
        ("drive.create bad doc_type", lambda: DriveCreateInput(title="x", doc_type="pdf")),
        ("drive.search bad scope", lambda: DriveSearchInput(scope="everywhere")),
        ("drive.permissions bad action", lambda: DrivePermissionsInput(file_id="f", action="grant")),
        # wrong scalar type (string that is not int-coercible)
        ("gmail.list non-int max_results", lambda: GmailListInput(max_results="lots")),
        ("tasks.list_lists non-int max", lambda: TasksListListsInput(max_results="all")),
        # out-of-bounds numeric (ge/le)
        ("drive.search limit too high", lambda: DriveSearchInput(limit=10_000)),
        ("drive.search limit too low", lambda: DriveSearchInput(limit=0)),
        ("gmail.search max_results too high", lambda: GmailSearchInput(q="x", max_results=99_999)),
    ]


@pytest.mark.parametrize("label,factory", _malformed_cases(), ids=[c[0] for c in _malformed_cases()])
def test_malformed_parameters_raise_validation_error(label: str, factory: Callable[[], Any]) -> None:
    with pytest.raises(ValidationError):
        factory()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Missing required parameters
# ─────────────────────────────────────────────────────────────────────────────


def _missing_required_cases() -> list[tuple[str, Callable[[], Any]]]:
    from google_kit.services.drive.models import DriveCopyInput, DriveFetchInput
    from google_kit.services.gmail.models import GmailGetInput, GmailSendInput
    from google_kit.services.people.models import PeopleGetInput

    return [
        ("drive.fetch missing url_or_id", lambda: DriveFetchInput()),
        ("drive.copy missing file_id", lambda: DriveCopyInput()),
        ("gmail.get missing message_id", lambda: GmailGetInput()),
        ("gmail.send missing to/subject/body", lambda: GmailSendInput(subject="hi")),
        ("people.get missing resource_name", lambda: PeopleGetInput()),
    ]


@pytest.mark.parametrize(
    "label,factory", _missing_required_cases(), ids=[c[0] for c in _missing_required_cases()]
)
def test_missing_required_parameters_raise_validation_error(label: str, factory: Callable[[], Any]) -> None:
    with pytest.raises(ValidationError):
        factory()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Mutually exclusive parameters — drive.upload content source
# ─────────────────────────────────────────────────────────────────────────────


def test_drive_upload_rejects_both_sources() -> None:
    from google_kit.services.drive.models import DriveUploadInput

    with pytest.raises(ValidationError, match="exactly one"):
        DriveUploadInput(path="/tmp/x", content_b64="QQ==", folder_id="f")


def test_drive_upload_rejects_neither_source() -> None:
    from google_kit.services.drive.models import DriveUploadInput

    with pytest.raises(ValidationError, match="exactly one"):
        DriveUploadInput(filename="x.txt", folder_id="f")


def test_drive_changes_watch_rejects_non_https() -> None:
    from google_kit.services.drive.models import DriveChangesWatchInput

    with pytest.raises(ValidationError, match="https"):
        DriveChangesWatchInput(page_token="t", channel_id="c", address="http://insecure.example/x")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Writes when the write flag is disabled
# ─────────────────────────────────────────────────────────────────────────────


def _one_write_op_per_service() -> list[Any]:
    """First flag-gated mutating op per service (covers 'each service sample')."""
    by_service: dict[str, Any] = {}
    for spec in all_specs():
        if spec.posture in _MUTATING and spec.flag:
            svc = spec.name.split(".")[0]
            by_service.setdefault(svc, spec)
    return list(by_service.values())


@pytest.mark.parametrize(
    "spec", _one_write_op_per_service(), ids=[s.name for s in _one_write_op_per_service()]
)
def test_every_write_op_is_blocked_when_flag_disabled(
    spec: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_write_flags(monkeypatch)
    with pytest.raises(FlagDisabledError) as exc:
        ensure_enabled(spec)
    # Structured: a GoogleKitError carrying the op name and a non-zero exit code.
    assert isinstance(exc.value, GoogleKitError)
    assert exc.value.op == spec.name
    assert exc.value.to_exit_code() != 0
    assert spec.flag in str(exc.value)


def test_cli_write_blocked_without_flag_drive_create(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_write_flags(monkeypatch)
    svc = FakeService()
    with pytest.raises(SystemExit) as exc:
        cli_main(
            ["drive", "create", "--title", "Doc", "--doc-type", "doc"],
            _service_factory=_factory_for(svc),
        )
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "GOOGLE_KIT_ENABLE_DRIVE_WRITE" in err
    assert _TRACEBACK_MARKER not in err
    assert svc.calls == [], "no Google API call may fire when the gate blocks"


def test_mcp_write_blocked_returns_structured_payload(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_write_flags(monkeypatch)
    svc = FakeService()
    server = build_mcp_server(_service_factory=_factory_for(svc))
    root = _call_mcp(server, "tasks_create", {"title": "Task"})
    payload = _assert_structured_mcp_error(_mcp_text(root))
    assert payload["error"] == "FlagDisabledError"
    assert svc.calls == [], "no Google API call may fire when the gate blocks"


def test_cli_write_allowed_with_umbrella_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_write_flags(monkeypatch)
    monkeypatch.setenv(ENABLE_WRITES_FLAG, "1")

    def handler(resource: str, method: str, kwargs: dict[str, Any]) -> Any:
        return {"id": "f1", "name": "Doc", "webViewLink": "https://drive/f1"}

    svc = FakeService(handler)
    cli_main(
        ["drive", "create", "--title", "Doc", "--doc-type", "doc"],
        _service_factory=_factory_for(svc),
    )
    out = json.loads(capsys.readouterr().out)
    assert out["data"]["id"] == "f1"
    assert any(method == "create" for _, method, _ in svc.calls)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Invalid characters in queries / filenames
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad_date", ["not-a-date", "2026-13-99", "12/31/2026", "yesterday"])
def test_drive_search_bad_date_is_structured_validation(bad_date: str) -> None:
    from google_kit.services.drive.core import drive_search
    from google_kit.services.drive.models import DriveSearchInput

    svc = FakeService()
    with pytest.raises(Validation) as exc:
        drive_search(DriveSearchInput(after=bad_date), service=svc)
    # Structured taxonomy error (and still a ValueError for back-compat callers).
    assert isinstance(exc.value, GoogleKitError)
    assert isinstance(exc.value, ValueError)
    assert svc.calls == [], "must reject the malformed date before any files.list"


def test_drive_search_escapes_query_injection() -> None:
    """A query containing quotes/backslashes must be escaped into the Drive q-string."""
    from google_kit.services.drive.core import drive_search
    from google_kit.services.drive.models import DriveSearchInput

    captured: dict[str, Any] = {}

    def handler(resource: str, method: str, kwargs: dict[str, Any]) -> Any:
        captured.update(kwargs)
        return {"files": []}

    svc = FakeService(handler)
    drive_search(DriveSearchInput(query="a' or name contains '\\evil"), service=svc)
    q = captured["q"]
    # The raw apostrophe is backslash-escaped, not left to break out of the literal.
    assert "\\'" in q
    assert "\\\\" in q


def test_drive_search_bad_date_via_mcp_is_structured() -> None:
    server = build_mcp_server(_service_factory=_factory_for(FakeService()))
    root = _call_mcp(server, "drive_search", {"after": "not-a-date"})
    payload = _assert_structured_mcp_error(_mcp_text(root))
    assert payload["error"] == "Validation"


# ─────────────────────────────────────────────────────────────────────────────
# 6. File sizes exceeding limits / path containment
# ─────────────────────────────────────────────────────────────────────────────


def test_drive_upload_oversize_content_b64_is_structured_validation() -> None:
    from google_kit.services.drive.core import MAX_INLINE_UPLOAD_BYTES, drive_upload
    from google_kit.services.drive.models import DriveUploadInput

    oversized = base64.b64encode(b"x" * (MAX_INLINE_UPLOAD_BYTES + 1)).decode()
    svc = FakeService()
    with pytest.raises(Validation, match="inline cap"):
        drive_upload(
            DriveUploadInput(content_b64=oversized, filename="big.bin", folder_id="f1"),
            service=svc,
        )
    assert svc.calls == []


def test_drive_upload_invalid_base64_is_structured_validation() -> None:
    from google_kit.services.drive.core import drive_upload
    from google_kit.services.drive.models import DriveUploadInput

    svc = FakeService()
    with pytest.raises(Validation, match="Invalid base64"):
        drive_upload(
            DriveUploadInput(content_b64="!!!not-base64!!!", filename="x.txt", folder_id="f1"),
            service=svc,
        )
    assert svc.calls == []


def test_drive_upload_path_outside_root_is_structured_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from google_kit.services.drive.core import UPLOAD_ROOT_ENV, drive_upload
    from google_kit.services.drive.models import DriveUploadInput

    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setenv(UPLOAD_ROOT_ENV, str(root))
    outside = tmp_path / "secret.txt"
    outside.write_text("classified")

    svc = FakeService()
    with pytest.raises(Validation, match="escapes the permitted upload root"):
        drive_upload(DriveUploadInput(path=str(outside), folder_id="f1"), service=svc)
    assert svc.calls == []


def test_drive_upload_oversize_via_mcp_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    from google_kit.services.drive.core import MAX_INLINE_UPLOAD_BYTES

    _clear_write_flags(monkeypatch)
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_WRITE", "1")
    oversized = base64.b64encode(b"x" * (MAX_INLINE_UPLOAD_BYTES + 1)).decode()
    svc = FakeService()
    server = build_mcp_server(_service_factory=_factory_for(svc))
    root = _call_mcp(
        server, "drive_upload", {"content_b64": oversized, "filename": "big.bin", "folder_id": "f1"}
    )
    payload = _assert_structured_mcp_error(_mcp_text(root))
    assert payload["error"] == "Validation"
    assert svc.calls == []


def test_drive_upload_invalid_base64_via_cli_exits_validation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_write_flags(monkeypatch)
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_WRITE", "1")
    svc = FakeService()
    with pytest.raises(SystemExit) as exc:
        cli_main(
            ["drive", "upload", "--content-b64", "!!!bad!!!", "--filename", "x.txt", "--folder-id", "f1"],
            _service_factory=_factory_for(svc),
        )
    # Validation -> exit code 7 (taxonomy), redacted message, no traceback.
    assert exc.value.code == 7
    err = capsys.readouterr().err
    assert "Invalid base64" in err
    assert _TRACEBACK_MARKER not in err
    assert svc.calls == []


# ─────────────────────────────────────────────────────────────────────────────
# 7. Permission-denied API responses (403 / 404 fakes) -> taxonomy
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,exc_type,exit_code",
    [(403, Permission, 5), (404, NotFound, 6)],
)
def test_api_http_error_classifies_to_taxonomy(status: int, exc_type: type, exit_code: int) -> None:
    from google_kit.services.people.core import people_get
    from google_kit.services.people.models import PeopleGetInput

    def handler(resource: str, method: str, kwargs: dict[str, Any]) -> Any:
        raise _http_error(status)

    svc = FakeService(handler)
    with pytest.raises(exc_type) as exc:
        people_get(PeopleGetInput(resource_name="people/x"), service=svc)
    assert exc.value.to_exit_code() == exit_code


def test_api_403_via_cli_exits_permission(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def handler(resource: str, method: str, kwargs: dict[str, Any]) -> Any:
        raise _http_error(403)

    svc = FakeService(handler)
    with pytest.raises(SystemExit) as exc:
        cli_main(
            ["people", "get", "--resource-name", "people/x"],
            _service_factory=_factory_for(svc),
        )
    assert exc.value.code == 5  # Permission
    assert _TRACEBACK_MARKER not in capsys.readouterr().err


def test_api_404_via_mcp_is_structured() -> None:
    def handler(resource: str, method: str, kwargs: dict[str, Any]) -> Any:
        raise _http_error(404)

    server = build_mcp_server(_service_factory=_factory_for(FakeService(handler)))
    root = _call_mcp(server, "people_get", {"resource_name": "people/x"})
    payload = _assert_structured_mcp_error(_mcp_text(root))
    assert payload["error"] == "NotFound"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Pagination edge cases — empty page, truncated token
# ─────────────────────────────────────────────────────────────────────────────


def test_drive_search_empty_page_returns_zero_results() -> None:
    from google_kit.services.drive.core import drive_search
    from google_kit.services.drive.models import DriveSearchInput

    svc = FakeService(lambda *a: {"files": []})
    out = drive_search(DriveSearchInput(name="nothing"), service=svc)
    assert out.data.count == 0
    assert out.data.results == []
    assert out.data.truncated is False


def test_drive_search_truncates_when_limit_reached_with_token() -> None:
    from google_kit.services.drive.core import drive_search
    from google_kit.services.drive.models import DriveSearchInput

    def handler(resource: str, method: str, kwargs: dict[str, Any]) -> Any:
        # Always offer another page so reaching the limit must mark truncation.
        return {
            "files": [{"id": "f1", "name": "A", "mimeType": "x"}],
            "nextPageToken": "MORE",
        }

    svc = FakeService(handler)
    out = drive_search(DriveSearchInput(name="x", limit=1), service=svc)
    assert out.data.count == 1
    assert out.data.truncated is True


def test_drive_changes_truncated_token_surfaced() -> None:
    from google_kit.services.drive.core import drive_changes
    from google_kit.services.drive.models import DriveChangesInput

    def handler(resource: str, method: str, kwargs: dict[str, Any]) -> Any:
        return {"changes": [], "nextPageToken": "NEXT", "newStartPageToken": None}

    svc = FakeService(handler)
    out = drive_changes(DriveChangesInput(page_token="start"), service=svc)
    assert out.page is not None
    assert out.page.next_page_token == "NEXT"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Oversized batch arrays
# ─────────────────────────────────────────────────────────────────────────────


def test_gmail_batch_modify_empty_ids_rejected() -> None:
    from google_kit.services.gmail.models import GmailBatchModifyInput

    with pytest.raises(ValidationError, match="at least one"):
        GmailBatchModifyInput(ids=[], add_label_ids=["L"])


def test_gmail_batch_modify_no_labels_rejected() -> None:
    from google_kit.services.gmail.models import GmailBatchModifyInput

    with pytest.raises(ValidationError, match="add_label_ids or remove_label_ids"):
        GmailBatchModifyInput(ids=["m1"])


def test_gmail_batch_modify_oversized_ids_are_chunked_not_dropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """An id list over Gmail's 1000-per-call cap is split into bounded calls.

    The adversarial concern is silent loss/oversend: assert every id is sent
    exactly once across <=1000-id chunks and the aggregate count is exact.
    """
    import google_kit.core.audit as audit_mod
    from google_kit.services.gmail.core import gmail_batch_modify
    from google_kit.services.gmail.models import GmailBatchModifyInput

    monkeypatch.setattr(audit_mod, "_DEFAULT_AUDIT_PATH", tmp_path / "audit.jsonl")

    ids = [f"m{i}" for i in range(2500)]
    svc = FakeService(lambda *a: None)  # batchModify returns 204/empty
    result = gmail_batch_modify(
        GmailBatchModifyInput(ids=ids, add_label_ids=["IMPORTANT"]),
        service=svc,
    )
    batch_calls = [c for c in svc.calls if c[1] == "batchModify"]
    assert [len(c[2]["body"]["ids"]) for c in batch_calls] == [1000, 1000, 500]
    recombined = [mid for c in batch_calls for mid in c[2]["body"]["ids"]]
    assert recombined == ids, "oversized batch must not drop or reorder ids"
    assert result.data.modified_count == 2500


def test_people_batch_get_large_list_handled_without_error() -> None:
    """A large people.batch_get request is forwarded intact (no client crash)."""
    from google_kit.services.people.core import people_batch_get
    from google_kit.services.people.models import PeopleBatchGetInput

    captured: dict[str, Any] = {}

    def handler(resource: str, method: str, kwargs: dict[str, Any]) -> Any:
        captured.update(kwargs)
        return {"responses": []}

    svc = FakeService(handler)
    names = [f"people/{i}" for i in range(500)]
    out = people_batch_get(PeopleBatchGetInput(resource_names=names), service=svc)
    assert out.data.count == 0
    assert captured["resourceNames"] == names


# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting: unknown MCP arguments + unknown tool never leak a traceback
# ─────────────────────────────────────────────────────────────────────────────


def test_mcp_unknown_argument_is_structured() -> None:
    server = build_mcp_server(_service_factory=_factory_for(FakeService()))
    root = _call_mcp(server, "drive_search", {"name": "x", "bogus_param": 1})
    payload = _assert_structured_mcp_error(_mcp_text(root))
    assert payload["error"] == "Validation"


def test_mcp_unknown_tool_does_not_emit_traceback() -> None:
    server = build_mcp_server(_service_factory=_factory_for(FakeService()))
    root = _call_mcp(server, "this_tool_does_not_exist", {})
    assert root.isError is True
    assert _TRACEBACK_MARKER not in _mcp_text(root)
