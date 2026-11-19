"""Fake Google API client for unit and parity tests.

Provides ``MockGoogleService``: a fake that replaces a live ``googleapiclient``
service resource.  Two testing modes:

READ parity
    Pre-load canned responses keyed by ``(resource, method)``; assert the
    normalized output envelope matches the legacy-equivalent shape.

MUTATION-REQUEST parity
    The mock records the full kwargs (including ``body=``) of every method call.
    After invoking the core fn, inspect ``mock.get_requests()`` or
    ``mock.last_request_body()`` to assert the request body equals the
    legacy-equivalent body.

Usage::

    from kp_mcp_testkit.mock_google import MockGoogleService, mock_tasks_service

    # READ parity
    svc = MockGoogleService(responses={
        ("tasklists", "list"): {"kind": "tasks#taskLists", "items": [...]},
    })
    result = tasks_list_lists(TasksListListsInput(), service=svc)
    assert result.data.count == 2

    # MUTATION-REQUEST parity
    svc = MockGoogleService(responses={
        ("tasks", "get"):    {"id": "abc", "title": "Buy milk", "status": "needsAction"},
        ("tasks", "update"): {"id": "abc", "title": "Buy milk", "status": "completed"},
    })
    tasks_complete(TasksCompleteInput(task_id="abc"), service=svc)
    body = svc.last_request_body()
    assert body["status"] == "completed"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestRecord:
    """One recorded outgoing API method call."""

    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> dict[str, Any] | None:
        """Return the ``body=`` kwarg if present, else None."""
        return self.kwargs.get("body")


class _MockExecutable:
    """Fake ``googleapiclient`` request object; ``.execute()`` returns canned data."""

    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _MockResourceProxy:
    """Fake ``googleapiclient`` resource (e.g. ``svc.tasks()``)."""

    def __init__(
        self,
        resource: str,
        responses: dict[tuple[str, str], Any],
        requests: list[RequestRecord],
    ) -> None:
        self._resource = resource
        self._responses = responses
        self._requests = requests

    def list(self, **kwargs: Any) -> _MockExecutable:
        return self._call("list", **kwargs)

    def get(self, **kwargs: Any) -> _MockExecutable:
        return self._call("get", **kwargs)

    def insert(self, **kwargs: Any) -> _MockExecutable:
        return self._call("insert", **kwargs)

    def update(self, **kwargs: Any) -> _MockExecutable:
        return self._call("update", **kwargs)

    def delete(self, **kwargs: Any) -> _MockExecutable:
        return self._call("delete", **kwargs)

    def patch(self, **kwargs: Any) -> _MockExecutable:
        return self._call("patch", **kwargs)

    def _call(self, method: str, **kwargs: Any) -> _MockExecutable:
        self._requests.append(
            RequestRecord(resource=self._resource, method=method, kwargs=dict(kwargs))
        )
        key = (self._resource, method)
        response = self._responses.get(key)
        return _MockExecutable(response)


class MockGoogleService:
    """Fake ``googleapiclient`` service resource.

    Args:
        responses: Dict mapping ``(resource_name, method_name)`` to the canned
                   response that ``.execute()`` will return.  Unmapped keys
                   return ``None`` (suitable for ``delete`` or empty responses).

    Examples::

        svc = MockGoogleService(responses={
            ("tasks", "list"): {"items": [], "kind": "tasks#tasks"},
        })
    """

    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self._responses: dict[tuple[str, str], Any] = responses or {}
        self._requests: list[RequestRecord] = []

    def tasklists(self) -> _MockResourceProxy:
        return _MockResourceProxy("tasklists", self._responses, self._requests)

    def tasks(self) -> _MockResourceProxy:
        return _MockResourceProxy("tasks", self._responses, self._requests)

    def get_requests(self) -> list[RequestRecord]:
        """Return all recorded outgoing method calls in order."""
        return list(self._requests)

    def last_request_body(self) -> dict[str, Any] | None:
        """Return the ``body=`` kwarg of the last recorded call, or None."""
        for rec in reversed(self._requests):
            if rec.body is not None:
                return rec.body
        return None

    def requests_for(self, resource: str, method: str) -> list[RequestRecord]:
        """Return all recorded calls matching (resource, method)."""
        return [r for r in self._requests if r.resource == resource and r.method == method]

    def reset(self) -> None:
        """Clear all recorded requests (keep responses)."""
        self._requests.clear()
