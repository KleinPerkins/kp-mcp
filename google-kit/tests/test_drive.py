"""Tests for the Drive service.

Coverage:
  drive_fetch         — mock-read parity (REST path: normalized-json); Sites seam unit test
  drive_create        — mutation-request parity (files.create body)
  drive_search        — mock-read parity (normalized-json)
  drive_upload        — mutation-request parity (files.create body + permissions.create body)
  drive_copy          — mutation-request parity (files.copy body)
  drive_update        — mutation-request parity (files.update body + kwargs)
  drive_trash         — mutation-request parity (files.update body)
  drive_permissions   — mutation-request parity (permissions.create body); mock-read (list)
  drive_comments      — mutation-request parity (comments.create body); mock-read (list)
  drive_revisions     — mock-read parity (revisions.list + revisions.get)
  drive_changes       — mock-read parity (changes.list + getStartPageToken)
  drive_changes_watch — mutation-request parity (changes.watch body + pageToken forwarding)

Parity status per op:
  drive_fetch         — mock-read DONE (REST paths); Sites path seam DONE (injected fake);
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

Test-local mock classes (MockDriveService) model the Drive API's nested resource
chains (files(), permissions()) that MockGoogleService's flat model does not cover.

R18 note (amended): drive_upload is private-by-default; the public-reader
permission is granted only on explicit share="anyone_reader" opt-in. These tests
verify the documented-correct behavior, not the legacy broken implementation.
See test_drive_upload_fix.py for the path-upload + opt-in-sharing coverage.
"""
from __future__ import annotations

import base64
import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.parity import compare

FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "drive"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# ─── Test-local mock infrastructure ──────────────────────────────────────────


@dataclass
class _DriveRecord:
    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> dict[str, Any] | None:
        return self.kwargs.get("body")


class _FakeExec:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _FakeFilesProxy:
    def __init__(self, responses: dict, log: list[_DriveRecord]) -> None:
        self._responses = responses
        self._log = log

    def get(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("files", "get", dict(kwargs)))
        return _FakeExec(self._responses.get(("files", "get")))

    def export(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("files", "export", dict(kwargs)))
        mime = kwargs.get("mimeType", "")
        key = ("files", f"export:{mime}")
        return _FakeExec(self._responses.get(key, self._responses.get(("files", "export"))))

    def create(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("files", "create", dict(kwargs)))
        return _FakeExec(self._responses.get(("files", "create")))

    def copy(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("files", "copy", dict(kwargs)))
        return _FakeExec(self._responses.get(("files", "copy")))

    def list(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("files", "list", dict(kwargs)))
        return _FakeExec(self._responses.get(("files", "list")))

    def update(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("files", "update", dict(kwargs)))
        return _FakeExec(self._responses.get(("files", "update")))


class _FakePermissionsProxy:
    def __init__(self, responses: dict, log: list[_DriveRecord]) -> None:
        self._responses = responses
        self._log = log

    def create(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("permissions", "create", dict(kwargs)))
        return _FakeExec(self._responses.get(("permissions", "create")))

    def list(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("permissions", "list", dict(kwargs)))
        return _FakeExec(self._responses.get(("permissions", "list")))

    def delete(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("permissions", "delete", dict(kwargs)))
        return _FakeExec(self._responses.get(("permissions", "delete")))


class _FakeCommentsProxy:
    def __init__(self, responses: dict, log: list[_DriveRecord]) -> None:
        self._responses = responses
        self._log = log

    def create(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("comments", "create", dict(kwargs)))
        return _FakeExec(self._responses.get(("comments", "create")))

    def list(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("comments", "list", dict(kwargs)))
        return _FakeExec(self._responses.get(("comments", "list")))


class _FakeRevisionsProxy:
    def __init__(self, responses: dict, log: list[_DriveRecord]) -> None:
        self._responses = responses
        self._log = log

    def list(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("revisions", "list", dict(kwargs)))
        return _FakeExec(self._responses.get(("revisions", "list")))

    def get(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("revisions", "get", dict(kwargs)))
        return _FakeExec(self._responses.get(("revisions", "get")))


class _FakeChangesProxy:
    def __init__(self, responses: dict, log: list[_DriveRecord]) -> None:
        self._responses = responses
        self._log = log

    def list(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("changes", "list", dict(kwargs)))
        return _FakeExec(self._responses.get(("changes", "list")))

    def getStartPageToken(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("changes", "getStartPageToken", dict(kwargs)))
        return _FakeExec(self._responses.get(("changes", "getStartPageToken")))

    def watch(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_DriveRecord("changes", "watch", dict(kwargs)))
        return _FakeExec(self._responses.get(("changes", "watch")))


class MockDriveService:
    """Test-local mock for the Google Drive API service (drive v3)."""

    def __init__(self, responses: dict | None = None) -> None:
        self._responses: dict = responses or {}
        self._log: list[_DriveRecord] = []

    def files(self) -> _FakeFilesProxy:
        return _FakeFilesProxy(self._responses, self._log)

    def permissions(self) -> _FakePermissionsProxy:
        return _FakePermissionsProxy(self._responses, self._log)

    def comments(self) -> _FakeCommentsProxy:
        return _FakeCommentsProxy(self._responses, self._log)

    def revisions(self) -> _FakeRevisionsProxy:
        return _FakeRevisionsProxy(self._responses, self._log)

    def changes(self) -> _FakeChangesProxy:
        return _FakeChangesProxy(self._responses, self._log)

    def last_request_body(self) -> dict[str, Any] | None:
        for rec in reversed(self._log):
            if rec.body is not None:
                return rec.body
        return None

    def requests_for(self, resource: str, method: str) -> list[_DriveRecord]:
        return [r for r in self._log if r.resource == resource and r.method == method]

    def reset(self) -> None:
        self._log.clear()


# ─── Registry isolation fixture ──────────────────────────────────────────────


@pytest.fixture(autouse=True, scope="module")
def _ensure_drive() -> None:
    """Re-register Drive ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.drive as drive_mod

    if "drive.fetch" not in {s.name for s in reg.all_specs()}:
        importlib.reload(drive_mod)


# ─── drive.fetch ──────────────────────────────────────────────────────────────


class TestDriveFetch:
    def test_mock_read_parity_html_export(self) -> None:
        from google_kit.services.drive.core import drive_fetch
        from google_kit.services.drive.models import DriveFetchInput

        meta_resp = {
            "id": "doc001",
            "name": "My Report",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": "https://docs.google.com/document/d/doc001/edit",
        }
        html_resp = b"<html><body><h1>My Report</h1><p>This is the report body.</p></body></html>"

        svc = MockDriveService(responses={
            ("files", "get"): meta_resp,
            ("files", "export:text/html"): html_resp,
        })

        result = drive_fetch(DriveFetchInput(url_or_id="doc001"), service=svc)

        expected = _load("fetch_expected.json")
        actual = result.data.model_dump()

        parity = compare("semantic", expected, actual)
        assert parity.match, f"semantic mock-read mismatch:\n{parity.diff}"

    def test_sites_seam_injectable(self) -> None:
        from google_kit.services.drive.core import drive_fetch
        from google_kit.services.drive.models import DriveFetchInput

        def _fake_sites(url: str) -> tuple[dict, str]:
            return (
                {
                    "id": url,
                    "title": "Test Sites Page",
                    "fetch_method": "injected_fake",
                    "web_url": url,
                },
                "## Test\n\nSites content.",
            )

        result = drive_fetch(
            DriveFetchInput(url_or_id="https://sites.google.com/view/test"),
            sites_fetcher=_fake_sites,
        )
        assert result.data.platform == "google_sites"
        assert result.data.title == "Test Sites Page"
        assert result.data.content == "## Test\n\nSites content."
        assert result.data.fetch_method == "injected_fake"

    def test_sites_default_raises_not_implemented(self) -> None:
        from google_kit.services.drive.core import drive_fetch, _sites_fetcher_default
        from google_kit.services.drive.models import DriveFetchInput

        with pytest.raises(NotImplementedError, match="P6"):
            _sites_fetcher_default("https://sites.google.com/view/test")

    def test_metadata_only_skips_export(self) -> None:
        from google_kit.services.drive.core import drive_fetch
        from google_kit.services.drive.models import DriveFetchInput

        meta_resp = {
            "id": "doc002",
            "name": "Meta Only",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": "https://docs.google.com/document/d/doc002/edit",
        }
        svc = MockDriveService(responses={("files", "get"): meta_resp})
        result = drive_fetch(DriveFetchInput(url_or_id="doc002", metadata_only=True), service=svc)

        assert result.data.content is None
        assert result.data.id == "doc002"
        export_calls = svc.requests_for("files", "export")
        assert export_calls == []

    def test_url_file_id_extraction(self) -> None:
        from google_kit.services.drive.core import _extract_file_id

        url = "https://docs.google.com/document/d/abc123xyz789012345678/edit"
        assert _extract_file_id(url) == "abc123xyz789012345678"
        assert _extract_file_id("bare_id_here") == "bare_id_here"

    def test_output_envelope_structure(self) -> None:
        from google_kit.services.drive.core import drive_fetch
        from google_kit.services.drive.models import DriveFetchInput

        meta_resp = {
            "id": "doc003",
            "name": "Report",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": "https://docs.google.com/document/d/doc003/edit",
        }
        svc = MockDriveService(responses={
            ("files", "get"): meta_resp,
            ("files", "export:text/html"): b"<p>Hello</p>",
        })
        result = drive_fetch(DriveFetchInput(url_or_id="doc003"), service=svc)
        assert result.meta.op == "drive.fetch"
        assert result.data.id == "doc003"
        assert result.data.title == "Report"


# ─── drive.create ─────────────────────────────────────────────────────────────


class TestDriveCreate:
    def test_mutation_request_parity_doc(self) -> None:
        from google_kit.services.drive.core import drive_create
        from google_kit.services.drive.models import DriveCreateInput

        expected_body = _load("create_expected_body.json")
        canned_resp = {
            "id": "doc001",
            "name": "My New Doc",
            "webViewLink": "https://docs.google.com/document/d/doc001/edit",
        }
        svc = MockDriveService(responses={("files", "create"): canned_resp})
        drive_create(DriveCreateInput(title="My New Doc", doc_type="doc"), service=svc)

        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_folder_body_contains_folder_mimeType(self) -> None:
        from google_kit.services.drive.core import drive_create
        from google_kit.services.drive.models import DriveCreateInput

        canned_resp = {"id": "folder001", "name": "My Folder", "webViewLink": "https://drive.google.com/drive/folders/folder001"}
        svc = MockDriveService(responses={("files", "create"): canned_resp})
        drive_create(DriveCreateInput(title="My Folder", doc_type="folder"), service=svc)

        body = svc.last_request_body()
        assert body is not None
        assert body["mimeType"] == "application/vnd.google-apps.folder"

    def test_folder_id_adds_parents(self) -> None:
        from google_kit.services.drive.core import drive_create
        from google_kit.services.drive.models import DriveCreateInput

        canned_resp = {"id": "doc002", "name": "Doc In Folder", "webViewLink": "https://docs.google.com/document/d/doc002/edit"}
        svc = MockDriveService(responses={("files", "create"): canned_resp})
        drive_create(DriveCreateInput(title="Doc In Folder", doc_type="doc", folder_id="folder123"), service=svc)

        body = svc.last_request_body()
        assert body is not None
        assert body.get("parents") == ["folder123"]

    def test_no_folder_id_no_parents(self) -> None:
        from google_kit.services.drive.core import drive_create
        from google_kit.services.drive.models import DriveCreateInput

        canned_resp = {"id": "doc003", "name": "Standalone", "webViewLink": "https://docs.google.com/document/d/doc003/edit"}
        svc = MockDriveService(responses={("files", "create"): canned_resp})
        drive_create(DriveCreateInput(title="Standalone", doc_type="doc"), service=svc)

        body = svc.last_request_body()
        assert body is not None
        assert "parents" not in body

    def test_output_envelope(self) -> None:
        from google_kit.services.drive.core import drive_create
        from google_kit.services.drive.models import DriveCreateInput

        canned_resp = {"id": "sheet001", "name": "Sheet", "webViewLink": "https://docs.google.com/spreadsheets/d/sheet001/edit"}
        svc = MockDriveService(responses={("files", "create"): canned_resp})
        result = drive_create(DriveCreateInput(title="Sheet", doc_type="sheet"), service=svc)

        assert result.meta.op == "drive.create"
        assert result.data.id == "sheet001"
        assert result.data.doc_type == "sheet"
        assert "sheet001" in result.data.url

    def test_sheet_mime_type(self) -> None:
        from google_kit.services.drive.core import drive_create
        from google_kit.services.drive.models import DriveCreateInput

        canned_resp = {"id": "ss001", "name": "My Sheet", "webViewLink": "https://docs.google.com/spreadsheets/d/ss001/edit"}
        svc = MockDriveService(responses={("files", "create"): canned_resp})
        drive_create(DriveCreateInput(title="My Sheet", doc_type="sheet"), service=svc)

        body = svc.last_request_body()
        assert body is not None
        assert body["mimeType"] == "application/vnd.google-apps.spreadsheet"


# ─── drive.search ─────────────────────────────────────────────────────────────


class TestDriveSearch:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.drive.core import drive_search
        from google_kit.services.drive.models import DriveSearchInput

        search_resp = _load("search_response.json")
        expected = _load("search_expected.json")

        svc = MockDriveService(responses={("files", "list"): search_resp})
        result = drive_search(DriveSearchInput(query="project"), service=svc)

        actual = result.data.model_dump()
        nondeterministic = {"modified", "created"}
        parity = compare(
            "normalized-json",
            {k: v for k, v in expected.items() if k not in nondeterministic},
            {k: v for k, v in actual.items() if k not in nondeterministic},
        )
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_query_building_text_search(self) -> None:
        from google_kit.services.drive.core import _build_search_query
        from google_kit.services.drive.models import DriveSearchInput

        q = _build_search_query(DriveSearchInput(query="budget report"))
        assert "fullText contains 'budget report'" in q
        assert "trashed = false" in q

    def test_query_building_name_filter(self) -> None:
        from google_kit.services.drive.core import _build_search_query
        from google_kit.services.drive.models import DriveSearchInput

        q = _build_search_query(DriveSearchInput(name="Q4 plan"))
        assert "name contains 'Q4 plan'" in q

    def test_query_building_type_filter(self) -> None:
        from google_kit.services.drive.core import _build_search_query
        from google_kit.services.drive.models import DriveSearchInput

        q = _build_search_query(DriveSearchInput(query="x", doc_type="doc"))
        assert "mimeType = 'application/vnd.google-apps.document'" in q

    def test_query_building_shared_with_me(self) -> None:
        from google_kit.services.drive.core import _build_search_query
        from google_kit.services.drive.models import DriveSearchInput

        q = _build_search_query(DriveSearchInput(query="x", shared_with_me=True))
        assert "sharedWithMe = true" in q

    def test_empty_results(self) -> None:
        from google_kit.services.drive.core import drive_search
        from google_kit.services.drive.models import DriveSearchInput

        svc = MockDriveService(responses={("files", "list"): {"files": [], "nextPageToken": None}})
        result = drive_search(DriveSearchInput(query="nonexistent"), service=svc)
        assert result.data.count == 0
        assert result.data.results == []
        assert not result.data.truncated

    def test_output_envelope(self) -> None:
        from google_kit.services.drive.core import drive_search
        from google_kit.services.drive.models import DriveSearchInput

        svc = MockDriveService(responses={("files", "list"): {"files": [], "nextPageToken": None}})
        result = drive_search(DriveSearchInput(query="test"), service=svc)
        assert result.meta.op == "drive.search"

    def test_escape_query_literal(self) -> None:
        from google_kit.services.drive.core import _escape_query_literal

        assert _escape_query_literal("jane's report") == "jane\\'s report"
        assert _escape_query_literal("back\\slash") == "back\\\\slash"


class TestDriveSearchCorporaFallback:
    """drive.search documents an allDrives→user 403 fallback (legacy parity)."""

    @staticmethod
    def _raising_exec() -> Any:
        from google_kit.core.errors import Permission

        class _Raise:
            def execute(self) -> Any:
                raise Permission("allDrives corpora not permitted", op="drive.search")

        return _Raise()

    def test_falls_back_to_user_corpora_on_alldrives_403(self) -> None:
        from google_kit.services.drive.core import drive_search
        from google_kit.services.drive.models import DriveSearchInput

        outer = self

        class _Files:
            def __init__(self, log: list[str]) -> None:
                self._log = log

            def list(self, **kwargs: Any) -> Any:
                corpora = kwargs.get("corpora")
                self._log.append(corpora)
                if corpora == "allDrives":
                    return outer._raising_exec()
                return _FakeExec({
                    "files": [{
                        "id": "f1",
                        "name": "User File",
                        "mimeType": "application/vnd.google-apps.document",
                        "webViewLink": "https://docs.google.com/document/d/f1/edit",
                    }]
                })

        class _Svc:
            def __init__(self) -> None:
                self.corpora_log: list[str] = []

            def files(self) -> Any:
                return _Files(self.corpora_log)

        svc = _Svc()
        result = drive_search(DriveSearchInput(query="x"), service=svc)

        assert "allDrives" in svc.corpora_log
        assert "user" in svc.corpora_log
        assert result.data.count == 1
        assert result.data.results[0].id == "f1"
        assert any("user" in w for w in result.warnings), result.warnings

    def test_user_corpora_403_is_not_swallowed(self) -> None:
        from google_kit.services.drive.core import drive_search
        from google_kit.services.drive.models import DriveSearchInput
        from google_kit.core.errors import Permission

        outer = self

        class _Files:
            def list(self, **kwargs: Any) -> Any:
                return outer._raising_exec()

        class _Svc:
            def files(self) -> Any:
                return _Files()

        with pytest.raises(Permission):
            drive_search(DriveSearchInput(query="x", scope="user"), service=_Svc())


# ─── drive.upload ─────────────────────────────────────────────────────────────


class TestDriveUpload:
    def _make_svc(self, folder_id: str = "folder001") -> MockDriveService:
        return MockDriveService(responses={
            ("files", "create"): {
                "id": "upload001",
                "name": "report.pdf",
                "webViewLink": "https://drive.google.com/file/d/upload001/view",
                "mimeType": "application/pdf",
            },
            ("permissions", "create"): {"id": "perm001"},
        })

    def test_mutation_request_parity_file_body(self) -> None:
        from google_kit.services.drive.core import drive_upload
        from google_kit.services.drive.models import DriveUploadInput

        expected_body = _load("upload_expected_body.json")
        svc = self._make_svc()
        content_b64 = base64.b64encode(b"PDF content").decode()

        drive_upload(
            DriveUploadInput(
                content_b64=content_b64,
                filename="report.pdf",
                folder_id="folder001",
            ),
            service=svc,
        )

        file_creates = svc.requests_for("files", "create")
        assert file_creates, "Expected at least one files.create call"
        actual_body = file_creates[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_mutation_request_parity_permission_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from google_kit.services.drive.core import drive_upload
        from google_kit.services.drive.models import DriveUploadInput

        monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", "1")
        expected_perm = _load("upload_expected_permission_body.json")
        svc = self._make_svc()
        content_b64 = base64.b64encode(b"PDF content").decode()

        drive_upload(
            DriveUploadInput(
                content_b64=content_b64,
                filename="report.pdf",
                folder_id="folder001",
                share="anyone_reader",
            ),
            service=svc,
        )

        perm_creates = svc.requests_for("permissions", "create")
        assert len(perm_creates) == 1
        actual_body = perm_creates[0].body
        parity = compare("mutation-request", expected_perm, actual_body)
        assert parity.match, f"permission body mismatch:\n{parity.diff}"

    def test_upload_uses_resumable_media(self) -> None:
        from googleapiclient.http import MediaIoBaseUpload
        from google_kit.services.drive.core import drive_upload
        from google_kit.services.drive.models import DriveUploadInput

        svc = self._make_svc()
        content_b64 = base64.b64encode(b"test content").decode()
        drive_upload(
            DriveUploadInput(content_b64=content_b64, filename="test.txt", folder_id="folder001"),
            service=svc,
        )

        file_creates = svc.requests_for("files", "create")
        assert file_creates
        media = file_creates[0].kwargs.get("media_body")
        assert isinstance(media, MediaIoBaseUpload)
        assert media._resumable is True

    def test_title_override(self) -> None:
        from google_kit.services.drive.core import drive_upload
        from google_kit.services.drive.models import DriveUploadInput

        svc = MockDriveService(responses={
            ("files", "create"): {"id": "u001", "name": "Custom Title", "webViewLink": "https://drive.google.com/file/d/u001/view", "mimeType": "text/plain"},
            ("permissions", "create"): {"id": "p001"},
        })
        content_b64 = base64.b64encode(b"text").decode()
        drive_upload(
            DriveUploadInput(content_b64=content_b64, filename="file.txt", title="Custom Title", folder_id="f001"),
            service=svc,
        )

        file_creates = svc.requests_for("files", "create")
        assert file_creates[0].body["name"] == "Custom Title"

    def test_folder_lookup_when_no_folder_id(self) -> None:
        from google_kit.services.drive.core import drive_upload
        from google_kit.services.drive.models import DriveUploadInput

        svc = MockDriveService(responses={
            ("files", "list"): {"files": [{"id": "existing_folder"}]},
            ("files", "create"): {"id": "u001", "name": "file.txt", "webViewLink": "https://drive.google.com/file/d/u001/view", "mimeType": "text/plain"},
            ("permissions", "create"): {"id": "p001"},
        })
        content_b64 = base64.b64encode(b"text").decode()
        drive_upload(
            DriveUploadInput(content_b64=content_b64, filename="file.txt"),
            service=svc,
        )

        list_calls = svc.requests_for("files", "list")
        assert list_calls, "Expected files.list call to find/create folder"

    def test_output_envelope(self) -> None:
        from google_kit.services.drive.core import drive_upload
        from google_kit.services.drive.models import DriveUploadInput

        svc = self._make_svc()
        content_b64 = base64.b64encode(b"data").decode()
        result = drive_upload(
            DriveUploadInput(content_b64=content_b64, filename="report.pdf", folder_id="folder001"),
            service=svc,
        )

        assert result.meta.op == "drive.upload"
        assert result.data.id == "upload001"
        assert result.data.mime_type == "application/pdf"

    def test_mime_auto_detected_from_extension(self) -> None:
        from google_kit.services.drive.core import _detect_mime

        assert _detect_mime("file.pdf") == "application/pdf"
        assert _detect_mime("data.csv") == "text/csv"
        assert _detect_mime("unknown.xyz") == "application/octet-stream"


# ─── drive.copy ───────────────────────────────────────────────────────────────


class TestDriveCopy:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.drive.core import drive_copy
        from google_kit.services.drive.models import DriveCopyInput

        expected_body = _load("copy_expected_body.json")
        svc = MockDriveService(responses={
            ("files", "copy"): {
                "id": "copy001",
                "name": "Copy of File",
                "webViewLink": "https://drive.google.com/file/d/copy001/view",
            }
        })
        drive_copy(
            DriveCopyInput(file_id="file001", name="Copy of File", folder_id="folder001"),
            service=svc,
        )

        copies = svc.requests_for("files", "copy")
        assert copies, "Expected files.copy call"
        actual_body = copies[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_output_envelope(self) -> None:
        from google_kit.services.drive.core import drive_copy
        from google_kit.services.drive.models import DriveCopyInput

        svc = MockDriveService(responses={
            ("files", "copy"): {
                "id": "copy002",
                "name": "My Copy",
                "webViewLink": "https://drive.google.com/file/d/copy002/view",
            }
        })
        result = drive_copy(DriveCopyInput(file_id="file001", name="My Copy"), service=svc)

        assert result.meta.op == "drive.copy"
        assert result.data.id == "copy002"
        assert result.data.name == "My Copy"
        assert "copy002" in result.data.url

    def test_empty_body_when_no_name_or_folder(self) -> None:
        from google_kit.services.drive.core import drive_copy
        from google_kit.services.drive.models import DriveCopyInput

        svc = MockDriveService(responses={
            ("files", "copy"): {"id": "c001", "name": "", "webViewLink": "https://drive.google.com/file/d/c001/view"}
        })
        drive_copy(DriveCopyInput(file_id="file001"), service=svc)

        body = svc.requests_for("files", "copy")[0].body
        assert body == {}


# ─── drive.update ─────────────────────────────────────────────────────────────


class TestDriveUpdate:
    def _canned_resp(self) -> dict:
        return {"id": "file001", "name": "Renamed File", "parents": ["parent001"]}

    def test_mutation_request_parity_rename(self) -> None:
        from google_kit.services.drive.core import drive_update
        from google_kit.services.drive.models import DriveUpdateInput

        expected_body = _load("update_expected_body.json")
        svc = MockDriveService(responses={("files", "update"): self._canned_resp()})
        drive_update(DriveUpdateInput(file_id="file001", name="Renamed File"), service=svc)

        updates = svc.requests_for("files", "update")
        assert updates
        actual_body = updates[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_move_sets_add_remove_parents(self) -> None:
        from google_kit.services.drive.core import drive_update
        from google_kit.services.drive.models import DriveUpdateInput

        svc = MockDriveService(responses={("files", "update"): self._canned_resp()})
        drive_update(
            DriveUpdateInput(file_id="file001", add_parents=["newFolder"], remove_parents=["oldFolder"]),
            service=svc,
        )

        rec = svc.requests_for("files", "update")[0]
        assert rec.kwargs.get("addParents") == "newFolder"
        assert rec.kwargs.get("removeParents") == "oldFolder"

    def test_output_envelope(self) -> None:
        from google_kit.services.drive.core import drive_update
        from google_kit.services.drive.models import DriveUpdateInput

        svc = MockDriveService(responses={("files", "update"): self._canned_resp()})
        result = drive_update(DriveUpdateInput(file_id="file001", name="Renamed File"), service=svc)

        assert result.meta.op == "drive.update"
        assert result.data.id == "file001"
        assert result.data.name == "Renamed File"


# ─── drive.trash ──────────────────────────────────────────────────────────────


class TestDriveTrash:
    def test_mutation_request_parity_trash(self) -> None:
        from google_kit.services.drive.core import drive_trash
        from google_kit.services.drive.models import DriveTrashInput

        expected_body = _load("trash_expected_body.json")
        svc = MockDriveService(responses={
            ("files", "update"): {"id": "file001", "trashed": True, "name": "My File"}
        })
        drive_trash(DriveTrashInput(file_id="file001"), service=svc)

        updates = svc.requests_for("files", "update")
        assert updates
        actual_body = updates[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_untrash_sends_trashed_false(self) -> None:
        from google_kit.services.drive.core import drive_trash
        from google_kit.services.drive.models import DriveTrashInput

        svc = MockDriveService(responses={
            ("files", "update"): {"id": "file001", "trashed": False, "name": "My File"}
        })
        drive_trash(DriveTrashInput(file_id="file001", untrash=True), service=svc)

        body = svc.requests_for("files", "update")[0].body
        assert body == {"trashed": False}

    def test_output_envelope(self) -> None:
        from google_kit.services.drive.core import drive_trash
        from google_kit.services.drive.models import DriveTrashInput

        svc = MockDriveService(responses={
            ("files", "update"): {"id": "file001", "trashed": True, "name": "My File"}
        })
        result = drive_trash(DriveTrashInput(file_id="file001"), service=svc)

        assert result.meta.op == "drive.trash"
        assert result.data.id == "file001"
        assert result.data.trashed is True


# ─── drive.permissions ────────────────────────────────────────────────────────


class TestDrivePermissions:
    def test_mock_read_parity_list(self) -> None:
        from google_kit.services.drive.core import drive_permissions
        from google_kit.services.drive.models import DrivePermissionsInput

        list_resp = _load("permissions_list_response.json")
        expected = _load("permissions_list_expected.json")

        svc = MockDriveService(responses={("permissions", "list"): list_resp})
        result = drive_permissions(
            DrivePermissionsInput(file_id="file001", action="list"), service=svc
        )

        parity = compare("normalized-json", expected, result.data.model_dump())
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_mutation_request_parity_create(self) -> None:
        from google_kit.services.drive.core import drive_permissions
        from google_kit.services.drive.models import DrivePermissionsInput

        expected_body = _load("permissions_create_expected_body.json")
        svc = MockDriveService(responses={
            ("permissions", "create"): {"id": "perm001", "type": "user", "role": "reader", "emailAddress": "test@example.com"}
        })
        drive_permissions(
            DrivePermissionsInput(
                file_id="file001",
                action="create",
                type="user",
                role="reader",
                email_address="test@example.com",
            ),
            service=svc,
        )

        creates = svc.requests_for("permissions", "create")
        assert creates
        parity = compare("mutation-request", expected_body, creates[0].body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_delete_calls_permissions_delete(self) -> None:
        from google_kit.services.drive.core import drive_permissions
        from google_kit.services.drive.models import DrivePermissionsInput

        svc = MockDriveService(responses={("permissions", "delete"): None})
        result = drive_permissions(
            DrivePermissionsInput(file_id="file001", action="delete", permission_id="perm001"),
            service=svc,
        )

        deletes = svc.requests_for("permissions", "delete")
        assert len(deletes) == 1
        assert deletes[0].kwargs.get("permissionId") == "perm001"
        assert result.data.deleted is True

    def test_output_envelope_list(self) -> None:
        from google_kit.services.drive.core import drive_permissions
        from google_kit.services.drive.models import DrivePermissionsInput

        svc = MockDriveService(responses={("permissions", "list"): {"permissions": []}})
        result = drive_permissions(
            DrivePermissionsInput(file_id="file001", action="list"), service=svc
        )
        assert result.meta.op == "drive.permissions"
        assert result.data.action == "list"
        assert result.data.permissions == []


# ─── drive.comments ───────────────────────────────────────────────────────────


class TestDriveComments:
    def test_mock_read_parity_list(self) -> None:
        from google_kit.services.drive.core import drive_comments
        from google_kit.services.drive.models import DriveCommentsInput

        list_resp = _load("comments_list_response.json")
        expected = _load("comments_list_expected.json")

        svc = MockDriveService(responses={("comments", "list"): list_resp})
        result = drive_comments(
            DriveCommentsInput(file_id="file001", action="list"), service=svc
        )

        parity = compare("normalized-json", expected, result.data.model_dump())
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_mutation_request_parity_create(self) -> None:
        from google_kit.services.drive.core import drive_comments
        from google_kit.services.drive.models import DriveCommentsInput

        expected_body = _load("comments_create_expected_body.json")
        svc = MockDriveService(responses={
            ("comments", "create"): {
                "id": "comment001",
                "content": "Great document!",
                "author": {"displayName": "Alice"},
                "createdTime": "2024-03-20T10:00:00Z",
            }
        })
        drive_comments(
            DriveCommentsInput(file_id="file001", action="create", content="Great document!"),
            service=svc,
        )

        creates = svc.requests_for("comments", "create")
        assert creates
        parity = compare("mutation-request", expected_body, creates[0].body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_output_envelope_create(self) -> None:
        from google_kit.services.drive.core import drive_comments
        from google_kit.services.drive.models import DriveCommentsInput

        svc = MockDriveService(responses={
            ("comments", "create"): {"id": "c001", "content": "Hello", "author": {}, "createdTime": "2024-01-01T00:00:00Z"}
        })
        result = drive_comments(
            DriveCommentsInput(file_id="file001", action="create", content="Hello"), service=svc
        )
        assert result.meta.op == "drive.comments"
        assert result.data.action == "create"
        assert result.data.comment is not None


# ─── drive.revisions ──────────────────────────────────────────────────────────


class TestDriveRevisions:
    def test_mock_read_parity_list(self) -> None:
        from google_kit.services.drive.core import drive_revisions
        from google_kit.services.drive.models import DriveRevisionsInput

        list_resp = _load("revisions_list_response.json")
        expected = _load("revisions_list_expected.json")

        svc = MockDriveService(responses={("revisions", "list"): list_resp})
        result = drive_revisions(DriveRevisionsInput(file_id="file001"), service=svc)

        parity = compare("normalized-json", expected, result.data.model_dump())
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_mock_read_parity_get(self) -> None:
        from google_kit.services.drive.core import drive_revisions
        from google_kit.services.drive.models import DriveRevisionsInput

        get_resp = _load("revisions_get_response.json")
        expected = _load("revisions_get_expected.json")

        svc = MockDriveService(responses={("revisions", "get"): get_resp})
        result = drive_revisions(
            DriveRevisionsInput(file_id="file001", revision_id="1"), service=svc
        )

        parity = compare("normalized-json", expected, result.data.model_dump())
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_output_envelope_list(self) -> None:
        from google_kit.services.drive.core import drive_revisions
        from google_kit.services.drive.models import DriveRevisionsInput

        svc = MockDriveService(responses={("revisions", "list"): {"revisions": []}})
        result = drive_revisions(DriveRevisionsInput(file_id="file001"), service=svc)
        assert result.meta.op == "drive.revisions"
        assert result.data.revisions == []


# ─── drive.changes ────────────────────────────────────────────────────────────


class TestDriveChanges:
    def test_mock_read_parity_start_token(self) -> None:
        from google_kit.services.drive.core import drive_changes
        from google_kit.services.drive.models import DriveChangesInput

        token_resp = _load("changes_token_response.json")
        expected = _load("changes_token_expected.json")

        svc = MockDriveService(responses={("changes", "getStartPageToken"): token_resp})
        result = drive_changes(DriveChangesInput(), service=svc)

        parity = compare("normalized-json", expected, result.data.model_dump())
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_mock_read_parity_list(self) -> None:
        from google_kit.services.drive.core import drive_changes
        from google_kit.services.drive.models import DriveChangesInput

        list_resp = _load("changes_list_response.json")
        expected = _load("changes_list_expected.json")

        svc = MockDriveService(responses={("changes", "list"): list_resp})
        result = drive_changes(DriveChangesInput(page_token="token_abc"), service=svc)

        parity = compare("normalized-json", expected, result.data.model_dump())
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_no_page_token_returns_empty_changes(self) -> None:
        from google_kit.services.drive.core import drive_changes
        from google_kit.services.drive.models import DriveChangesInput

        svc = MockDriveService(responses={
            ("changes", "getStartPageToken"): {"startPageToken": "tok001"}
        })
        result = drive_changes(DriveChangesInput(), service=svc)
        assert result.data.changes == []
        assert result.data.new_start_page_token == "tok001"

    def test_output_envelope_list(self) -> None:
        from google_kit.services.drive.core import drive_changes
        from google_kit.services.drive.models import DriveChangesInput

        svc = MockDriveService(responses={
            ("changes", "list"): {"changes": [], "newStartPageToken": "nxt", "nextPageToken": None}
        })
        result = drive_changes(DriveChangesInput(page_token="tok"), service=svc)
        assert result.meta.op == "drive.changes"
        assert result.data.changes == []
        assert result.data.new_start_page_token == "nxt"


# ─── drive.changes_watch ──────────────────────────────────────────────────────


class TestDriveChangesWatch:
    _CHANNEL_RESP = {
        "id": "channel-abc123",
        "resourceId": "resource-xyz789",
        "resourceUri": "https://www.googleapis.com/drive/v3/changes",
        "expiration": "1735689600000",
    }

    def _svc(self) -> MockDriveService:
        return MockDriveService(responses={("changes", "watch"): self._CHANNEL_RESP})

    def test_mutation_request_parity_body_with_expiration(self) -> None:
        from google_kit.services.drive.core import drive_changes_watch
        from google_kit.services.drive.models import DriveChangesWatchInput

        expected_body = _load("changes_watch_expected_body.json")
        svc = self._svc()
        drive_changes_watch(
            DriveChangesWatchInput(
                page_token="token_abc",
                channel_id="channel-abc123",
                address="https://example.com/webhook/drive",
                expiration_ms=1735689600000,
            ),
            service=svc,
        )

        watches = svc.requests_for("changes", "watch")
        assert watches, "Expected changes.watch call"
        actual_body = watches[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_body_construction_without_expiration(self) -> None:
        from google_kit.services.drive.core import drive_changes_watch
        from google_kit.services.drive.models import DriveChangesWatchInput

        svc = self._svc()
        drive_changes_watch(
            DriveChangesWatchInput(
                page_token="token_abc",
                channel_id="channel-no-exp",
                address="https://example.com/webhook/drive",
            ),
            service=svc,
        )

        watches = svc.requests_for("changes", "watch")
        body = watches[0].body
        assert "expiration" not in body
        assert body["type"] == "web_hook"
        assert body["id"] == "channel-no-exp"
        assert body["address"] == "https://example.com/webhook/drive"

    def test_page_token_forwarded(self) -> None:
        from google_kit.services.drive.core import drive_changes_watch
        from google_kit.services.drive.models import DriveChangesWatchInput

        svc = self._svc()
        drive_changes_watch(
            DriveChangesWatchInput(
                page_token="mytoken123",
                channel_id="ch",
                address="https://example.com/hook",
            ),
            service=svc,
        )

        watches = svc.requests_for("changes", "watch")
        assert watches[0].kwargs.get("pageToken") == "mytoken123"

    def test_normalization(self) -> None:
        from google_kit.services.drive.core import drive_changes_watch
        from google_kit.services.drive.models import DriveChangesWatchInput

        expected = _load("changes_watch_response.json")
        svc = self._svc()
        result = drive_changes_watch(
            DriveChangesWatchInput(
                page_token="tok",
                channel_id="channel-abc123",
                address="https://example.com/webhook/drive",
                expiration_ms=1735689600000,
            ),
            service=svc,
        )

        assert result.data.id == expected["id"]
        assert result.data.resourceId == expected["resourceId"]
        assert result.data.resourceUri == expected["resourceUri"]
        assert result.data.expiration == expected["expiration"]

    def test_registry_integration(self) -> None:
        from google_kit.registry import all_specs

        specs = {s.name: s for s in all_specs()}
        assert "drive.changes_watch" in specs
        s = specs["drive.changes_watch"]
        assert s.posture == "write"
        assert s.plane == "eventing"
        assert s.capability == "eventing.watch"
        assert "https://www.googleapis.com/auth/drive.readonly" in s.scopes
        assert s.flag == "GOOGLE_KIT_ENABLE_DRIVE_WATCH"
