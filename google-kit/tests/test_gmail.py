"""Tests for the Gmail service.

Note on registry isolation: ``test_registry.py`` clears ``_REGISTRY`` during
its own tests.  The module-scoped ``_ensure_gmail`` fixture below re-registers
Gmail ops if needed so these tests remain order-independent.

Note on mock design: Gmail's API uses nested resources (``service.users().messages()``
etc.) which differ from the flat Tasks API structure in ``MockGoogleService``.
``_GmailMockService`` is a test-local implementation for the nested Gmail structure.

Coverage:
  gmail_list          — mock-read parity (normalized-json)
  gmail_get           — mock-read parity (normalized-json; body decode + 500-char truncation)
  gmail_search        — mock-read parity (normalized-json)
  gmail_labels        — mock-read parity (normalized-json)
  gmail_profile       — mock-read parity (normalized-json; emailAddress redacted)
  gmail_history       — mock-read parity (normalized-json)
  gmail_attachments   — mock-read parity (normalized-json)
  gmail_draft         — mutation-request parity (outer shape + decoded MIME; F5 gate)
  gmail_send          — mutation-request parity (outer shape + decoded MIME; F5 gate)
  gmail_modify        — mutation-request parity (request body)
  gmail_manage_labels — mutation-request parity (request body)
  gmail_watch         — mutation-request parity (request body)

Parity status per op:
  gmail_list        — mock-read DONE; sandbox-e2e awaiting operator creds (P6 gate)
  gmail_get         — mock-read DONE; sandbox-e2e awaiting operator creds (P6 gate)
  gmail_search      — mock-read DONE; sandbox-e2e awaiting operator creds (P6 gate)
  gmail_labels      — mock-read DONE; sandbox-e2e awaiting operator creds (P6 gate)
  gmail_profile     — mock-read DONE; sandbox-e2e awaiting operator creds (P6 gate)
  gmail_history     — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
  gmail_attachments — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
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


@pytest.fixture(autouse=True, scope="module")
def _ensure_gmail() -> None:
    """Re-register Gmail ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.gmail as gmail_mod

    if "gmail.list" not in {s.name for s in reg.all_specs()}:
        importlib.reload(gmail_mod)
    if "gmail.history" not in {s.name for s in reg.all_specs()}:
        importlib.reload(gmail_mod)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "gmail"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@dataclass
class _GmailRequestRecord:
    """One recorded outgoing Gmail API call."""

    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class _GmailExecutable:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _GmailResourceProxy:
    """Proxy for a nested Gmail API resource (messages, labels, history)."""

    def __init__(
        self,
        resource: str,
        responses: dict[tuple[str, str], Any],
        requests: list[_GmailRequestRecord],
    ) -> None:
        self._resource = resource
        self._responses = responses
        self._requests = requests

    def list(self, **kwargs: Any) -> _GmailExecutable:
        return self._call("list", **kwargs)

    def get(self, **kwargs: Any) -> _GmailExecutable:
        return self._call("get", **kwargs)

    def attachments(self) -> "_GmailResourceProxy":
        return _GmailResourceProxy(
            f"{self._resource}.attachments", self._responses, self._requests
        )

    def create(self, **kwargs: Any) -> _GmailExecutable:
        return self._call("create", **kwargs)

    def send(self, **kwargs: Any) -> _GmailExecutable:
        return self._call("send", **kwargs)

    def modify(self, **kwargs: Any) -> _GmailExecutable:
        return self._call("modify", **kwargs)

    def _call(self, method: str, **kwargs: Any) -> _GmailExecutable:
        self._requests.append(
            _GmailRequestRecord(resource=self._resource, method=method, kwargs=dict(kwargs))
        )
        return _GmailExecutable(self._responses.get((self._resource, method)))


class _GmailUsersProxy:
    """Proxy for ``service.users()`` — provides messages(), labels(), history(), getProfile()."""

    def __init__(
        self,
        responses: dict[tuple[str, str], Any],
        requests: list[_GmailRequestRecord],
    ) -> None:
        self._responses = responses
        self._requests = requests

    def messages(self) -> _GmailResourceProxy:
        return _GmailResourceProxy("messages", self._responses, self._requests)

    def labels(self) -> _GmailResourceProxy:
        return _GmailResourceProxy("labels", self._responses, self._requests)

    def history(self) -> _GmailResourceProxy:
        return _GmailResourceProxy("history", self._responses, self._requests)

    def drafts(self) -> _GmailResourceProxy:
        return _GmailResourceProxy("drafts", self._responses, self._requests)

    def watch(self, **kwargs: Any) -> _GmailExecutable:
        self._requests.append(
            _GmailRequestRecord(resource="users", method="watch", kwargs=dict(kwargs))
        )
        return _GmailExecutable(self._responses.get(("users", "watch")))

    def getProfile(self, **kwargs: Any) -> _GmailExecutable:
        self._requests.append(
            _GmailRequestRecord(resource="profile", method="get", kwargs=dict(kwargs))
        )
        return _GmailExecutable(self._responses.get(("profile", "get")))


class _GmailMockService:
    """Test-local fake Gmail service for mock-read and mutation-request parity tests.

    Responses are keyed by ``(resource, method)``:
      - ``("messages", "list")``   — users.messages.list response
      - ``("messages", "get")``    — users.messages.get response
      - ``("messages", "send")``   — users.messages.send response
      - ``("messages", "modify")`` — users.messages.modify response
      - ``("labels", "list")``     — users.labels.list response
      - ``("labels", "create")``   — users.labels.create response
      - ``("profile", "get")``     — users.getProfile response
      - ``("drafts", "create")``   — users.drafts.create response
      - ``("users", "watch")``     — users.watch response
    """

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self._responses: dict[tuple[str, str], Any] = responses or {}
        self._requests: list[_GmailRequestRecord] = []

    def users(self) -> _GmailUsersProxy:
        return _GmailUsersProxy(self._responses, self._requests)

    def get_requests(self) -> list[_GmailRequestRecord]:
        return list(self._requests)

    def requests_for(self, resource: str, method: str) -> list[_GmailRequestRecord]:
        return [r for r in self._requests if r.resource == resource and r.method == method]

    def reset(self) -> None:
        self._requests.clear()


class TestGmailList:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_list
        from google_kit.services.gmail.models import GmailListInput

        response = _load("list_response.json")
        expected = _load("list_expected.json")

        svc = _GmailMockService(responses={("messages", "list"): response})
        result = gmail_list(GmailListInput(), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_count_matches_messages(self) -> None:
        from google_kit.services.gmail.core import gmail_list
        from google_kit.services.gmail.models import GmailListInput

        response = _load("list_response.json")
        svc = _GmailMockService(responses={("messages", "list"): response})
        result = gmail_list(GmailListInput(), service=svc)
        assert result.data.count == len(result.data.messages)

    def test_empty_list(self) -> None:
        from google_kit.services.gmail.core import gmail_list
        from google_kit.services.gmail.models import GmailListInput

        svc = _GmailMockService(responses={("messages", "list"): {"messages": []}})
        result = gmail_list(GmailListInput(), service=svc)
        assert result.data.count == 0
        assert result.data.messages == []

    def test_null_response(self) -> None:
        from google_kit.services.gmail.core import gmail_list
        from google_kit.services.gmail.models import GmailListInput

        svc = _GmailMockService(responses={("messages", "list"): None})
        result = gmail_list(GmailListInput(), service=svc)
        assert result.data.count == 0

    def test_q_param_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_list
        from google_kit.services.gmail.models import GmailListInput

        svc = _GmailMockService(responses={("messages", "list"): {"messages": []}})
        gmail_list(GmailListInput(q="is:unread"), service=svc)
        req = svc.requests_for("messages", "list")[0]
        assert req.kwargs.get("q") == "is:unread"

    def test_label_ids_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_list
        from google_kit.services.gmail.models import GmailListInput

        svc = _GmailMockService(responses={("messages", "list"): {"messages": []}})
        gmail_list(GmailListInput(label_ids=["INBOX", "UNREAD"]), service=svc)
        req = svc.requests_for("messages", "list")[0]
        assert req.kwargs.get("labelIds") == ["INBOX", "UNREAD"]

    def test_max_results_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_list
        from google_kit.services.gmail.models import GmailListInput

        svc = _GmailMockService(responses={("messages", "list"): {"messages": []}})
        gmail_list(GmailListInput(max_results=10), service=svc)
        req = svc.requests_for("messages", "list")[0]
        assert req.kwargs.get("maxResults") == 10


class TestGmailGet:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_get
        from google_kit.services.gmail.models import GmailGetInput

        response = _load("get_response.json")
        expected = _load("get_expected.json")

        svc = _GmailMockService(responses={("messages", "get"): response})
        result = gmail_get(GmailGetInput(message_id="msg001abc"), service=svc)

        actual = result.data.model_dump()
        parity = compare("semantic", expected, actual)
        assert parity.match, f"semantic mismatch:\n{parity.diff}"

    def test_body_decode_plain_text(self) -> None:
        from google_kit.services.gmail.core import gmail_get
        from google_kit.services.gmail.models import GmailGetInput

        body_bytes = b"Plain text content."
        encoded = base64.urlsafe_b64encode(body_bytes).decode()
        msg = {
            "id": "plain001",
            "threadId": "t001",
            "snippet": "Plain",
            "labelIds": [],
            "payload": {
                "mimeType": "text/plain",
                "headers": [],
                "body": {"data": encoded},
            },
        }
        svc = _GmailMockService(responses={("messages", "get"): msg})
        result = gmail_get(GmailGetInput(message_id="plain001"), service=svc)
        assert result.data.body == "Plain text content."

    def test_body_truncated_at_500_chars(self) -> None:
        from google_kit.services.gmail.core import gmail_get
        from google_kit.services.gmail.models import GmailGetInput

        long_body = "A" * 600
        encoded = base64.urlsafe_b64encode(long_body.encode()).decode()
        msg = {
            "id": "long001",
            "threadId": "t001",
            "snippet": "",
            "labelIds": [],
            "payload": {
                "mimeType": "text/plain",
                "headers": [],
                "body": {"data": encoded},
            },
        }
        svc = _GmailMockService(responses={("messages", "get"): msg})
        result = gmail_get(GmailGetInput(message_id="long001"), service=svc)
        assert result.data.body == "A" * 500 + "..."

    def test_body_not_truncated_when_under_500(self) -> None:
        from google_kit.services.gmail.core import gmail_get
        from google_kit.services.gmail.models import GmailGetInput

        short_body = "Short."
        encoded = base64.urlsafe_b64encode(short_body.encode()).decode()
        msg = {
            "id": "short001",
            "threadId": "t001",
            "snippet": "",
            "labelIds": [],
            "payload": {
                "mimeType": "text/plain",
                "headers": [],
                "body": {"data": encoded},
            },
        }
        svc = _GmailMockService(responses={("messages", "get"): msg})
        result = gmail_get(GmailGetInput(message_id="short001"), service=svc)
        assert result.data.body == "Short."
        assert not result.data.body.endswith("...")

    def test_format_full_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_get
        from google_kit.services.gmail.models import GmailGetInput

        msg = {
            "id": "m1",
            "threadId": "t1",
            "snippet": "",
            "labelIds": [],
            "payload": {"mimeType": "text/plain", "headers": [], "body": {}},
        }
        svc = _GmailMockService(responses={("messages", "get"): msg})
        gmail_get(GmailGetInput(message_id="m1"), service=svc)
        req = svc.requests_for("messages", "get")[0]
        assert req.kwargs.get("format") == "full"
        assert req.kwargs.get("id") == "m1"

    def test_html_body_stripped(self) -> None:
        from google_kit.services.gmail.core import gmail_get
        from google_kit.services.gmail.models import GmailGetInput

        html_body = b"<p>Hello <b>World</b></p>"
        encoded = base64.urlsafe_b64encode(html_body).decode()
        msg = {
            "id": "html001",
            "threadId": "t001",
            "snippet": "",
            "labelIds": [],
            "payload": {
                "mimeType": "text/html",
                "headers": [],
                "body": {"data": encoded},
            },
        }
        svc = _GmailMockService(responses={("messages", "get"): msg})
        result = gmail_get(GmailGetInput(message_id="html001"), service=svc)
        assert "<" not in result.data.body
        assert "Hello" in result.data.body
        assert "World" in result.data.body

    def test_multipart_body_recursive(self) -> None:
        from google_kit.services.gmail.core import gmail_get
        from google_kit.services.gmail.models import GmailGetInput

        plain_body = b"Multipart plain part."
        encoded = base64.urlsafe_b64encode(plain_body).decode()
        msg = {
            "id": "multi001",
            "threadId": "t001",
            "snippet": "",
            "labelIds": [],
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [],
                "body": {},
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": encoded},
                        "headers": [],
                    }
                ],
            },
        }
        svc = _GmailMockService(responses={("messages", "get"): msg})
        result = gmail_get(GmailGetInput(message_id="multi001"), service=svc)
        assert result.data.body == "Multipart plain part."


class TestGmailSearch:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_search
        from google_kit.services.gmail.models import GmailSearchInput

        response = _load("search_response.json")
        expected = _load("search_expected.json")

        svc = _GmailMockService(responses={("messages", "list"): response})
        result = gmail_search(
            GmailSearchInput(q="from:boss@example.com"), service=svc
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_query_echoed_in_output(self) -> None:
        from google_kit.services.gmail.core import gmail_search
        from google_kit.services.gmail.models import GmailSearchInput

        svc = _GmailMockService(responses={("messages", "list"): {"messages": []}})
        result = gmail_search(GmailSearchInput(q="subject:hello"), service=svc)
        assert result.data.query == "subject:hello"
        assert result.data.count == 0

    def test_q_forwarded_to_api(self) -> None:
        from google_kit.services.gmail.core import gmail_search
        from google_kit.services.gmail.models import GmailSearchInput

        svc = _GmailMockService(responses={("messages", "list"): {"messages": []}})
        gmail_search(GmailSearchInput(q="label:INBOX"), service=svc)
        req = svc.requests_for("messages", "list")[0]
        assert req.kwargs.get("q") == "label:INBOX"

    def test_empty_result(self) -> None:
        from google_kit.services.gmail.core import gmail_search
        from google_kit.services.gmail.models import GmailSearchInput

        svc = _GmailMockService(responses={("messages", "list"): {}})
        result = gmail_search(GmailSearchInput(q="from:nobody"), service=svc)
        assert result.data.count == 0
        assert result.data.messages == []


class TestGmailLabels:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_labels
        from google_kit.services.gmail.models import GmailLabelsInput

        response = _load("labels_response.json")
        expected = _load("labels_expected.json")

        svc = _GmailMockService(responses={("labels", "list"): response})
        result = gmail_labels(GmailLabelsInput(), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_count_matches_labels(self) -> None:
        from google_kit.services.gmail.core import gmail_labels
        from google_kit.services.gmail.models import GmailLabelsInput

        response = _load("labels_response.json")
        svc = _GmailMockService(responses={("labels", "list"): response})
        result = gmail_labels(GmailLabelsInput(), service=svc)
        assert result.data.count == len(result.data.labels)

    def test_label_type_preserved(self) -> None:
        from google_kit.services.gmail.core import gmail_labels
        from google_kit.services.gmail.models import GmailLabelsInput

        response = {"labels": [
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "Custom", "name": "Custom", "type": "user"},
        ]}
        svc = _GmailMockService(responses={("labels", "list"): response})
        result = gmail_labels(GmailLabelsInput(), service=svc)
        types = {lbl.id: lbl.label_type for lbl in result.data.labels}
        assert types["INBOX"] == "system"
        assert types["Custom"] == "user"

    def test_empty_labels(self) -> None:
        from google_kit.services.gmail.core import gmail_labels
        from google_kit.services.gmail.models import GmailLabelsInput

        svc = _GmailMockService(responses={("labels", "list"): {"labels": []}})
        result = gmail_labels(GmailLabelsInput(), service=svc)
        assert result.data.count == 0
        assert result.data.labels == []


class TestGmailProfile:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_profile
        from google_kit.services.gmail.models import GmailProfileInput

        response = _load("profile_response.json")
        expected = _load("profile_expected.json")

        svc = _GmailMockService(responses={("profile", "get"): response})
        result = gmail_profile(GmailProfileInput(), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_email_always_redacted(self) -> None:
        from google_kit.services.gmail.core import gmail_profile
        from google_kit.services.gmail.models import GmailProfileInput

        response = {"emailAddress": "real.user@company.com", "messagesTotal": 10, "threadsTotal": 5}
        svc = _GmailMockService(responses={("profile", "get"): response})
        result = gmail_profile(GmailProfileInput(), service=svc)
        assert result.data.email_address == "[REDACTED]"
        assert "real.user@company.com" not in str(result.data.model_dump())

    def test_counts_preserved(self) -> None:
        from google_kit.services.gmail.core import gmail_profile
        from google_kit.services.gmail.models import GmailProfileInput

        response = {"emailAddress": "x@y.com", "messagesTotal": 999, "threadsTotal": 777}
        svc = _GmailMockService(responses={("profile", "get"): response})
        result = gmail_profile(GmailProfileInput(), service=svc)
        assert result.data.messages_total == 999
        assert result.data.threads_total == 777

    def test_null_response_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_profile
        from google_kit.services.gmail.models import GmailProfileInput

        svc = _GmailMockService(responses={("profile", "get"): None})
        result = gmail_profile(GmailProfileInput(), service=svc)
        assert result.data.email_address == "[REDACTED]"
        assert result.data.messages_total == 0
        assert result.data.threads_total == 0


class TestRegistryIntegration:
    def test_all_seven_ops_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        expected = {
            "gmail.list",
            "gmail.get",
            "gmail.search",
            "gmail.labels",
            "gmail.profile",
            "gmail.history",
            "gmail.attachments",
        }
        assert expected.issubset(names), f"Missing ops: {expected - names}"

    def test_all_gmail_postures_read(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        all_ops = (
            "gmail.list", "gmail.get", "gmail.search", "gmail.labels",
            "gmail.profile", "gmail.history", "gmail.attachments",
        )
        for op in all_ops:
            assert specs[op].posture == "read", f"{op} posture should be 'read'"

    def test_all_gmail_scopes_readonly(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        scope = "https://www.googleapis.com/auth/gmail.readonly"
        all_ops = (
            "gmail.list", "gmail.get", "gmail.search", "gmail.labels",
            "gmail.profile", "gmail.history", "gmail.attachments",
        )
        for op in all_ops:
            assert scope in specs[op].scopes, f"{op} missing gmail.readonly scope"

    def test_e1_ops_plane_and_capability(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["gmail.history"].plane == "messaging"
        assert specs["gmail.history"].capability == "history.read"
        assert specs["gmail.attachments"].plane == "messaging"
        assert specs["gmail.attachments"].capability == "attachment.read"


class TestGmailHistory:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_history
        from google_kit.services.gmail.models import GmailHistoryInput

        response = _load("history_response.json")
        expected = _load("history_expected.json")

        svc = _GmailMockService(responses={("history", "list"): response})
        result = gmail_history(GmailHistoryInput(start_history_id="8000"), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_start_history_id_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_history
        from google_kit.services.gmail.models import GmailHistoryInput

        svc = _GmailMockService(responses={("history", "list"): {"history": [], "historyId": "100"}})
        gmail_history(GmailHistoryInput(start_history_id="50"), service=svc)
        req = svc.requests_for("history", "list")[0]
        assert req.kwargs.get("startHistoryId") == "50"
        assert req.kwargs.get("userId") == "me"

    def test_history_types_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_history
        from google_kit.services.gmail.models import GmailHistoryInput

        svc = _GmailMockService(responses={("history", "list"): {"history": []}})
        gmail_history(
            GmailHistoryInput(start_history_id="1", history_types=["messageAdded"]),
            service=svc,
        )
        req = svc.requests_for("history", "list")[0]
        assert req.kwargs.get("historyTypes") == ["messageAdded"]

    def test_optional_params_none_when_absent(self) -> None:
        from google_kit.services.gmail.core import gmail_history
        from google_kit.services.gmail.models import GmailHistoryInput

        svc = _GmailMockService(responses={("history", "list"): {"history": []}})
        gmail_history(GmailHistoryInput(start_history_id="1"), service=svc)
        req = svc.requests_for("history", "list")[0]
        assert req.kwargs.get("historyTypes") is None
        assert req.kwargs.get("labelId") is None
        assert req.kwargs.get("pageToken") is None

    def test_empty_history(self) -> None:
        from google_kit.services.gmail.core import gmail_history
        from google_kit.services.gmail.models import GmailHistoryInput

        svc = _GmailMockService(responses={("history", "list"): {"history": [], "historyId": "200"}})
        result = gmail_history(GmailHistoryInput(start_history_id="1"), service=svc)
        assert result.data.history == []
        assert result.data.history_id == "200"
        assert result.page is not None
        assert result.page.next_page_token is None

    def test_null_response_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_history
        from google_kit.services.gmail.models import GmailHistoryInput

        svc = _GmailMockService(responses={("history", "list"): None})
        result = gmail_history(GmailHistoryInput(start_history_id="1"), service=svc)
        assert result.data.history == []
        assert result.data.history_id is None


class TestGmailAttachments:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_attachments
        from google_kit.services.gmail.models import GmailAttachmentsInput

        response = _load("attachments_response.json")
        expected = _load("attachments_expected.json")

        svc = _GmailMockService(responses={("messages.attachments", "get"): response})
        result = gmail_attachments(
            GmailAttachmentsInput(message_id="msg001abc", attachment_id="ANGjdJ8abc123"),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_attachment_id_echoed(self) -> None:
        from google_kit.services.gmail.core import gmail_attachments
        from google_kit.services.gmail.models import GmailAttachmentsInput

        svc = _GmailMockService(
            responses={("messages.attachments", "get"): {"size": 0, "data": ""}}
        )
        result = gmail_attachments(
            GmailAttachmentsInput(message_id="m1", attachment_id="att42"),
            service=svc,
        )
        assert result.data.attachment_id == "att42"

    def test_size_and_data_passed_through(self) -> None:
        from google_kit.services.gmail.core import gmail_attachments
        from google_kit.services.gmail.models import GmailAttachmentsInput

        payload = {"size": 1234, "data": "dGVzdA=="}
        svc = _GmailMockService(responses={("messages.attachments", "get"): payload})
        result = gmail_attachments(
            GmailAttachmentsInput(message_id="m1", attachment_id="att1"),
            service=svc,
        )
        assert result.data.size == 1234
        assert result.data.data_b64 == "dGVzdA=="

    def test_null_response_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_attachments
        from google_kit.services.gmail.models import GmailAttachmentsInput

        svc = _GmailMockService(responses={("messages.attachments", "get"): None})
        result = gmail_attachments(
            GmailAttachmentsInput(message_id="m1", attachment_id="att1"),
            service=svc,
        )
        assert result.data.size == 0
        assert result.data.data_b64 == ""


class TestBodyDecoding:
    def test_decode_body_plain(self) -> None:
        from google_kit.services.gmail.core import _decode_body

        data = base64.urlsafe_b64encode(b"hello plain").decode()
        payload = {"mimeType": "text/plain", "body": {"data": data}}
        assert _decode_body(payload) == "hello plain"

    def test_decode_body_html(self) -> None:
        from google_kit.services.gmail.core import _decode_body

        html = b"<p>Hello <b>World</b></p>"
        data = base64.urlsafe_b64encode(html).decode()
        payload = {"mimeType": "text/html", "body": {"data": data}}
        result = _decode_body(payload)
        assert "Hello" in result
        assert "<" not in result

    def test_decode_body_empty(self) -> None:
        from google_kit.services.gmail.core import _decode_body

        assert _decode_body({}) == ""
        assert _decode_body({"mimeType": "text/plain", "body": {}}) == ""


# ---------------------------------------------------------------------------
# Write ops
# ---------------------------------------------------------------------------


def _decode_raw_mime(raw_b64: str) -> Any:
    """Decode a base64url raw string into an email.message.Message."""
    import email as _email
    raw_bytes = base64.urlsafe_b64decode(raw_b64 + "==")
    return _email.message_from_bytes(raw_bytes)


class TestGmailDraft:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_draft
        from google_kit.services.gmail.models import GmailDraftInput

        expected_decoded = _load("draft_decoded_content.json")
        svc = _GmailMockService(responses={
            ("drafts", "create"): {"id": "draft001", "message": {"id": "msg001"}},
        })
        gmail_draft(
            GmailDraftInput(
                to=expected_decoded["to"],
                subject=expected_decoded["subject"],
                body_text=expected_decoded["body"],
            ),
            service=svc,
        )

        creates = svc.requests_for("drafts", "create")
        assert creates, "Expected drafts.create call"
        body = creates[0].kwargs["body"]

        assert "message" in body, "Outer body must have 'message' key"
        assert "raw" in body["message"], "body['message'] must have 'raw' key"

        msg = _decode_raw_mime(body["message"]["raw"])
        assert msg["To"] == expected_decoded["to"]
        assert msg["Subject"] == expected_decoded["subject"]
        decoded_body = msg.get_payload(decode=True)
        assert decoded_body is not None
        assert expected_decoded["body"].encode() in decoded_body or \
               expected_decoded["body"] in decoded_body.decode("utf-8", errors="replace")

    def test_output_envelope(self) -> None:
        from google_kit.services.gmail.core import gmail_draft
        from google_kit.services.gmail.models import GmailDraftInput

        svc = _GmailMockService(responses={
            ("drafts", "create"): {"id": "draft999", "message": {"id": "msgXYZ"}},
        })
        result = gmail_draft(
            GmailDraftInput(to="a@b.com", subject="S", body_text="B"),
            service=svc,
        )
        assert result.meta.op == "gmail.draft"
        assert result.data.draft_id == "draft999"
        assert result.data.message_id == "msgXYZ"

    def test_cc_header_included_when_provided(self) -> None:
        from google_kit.services.gmail.core import gmail_draft
        from google_kit.services.gmail.models import GmailDraftInput

        svc = _GmailMockService(responses={
            ("drafts", "create"): {"id": "d1", "message": {"id": "m1"}},
        })
        gmail_draft(
            GmailDraftInput(to="a@b.com", subject="S", body_text="B", cc="cc@b.com"),
            service=svc,
        )
        raw = svc.requests_for("drafts", "create")[0].kwargs["body"]["message"]["raw"]
        msg = _decode_raw_mime(raw)
        assert msg["Cc"] == "cc@b.com"

    def test_no_date_or_message_id_header(self) -> None:
        from google_kit.services.gmail.core import gmail_draft
        from google_kit.services.gmail.models import GmailDraftInput

        svc = _GmailMockService(responses={
            ("drafts", "create"): {"id": "d1", "message": {"id": "m1"}},
        })
        gmail_draft(
            GmailDraftInput(to="a@b.com", subject="S", body_text="B"),
            service=svc,
        )
        raw = svc.requests_for("drafts", "create")[0].kwargs["body"]["message"]["raw"]
        msg = _decode_raw_mime(raw)
        assert msg["Date"] is None, "Date header must not be auto-added"
        assert msg["Message-ID"] is None, "Message-ID header must not be auto-added"

    def test_null_response_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_draft
        from google_kit.services.gmail.models import GmailDraftInput

        svc = _GmailMockService(responses={("drafts", "create"): None})
        result = gmail_draft(GmailDraftInput(to="a@b.com", subject="S", body_text="B"), service=svc)
        assert result.data.draft_id == ""
        assert result.data.message_id == ""


class TestGmailSend:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_send
        from google_kit.services.gmail.models import GmailSendInput

        expected_decoded = _load("send_decoded_content.json")
        svc = _GmailMockService(responses={
            ("messages", "send"): {"id": "msg001", "threadId": "t001", "labelIds": ["SENT"]},
        })
        gmail_send(
            GmailSendInput(
                to=expected_decoded["to"],
                subject=expected_decoded["subject"],
                body_text=expected_decoded["body"],
            ),
            service=svc,
        )

        sends = svc.requests_for("messages", "send")
        assert sends, "Expected messages.send call"
        body = sends[0].kwargs["body"]

        assert "raw" in body, "Outer send body must have 'raw' key"
        assert "message" not in body, "Send body must NOT wrap in 'message'"

        msg = _decode_raw_mime(body["raw"])
        assert msg["To"] == expected_decoded["to"]
        assert msg["Subject"] == expected_decoded["subject"]
        decoded_body = msg.get_payload(decode=True)
        assert decoded_body is not None
        assert expected_decoded["body"] in decoded_body.decode("utf-8", errors="replace")

    def test_output_envelope(self) -> None:
        from google_kit.services.gmail.core import gmail_send
        from google_kit.services.gmail.models import GmailSendInput

        svc = _GmailMockService(responses={
            ("messages", "send"): {"id": "msgSENT", "threadId": "tSENT", "labelIds": ["SENT", "INBOX"]},
        })
        result = gmail_send(
            GmailSendInput(to="a@b.com", subject="S", body_text="B"),
            service=svc,
        )
        assert result.meta.op == "gmail.send"
        assert result.data.message_id == "msgSENT"
        assert result.data.thread_id == "tSENT"
        assert "SENT" in result.data.label_ids

    def test_null_response_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_send
        from google_kit.services.gmail.models import GmailSendInput

        svc = _GmailMockService(responses={("messages", "send"): None})
        result = gmail_send(GmailSendInput(to="a@b.com", subject="S", body_text="B"), service=svc)
        assert result.data.message_id == ""
        assert result.data.thread_id == ""
        assert result.data.label_ids == []


class TestGmailModify:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_modify
        from google_kit.services.gmail.models import GmailModifyInput

        expected_body = _load("modify_request_body.json")
        svc = _GmailMockService(responses={
            ("messages", "modify"): {"id": "msg001", "labelIds": ["INBOX"]},
        })
        gmail_modify(
            GmailModifyInput(
                message_id="msg001",
                add_label_ids=["INBOX"],
                remove_label_ids=["SPAM"],
            ),
            service=svc,
        )

        modifies = svc.requests_for("messages", "modify")
        assert modifies, "Expected messages.modify call"
        actual_body = modifies[0].kwargs["body"]
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_message_id_forwarded_as_kwarg(self) -> None:
        from google_kit.services.gmail.core import gmail_modify
        from google_kit.services.gmail.models import GmailModifyInput

        svc = _GmailMockService(responses={("messages", "modify"): {"id": "msg999", "labelIds": []}})
        gmail_modify(GmailModifyInput(message_id="msg999"), service=svc)
        req = svc.requests_for("messages", "modify")[0]
        assert req.kwargs.get("id") == "msg999"
        assert req.kwargs.get("userId") == "me"

    def test_output_envelope(self) -> None:
        from google_kit.services.gmail.core import gmail_modify
        from google_kit.services.gmail.models import GmailModifyInput

        svc = _GmailMockService(responses={
            ("messages", "modify"): {"id": "m1", "labelIds": ["INBOX", "UNREAD"]},
        })
        result = gmail_modify(GmailModifyInput(message_id="m1", add_label_ids=["UNREAD"]), service=svc)
        assert result.meta.op == "gmail.modify"
        assert result.data.message_id == "m1"
        assert "INBOX" in result.data.label_ids

    def test_null_response_falls_back_to_input_id(self) -> None:
        from google_kit.services.gmail.core import gmail_modify
        from google_kit.services.gmail.models import GmailModifyInput

        svc = _GmailMockService(responses={("messages", "modify"): None})
        result = gmail_modify(GmailModifyInput(message_id="fallback123"), service=svc)
        assert result.data.message_id == "fallback123"
        assert result.data.label_ids == []

    def test_empty_labels_sent_when_not_provided(self) -> None:
        from google_kit.services.gmail.core import gmail_modify
        from google_kit.services.gmail.models import GmailModifyInput

        svc = _GmailMockService(responses={("messages", "modify"): {"id": "m1", "labelIds": []}})
        gmail_modify(GmailModifyInput(message_id="m1"), service=svc)
        body = svc.requests_for("messages", "modify")[0].kwargs["body"]
        assert body["addLabelIds"] == []
        assert body["removeLabelIds"] == []


class TestGmailManageLabels:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_manage_labels
        from google_kit.services.gmail.models import GmailManageLabelsInput

        expected_body = _load("manage_labels_request_body.json")
        svc = _GmailMockService(responses={
            ("labels", "create"): {"id": "Label_001", "name": "MyLabel"},
        })
        gmail_manage_labels(GmailManageLabelsInput(name="MyLabel"), service=svc)

        creates = svc.requests_for("labels", "create")
        assert creates, "Expected labels.create call"
        actual_body = creates[0].kwargs["body"]
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_output_envelope(self) -> None:
        from google_kit.services.gmail.core import gmail_manage_labels
        from google_kit.services.gmail.models import GmailManageLabelsInput

        svc = _GmailMockService(responses={
            ("labels", "create"): {"id": "Label_XYZ", "name": "ProjectX"},
        })
        result = gmail_manage_labels(GmailManageLabelsInput(name="ProjectX"), service=svc)
        assert result.meta.op == "gmail.manage_labels"
        assert result.data.label_id == "Label_XYZ"
        assert result.data.name == "ProjectX"

    def test_custom_visibility_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_manage_labels
        from google_kit.services.gmail.models import GmailManageLabelsInput

        svc = _GmailMockService(responses={("labels", "create"): {"id": "L1", "name": "X"}})
        gmail_manage_labels(
            GmailManageLabelsInput(
                name="X",
                label_list_visibility="labelHide",
                message_list_visibility="hide",
            ),
            service=svc,
        )
        body = svc.requests_for("labels", "create")[0].kwargs["body"]
        assert body["labelListVisibility"] == "labelHide"
        assert body["messageListVisibility"] == "hide"

    def test_null_response_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_manage_labels
        from google_kit.services.gmail.models import GmailManageLabelsInput

        svc = _GmailMockService(responses={("labels", "create"): None})
        result = gmail_manage_labels(GmailManageLabelsInput(name="Fallback"), service=svc)
        assert result.data.label_id == ""
        assert result.data.name == "Fallback"


class TestGmailWatch:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.gmail.core import gmail_watch
        from google_kit.services.gmail.models import GmailWatchInput

        expected_body = _load("watch_request_body.json")
        svc = _GmailMockService(responses={
            ("users", "watch"): {"historyId": "99999", "expiration": "1700000000000"},
        })
        gmail_watch(
            GmailWatchInput(
                topic_name="projects/my-project/topics/gmail-watch",
                label_ids=["INBOX"],
            ),
            service=svc,
        )

        watches = svc.requests_for("users", "watch")
        assert watches, "Expected users.watch call"
        actual_body = watches[0].kwargs["body"]
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_output_envelope(self) -> None:
        from google_kit.services.gmail.core import gmail_watch
        from google_kit.services.gmail.models import GmailWatchInput

        svc = _GmailMockService(responses={
            ("users", "watch"): {"historyId": "12345", "expiration": "1800000000000"},
        })
        result = gmail_watch(
            GmailWatchInput(topic_name="projects/p/topics/t"),
            service=svc,
        )
        assert result.meta.op == "gmail.watch"
        assert result.data.history_id == "12345"
        assert result.data.expiration == "1800000000000"

    def test_optional_params_omitted_when_absent(self) -> None:
        from google_kit.services.gmail.core import gmail_watch
        from google_kit.services.gmail.models import GmailWatchInput

        svc = _GmailMockService(responses={
            ("users", "watch"): {"historyId": "1", "expiration": "2"},
        })
        gmail_watch(GmailWatchInput(topic_name="projects/p/topics/t"), service=svc)
        body = svc.requests_for("users", "watch")[0].kwargs["body"]
        assert "labelIds" not in body
        assert "labelFilterBehavior" not in body

    def test_label_filter_behavior_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_watch
        from google_kit.services.gmail.models import GmailWatchInput

        svc = _GmailMockService(responses={
            ("users", "watch"): {"historyId": "1", "expiration": "2"},
        })
        gmail_watch(
            GmailWatchInput(
                topic_name="projects/p/topics/t",
                label_filter_behavior="include",
            ),
            service=svc,
        )
        body = svc.requests_for("users", "watch")[0].kwargs["body"]
        assert body["labelFilterBehavior"] == "include"

    def test_null_response_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_watch
        from google_kit.services.gmail.models import GmailWatchInput

        svc = _GmailMockService(responses={("users", "watch"): None})
        result = gmail_watch(GmailWatchInput(topic_name="projects/p/topics/t"), service=svc)
        assert result.data.history_id == ""
        assert result.data.expiration == ""


class TestGmailWriteGate:
    """F5 gate tests: prove GOOGLE_KIT_ENABLE_GMAIL_WRITE wiring end-to-end."""

    def test_send_blocked_when_flag_unset(self, monkeypatch: Any) -> None:
        from google_kit.cli import main

        monkeypatch.delenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", raising=False)
        mock_svc = _GmailMockService(responses={
            ("messages", "send"): {"id": "msg001", "threadId": "t001", "labelIds": ["SENT"]},
        })

        with pytest.raises(SystemExit) as exc:
            main(
                ["gmail", "send", "--to", "a@b.com", "--subject", "Hi", "--body-text", "Hey"],
                _service_factory=lambda op, **kw: mock_svc,
            )
        assert exc.value.code != 0

    def test_send_succeeds_when_flag_set(self, monkeypatch: Any, capsys: Any) -> None:
        from google_kit.cli import main

        monkeypatch.setenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", "1")
        mock_svc = _GmailMockService(responses={
            ("messages", "send"): {"id": "msg001", "threadId": "t001", "labelIds": ["SENT"]},
        })

        main(
            ["gmail", "send", "--to", "a@b.com", "--subject", "Hi", "--body-text", "Hey"],
            _service_factory=lambda op, **kw: mock_svc,
        )
        captured = capsys.readouterr()
        envelope = json.loads(captured.out)
        assert envelope["data"]["message_id"] == "msg001"

    def test_write_opspecs_have_flag(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        for op in ("gmail.draft", "gmail.send", "gmail.modify", "gmail.manage_labels"):
            assert specs[op].flag == "GOOGLE_KIT_ENABLE_GMAIL_WRITE", \
                f"{op} missing flag 'GOOGLE_KIT_ENABLE_GMAIL_WRITE'"

    def test_watch_is_gmail_write_gated(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        # F5 global write gating (operator decision): every write/destructive op
        # is gated; gmail.watch (a mutating push-channel op) rides the shared
        # GOOGLE_KIT_ENABLE_GMAIL_WRITE gate.
        assert specs["gmail.watch"].flag == "GOOGLE_KIT_ENABLE_GMAIL_WRITE"

    def test_all_twelve_ops_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        expected = {
            "gmail.list", "gmail.get", "gmail.search", "gmail.labels",
            "gmail.profile", "gmail.history", "gmail.attachments",
            "gmail.draft", "gmail.send", "gmail.modify", "gmail.manage_labels",
            "gmail.watch",
        }
        assert expected.issubset(names), f"Missing ops: {expected - names}"

    def test_write_ops_posture_write(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        for op in ("gmail.draft", "gmail.send", "gmail.modify", "gmail.manage_labels", "gmail.watch"):
            assert specs[op].posture == "write", f"{op} posture should be 'write'"

    def test_write_ops_plane_and_capability(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["gmail.draft"].plane == "messaging"
        assert specs["gmail.draft"].capability == "mail.compose"
        assert specs["gmail.send"].plane == "messaging"
        assert specs["gmail.send"].capability == "mail.send"
        assert specs["gmail.modify"].plane == "messaging"
        assert specs["gmail.modify"].capability == "mail.modify"
        assert specs["gmail.manage_labels"].plane == "messaging"
        assert specs["gmail.manage_labels"].capability == "mail.labels"
        assert specs["gmail.watch"].plane == "eventing"
        assert specs["gmail.watch"].capability == "eventing.watch"
