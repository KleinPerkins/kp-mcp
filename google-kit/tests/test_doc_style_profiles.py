"""Focused tests for google-kit Docs style profiles."""
from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest


class _Exec:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _Proxy:
    def __init__(self, svc: "FakeDocsService") -> None:
        self._svc = svc

    def get(self, **kwargs: Any) -> _Exec:
        self._svc.log.append(("get", dict(kwargs)))
        return _Exec(self._svc.responses.get("get"))

    def batchUpdate(self, **kwargs: Any) -> _Exec:
        self._svc.log.append(("batchUpdate", dict(kwargs)))
        return _Exec(self._svc.responses.get("batchUpdate", {"documentId": kwargs.get("documentId"), "replies": []}))


class FakeDocsService:
    def __init__(self, *, get_response: dict[str, Any] | None = None) -> None:
        self.responses = {
            "get": get_response or {"body": {"content": []}},
            "batchUpdate": {"documentId": "doc1", "replies": [{"ok": True}]},
        }
        self.log: list[tuple[str, dict[str, Any]]] = []

    def documents(self) -> _Proxy:
        return _Proxy(self)

    def calls(self, method: str) -> list[dict[str, Any]]:
        return [kw for name, kw in self.log if name == method]


class _DriveFiles:
    def __init__(self, svc: "FakeDriveService") -> None:
        self._svc = svc

    def create(self, **kwargs: Any) -> _Exec:
        self._svc.log.append(("create", dict(kwargs)))
        return _Exec({"id": "doc1", "webViewLink": "https://docs.google.com/document/d/doc1/edit"})

    def update(self, **kwargs: Any) -> _Exec:
        self._svc.log.append(("update", dict(kwargs)))
        return _Exec({"id": kwargs.get("fileId"), "trashed": True})


class FakeDriveService:
    def __init__(self) -> None:
        self.log: list[tuple[str, dict[str, Any]]] = []

    def files(self) -> _DriveFiles:
        return _DriveFiles(self)


def _profile(mode: str = "PAGES") -> dict[str, Any]:
    return {
        "schema": 1,
        "named_styles": {
            "NORMAL_TEXT": {
                "textStyle": {"fontSize": {"magnitude": 12, "unit": "PT"}},
                "paragraphStyle": {"lineSpacing": 120},
            }
        },
        "document_style": {
            "documentFormat": {"documentMode": mode},
            "marginTop": {"magnitude": 72, "unit": "PT"},
            "marginBottom": {"magnitude": 72, "unit": "PT"},
            "background": {"color": {"rgbColor": {"red": 1, "green": 1, "blue": 1}}},
        },
    }


def test_profile_store_round_trip_and_permissions() -> None:
    from google_kit.core.profiles import load_profile, profile_path, save_profile

    path = save_profile("team", _profile())
    assert path == profile_path("team")
    assert load_profile("team")["named_styles"]["NORMAL_TEXT"]["paragraphStyle"]["lineSpacing"] == 120
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "/abs", "équipe"])
def test_profile_store_rejects_unsafe_names(name: str) -> None:
    from google_kit.core.errors import Validation
    from google_kit.core.profiles import save_profile

    with pytest.raises(Validation):
        save_profile(name, _profile())


def test_profile_store_missing_and_corrupt_errors() -> None:
    from google_kit.core.errors import NotFound, Validation
    from google_kit.core.profiles import load_profile, profile_path

    with pytest.raises(NotFound):
        load_profile("missing")
    path = profile_path("bad")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(Validation):
        load_profile("bad")


def test_extract_styles_tab_aware_save() -> None:
    from google_kit.core.profiles import load_profile
    from google_kit.services.docs.core import docs_extract_styles
    from google_kit.services.docs.models import DocsExtractStylesInput

    source = {
        "tabs": [{
            "tabProperties": {"tabId": "tab-a"},
            "documentTab": {
                "namedStyles": {
                    "styles": [{
                        "namedStyleType": "NORMAL_TEXT",
                        "textStyle": {"fontSize": {"magnitude": 11.123456, "unit": "PT"}},
                        "paragraphStyle": {"lineSpacing": 150, "headingId": "ignored"},
                    }]
                },
                "documentStyle": {"documentFormat": {"documentMode": "PAGES"}},
            },
        }]
    }
    svc = FakeDocsService(get_response=source)

    out = docs_extract_styles(
        DocsExtractStylesInput(document_id="doc-source", style_profile="default"),
        docs_service=svc,
    )

    assert svc.calls("get")[0]["includeTabsContent"] is True
    assert out.data.saved_path
    saved = load_profile("default")
    assert saved["tab_id"] == "tab-a"
    assert saved["named_styles"]["NORMAL_TEXT"]["textStyle"]["fontSize"]["magnitude"] == 11.1235
    assert "headingId" not in saved["named_styles"]["NORMAL_TEXT"]["paragraphStyle"]


def test_extract_styles_multi_tab_requires_tab_id() -> None:
    from google_kit.core.errors import Validation
    from google_kit.services.docs.core import docs_extract_styles
    from google_kit.services.docs.models import DocsExtractStylesInput

    svc = FakeDocsService(get_response={"tabs": [{"documentTab": {}}, {"documentTab": {}}]})
    with pytest.raises(Validation):
        docs_extract_styles(DocsExtractStylesInput(document_id="doc-source"), docs_service=svc)


def test_apply_styles_dry_run_pageless_omits_geometry() -> None:
    from google_kit.services.docs.core import docs_apply_styles
    from google_kit.services.docs.models import DocsApplyStylesInput

    out = docs_apply_styles(
        DocsApplyStylesInput(document_id="doc1", style_profile="team", dry_run=True),
        _profile_loader=lambda _name: _profile("PAGELESS"),
    )

    assert out.data.style_profile == "team"
    assert out.data.requests_applied == 0
    named_req = out.data.requests[0]["updateNamedStyle"]
    assert "namedStyleType" not in named_req
    assert named_req["namedStyle"]["namedStyleType"] == "NORMAL_TEXT"
    assert named_req["fields"] == "namedStyleType,paragraphStyle,textStyle"
    doc_requests = [r["updateDocumentStyle"] for r in out.data.requests if "updateDocumentStyle" in r]
    assert doc_requests[0]["fields"] == "documentFormat.documentMode"
    assert all("marginTop" not in r["documentStyle"] for r in doc_requests[1:])
    assert all("tabId" not in r for r in doc_requests)


def test_apply_styles_omits_stored_tab_id_for_other_doc() -> None:
    from google_kit.services.docs.core import docs_apply_styles
    from google_kit.services.docs.models import DocsApplyStylesInput

    profile = _profile()
    profile["source_doc_id"] = "source-doc"
    profile["tab_id"] = "tab-a"

    out = docs_apply_styles(
        DocsApplyStylesInput(document_id="other-doc", style_profile="team", dry_run=True),
        _profile_loader=lambda _name: profile,
    )

    assert all(
        "tabId" not in req.get("updateNamedStyle", req.get("updateDocumentStyle", {}))
        for req in out.data.requests
    )


def test_apply_styles_uses_stored_tab_id_for_source_doc() -> None:
    from google_kit.services.docs.core import docs_apply_styles
    from google_kit.services.docs.models import DocsApplyStylesInput

    profile = _profile()
    profile["source_doc_id"] = "doc1"
    profile["tab_id"] = "tab-a"

    out = docs_apply_styles(
        DocsApplyStylesInput(document_id="doc1", style_profile="team", dry_run=True),
        _profile_loader=lambda _name: profile,
    )

    assert out.data.requests[0]["updateNamedStyle"]["tabId"] == "tab-a"


def test_apply_styles_without_tab_id_single_tab_doc() -> None:
    from google_kit.services.docs.core import docs_apply_styles
    from google_kit.services.docs.models import DocsApplyStylesInput

    out = docs_apply_styles(
        DocsApplyStylesInput(document_id="doc1", style_profile="team", dry_run=True),
        _profile_loader=lambda _name: _profile(),
    )

    assert all(
        "tabId" not in req.get("updateNamedStyle", req.get("updateDocumentStyle", {}))
        for req in out.data.requests
    )


def test_apply_styles_echoes_env_resolved_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    from google_kit.core.profiles import save_profile
    from google_kit.services.docs.core import docs_apply_styles
    from google_kit.services.docs.models import DocsApplyStylesInput

    save_profile("default", _profile())
    monkeypatch.setenv("GOOGLE_KIT_DEFAULT_STYLE_PROFILE", "default")

    out = docs_apply_styles(
        DocsApplyStylesInput(document_id="doc1", dry_run=True),
    )
    assert out.data.style_profile == "default"


def test_apply_styles_requires_profile_without_env() -> None:
    from google_kit.core.errors import Validation
    from google_kit.services.docs.core import docs_apply_styles
    from google_kit.services.docs.models import DocsApplyStylesInput

    with pytest.raises(Validation):
        docs_apply_styles(DocsApplyStylesInput(document_id="doc1", dry_run=True))


def test_normalize_mode_adds_range_requests() -> None:
    from google_kit.services.docs.core import docs_apply_styles
    from google_kit.services.docs.models import DocsApplyStylesInput

    doc = {
        "body": {
            "content": [{
                "startIndex": 1,
                "endIndex": 10,
                "paragraph": {
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                },
            }]
        }
    }
    svc = FakeDocsService(get_response=doc)
    out = docs_apply_styles(
        DocsApplyStylesInput(document_id="doc1", style_profile="team", mode="normalize", dry_run=True),
        docs_service=svc,
        _profile_loader=lambda _name: _profile(),
    )

    assert svc.calls("get")
    assert any("updateParagraphStyle" in req for req in out.data.requests)
    assert any("updateTextStyle" in req for req in out.data.requests)


def test_from_markdown_profile_update_named_style_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from google_kit.core.profiles import save_profile
    from google_kit.services.docs.core import docs_from_markdown
    from google_kit.services.docs.models import DocsFromMarkdownInput

    save_profile("default", _profile())
    monkeypatch.setenv("GOOGLE_KIT_DEFAULT_STYLE_PROFILE", "default")
    drive = FakeDriveService()
    docs = FakeDocsService()
    docs_from_markdown(
        DocsFromMarkdownInput(markdown_content="# Hello", title="T"),
        drive_service=drive,
        docs_service=docs,
    )

    requests = docs.calls("batchUpdate")[0]["body"]["requests"]
    assert not any("updateParagraphStyle" in req for req in requests)
    assert not any("updateTextStyle" in req for req in requests)
    named_reqs = [
        req["updateNamedStyle"]
        for req in requests
        if "updateNamedStyle" in req
    ]
    assert len(named_reqs) == 1
    assert "namedStyleType" not in named_reqs[0]
    assert named_reqs[0]["namedStyle"]["namedStyleType"] == "NORMAL_TEXT"
    assert named_reqs[0]["fields"] == "namedStyleType,paragraphStyle,textStyle"


def test_from_markdown_skips_legacy_formatting_with_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    from google_kit.core.profiles import save_profile
    from google_kit.services.docs.core import docs_from_markdown
    from google_kit.services.docs.models import DocsFromMarkdownInput

    save_profile("default", _profile())
    monkeypatch.setenv("GOOGLE_KIT_DEFAULT_STYLE_PROFILE", "default")
    drive = FakeDriveService()
    docs = FakeDocsService(get_response={
        "body": {
            "content": [{
                "startIndex": 1,
                "endIndex": 8,
                "paragraph": {
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                },
            }]
        }
    })
    docs_from_markdown(
        DocsFromMarkdownInput(markdown_content="# Hello", title="T"),
        drive_service=drive,
        docs_service=docs,
    )

    requests = docs.calls("batchUpdate")[0]["body"]["requests"]
    assert not any("updateParagraphStyle" in req for req in requests)
    assert not any("updateTextStyle" in req for req in requests)
    assert any("updateNamedStyle" in req for req in requests)


def test_batch_update_appends_profile_requests_atomically() -> None:
    from google_kit.services.docs.core import docs_batch_update
    from google_kit.services.docs.models import DocsBatchUpdateInput

    svc = FakeDocsService()
    docs_batch_update(
        DocsBatchUpdateInput(
            document_id="doc1",
            requests=[{"insertText": {"location": {"index": 1}, "text": "Hi"}}],
            style_profile="team",
        ),
        docs_service=svc,
        _profile_loader=lambda _name: _profile(),
    )

    body = svc.calls("batchUpdate")[0]["body"]
    assert "insertText" in body["requests"][0]
    assert any("updateNamedStyle" in req for req in body["requests"][1:])


def test_from_markdown_ignores_ambient_default_without_env() -> None:
    from google_kit.core.profiles import save_profile
    from google_kit.services.docs.core import docs_from_markdown
    from google_kit.services.docs.models import DocsFromMarkdownInput

    save_profile("default", _profile())
    drive = FakeDriveService()
    docs = FakeDocsService()
    docs_from_markdown(
        DocsFromMarkdownInput(markdown_content="# Hello", title="T"),
        drive_service=drive,
        docs_service=docs,
    )

    requests = docs.calls("batchUpdate")[0]["body"]["requests"]
    assert not any("updateNamedStyle" in req for req in requests)


def test_from_markdown_env_default_is_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from google_kit.core.profiles import save_profile
    from google_kit.services.docs.core import docs_from_markdown
    from google_kit.services.docs.models import DocsFromMarkdownInput

    save_profile("default", _profile())
    monkeypatch.setenv("GOOGLE_KIT_DEFAULT_STYLE_PROFILE", "default")
    drive = FakeDriveService()
    docs = FakeDocsService()
    docs_from_markdown(
        DocsFromMarkdownInput(markdown_content="# Hello", title="T"),
        drive_service=drive,
        docs_service=docs,
    )

    requests = docs.calls("batchUpdate")[0]["body"]["requests"]
    assert any("updateNamedStyle" in req for req in requests)


def test_styles_verbs_round_trip() -> None:
    from google_kit.services.docs.core import (
        docs_styles_add,
        docs_styles_remove,
        docs_styles_set_default,
        docs_styles_update,
        docs_styles_view,
    )
    from google_kit.services.docs.models import (
        DocsStylesAddInput,
        DocsStylesRemoveInput,
        DocsStylesSetDefaultInput,
        DocsStylesUpdateInput,
        DocsStylesViewInput,
    )

    add = docs_styles_add(DocsStylesAddInput(style_profile="team", profile_data=_profile()))
    assert add.data.path
    update = docs_styles_update(DocsStylesUpdateInput(style_profile="team", updates={"template_doc_id": "tmpl"}))
    assert update.data.profile["template_doc_id"] == "tmpl"
    docs_styles_set_default(DocsStylesSetDefaultInput(style_profile="team"))
    view = docs_styles_view(DocsStylesViewInput())
    assert "team" in view.data.profiles
    assert "default" in view.data.profiles
    removed = docs_styles_remove(DocsStylesRemoveInput(style_profile="team"))
    assert removed.data.deleted is True


def test_build_styled_recipe_trashes_on_apply_failure() -> None:
    from google_kit.services.recipes.core import recipe_build_styled
    from google_kit.services.recipes.models import BuildStyledInput

    drive = FakeDriveService()
    docs = FakeDocsService()
    result = recipe_build_styled(
        BuildStyledInput(markdown_content="# Hi", title="T", style_profile="missing"),
        service={"drive": drive, "docs": docs},
    )

    assert result.data.status == "rolled_back"
    assert any(method == "update" for method, _kw in drive.log)
