"""Tests for the Workspace Events service.

Coverage:
  events_subscribe — mutation-request parity (subscriptions.create body)
  events_list      — mock-read parity (normalized-json)
  events_patch     — mutation-request parity (subscriptions.patch body + kwargs)
  events_delete    — request parity (name forwarded)

Parity status per op:
  events_subscribe — mutation-request DONE; sandbox-e2e DEFERRED
  events_list      — mock-read DONE; sandbox-e2e DEFERRED
  events_patch     — mutation-request DONE; sandbox-e2e DEFERRED
  events_delete    — request DONE; sandbox-e2e DEFERRED

Test-local MockWorkspaceEventsService models the Workspace Events API's
subscriptions() resource chain.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.parity import compare

FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "workspace_events"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# ─── Test-local mock infrastructure ──────────────────────────────────────────


@dataclass
class _EventsRecord:
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


class _FakeSubscriptionsProxy:
    def __init__(self, responses: dict, log: list[_EventsRecord]) -> None:
        self._responses = responses
        self._log = log

    def create(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_EventsRecord("subscriptions", "create", dict(kwargs)))
        return _FakeExec(self._responses.get(("subscriptions", "create")))

    def list(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_EventsRecord("subscriptions", "list", dict(kwargs)))
        return _FakeExec(self._responses.get(("subscriptions", "list")))

    def patch(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_EventsRecord("subscriptions", "patch", dict(kwargs)))
        return _FakeExec(self._responses.get(("subscriptions", "patch")))

    def delete(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_EventsRecord("subscriptions", "delete", dict(kwargs)))
        return _FakeExec(self._responses.get(("subscriptions", "delete")))


class MockWorkspaceEventsService:
    """Test-local mock for the Google Workspace Events API (workspaceevents v1)."""

    def __init__(self, responses: dict | None = None) -> None:
        self._responses: dict = responses or {}
        self._log: list[_EventsRecord] = []

    def subscriptions(self) -> _FakeSubscriptionsProxy:
        return _FakeSubscriptionsProxy(self._responses, self._log)

    def last_request_body(self) -> dict[str, Any] | None:
        for rec in reversed(self._log):
            if rec.body is not None:
                return rec.body
        return None

    def requests_for(self, resource: str, method: str) -> list[_EventsRecord]:
        return [r for r in self._log if r.resource == resource and r.method == method]

    def reset(self) -> None:
        self._log.clear()


# ─── Registry isolation fixture ───────────────────────────────────────────────


@pytest.fixture(autouse=True, scope="module")
def _ensure_workspace_events() -> None:
    """Re-register Workspace Events ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.workspace_events as we_mod

    if "events.subscribe" not in {s.name for s in reg.all_specs()}:
        importlib.reload(we_mod)


# ─── events.subscribe ─────────────────────────────────────────────────────────


class TestEventsSubscribe:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.workspace_events.core import events_subscribe
        from google_kit.services.workspace_events.models import EventsSubscribeInput

        expected_body = _load("subscribe_expected_body.json")
        canned_resp = {
            "name": "operations/op001",
            "done": False,
        }
        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "create"): canned_resp}
        )
        events_subscribe(
            EventsSubscribeInput(
                target_resource="//drive.googleapis.com/files/file001",
                event_types=["google.workspace.drive.file.v3.contentChanged"],
                pubsub_topic="projects/my-project/topics/drive-events",
            ),
            service=svc,
        )

        creates = svc.requests_for("subscriptions", "create")
        assert creates, "Expected subscriptions.create call"
        actual_body = creates[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_payload_options_included_when_given(self) -> None:
        from google_kit.services.workspace_events.core import events_subscribe
        from google_kit.services.workspace_events.models import EventsSubscribeInput

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "create"): {"name": "operations/op002", "done": False}}
        )
        events_subscribe(
            EventsSubscribeInput(
                target_resource="//drive.googleapis.com/files/file001",
                event_types=["google.workspace.drive.file.v3.contentChanged"],
                pubsub_topic="projects/my-project/topics/drive-events",
                payload_options={"includeResource": True},
            ),
            service=svc,
        )

        creates = svc.requests_for("subscriptions", "create")
        assert creates
        body = creates[0].body
        assert body is not None
        assert "payloadOptions" in body
        assert body["payloadOptions"] == {"includeResource": True}

    def test_payload_options_omitted_when_none(self) -> None:
        from google_kit.services.workspace_events.core import events_subscribe
        from google_kit.services.workspace_events.models import EventsSubscribeInput

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "create"): {"name": "operations/op003", "done": False}}
        )
        events_subscribe(
            EventsSubscribeInput(
                target_resource="//drive.googleapis.com/files/file001",
                event_types=["google.workspace.drive.file.v3.contentChanged"],
                pubsub_topic="projects/my-project/topics/drive-events",
            ),
            service=svc,
        )

        creates = svc.requests_for("subscriptions", "create")
        assert creates
        body = creates[0].body
        assert body is not None
        assert "payloadOptions" not in body

    def test_output_envelope(self) -> None:
        from google_kit.services.workspace_events.core import events_subscribe
        from google_kit.services.workspace_events.models import EventsSubscribeInput

        svc = MockWorkspaceEventsService(
            responses={
                ("subscriptions", "create"): {
                    "name": "operations/op_sub001",
                    "done": False,
                }
            }
        )
        result = events_subscribe(
            EventsSubscribeInput(
                target_resource="//drive.googleapis.com/files/file001",
                event_types=["google.workspace.drive.file.v3.contentChanged"],
                pubsub_topic="projects/my-project/topics/drive-events",
            ),
            service=svc,
        )

        assert result.meta.op == "events.subscribe"
        assert result.data.name == "operations/op_sub001"
        assert result.data.done is False


# ─── events.list ──────────────────────────────────────────────────────────────


class TestEventsList:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.workspace_events.core import events_list
        from google_kit.services.workspace_events.models import EventsListInput

        list_resp = _load("list_response.json")
        expected = _load("list_expected.json")

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "list"): list_resp}
        )
        result = events_list(
            EventsListInput(
                filter='target_resource="//drive.googleapis.com/files/file001"'
            ),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"mock-read mismatch:\n{parity.diff}"

    def test_next_page_token_forwarded(self) -> None:
        from google_kit.services.workspace_events.core import events_list
        from google_kit.services.workspace_events.models import EventsListInput

        list_resp = _load("list_response.json")
        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "list"): list_resp}
        )
        result = events_list(
            EventsListInput(
                filter='target_resource="//drive.googleapis.com/files/file001"',
                page_token="prev_token",
            ),
            service=svc,
        )

        assert result.page is not None
        assert result.page.next_page_token == "tok_next_page"
        calls = svc.requests_for("subscriptions", "list")
        assert calls
        assert calls[0].kwargs.get("pageToken") == "prev_token"

    def test_empty_subscriptions(self) -> None:
        from google_kit.services.workspace_events.core import events_list
        from google_kit.services.workspace_events.models import EventsListInput

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "list"): {"subscriptions": []}}
        )
        result = events_list(
            EventsListInput(filter='target_resource="//drive.googleapis.com/files/x"'),
            service=svc,
        )

        assert result.data.subscriptions == []
        assert result.page is not None
        assert result.page.next_page_token is None

    def test_page_size_forwarded(self) -> None:
        from google_kit.services.workspace_events.core import events_list
        from google_kit.services.workspace_events.models import EventsListInput

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "list"): {"subscriptions": []}}
        )
        events_list(
            EventsListInput(
                filter='target_resource="//drive.googleapis.com/files/x"',
                page_size=5,
            ),
            service=svc,
        )

        calls = svc.requests_for("subscriptions", "list")
        assert calls
        assert calls[0].kwargs.get("pageSize") == 5

    def test_output_envelope(self) -> None:
        from google_kit.services.workspace_events.core import events_list
        from google_kit.services.workspace_events.models import EventsListInput

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "list"): {"subscriptions": []}}
        )
        result = events_list(
            EventsListInput(filter="targetResource='//drive.googleapis.com/drives/x'"),
            service=svc,
        )

        assert result.meta.op == "events.list"


# ─── events.patch ─────────────────────────────────────────────────────────────


class TestEventsPatch:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.workspace_events.core import events_patch
        from google_kit.services.workspace_events.models import EventsPatchInput

        expected_body = _load("patch_expected_body.json")
        canned_resp = {"name": "operations/patch_op001", "done": False}
        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "patch"): canned_resp}
        )
        events_patch(
            EventsPatchInput(
                name="subscriptions/sub001",
                ttl="3600s",
            ),
            service=svc,
        )

        patches = svc.requests_for("subscriptions", "patch")
        assert patches, "Expected subscriptions.patch call"
        actual_body = patches[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_patch_name_and_update_mask_forwarded(self) -> None:
        from google_kit.services.workspace_events.core import events_patch
        from google_kit.services.workspace_events.models import EventsPatchInput

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "patch"): {"name": "operations/p002", "done": False}}
        )
        events_patch(
            EventsPatchInput(
                name="subscriptions/sub002",
                update_mask="ttl",
                ttl="7200s",
            ),
            service=svc,
        )

        patches = svc.requests_for("subscriptions", "patch")
        assert patches
        rec = patches[0]
        assert rec.kwargs.get("name") == "subscriptions/sub002"
        assert rec.kwargs.get("updateMask") == "ttl"

    def test_empty_body_when_no_ttl(self) -> None:
        from google_kit.services.workspace_events.core import events_patch
        from google_kit.services.workspace_events.models import EventsPatchInput

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "patch"): {"name": "operations/p003", "done": False}}
        )
        events_patch(
            EventsPatchInput(name="subscriptions/sub003"),
            service=svc,
        )

        patches = svc.requests_for("subscriptions", "patch")
        assert patches
        assert patches[0].body == {}

    def test_output_envelope(self) -> None:
        from google_kit.services.workspace_events.core import events_patch
        from google_kit.services.workspace_events.models import EventsPatchInput

        svc = MockWorkspaceEventsService(
            responses={
                ("subscriptions", "patch"): {
                    "name": "operations/patch_op_out",
                    "done": False,
                }
            }
        )
        result = events_patch(
            EventsPatchInput(name="subscriptions/sub004", ttl="3600s"),
            service=svc,
        )

        assert result.meta.op == "events.patch"
        assert result.data.name == "operations/patch_op_out"
        assert result.data.done is False


# ─── events.delete ────────────────────────────────────────────────────────────


class TestEventsDelete:
    def test_request_parity_name_forwarded(self) -> None:
        from google_kit.services.workspace_events.core import events_delete
        from google_kit.services.workspace_events.models import EventsDeleteInput

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "delete"): {"name": "operations/del001", "done": True}}
        )
        events_delete(
            EventsDeleteInput(name="subscriptions/sub_to_delete"),
            service=svc,
        )

        deletes = svc.requests_for("subscriptions", "delete")
        assert len(deletes) == 1
        assert deletes[0].kwargs.get("name") == "subscriptions/sub_to_delete"

    def test_output_envelope(self) -> None:
        from google_kit.services.workspace_events.core import events_delete
        from google_kit.services.workspace_events.models import EventsDeleteInput

        svc = MockWorkspaceEventsService(
            responses={
                ("subscriptions", "delete"): {
                    "name": "operations/del_op001",
                    "done": True,
                }
            }
        )
        result = events_delete(
            EventsDeleteInput(name="subscriptions/sub001"),
            service=svc,
        )

        assert result.meta.op == "events.delete"
        assert result.data.name == "operations/del_op001"
        assert result.data.done is True

    def test_only_one_delete_call(self) -> None:
        from google_kit.services.workspace_events.core import events_delete
        from google_kit.services.workspace_events.models import EventsDeleteInput

        svc = MockWorkspaceEventsService(
            responses={("subscriptions", "delete"): None}
        )
        events_delete(
            EventsDeleteInput(name="subscriptions/sub002"),
            service=svc,
        )

        deletes = svc.requests_for("subscriptions", "delete")
        assert len(deletes) == 1
