"""Tests for the drive.upload fix: path-based streaming + opt-in private sharing.

All tests inject a fake ``service=`` and capture calls — NO live network. They
cover the two production failures the fix addresses:
  1. base64-only could not move real binary files → path streaming from disk.
  2. uploads were auto-shared world-readable → private by default, explicit opt-in.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import ValidationError

from google_kit.services.drive.core import drive_upload
from google_kit.services.drive.models import DriveUploadInput


@pytest.fixture(autouse=True)
def _permit_uploads(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Scope these legacy upload tests under the new security gates.

    They stage files in ``tmp_path`` (outside the default home upload root) and
    exercise the explicit-opt-in public share, so widen the root to ``tmp_path``
    and enable the world-readable opt-in for the duration of each test.
    """
    monkeypatch.setenv("GOOGLE_KIT_UPLOAD_ROOT", str(tmp_path))
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", "1")


# ─── Fake service (captures calls; no network) ───────────────────────────────


@dataclass
class _Call:
    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class _Exec:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _FilesProxy:
    def __init__(self, responses: dict, log: list[_Call]) -> None:
        self._responses = responses
        self._log = log

    def list(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("files", "list", dict(kwargs)))
        return _Exec(self._responses.get(("files", "list"), {"files": [{"id": "folderX"}]}))

    def create(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("files", "create", dict(kwargs)))
        return _Exec(self._responses.get(("files", "create")))


class _PermissionsProxy:
    def __init__(self, responses: dict, log: list[_Call]) -> None:
        self._responses = responses
        self._log = log

    def create(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("permissions", "create", dict(kwargs)))
        return _Exec(self._responses.get(("permissions", "create"), {"id": "perm001"}))


class FakeDriveService:
    def __init__(self, responses: dict | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[_Call] = []

    def files(self) -> _FilesProxy:
        return _FilesProxy(self._responses, self.calls)

    def permissions(self) -> _PermissionsProxy:
        return _PermissionsProxy(self._responses, self.calls)

    def calls_for(self, resource: str, method: str) -> list[_Call]:
        return [c for c in self.calls if c.resource == resource and c.method == method]


_CREATE_RESP = {
    "id": "file001",
    "name": "upload",
    "webViewLink": "https://drive.google.com/file/d/file001/view",
}


def _svc(extra: dict | None = None) -> FakeDriveService:
    responses = {("files", "create"): dict(_CREATE_RESP)}
    if extra:
        responses.update(extra)
    return FakeDriveService(responses)


# ─── Path upload of real binary content (no base64 round-trip) ───────────────


def test_path_upload_streams_binary_file(tmp_path) -> None:
    from googleapiclient.http import MediaFileUpload

    binary = bytes(range(256)) + b"\xff\xfe\x00\x01not-utf8\x80\x81"
    p = tmp_path / "clip.bin"
    p.write_bytes(binary)

    svc = _svc()
    result = drive_upload(
        DriveUploadInput(path=str(p), folder_id="folder001"),
        service=svc,
    )

    creates = svc.calls_for("files", "create")
    assert len(creates) == 1
    media = creates[0].kwargs.get("media_body")
    assert isinstance(media, MediaFileUpload), "path upload must stream via MediaFileUpload"
    assert media.resumable() is True
    assert result.data.id == "file001"
    assert result.data.url == "https://drive.google.com/file/d/file001/view"


def test_path_upload_filename_defaults_to_basename(tmp_path) -> None:
    p = tmp_path / "my_report.pdf"
    p.write_bytes(b"%PDF-1.4 binary\x00\x01")

    svc = _svc()
    drive_upload(DriveUploadInput(path=str(p), folder_id="folder001"), service=svc)

    body = svc.calls_for("files", "create")[0].kwargs["body"]
    assert body["name"] == "my_report.pdf"


def test_path_upload_mime_inferred_from_extension(tmp_path) -> None:
    p = tmp_path / "image.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n binary")

    # No mimeType in the create response → output falls back to resolved MIME.
    svc = _svc()
    result = drive_upload(DriveUploadInput(path=str(p), folder_id="folder001"), service=svc)

    assert result.data.mime_type == "image/png"


# ─── Private by default; explicit opt-in sharing ─────────────────────────────


def test_default_share_is_private_no_permission_call(tmp_path) -> None:
    p = tmp_path / "secret.bin"
    p.write_bytes(b"\x00\x01\x02secret")

    svc = _svc()
    result = drive_upload(DriveUploadInput(path=str(p), folder_id="folder001"), service=svc)

    assert svc.calls_for("permissions", "create") == []
    assert result.data.shared is False


def test_share_anyone_reader_grants_public_permission_once(tmp_path) -> None:
    p = tmp_path / "public.bin"
    p.write_bytes(b"\x00public")

    svc = _svc()
    result = drive_upload(
        DriveUploadInput(path=str(p), folder_id="folder001", share="anyone_reader"),
        service=svc,
    )

    perms = svc.calls_for("permissions", "create")
    assert len(perms) == 1
    assert perms[0].kwargs["body"] == {"type": "anyone", "role": "reader"}
    assert result.data.shared is True


# ─── Source validation: exactly one of {content_b64, path} ───────────────────


def test_both_sources_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        DriveUploadInput(content_b64=base64.b64encode(b"x").decode(), path="/tmp/x", filename="x")


def test_neither_source_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        DriveUploadInput(filename="x")


# ─── Path validation errors are clear ValueErrors (not tracebacks) ───────────


def test_nonexistent_path_raises_value_error() -> None:
    svc = _svc()
    with pytest.raises(ValueError, match="does not exist"):
        drive_upload(
            DriveUploadInput(path="/no/such/file/anywhere.bin", folder_id="folder001"),
            service=svc,
        )
    assert svc.calls == []


def test_directory_path_raises_value_error(tmp_path) -> None:
    svc = _svc()
    with pytest.raises(ValueError, match="not a regular file"):
        drive_upload(
            DriveUploadInput(path=str(tmp_path), folder_id="folder001"),
            service=svc,
        )
    assert svc.calls == []


# ─── Back-compat: inline base64 still works ──────────────────────────────────


def test_content_b64_backcompat(tmp_path) -> None:
    from googleapiclient.http import MediaIoBaseUpload

    svc = _svc()
    content_b64 = base64.b64encode(b"hello inline").decode()
    result = drive_upload(
        DriveUploadInput(content_b64=content_b64, filename="note.txt", folder_id="folder001"),
        service=svc,
    )

    creates = svc.calls_for("files", "create")
    assert len(creates) == 1
    media = creates[0].kwargs.get("media_body")
    assert isinstance(media, MediaIoBaseUpload)
    assert media.resumable() is True
    assert result.data.id == "file001"
    assert result.data.shared is False
