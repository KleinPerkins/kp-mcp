"""Focused tests for newly covered Forms watch actions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class _FormsRequest:
    resource: str
    method: str
    kwargs: dict[str, Any]

    @property
    def body(self) -> Any:
        return self.kwargs.get("body")


class _FormsExecutable:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _WatchesProxy:
    def __init__(
        self,
        responses: dict[tuple[str, str], Any],
        requests: list[_FormsRequest],
    ) -> None:
        self._responses = responses
        self._requests = requests

    def create(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(_FormsRequest("watches", "create", dict(kwargs)))
        return _FormsExecutable(self._responses.get(("watches", "create")))

    def list(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(_FormsRequest("watches", "list", dict(kwargs)))
        return _FormsExecutable(self._responses.get(("watches", "list")))

    def delete(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(_FormsRequest("watches", "delete", dict(kwargs)))
        return _FormsExecutable(self._responses.get(("watches", "delete")))

    def renew(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(_FormsRequest("watches", "renew", dict(kwargs)))
        return _FormsExecutable(self._responses.get(("watches", "renew")))


class _FormsProxy:
    def __init__(
        self,
        responses: dict[tuple[str, str], Any],
        requests: list[_FormsRequest],
    ) -> None:
        self._responses = responses
        self._requests = requests

    def watches(self) -> _WatchesProxy:
        return _WatchesProxy(self._responses, self._requests)


class _FormsService:
    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self._responses = responses
        self._requests: list[_FormsRequest] = []

    def forms(self) -> _FormsProxy:
        return _FormsProxy(self._responses, self._requests)

    def requests_for(self, resource: str, method: str) -> list[_FormsRequest]:
        return [
            r
            for r in self._requests
            if r.resource == resource and r.method == method
        ]


class TestFormsWatchesList:
    def test_happy_path_records_list_and_envelope(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = _FormsService(
            responses={
                ("watches", "list"): {
                    "watches": [{
                        "id": "watch-1",
                        "state": "ACTIVE",
                        "eventType": "RESPONSES",
                        "createTime": "2026-01-01T00:00:00Z",
                        "expireTime": "2026-01-08T00:00:00Z",
                    }]
                }
            }
        )

        result = forms_watches(
            FormsWatchesInput(form_id="form-1", action="list"),
            service=svc,
        )

        req = svc.requests_for("watches", "list")[0]
        assert req.kwargs == {"formId": "form-1"}
        assert result.meta.op == "forms.watches"
        assert result.data.action == "list"
        assert result.data.count == 1
        assert result.data.watches is not None
        assert result.data.watches[0].watch_id == "watch-1"
        assert result.data.watches[0].expire_time == "2026-01-08T00:00:00Z"

    def test_empty_response_returns_empty_watches(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = _FormsService(responses={("watches", "list"): {}})

        result = forms_watches(
            FormsWatchesInput(form_id="form-1", action="list"),
            service=svc,
        )

        assert result.data.action == "list"
        assert result.data.count == 0
        assert result.data.watches == []


class TestFormsWatchesDelete:
    def test_happy_path_records_delete_and_204_envelope(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = _FormsService(responses={("watches", "delete"): None})

        result = forms_watches(
            FormsWatchesInput(form_id="form-1", action="delete", watch_id="watch-1"),
            service=svc,
        )

        req = svc.requests_for("watches", "delete")[0]
        assert req.kwargs == {"formId": "form-1", "watchId": "watch-1"}
        assert result.meta.op == "forms.watches"
        assert result.data.action == "delete"
        assert result.data.watch_id == "watch-1"
        assert result.data.deleted is True

    def test_missing_watch_id_raises(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = _FormsService(responses={})

        with pytest.raises(ValueError, match="watch_id is required for delete"):
            forms_watches(
                FormsWatchesInput(form_id="form-1", action="delete"),
                service=svc,
            )


class TestFormsWatchesRenew:
    def test_happy_path_records_renew_and_envelope(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = _FormsService(
            responses={
                ("watches", "renew"): {
                    "id": "watch-1",
                    "state": "ACTIVE",
                    "eventType": "RESPONSES",
                    "createTime": "2026-01-01T00:00:00Z",
                    "expireTime": "2026-01-08T00:00:00Z",
                }
            }
        )

        result = forms_watches(
            FormsWatchesInput(form_id="form-1", action="renew", watch_id="watch-1"),
            service=svc,
        )

        req = svc.requests_for("watches", "renew")[0]
        assert req.kwargs == {"formId": "form-1", "watchId": "watch-1"}
        assert result.meta.op == "forms.watches"
        assert result.data.action == "renew"
        assert result.data.watch_id == "watch-1"
        assert result.data.expire_time == "2026-01-08T00:00:00Z"

    def test_sparse_response_uses_requested_watch_id_defaults(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = _FormsService(responses={("watches", "renew"): {}})

        result = forms_watches(
            FormsWatchesInput(form_id="form-1", action="renew", watch_id="watch-1"),
            service=svc,
        )

        assert result.data.action == "renew"
        assert result.data.watch_id == "watch-1"
        assert result.data.state == ""
        assert result.data.event_type == ""
        assert result.data.create_time == ""
        assert result.data.expire_time is None

    def test_missing_watch_id_raises(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = _FormsService(responses={})

        with pytest.raises(ValueError, match="watch_id is required for renew"):
            forms_watches(
                FormsWatchesInput(form_id="form-1", action="renew"),
                service=svc,
            )
