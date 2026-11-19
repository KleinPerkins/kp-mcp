"""Tests for the People service.

Note on registry isolation: ``test_registry.py`` clears ``_REGISTRY`` during
its own tests.  The module-scoped ``_ensure_people`` fixture re-registers
People ops if needed so these tests remain order-independent.

Coverage:
  people_get              — mock-read parity (normalized-json)
  people_batch_get        — mock-read parity (normalized-json)
  people_search_directory — mock-read parity (normalized-json; next_page_token)
  people_list_directory   — mock-read parity (normalized-json; next_page_token)
  people_connections      — mock-read parity (normalized-json; next_page_token)

Parity status per op:
  people_get              — mock-read DONE; sandbox-e2e DEFERRED(P6)
  people_batch_get        — mock-read DONE; sandbox-e2e DEFERRED(P6)
  people_search_directory — mock-read DONE; sandbox-e2e DEFERRED(P6)
  people_list_directory   — mock-read DONE; sandbox-e2e DEFERRED(P6)
  people_connections      — mock-read DONE; sandbox-e2e DEFERRED(P6)
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.parity import compare


@pytest.fixture(autouse=True, scope="module")
def _ensure_people() -> None:
    """Re-register People ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.people as people_mod

    if "people.get" not in {s.name for s in reg.all_specs()}:
        importlib.reload(people_mod)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "people"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Test-local mock infrastructure
# ---------------------------------------------------------------------------


@dataclass
class _PeopleRequestRecord:
    """One recorded outgoing People API call."""

    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class _PeopleExecutable:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _ConnectionsResourceProxy:
    """Proxy for ``service.people().connections()``."""

    def __init__(
        self,
        responses: dict[tuple[str, str], Any],
        requests: list[_PeopleRequestRecord],
    ) -> None:
        self._responses = responses
        self._requests = requests

    def list(self, **kwargs: Any) -> _PeopleExecutable:
        self._requests.append(
            _PeopleRequestRecord(resource="people.connections", method="list", kwargs=dict(kwargs))
        )
        return _PeopleExecutable(self._responses.get(("people.connections", "list")))


class _PeopleResourceProxy:
    """Proxy for ``service.people()`` — provides get, getBatchGet,
    searchDirectoryPeople, listDirectoryPeople, and connections()."""

    def __init__(
        self,
        responses: dict[tuple[str, str], Any],
        requests: list[_PeopleRequestRecord],
    ) -> None:
        self._responses = responses
        self._requests = requests

    def get(self, **kwargs: Any) -> _PeopleExecutable:
        return self._call("get", **kwargs)

    def getBatchGet(self, **kwargs: Any) -> _PeopleExecutable:
        return self._call("getBatchGet", **kwargs)

    def searchDirectoryPeople(self, **kwargs: Any) -> _PeopleExecutable:
        return self._call("searchDirectoryPeople", **kwargs)

    def listDirectoryPeople(self, **kwargs: Any) -> _PeopleExecutable:
        return self._call("listDirectoryPeople", **kwargs)

    def connections(self) -> _ConnectionsResourceProxy:
        return _ConnectionsResourceProxy(self._responses, self._requests)

    def _call(self, method: str, **kwargs: Any) -> _PeopleExecutable:
        self._requests.append(
            _PeopleRequestRecord(resource="people", method=method, kwargs=dict(kwargs))
        )
        return _PeopleExecutable(self._responses.get(("people", method)))


class _PeopleMockService:
    """Test-local fake People API service for mock-read parity tests.

    Responses are keyed by ``(resource, method)``:
      - ``("people", "get")``                    — people.get response
      - ``("people", "getBatchGet")``             — people.getBatchGet response
      - ``("people", "searchDirectoryPeople")``   — searchDirectoryPeople response
      - ``("people", "listDirectoryPeople")``     — listDirectoryPeople response
      - ``("people.connections", "list")``        — connections.list response
    """

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self._responses: dict[tuple[str, str], Any] = responses or {}
        self._requests: list[_PeopleRequestRecord] = []

    def people(self) -> _PeopleResourceProxy:
        return _PeopleResourceProxy(self._responses, self._requests)

    def get_requests(self) -> list[_PeopleRequestRecord]:
        return list(self._requests)

    def requests_for(self, resource: str, method: str) -> list[_PeopleRequestRecord]:
        return [r for r in self._requests if r.resource == resource and r.method == method]

    def reset(self) -> None:
        self._requests.clear()


# ---------------------------------------------------------------------------
# TestPeopleGet
# ---------------------------------------------------------------------------


class TestPeopleGet:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.people.core import people_get
        from google_kit.services.people.models import PeopleGetInput

        response = _load("get_response.json")
        expected = _load("get_expected.json")

        svc = _PeopleMockService(responses={("people", "get"): response})
        result = people_get(PeopleGetInput(resource_name="people/p001"), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_resource_name_forwarded(self) -> None:
        from google_kit.services.people.core import people_get
        from google_kit.services.people.models import PeopleGetInput

        svc = _PeopleMockService(responses={("people", "get"): {"resourceName": "people/x"}})
        people_get(PeopleGetInput(resource_name="people/me"), service=svc)
        req = svc.requests_for("people", "get")[0]
        assert req.kwargs.get("resourceName") == "people/me"

    def test_person_fields_forwarded(self) -> None:
        from google_kit.services.people.core import people_get
        from google_kit.services.people.models import PeopleGetInput

        svc = _PeopleMockService(responses={("people", "get"): {"resourceName": "people/x"}})
        people_get(
            PeopleGetInput(resource_name="people/me", person_fields="names,phoneNumbers"),
            service=svc,
        )
        req = svc.requests_for("people", "get")[0]
        assert req.kwargs.get("personFields") == "names,phoneNumbers"

    def test_null_response_handled(self) -> None:
        from google_kit.services.people.core import people_get
        from google_kit.services.people.models import PeopleGetInput

        svc = _PeopleMockService(responses={("people", "get"): None})
        result = people_get(PeopleGetInput(resource_name="people/me"), service=svc)
        assert result.data.resource_name == ""
        assert result.data.names == []
        assert result.data.email_addresses == []

    def test_names_normalized(self) -> None:
        from google_kit.services.people.core import people_get
        from google_kit.services.people.models import PeopleGetInput

        raw = {
            "resourceName": "people/p001",
            "names": [{"displayName": "Test User", "familyName": "User", "givenName": "Test"}],
            "emailAddresses": [],
        }
        svc = _PeopleMockService(responses={("people", "get"): raw})
        result = people_get(PeopleGetInput(resource_name="people/p001"), service=svc)
        assert result.data.names[0].display_name == "Test User"
        assert result.data.names[0].family_name == "User"
        assert result.data.names[0].given_name == "Test"


# ---------------------------------------------------------------------------
# TestPeopleBatchGet
# ---------------------------------------------------------------------------


class TestPeopleBatchGet:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.people.core import people_batch_get
        from google_kit.services.people.models import PeopleBatchGetInput

        response = _load("batch_get_response.json")
        expected = _load("batch_get_expected.json")

        svc = _PeopleMockService(responses={("people", "getBatchGet"): response})
        result = people_batch_get(
            PeopleBatchGetInput(resource_names=["people/p001", "people/p002"]),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_count_matches_people(self) -> None:
        from google_kit.services.people.core import people_batch_get
        from google_kit.services.people.models import PeopleBatchGetInput

        response = _load("batch_get_response.json")
        svc = _PeopleMockService(responses={("people", "getBatchGet"): response})
        result = people_batch_get(
            PeopleBatchGetInput(resource_names=["people/p001", "people/p002"]),
            service=svc,
        )
        assert result.data.count == len(result.data.people)

    def test_resource_names_forwarded(self) -> None:
        from google_kit.services.people.core import people_batch_get
        from google_kit.services.people.models import PeopleBatchGetInput

        svc = _PeopleMockService(responses={("people", "getBatchGet"): {"responses": []}})
        people_batch_get(
            PeopleBatchGetInput(resource_names=["people/p001"]),
            service=svc,
        )
        req = svc.requests_for("people", "getBatchGet")[0]
        assert req.kwargs.get("resourceNames") == ["people/p001"]

    def test_empty_responses(self) -> None:
        from google_kit.services.people.core import people_batch_get
        from google_kit.services.people.models import PeopleBatchGetInput

        svc = _PeopleMockService(responses={("people", "getBatchGet"): {"responses": []}})
        result = people_batch_get(PeopleBatchGetInput(resource_names=[]), service=svc)
        assert result.data.count == 0
        assert result.data.people == []

    def test_null_response_handled(self) -> None:
        from google_kit.services.people.core import people_batch_get
        from google_kit.services.people.models import PeopleBatchGetInput

        svc = _PeopleMockService(responses={("people", "getBatchGet"): None})
        result = people_batch_get(PeopleBatchGetInput(resource_names=[]), service=svc)
        assert result.data.count == 0


# ---------------------------------------------------------------------------
# TestPeopleSearchDirectory
# ---------------------------------------------------------------------------


class TestPeopleSearchDirectory:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.people.core import people_search_directory
        from google_kit.services.people.models import PeopleSearchDirectoryInput

        response = _load("search_directory_response.json")
        expected = _load("search_directory_expected.json")

        svc = _PeopleMockService(responses={("people", "searchDirectoryPeople"): response})
        result = people_search_directory(
            PeopleSearchDirectoryInput(query="Carol"), service=svc
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_next_page_token_propagated(self) -> None:
        from google_kit.services.people.core import people_search_directory
        from google_kit.services.people.models import PeopleSearchDirectoryInput

        response = _load("search_directory_response.json")
        svc = _PeopleMockService(responses={("people", "searchDirectoryPeople"): response})
        result = people_search_directory(PeopleSearchDirectoryInput(query="Carol"), service=svc)
        assert result.page is not None
        assert result.page.next_page_token == "tok001"

    def test_query_forwarded(self) -> None:
        from google_kit.services.people.core import people_search_directory
        from google_kit.services.people.models import PeopleSearchDirectoryInput

        svc = _PeopleMockService(responses={("people", "searchDirectoryPeople"): {"people": []}})
        people_search_directory(PeopleSearchDirectoryInput(query="Alice"), service=svc)
        req = svc.requests_for("people", "searchDirectoryPeople")[0]
        assert req.kwargs.get("query") == "Alice"

    def test_page_token_forwarded(self) -> None:
        from google_kit.services.people.core import people_search_directory
        from google_kit.services.people.models import PeopleSearchDirectoryInput

        svc = _PeopleMockService(responses={("people", "searchDirectoryPeople"): {"people": []}})
        people_search_directory(
            PeopleSearchDirectoryInput(query="x", page_token="tok_abc"), service=svc
        )
        req = svc.requests_for("people", "searchDirectoryPeople")[0]
        assert req.kwargs.get("pageToken") == "tok_abc"

    def test_no_page_token_when_absent(self) -> None:
        from google_kit.services.people.core import people_search_directory
        from google_kit.services.people.models import PeopleSearchDirectoryInput

        svc = _PeopleMockService(responses={("people", "searchDirectoryPeople"): {"people": []}})
        people_search_directory(PeopleSearchDirectoryInput(query="x"), service=svc)
        req = svc.requests_for("people", "searchDirectoryPeople")[0]
        assert "pageToken" not in req.kwargs

    def test_empty_result(self) -> None:
        from google_kit.services.people.core import people_search_directory
        from google_kit.services.people.models import PeopleSearchDirectoryInput

        svc = _PeopleMockService(responses={("people", "searchDirectoryPeople"): {"people": []}})
        result = people_search_directory(PeopleSearchDirectoryInput(query="nobody"), service=svc)
        assert result.data.count == 0
        assert result.data.people == []
        assert result.page is not None
        assert result.page.next_page_token is None


# ---------------------------------------------------------------------------
# TestPeopleListDirectory
# ---------------------------------------------------------------------------


class TestPeopleListDirectory:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.people.core import people_list_directory
        from google_kit.services.people.models import PeopleListDirectoryInput

        response = _load("list_directory_response.json")
        expected = _load("list_directory_expected.json")

        svc = _PeopleMockService(responses={("people", "listDirectoryPeople"): response})
        result = people_list_directory(PeopleListDirectoryInput(), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_next_page_token_propagated(self) -> None:
        from google_kit.services.people.core import people_list_directory
        from google_kit.services.people.models import PeopleListDirectoryInput

        response = _load("list_directory_response.json")
        svc = _PeopleMockService(responses={("people", "listDirectoryPeople"): response})
        result = people_list_directory(PeopleListDirectoryInput(), service=svc)
        assert result.page is not None
        assert result.page.next_page_token == "tok002"

    def test_read_mask_forwarded(self) -> None:
        from google_kit.services.people.core import people_list_directory
        from google_kit.services.people.models import PeopleListDirectoryInput

        svc = _PeopleMockService(responses={("people", "listDirectoryPeople"): {"people": []}})
        people_list_directory(
            PeopleListDirectoryInput(read_mask="names,phoneNumbers"), service=svc
        )
        req = svc.requests_for("people", "listDirectoryPeople")[0]
        assert req.kwargs.get("readMask") == "names,phoneNumbers"

    def test_page_token_forwarded(self) -> None:
        from google_kit.services.people.core import people_list_directory
        from google_kit.services.people.models import PeopleListDirectoryInput

        svc = _PeopleMockService(responses={("people", "listDirectoryPeople"): {"people": []}})
        people_list_directory(PeopleListDirectoryInput(page_token="tok_xyz"), service=svc)
        req = svc.requests_for("people", "listDirectoryPeople")[0]
        assert req.kwargs.get("pageToken") == "tok_xyz"

    def test_no_page_token_when_absent(self) -> None:
        from google_kit.services.people.core import people_list_directory
        from google_kit.services.people.models import PeopleListDirectoryInput

        svc = _PeopleMockService(responses={("people", "listDirectoryPeople"): {"people": []}})
        people_list_directory(PeopleListDirectoryInput(), service=svc)
        req = svc.requests_for("people", "listDirectoryPeople")[0]
        assert "pageToken" not in req.kwargs

    def test_empty_result(self) -> None:
        from google_kit.services.people.core import people_list_directory
        from google_kit.services.people.models import PeopleListDirectoryInput

        svc = _PeopleMockService(responses={("people", "listDirectoryPeople"): {"people": []}})
        result = people_list_directory(PeopleListDirectoryInput(), service=svc)
        assert result.data.count == 0
        assert result.data.people == []

    def test_null_response_handled(self) -> None:
        from google_kit.services.people.core import people_list_directory
        from google_kit.services.people.models import PeopleListDirectoryInput

        svc = _PeopleMockService(responses={("people", "listDirectoryPeople"): None})
        result = people_list_directory(PeopleListDirectoryInput(), service=svc)
        assert result.data.count == 0
        assert result.page is not None
        assert result.page.next_page_token is None


# ---------------------------------------------------------------------------
# TestPeopleConnections
# ---------------------------------------------------------------------------


class TestPeopleConnections:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.people.core import people_connections
        from google_kit.services.people.models import PeopleConnectionsInput

        response = _load("connections_response.json")
        expected = _load("connections_expected.json")

        svc = _PeopleMockService(responses={("people.connections", "list"): response})
        result = people_connections(PeopleConnectionsInput(), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_next_page_token_propagated(self) -> None:
        from google_kit.services.people.core import people_connections
        from google_kit.services.people.models import PeopleConnectionsInput

        response = _load("connections_response.json")
        svc = _PeopleMockService(responses={("people.connections", "list"): response})
        result = people_connections(PeopleConnectionsInput(), service=svc)
        assert result.page is not None
        assert result.page.next_page_token == "tok003"

    def test_resource_name_always_people_me(self) -> None:
        from google_kit.services.people.core import people_connections
        from google_kit.services.people.models import PeopleConnectionsInput

        svc = _PeopleMockService(responses={("people.connections", "list"): {"connections": []}})
        people_connections(PeopleConnectionsInput(), service=svc)
        req = svc.requests_for("people.connections", "list")[0]
        assert req.kwargs.get("resourceName") == "people/me"

    def test_person_fields_forwarded(self) -> None:
        from google_kit.services.people.core import people_connections
        from google_kit.services.people.models import PeopleConnectionsInput

        svc = _PeopleMockService(responses={("people.connections", "list"): {"connections": []}})
        people_connections(
            PeopleConnectionsInput(person_fields="names,phoneNumbers"), service=svc
        )
        req = svc.requests_for("people.connections", "list")[0]
        assert req.kwargs.get("personFields") == "names,phoneNumbers"

    def test_page_token_forwarded(self) -> None:
        from google_kit.services.people.core import people_connections
        from google_kit.services.people.models import PeopleConnectionsInput

        svc = _PeopleMockService(responses={("people.connections", "list"): {"connections": []}})
        people_connections(PeopleConnectionsInput(page_token="tok_p"), service=svc)
        req = svc.requests_for("people.connections", "list")[0]
        assert req.kwargs.get("pageToken") == "tok_p"

    def test_no_page_token_when_absent(self) -> None:
        from google_kit.services.people.core import people_connections
        from google_kit.services.people.models import PeopleConnectionsInput

        svc = _PeopleMockService(responses={("people.connections", "list"): {"connections": []}})
        people_connections(PeopleConnectionsInput(), service=svc)
        req = svc.requests_for("people.connections", "list")[0]
        assert "pageToken" not in req.kwargs

    def test_empty_connections(self) -> None:
        from google_kit.services.people.core import people_connections
        from google_kit.services.people.models import PeopleConnectionsInput

        svc = _PeopleMockService(responses={("people.connections", "list"): {"connections": []}})
        result = people_connections(PeopleConnectionsInput(), service=svc)
        assert result.data.count == 0
        assert result.data.connections == []

    def test_null_response_handled(self) -> None:
        from google_kit.services.people.core import people_connections
        from google_kit.services.people.models import PeopleConnectionsInput

        svc = _PeopleMockService(responses={("people.connections", "list"): None})
        result = people_connections(PeopleConnectionsInput(), service=svc)
        assert result.data.count == 0
        assert result.page is not None
        assert result.page.next_page_token is None


# ---------------------------------------------------------------------------
# TestRegistryIntegration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    def test_all_five_ops_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        expected = {
            "people.get",
            "people.batch_get",
            "people.search_directory",
            "people.list_directory",
            "people.connections",
        }
        assert expected.issubset(names), f"Missing ops: {expected - names}"

    def test_all_people_postures_read(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        all_ops = (
            "people.get",
            "people.batch_get",
            "people.search_directory",
            "people.list_directory",
            "people.connections",
        )
        for op in all_ops:
            assert specs[op].posture == "read", f"{op} posture should be 'read'"

    def test_all_people_plane_identity(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        all_ops = (
            "people.get",
            "people.batch_get",
            "people.search_directory",
            "people.list_directory",
            "people.connections",
        )
        for op in all_ops:
            assert specs[op].plane == "identity", f"{op} plane should be 'identity'"

    def test_identity_read_ops_capability(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        for op in ("people.get", "people.batch_get", "people.connections"):
            assert specs[op].capability == "identity.read", (
                f"{op} capability should be 'identity.read'"
            )

    def test_identity_search_ops_capability(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        for op in ("people.search_directory", "people.list_directory"):
            assert specs[op].capability == "identity.search", (
                f"{op} capability should be 'identity.search'"
            )

    def test_directory_ops_have_directory_scope(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        scope = "https://www.googleapis.com/auth/directory.readonly"
        for op in ("people.get", "people.batch_get", "people.search_directory", "people.list_directory"):
            assert scope in specs[op].scopes, f"{op} missing directory.readonly scope"

    def test_contacts_ops_have_contacts_scope(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        scope = "https://www.googleapis.com/auth/contacts.readonly"
        for op in ("people.get", "people.batch_get", "people.connections"):
            assert scope in specs[op].scopes, f"{op} missing contacts.readonly scope"

    def test_connections_only_contacts_scope(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        scopes = specs["people.connections"].scopes
        assert "https://www.googleapis.com/auth/contacts.readonly" in scopes
        assert "https://www.googleapis.com/auth/directory.readonly" not in scopes
