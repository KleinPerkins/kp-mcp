"""Tests for the newly-added Gmail thread + batchModify ops.

Mirrors the mock design in ``test_gmail.py``: a test-local fake service for
Gmail's nested resource structure (``service.users().threads()`` etc.) with
recorded requests, injected via ``service=``.  No live network.

Coverage:
  gmail_threads      — mock-read parity (list + q/search path + pagination token)
  gmail_thread_get   — mock-read parity (messages[]; sparse/missing fields)
  gmail_batch_modify — mutation-request parity (body + empty-204 response)
  GmailBatchModifyInput — validation errors (empty ids; no labels)

Parity status per op:
  gmail_threads      — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
  gmail_thread_get   — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
  gmail_batch_modify — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
"""
from __future__ import annotations

import base64
import importlib
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True, scope="module")
def _ensure_gmail() -> None:
    """Re-register Gmail ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.gmail as gmail_mod

    if "gmail.threads" not in {s.name for s in reg.all_specs()}:
        importlib.reload(gmail_mod)
    if "gmail.batch_modify" not in {s.name for s in reg.all_specs()}:
        importlib.reload(gmail_mod)


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
    """Proxy for a nested Gmail API resource (messages, threads)."""

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

    def batchModify(self, **kwargs: Any) -> _GmailExecutable:
        return self._call("batchModify", **kwargs)

    def _call(self, method: str, **kwargs: Any) -> _GmailExecutable:
        self._requests.append(
            _GmailRequestRecord(resource=self._resource, method=method, kwargs=dict(kwargs))
        )
        return _GmailExecutable(self._responses.get((self._resource, method)))


class _GmailUsersProxy:
    """Proxy for ``service.users()`` — provides messages(), threads()."""

    def __init__(
        self,
        responses: dict[tuple[str, str], Any],
        requests: list[_GmailRequestRecord],
    ) -> None:
        self._responses = responses
        self._requests = requests

    def messages(self) -> _GmailResourceProxy:
        return _GmailResourceProxy("messages", self._responses, self._requests)

    def threads(self) -> _GmailResourceProxy:
        return _GmailResourceProxy("threads", self._responses, self._requests)


class _GmailMockService:
    """Test-local fake Gmail service keyed by ``(resource, method)``."""

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self._responses: dict[tuple[str, str], Any] = responses or {}
        self._requests: list[_GmailRequestRecord] = []

    def users(self) -> _GmailUsersProxy:
        return _GmailUsersProxy(self._responses, self._requests)

    def requests_for(self, resource: str, method: str) -> list[_GmailRequestRecord]:
        return [r for r in self._requests if r.resource == resource and r.method == method]


def _b64(text: bytes) -> str:
    return base64.urlsafe_b64encode(text).decode()


# ---------------------------------------------------------------------------
# gmail.threads (users.threads.list; q optional => search)
# ---------------------------------------------------------------------------


class TestGmailThreads:
    def test_lists_threads_with_fields(self) -> None:
        from google_kit.services.gmail.core import gmail_threads
        from google_kit.services.gmail.models import GmailThreadsInput

        response = {
            "threads": [
                {"id": "t1", "snippet": "hello", "historyId": "111"},
                {"id": "t2", "snippet": "world", "historyId": "222"},
            ],
        }
        svc = _GmailMockService(responses={("threads", "list"): response})
        result = gmail_threads(GmailThreadsInput(), service=svc)

        assert result.meta.op == "gmail.threads"
        assert result.data.count == 2
        assert result.data.threads[0].id == "t1"
        assert result.data.threads[0].snippet == "hello"
        assert result.data.threads[0].history_id == "111"

    def test_q_forwarded_for_search(self) -> None:
        from google_kit.services.gmail.core import gmail_threads
        from google_kit.services.gmail.models import GmailThreadsInput

        svc = _GmailMockService(responses={("threads", "list"): {"threads": []}})
        gmail_threads(GmailThreadsInput(q="from:boss@example.com"), service=svc)
        req = svc.requests_for("threads", "list")[0]
        assert req.kwargs.get("q") == "from:boss@example.com"
        assert req.kwargs.get("userId") == "me"

    def test_label_ids_and_max_results_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_threads
        from google_kit.services.gmail.models import GmailThreadsInput

        svc = _GmailMockService(responses={("threads", "list"): {"threads": []}})
        gmail_threads(
            GmailThreadsInput(label_ids=["INBOX", "UNREAD"], max_results=10),
            service=svc,
        )
        req = svc.requests_for("threads", "list")[0]
        assert req.kwargs.get("labelIds") == ["INBOX", "UNREAD"]
        assert req.kwargs.get("maxResults") == 10

    def test_pagination_token_surfaced_in_page(self) -> None:
        from google_kit.services.gmail.core import gmail_threads
        from google_kit.services.gmail.models import GmailThreadsInput

        response = {"threads": [{"id": "t1"}], "nextPageToken": "NEXT123"}
        svc = _GmailMockService(responses={("threads", "list"): response})
        result = gmail_threads(GmailThreadsInput(), service=svc)
        assert result.page is not None
        assert result.page.next_page_token == "NEXT123"

    def test_page_token_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_threads
        from google_kit.services.gmail.models import GmailThreadsInput

        svc = _GmailMockService(responses={("threads", "list"): {"threads": []}})
        gmail_threads(GmailThreadsInput(page_token="PREV456"), service=svc)
        req = svc.requests_for("threads", "list")[0]
        assert req.kwargs.get("pageToken") == "PREV456"

    def test_no_next_page_token_is_none(self) -> None:
        from google_kit.services.gmail.core import gmail_threads
        from google_kit.services.gmail.models import GmailThreadsInput

        svc = _GmailMockService(responses={("threads", "list"): {"threads": []}})
        result = gmail_threads(GmailThreadsInput(), service=svc)
        assert result.page is not None
        assert result.page.next_page_token is None

    def test_null_response_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_threads
        from google_kit.services.gmail.models import GmailThreadsInput

        svc = _GmailMockService(responses={("threads", "list"): None})
        result = gmail_threads(GmailThreadsInput(), service=svc)
        assert result.data.count == 0
        assert result.data.threads == []


# ---------------------------------------------------------------------------
# gmail.thread_get (users.threads.get)
# ---------------------------------------------------------------------------


class TestGmailThreadGet:
    def test_decodes_messages_and_headers(self) -> None:
        from google_kit.services.gmail.core import gmail_thread_get
        from google_kit.services.gmail.models import GmailThreadGetInput

        response = {
            "id": "t1",
            "historyId": "999",
            "snippet": "thread snip",
            "messages": [
                {
                    "id": "m1",
                    "threadId": "t1",
                    "snippet": "msg one",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "mimeType": "text/plain",
                        "headers": [
                            {"name": "Subject", "value": "Hello"},
                            {"name": "From", "value": "alice@example.com"},
                            {"name": "Date", "value": "Mon, 1 Jan 2024"},
                        ],
                        "body": {"data": _b64(b"First message body.")},
                    },
                },
            ],
        }
        svc = _GmailMockService(responses={("threads", "get"): response})
        result = gmail_thread_get(GmailThreadGetInput(thread_id="t1"), service=svc)

        assert result.meta.op == "gmail.thread_get"
        assert result.data.id == "t1"
        assert result.data.history_id == "999"
        assert result.data.snippet == "thread snip"
        assert result.data.message_count == 1
        msg = result.data.messages[0]
        assert msg.id == "m1"
        assert msg.thread_id == "t1"
        assert msg.subject == "Hello"
        assert msg.from_ == "alice@example.com"
        assert msg.date == "Mon, 1 Jan 2024"
        assert msg.body == "First message body."
        assert msg.label_ids == ["INBOX"]

    def test_format_full_and_id_forwarded(self) -> None:
        from google_kit.services.gmail.core import gmail_thread_get
        from google_kit.services.gmail.models import GmailThreadGetInput

        svc = _GmailMockService(responses={("threads", "get"): {"id": "t1", "messages": []}})
        gmail_thread_get(GmailThreadGetInput(thread_id="t1"), service=svc)
        req = svc.requests_for("threads", "get")[0]
        assert req.kwargs.get("format") == "full"
        assert req.kwargs.get("id") == "t1"
        assert req.kwargs.get("userId") == "me"

    def test_body_truncated_at_500(self) -> None:
        from google_kit.services.gmail.core import gmail_thread_get
        from google_kit.services.gmail.models import GmailThreadGetInput

        response = {
            "id": "t1",
            "messages": [
                {
                    "id": "m1",
                    "threadId": "t1",
                    "payload": {
                        "mimeType": "text/plain",
                        "headers": [],
                        "body": {"data": _b64(b"A" * 600)},
                    },
                },
            ],
        }
        svc = _GmailMockService(responses={("threads", "get"): response})
        result = gmail_thread_get(GmailThreadGetInput(thread_id="t1"), service=svc)
        assert result.data.messages[0].body == "A" * 500 + "..."

    def test_sparse_message_fields_default_empty(self) -> None:
        from google_kit.services.gmail.core import gmail_thread_get
        from google_kit.services.gmail.models import GmailThreadGetInput

        response = {"id": "t1", "messages": [{"id": "m1"}]}
        svc = _GmailMockService(responses={("threads", "get"): response})
        result = gmail_thread_get(GmailThreadGetInput(thread_id="t1"), service=svc)
        msg = result.data.messages[0]
        assert msg.id == "m1"
        assert msg.thread_id == "t1"  # falls back to thread id
        assert msg.subject == ""
        assert msg.from_ == ""
        assert msg.body == ""
        assert msg.label_ids == []

    def test_missing_thread_fields_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_thread_get
        from google_kit.services.gmail.models import GmailThreadGetInput

        svc = _GmailMockService(responses={("threads", "get"): {}})
        result = gmail_thread_get(GmailThreadGetInput(thread_id="fallback"), service=svc)
        assert result.data.id == "fallback"
        assert result.data.history_id == ""
        assert result.data.message_count == 0
        assert result.data.messages == []

    def test_null_response_handled(self) -> None:
        from google_kit.services.gmail.core import gmail_thread_get
        from google_kit.services.gmail.models import GmailThreadGetInput

        svc = _GmailMockService(responses={("threads", "get"): None})
        result = gmail_thread_get(GmailThreadGetInput(thread_id="t9"), service=svc)
        assert result.data.id == "t9"
        assert result.data.messages == []


# ---------------------------------------------------------------------------
# gmail.batch_modify (users.messages.batchModify)
# ---------------------------------------------------------------------------


class TestGmailBatchModify:
    def test_request_body_shape(self) -> None:
        from google_kit.services.gmail.core import gmail_batch_modify
        from google_kit.services.gmail.models import GmailBatchModifyInput

        # batchModify returns HTTP 204 / empty body — response is None.
        svc = _GmailMockService(responses={("messages", "batchModify"): None})
        gmail_batch_modify(
            GmailBatchModifyInput(
                ids=["m1", "m2", "m3"],
                add_label_ids=["IMPORTANT"],
                remove_label_ids=["UNREAD"],
            ),
            service=svc,
        )

        calls = svc.requests_for("messages", "batchModify")
        assert calls, "Expected messages.batchModify call"
        req = calls[0]
        assert req.kwargs.get("userId") == "me"
        assert req.kwargs["body"] == {
            "ids": ["m1", "m2", "m3"],
            "addLabelIds": ["IMPORTANT"],
            "removeLabelIds": ["UNREAD"],
        }

    def test_empty_204_response_builds_envelope(self) -> None:
        from google_kit.services.gmail.core import gmail_batch_modify
        from google_kit.services.gmail.models import GmailBatchModifyInput

        svc = _GmailMockService(responses={("messages", "batchModify"): None})
        result = gmail_batch_modify(
            GmailBatchModifyInput(ids=["m1", "m2"], remove_label_ids=["UNREAD"]),
            service=svc,
        )
        assert result.meta.op == "gmail.batch_modify"
        assert result.data.modified_count == 2
        assert result.data.ids == ["m1", "m2"]
        assert result.data.remove_label_ids == ["UNREAD"]
        assert result.data.add_label_ids == []

    def test_validation_empty_ids(self) -> None:
        from google_kit.services.gmail.models import GmailBatchModifyInput

        with pytest.raises(ValidationError):
            GmailBatchModifyInput(ids=[], add_label_ids=["INBOX"])

    def test_validation_no_labels(self) -> None:
        from google_kit.services.gmail.models import GmailBatchModifyInput

        with pytest.raises(ValidationError):
            GmailBatchModifyInput(ids=["m1"])


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestNewOpsRegistry:
    def test_thread_read_ops_registered_read_posture(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        for op in ("gmail.threads", "gmail.thread_get"):
            assert op in specs, f"{op} not registered"
            assert specs[op].posture == "read"
            assert specs[op].plane == "messaging"
            assert specs[op].capability == "thread.read"
            scope = "https://www.googleapis.com/auth/gmail.readonly"
            assert scope in specs[op].scopes

    def test_batch_modify_registered_write_flag_gated(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert "gmail.batch_modify" in specs
        spec = specs["gmail.batch_modify"]
        assert spec.posture == "write"
        assert spec.flag == "GOOGLE_KIT_ENABLE_GMAIL_WRITE"
        assert spec.capability == "mail.batch_modify"
        assert "https://www.googleapis.com/auth/gmail.modify" in spec.scopes
        assert spec.perf["method"] == "users.messages.batchModify"

    def test_batch_modify_flag_gate_blocks_when_unset(self, monkeypatch: Any) -> None:
        from google_kit.cli import main

        monkeypatch.delenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", raising=False)
        mock_svc = _GmailMockService(responses={("messages", "batchModify"): None})

        with pytest.raises(SystemExit) as exc:
            main(
                ["gmail", "batch-modify", "--ids", '["m1"]', "--remove-label-ids", '["UNREAD"]'],
                _service_factory=lambda op, **kw: mock_svc,
            )
        assert exc.value.code != 0

    def test_batch_modify_succeeds_when_flag_set(self, monkeypatch: Any, capsys: Any) -> None:
        from google_kit.cli import main

        monkeypatch.setenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", "1")
        mock_svc = _GmailMockService(responses={("messages", "batchModify"): None})

        main(
            ["gmail", "batch-modify", "--ids", '["m1","m2"]', "--remove-label-ids", '["UNREAD"]'],
            _service_factory=lambda op, **kw: mock_svc,
        )
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["data"]["modified_count"] == 2
