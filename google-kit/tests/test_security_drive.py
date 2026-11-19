"""Security-hardening tests for the Drive service (audit High #1/#2, Medium #4, Low #7/#8).

Covers the gaps closed after the read-only security audit:

  High #1 — drive.upload path containment (GOOGLE_KIT_UPLOAD_ROOT + symlink escape)
            and world-readable share opt-in (GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE).
  High #2 — drive.permissions write gate (OpSpec.flag GOOGLE_KIT_ENABLE_DRIVE_WRITE)
            and type=anyone public-share opt-in.
  Medium #4 — drive.changes_watch address must be https:// + OpSpec.flag.
  Low #8  — drive.upload content_b64 decoded-size cap.
  Low #7  — CLI redacts non-GoogleKitError error output.

All tests inject a fake ``service=`` / ``_service_factory`` and capture calls — no
network. The fakes assert that gated/invalid requests never dispatch to Drive.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import ValidationError

from google_kit.core.flags import FlagDisabledError
from google_kit.services.drive.core import (
    MAX_INLINE_UPLOAD_BYTES,
    drive_permissions,
    drive_upload,
)
from google_kit.services.drive.models import (
    DriveChangesWatchInput,
    DrivePermissionsInput,
    DriveUploadInput,
)


# ─── Fake Drive service (captures calls; no network) ─────────────────────────


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
        return _Exec(self._responses.get(("files", "create"), {
            "id": "file001",
            "name": "upload",
            "webViewLink": "https://drive.google.com/file/d/file001/view",
        }))


class _PermissionsProxy:
    def __init__(self, responses: dict, log: list[_Call]) -> None:
        self._responses = responses
        self._log = log

    def create(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("permissions", "create", dict(kwargs)))
        return _Exec(self._responses.get(("permissions", "create"), {"id": "perm001"}))

    def list(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("permissions", "list", dict(kwargs)))
        return _Exec(self._responses.get(("permissions", "list"), {"permissions": []}))


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


# ─── High #1: drive.upload path containment ──────────────────────────────────


class TestUploadPathContainment:
    def test_path_within_upload_root_is_allowed(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "root"
        root.mkdir()
        f = root / "ok.txt"
        f.write_bytes(b"hello")
        monkeypatch.setenv("GOOGLE_KIT_UPLOAD_ROOT", str(root))

        svc = FakeDriveService()
        result = drive_upload(DriveUploadInput(path=str(f), folder_id="folder1"), service=svc)

        assert result.data.id == "file001"
        assert svc.calls_for("files", "create"), "in-root upload must dispatch"

    def test_path_outside_upload_root_is_rejected(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_bytes(b"top secret")
        monkeypatch.setenv("GOOGLE_KIT_UPLOAD_ROOT", str(root))

        svc = FakeDriveService()
        with pytest.raises(ValueError, match="escapes the permitted upload root"):
            drive_upload(DriveUploadInput(path=str(secret), folder_id="folder1"), service=svc)
        assert svc.calls == [], "rejected path must not dispatch to Drive"

    def test_symlink_escape_is_rejected(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_bytes(b"top secret")
        link = root / "innocent.txt"
        os.symlink(secret, link)
        monkeypatch.setenv("GOOGLE_KIT_UPLOAD_ROOT", str(root))

        svc = FakeDriveService()
        with pytest.raises(ValueError, match="escapes the permitted upload root"):
            drive_upload(DriveUploadInput(path=str(link), folder_id="folder1"), service=svc)
        assert svc.calls == [], "symlink escape must not dispatch to Drive"

    def test_default_root_is_home_rejects_tmp(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No explicit root → default is the operator's home; a tmp path (outside
        # home) must be rejected, proving the default gate is active.
        monkeypatch.delenv("GOOGLE_KIT_UPLOAD_ROOT", raising=False)
        f = tmp_path / "elsewhere.txt"
        f.write_bytes(b"data")

        svc = FakeDriveService()
        with pytest.raises(ValueError, match="escapes the permitted upload root"):
            drive_upload(DriveUploadInput(path=str(f), folder_id="folder1"), service=svc)
        assert svc.calls == []


# ─── High #1 / #2: world-readable share opt-in ───────────────────────────────


class TestPublicShareOptIn:
    def test_upload_anyone_reader_blocked_without_flag(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", raising=False)
        monkeypatch.setenv("GOOGLE_KIT_UPLOAD_ROOT", str(tmp_path))
        f = tmp_path / "pub.txt"
        f.write_bytes(b"data")

        svc = FakeDriveService()
        with pytest.raises(FlagDisabledError, match="GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE"):
            drive_upload(
                DriveUploadInput(path=str(f), folder_id="folder1", share="anyone_reader"),
                service=svc,
            )
        assert svc.calls == [], "blocked public upload must not dispatch (no file created)"

    def test_upload_anyone_reader_allowed_with_flag(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", "1")
        monkeypatch.setenv("GOOGLE_KIT_UPLOAD_ROOT", str(tmp_path))
        f = tmp_path / "pub.txt"
        f.write_bytes(b"data")

        svc = FakeDriveService()
        result = drive_upload(
            DriveUploadInput(path=str(f), folder_id="folder1", share="anyone_reader"),
            service=svc,
        )
        perms = svc.calls_for("permissions", "create")
        assert len(perms) == 1
        assert perms[0].kwargs["body"] == {"type": "anyone", "role": "reader"}
        assert result.data.shared is True

    def test_private_upload_needs_no_flag(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", raising=False)
        monkeypatch.setenv("GOOGLE_KIT_UPLOAD_ROOT", str(tmp_path))
        f = tmp_path / "priv.txt"
        f.write_bytes(b"data")

        svc = FakeDriveService()
        result = drive_upload(DriveUploadInput(path=str(f), folder_id="folder1"), service=svc)
        assert svc.calls_for("permissions", "create") == []
        assert result.data.shared is False

    def test_permissions_anyone_blocked_without_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", raising=False)
        svc = FakeDriveService()
        with pytest.raises(FlagDisabledError, match="GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE"):
            drive_permissions(
                DrivePermissionsInput(
                    file_id="file1", action="create", type="anyone", role="reader"
                ),
                service=svc,
            )
        assert svc.calls == [], "blocked anyone-permission must not dispatch"

    def test_permissions_anyone_allowed_with_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", "1")
        svc = FakeDriveService()
        drive_permissions(
            DrivePermissionsInput(
                file_id="file1", action="create", type="anyone", role="reader"
            ),
            service=svc,
        )
        assert len(svc.calls_for("permissions", "create")) == 1

    def test_permissions_user_type_needs_no_public_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", raising=False)
        svc = FakeDriveService()
        drive_permissions(
            DrivePermissionsInput(
                file_id="file1",
                action="create",
                type="user",
                role="reader",
                email_address="user@example.com",
            ),
            service=svc,
        )
        assert len(svc.calls_for("permissions", "create")) == 1


# ─── High #2: drive.permissions OpSpec.flag (adapter-layer write gate) ────────


class TestPermissionsWriteGate:
    def test_registry_declares_write_flag(self) -> None:
        from google_kit.registry import all_specs

        spec = {s.name: s for s in all_specs()}["drive.permissions"]
        assert spec.flag == "GOOGLE_KIT_ENABLE_DRIVE_WRITE"

    def test_cli_create_blocked_without_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from google_kit.cli import main as cli_main

        monkeypatch.delenv("GOOGLE_KIT_ENABLE_DRIVE_WRITE", raising=False)

        def _factory(op_name: str, *, profile: str | None = None) -> Any:
            raise AssertionError("gated op must not build a service")

        with pytest.raises(SystemExit) as exc:
            cli_main(
                [
                    "drive", "permissions",
                    "--file-id", "f1", "--action", "create",
                    "--type", "user", "--role", "reader",
                    "--email-address", "user@example.com",
                ],
                _service_factory=_factory,
            )
        assert exc.value.code != 0
        assert "GOOGLE_KIT_ENABLE_DRIVE_WRITE" in capsys.readouterr().err

    def test_cli_list_also_gated_by_write_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from google_kit.cli import main as cli_main

        monkeypatch.delenv("GOOGLE_KIT_ENABLE_DRIVE_WRITE", raising=False)

        def _factory(op_name: str, *, profile: str | None = None) -> Any:
            raise AssertionError("gated op must not build a service")

        with pytest.raises(SystemExit) as exc:
            cli_main(
                ["drive", "permissions", "--file-id", "f1", "--action", "list"],
                _service_factory=_factory,
            )
        assert exc.value.code != 0
        assert "GOOGLE_KIT_ENABLE_DRIVE_WRITE" in capsys.readouterr().err

    def test_cli_create_allowed_with_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from google_kit.cli import main as cli_main

        monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_WRITE", "1")
        svc = FakeDriveService(responses={
            ("permissions", "create"): {"id": "perm001", "type": "user", "role": "reader"}
        })

        cli_main(
            [
                "drive", "permissions",
                "--file-id", "f1", "--action", "create",
                "--type", "user", "--role", "reader",
                "--email-address", "user@example.com",
            ],
            _service_factory=lambda *_a, **_k: svc,
        )
        capsys.readouterr()  # drain
        assert len(svc.calls_for("permissions", "create")) == 1


# ─── Medium #4: drive.changes_watch https validation + flag ──────────────────


class TestChangesWatchAddress:
    @pytest.mark.parametrize("bad", ["http://example.com/hook", "ftp://example.com", "example.com", ""])
    def test_non_https_address_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError, match="https://"):
            DriveChangesWatchInput(page_token="t", channel_id="c", address=bad)

    def test_https_address_accepted(self) -> None:
        inp = DriveChangesWatchInput(
            page_token="t", channel_id="c", address="https://example.com/hook"
        )
        assert inp.address == "https://example.com/hook"

    def test_registry_declares_watch_flag(self) -> None:
        from google_kit.registry import all_specs

        spec = {s.name: s for s in all_specs()}["drive.changes_watch"]
        assert spec.flag == "GOOGLE_KIT_ENABLE_DRIVE_WATCH"

    def test_cli_blocked_without_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from google_kit.cli import main as cli_main

        monkeypatch.delenv("GOOGLE_KIT_ENABLE_DRIVE_WATCH", raising=False)

        def _factory(op_name: str, *, profile: str | None = None) -> Any:
            raise AssertionError("gated op must not build a service")

        with pytest.raises(SystemExit) as exc:
            cli_main(
                [
                    "drive", "changes-watch",
                    "--page-token", "t", "--channel-id", "c",
                    "--address", "https://example.com/hook",
                ],
                _service_factory=_factory,
            )
        assert exc.value.code != 0
        assert "GOOGLE_KIT_ENABLE_DRIVE_WATCH" in capsys.readouterr().err


# ─── Low #8: content_b64 decoded-size cap ────────────────────────────────────


class TestInlineSizeCap:
    def test_oversize_content_b64_rejected(self) -> None:
        oversized = base64.b64encode(b"x" * (MAX_INLINE_UPLOAD_BYTES + 1)).decode()
        svc = FakeDriveService()
        with pytest.raises(ValueError, match="exceeding the .* inline cap"):
            drive_upload(
                DriveUploadInput(content_b64=oversized, filename="big.bin", folder_id="f1"),
                service=svc,
            )
        assert svc.calls == [], "oversized inline upload must not dispatch"

    def test_at_cap_content_b64_allowed(self) -> None:
        at_cap = base64.b64encode(b"x" * MAX_INLINE_UPLOAD_BYTES).decode()
        svc = FakeDriveService()
        result = drive_upload(
            DriveUploadInput(content_b64=at_cap, filename="ok.bin", folder_id="f1"),
            service=svc,
        )
        assert result.data.id == "file001"


# ─── Low #7: CLI redacts non-GoogleKitError output ───────────────────────────


class TestCliErrorRedaction:
    def test_generic_exception_message_is_redacted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from google_kit.cli import main as cli_main

        leaky = "connect failed for admin@corp.example token=SUPERSECRETVALUE123"

        class _BoomGet:
            def execute(self) -> Any:
                raise RuntimeError(leaky)

        class _Files:
            def get(self, **_kwargs: Any) -> Any:
                return _BoomGet()

        class _Svc:
            def files(self) -> Any:
                return _Files()

        with pytest.raises(SystemExit) as exc:
            cli_main(
                ["drive", "fetch", "--url-or-id", "file-1"],
                _service_factory=lambda *_a, **_k: _Svc(),
            )
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "admin@corp.example" not in err
        assert "SUPERSECRETVALUE123" not in err
        assert "[REDACTED]" in err
