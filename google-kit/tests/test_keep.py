"""Tests for the Keep service.

Transport: official Keep REST API v1 (keep.googleapis.com, googleapiclient).
The legacy ``gkeep.py`` uses ``build_service("keep", "v1", creds)`` and
``keep.notes().*`` — transport path (a).

``MockGoogleService`` does not expose a ``notes()`` resource; this module
provides a local ``MockKeepService`` that follows the same recording/response
contract without modifying any shared file.

Coverage:
  keep_list   — mock-read parity (normalized-json)
  keep_get    — mock-read parity (normalized-json)
  keep_create — mutation-request parity
  keep_delete — mutation-request parity (no body; delete by resource name)

Parity status per op:
  keep_list   — mock-read DONE; sandbox-e2e DEFERRED(P6)
  keep_get    — mock-read DONE; sandbox-e2e DEFERRED(P6)
  keep_create — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  keep_delete — mutation-request DONE; sandbox-e2e DEFERRED(P6)
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.parity import compare

FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "keep"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ─────────────────────────────────────────────────────────────────────────────
#  Local mock — mirrors MockGoogleService contract for the "notes" resource
# ─────────────────────────────────────────────────────────────────────────────

class _MockExec:
    def __init__(self, resp: Any) -> None:
        self._resp = resp

    def execute(self) -> Any:
        return self._resp


class _NotesProxy:
    def __init__(self, svc: "MockKeepService") -> None:
        self._svc = svc

    def list(self, **kw: Any) -> _MockExec:
        return self._svc._call("notes", "list", **kw)

    def get(self, **kw: Any) -> _MockExec:
        return self._svc._call("notes", "get", **kw)

    def create(self, **kw: Any) -> _MockExec:
        return self._svc._call("notes", "create", **kw)

    def delete(self, **kw: Any) -> _MockExec:
        return self._svc._call("notes", "delete", **kw)


class MockKeepService:
    """Fake Keep API client (mirrors MockGoogleService contract for notes resource).

    Instantiation mirrors MockGoogleService::

        svc = MockKeepService(responses={
            ("notes", "list"): {...},
        })

    Mutation-request inspection::

        svc.last_request_body()          # body kwarg of last call
        svc.requests_for("notes", "create")  # all matching calls
    """

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self._responses: dict[tuple[str, str], Any] = responses or {}
        self._requests: list[dict[str, Any]] = []

    def notes(self) -> _NotesProxy:
        return _NotesProxy(self)

    def _call(self, resource: str, method: str, **kw: Any) -> _MockExec:
        self._requests.append({"resource": resource, "method": method, "kwargs": kw})
        return _MockExec(self._responses.get((resource, method)))

    def last_request_body(self) -> dict[str, Any] | None:
        for rec in reversed(self._requests):
            if "body" in rec["kwargs"]:
                return rec["kwargs"]["body"]
        return None

    def requests_for(self, resource: str, method: str) -> list[dict[str, Any]]:
        return [r for r in self._requests if r["resource"] == resource and r["method"] == method]

    def get_requests(self) -> list[dict[str, Any]]:
        return list(self._requests)

    def reset(self) -> None:
        self._requests.clear()


# ─────────────────────────────────────────────────────────────────────────────
#  Registry isolation fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True, scope="module")
def _ensure_keep() -> None:
    """Re-register Keep ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.keep as keep_mod

    if "keep.list" not in {s.name for s in reg.all_specs()}:
        importlib.reload(keep_mod)


# ─────────────────────────────────────────────────────────────────────────────
#  keep.list
# ─────────────────────────────────────────────────────────────────────────────

class TestKeepList:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.keep.core import keep_list
        from google_kit.services.keep.models import KeepListInput

        response = _load("list_response.json")
        expected = _load("list_expected.json")

        svc = MockKeepService(responses={("notes", "list"): response})
        result = keep_list(KeepListInput(), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_empty_list(self) -> None:
        from google_kit.services.keep.core import keep_list
        from google_kit.services.keep.models import KeepListInput

        svc = MockKeepService(responses={("notes", "list"): {}})
        result = keep_list(KeepListInput(), service=svc)
        assert result.data.count == 0
        assert result.data.notes == []

    def test_page_size_default_50(self) -> None:
        from google_kit.services.keep.core import keep_list
        from google_kit.services.keep.models import KeepListInput

        svc = MockKeepService(responses={("notes", "list"): {}})
        keep_list(KeepListInput(), service=svc)
        req = svc.get_requests()[0]
        assert req["kwargs"]["pageSize"] == 50

    def test_filter_passed_as_empty_string_when_none(self) -> None:
        from google_kit.services.keep.core import keep_list
        from google_kit.services.keep.models import KeepListInput

        svc = MockKeepService(responses={("notes", "list"): {}})
        keep_list(KeepListInput(), service=svc)
        req = svc.get_requests()[0]
        assert req["kwargs"]["filter"] == ""

    def test_filter_string_forwarded(self) -> None:
        from google_kit.services.keep.core import keep_list
        from google_kit.services.keep.models import KeepListInput

        svc = MockKeepService(responses={("notes", "list"): {}})
        keep_list(KeepListInput(filter="label:important"), service=svc)
        req = svc.get_requests()[0]
        assert req["kwargs"]["filter"] == "label:important"

    def test_list_note_has_null_body_text(self) -> None:
        """List notes (checklist type) produce null body_text."""
        from google_kit.services.keep.core import keep_list
        from google_kit.services.keep.models import KeepListInput

        response = _load("list_response.json")
        svc = MockKeepService(responses={("notes", "list"): response})
        result = keep_list(KeepListInput(), service=svc)
        shopping = next(n for n in result.data.notes if n.name == "notes/abc002")
        assert shopping.body_text is None


# ─────────────────────────────────────────────────────────────────────────────
#  keep.get
# ─────────────────────────────────────────────────────────────────────────────

class TestKeepGet:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.keep.core import keep_get
        from google_kit.services.keep.models import KeepGetInput

        response = _load("get_response.json")
        expected = _load("get_expected.json")

        svc = MockKeepService(responses={("notes", "get"): response})
        result = keep_get(KeepGetInput(note_id="notes/abc001"), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_note_id_forwarded_as_name(self) -> None:
        from google_kit.services.keep.core import keep_get
        from google_kit.services.keep.models import KeepGetInput

        svc = MockKeepService(responses={
            ("notes", "get"): {"name": "notes/abc001", "title": "T"}
        })
        keep_get(KeepGetInput(note_id="notes/abc001"), service=svc)
        req = svc.get_requests()[0]
        assert req["kwargs"]["name"] == "notes/abc001"

    def test_text_body_extracted(self) -> None:
        from google_kit.services.keep.core import keep_get
        from google_kit.services.keep.models import KeepGetInput

        raw = {
            "name": "notes/x",
            "title": "T",
            "body": {"text": {"text": "hello"}},
        }
        svc = MockKeepService(responses={("notes", "get"): raw})
        result = keep_get(KeepGetInput(note_id="notes/x"), service=svc)
        assert result.data.body_text == "hello"

    def test_list_body_has_null_body_text(self) -> None:
        from google_kit.services.keep.core import keep_get
        from google_kit.services.keep.models import KeepGetInput

        raw = {
            "name": "notes/x",
            "title": "T",
            "body": {"list": {"listItems": [{"text": {"text": "item1"}}]}},
        }
        svc = MockKeepService(responses={("notes", "get"): raw})
        result = keep_get(KeepGetInput(note_id="notes/x"), service=svc)
        assert result.data.body_text is None


# ─────────────────────────────────────────────────────────────────────────────
#  keep.create
# ─────────────────────────────────────────────────────────────────────────────

class TestKeepCreate:
    def test_mutation_request_parity_text_note(self) -> None:
        from google_kit.services.keep.core import keep_create
        from google_kit.services.keep.models import KeepCreateInput

        expected_body = _load("create_expected_body.json")
        canned_response = {"name": "notes/new001", "title": "Meeting notes"}
        svc = MockKeepService(responses={("notes", "create"): canned_response})

        keep_create(
            KeepCreateInput(title="Meeting notes", body_text="Q1 planning session"),
            service=svc,
        )

        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_text_note_body_structure(self) -> None:
        from google_kit.services.keep.core import keep_create
        from google_kit.services.keep.models import KeepCreateInput

        svc = MockKeepService(responses={("notes", "create"): {"name": "notes/x", "title": "T"}})
        keep_create(KeepCreateInput(title="T", body_text="hello"), service=svc)
        body = svc.last_request_body()
        assert body == {"title": "T", "body": {"text": {"text": "hello"}}}

    def test_no_body_text_sends_empty_body(self) -> None:
        from google_kit.services.keep.core import keep_create
        from google_kit.services.keep.models import KeepCreateInput

        svc = MockKeepService(responses={("notes", "create"): {"name": "notes/x", "title": "T"}})
        keep_create(KeepCreateInput(title="T"), service=svc)
        body = svc.last_request_body()
        assert body == {"title": "T", "body": {}}

    def test_list_items_build_correct_structure(self) -> None:
        """Checklist body matches legacy gkeep.py structure exactly."""
        from google_kit.services.keep.core import keep_create
        from google_kit.services.keep.models import KeepCreateInput

        svc = MockKeepService(responses={("notes", "create"): {"name": "notes/x", "title": "T"}})
        keep_create(KeepCreateInput(title="T", list_items="Milk, Eggs"), service=svc)
        body = svc.last_request_body()
        assert body == {
            "title": "T",
            "body": {
                "list": {
                    "listItems": [
                        {"text": {"text": "Milk"}},
                        {"text": {"text": "Eggs"}},
                    ]
                }
            },
        }

    def test_list_items_overrides_body_text(self) -> None:
        from google_kit.services.keep.core import keep_create
        from google_kit.services.keep.models import KeepCreateInput

        svc = MockKeepService(responses={("notes", "create"): {"name": "notes/x", "title": "T"}})
        keep_create(
            KeepCreateInput(title="T", body_text="ignored", list_items="A, B"),
            service=svc,
        )
        body = svc.last_request_body()
        assert "list" in body["body"]
        assert "text" not in body["body"]

    def test_result_contains_name_and_title(self) -> None:
        from google_kit.services.keep.core import keep_create
        from google_kit.services.keep.models import KeepCreateInput

        svc = MockKeepService(responses={
            ("notes", "create"): {"name": "notes/new001", "title": "Meeting notes"}
        })
        result = keep_create(KeepCreateInput(title="Meeting notes"), service=svc)
        assert result.data.name == "notes/new001"
        assert result.data.title == "Meeting notes"


# ─────────────────────────────────────────────────────────────────────────────
#  keep.delete
# ─────────────────────────────────────────────────────────────────────────────

class TestKeepDelete:
    def test_mutation_request_recorded(self) -> None:
        from google_kit.services.keep.core import keep_delete
        from google_kit.services.keep.models import KeepDeleteInput

        svc = MockKeepService(responses={("notes", "delete"): None})
        result = keep_delete(KeepDeleteInput(note_id="notes/abc001"), service=svc)
        assert result.data.deleted is True
        assert result.data.note_id == "notes/abc001"

        delete_reqs = svc.requests_for("notes", "delete")
        assert len(delete_reqs) == 1
        assert delete_reqs[0]["kwargs"]["name"] == "notes/abc001"

    def test_delete_sends_name_kwarg(self) -> None:
        from google_kit.services.keep.core import keep_delete
        from google_kit.services.keep.models import KeepDeleteInput

        svc = MockKeepService(responses={("notes", "delete"): None})
        keep_delete(KeepDeleteInput(note_id="notes/xyz999"), service=svc)
        req = svc.get_requests()[0]
        assert req["kwargs"] == {"name": "notes/xyz999"}

    def test_delete_has_no_body(self) -> None:
        from google_kit.services.keep.core import keep_delete
        from google_kit.services.keep.models import KeepDeleteInput

        svc = MockKeepService(responses={("notes", "delete"): None})
        keep_delete(KeepDeleteInput(note_id="notes/abc001"), service=svc)
        assert svc.last_request_body() is None


# ─────────────────────────────────────────────────────────────────────────────
#  Registry integration
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistryIntegration:
    def test_all_four_ops_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        expected = {"keep.list", "keep.get", "keep.create", "keep.delete"}
        assert expected.issubset(names), f"Missing ops: {expected - names}"

    def test_keep_postures(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["keep.list"].posture == "read"
        assert specs["keep.get"].posture == "read"
        assert specs["keep.create"].posture == "write"
        assert specs["keep.delete"].posture == "destructive"

    def test_keep_scopes(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        # Writes/destructive hold the read-write keep scope.
        for name in ("keep.create", "keep.delete"):
            assert "https://www.googleapis.com/auth/keep" in specs[name].scopes
        # Pure reads tightened to keep.readonly (gate c).
        for name in ("keep.list", "keep.get"):
            assert "https://www.googleapis.com/auth/keep.readonly" in specs[name].scopes
