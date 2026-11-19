"""Tests for the Calendar service.

Note on registry isolation: ``test_registry.py`` clears ``_REGISTRY`` during
its own tests.  The module-scoped ``_ensure_calendar`` fixture below re-registers
Calendar ops if needed so these tests remain order-independent.

Coverage:
  calendar_list      — mock-read parity (normalized-json); attendee email redaction
  calendar_create    — mutation-request parity (Meet + attendees)
  calendar_freebusy  — mock-read parity (normalized-json)
  calendar_update    — mutation-request parity (GET-then-PATCH; add_attendees merge)
  calendar_delete    — mutation-request parity (sendUpdates=all; no body)
  calendar_watch     — mutation-request parity (body w/wo expiration; calendarId forward)

Parity status per op:
  calendar_list      — mock-read DONE; sandbox-e2e DEFERRED(P6)
  calendar_create    — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  calendar_freebusy  — mock-read DONE; sandbox-e2e DEFERRED(P6)
  calendar_update    — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  calendar_delete    — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  calendar_watch     — mutation-request DONE; sandbox-e2e DEFERRED(P6)

MockCalendarService extends MockGoogleService (no shared-file edit) to add
events() and freebusy() resource proxies. _FreebusyProxy adds query();
_EventsProxy adds watch() — both extend _MockResourceProxy.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.mock_google import MockGoogleService, _MockResourceProxy
from kp_mcp_testkit.parity import compare


class _FreebusyProxy(_MockResourceProxy):
    """Extends _MockResourceProxy with the query() method for freebusy.query()."""

    def query(self, **kwargs: Any) -> Any:
        return self._call("query", **kwargs)


class _EventsProxy(_MockResourceProxy):
    """Extends _MockResourceProxy with watch() for events.watch()."""

    def watch(self, **kwargs: Any) -> Any:
        return self._call("watch", **kwargs)


class MockCalendarService(MockGoogleService):
    """MockGoogleService extended with Calendar-specific resource proxies."""

    def events(self) -> _EventsProxy:
        return _EventsProxy("events", self._responses, self._requests)

    def freebusy(self) -> _FreebusyProxy:
        return _FreebusyProxy("freebusy", self._responses, self._requests)


@pytest.fixture(autouse=True, scope="module")
def _ensure_calendar(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Re-register Calendar ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.calendar as cal_mod

    if "calendar.list" not in {s.name for s in reg.all_specs()}:
        importlib.reload(cal_mod)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "calendar"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _raw_event_stub() -> dict:
    return {
        "id": "evt001",
        "kind": "calendar#event",
        "status": "confirmed",
        "summary": "Existing Meeting",
        "start": {"dateTime": "2026-06-20T10:00:00Z", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-06-20T11:00:00Z", "timeZone": "America/New_York"},
        "attendees": [{"email": "alice@example.com", "responseStatus": "accepted"}],
    }


class TestCalendarList:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.calendar.core import calendar_list
        from google_kit.services.calendar.models import CalendarListInput

        response = _load("list_response.json")
        expected = _load("list_expected.json")

        svc = MockCalendarService(responses={("events", "list"): response})
        result = calendar_list(
            CalendarListInput(
                calendar_id="primary",
                time_min="2026-06-20T09:00:00Z",
                time_max="2026-06-20T17:00:00Z",
            ),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_attendee_emails_redacted(self) -> None:
        from google_kit.services.calendar.core import calendar_list
        from google_kit.services.calendar.models import CalendarListInput

        response = _load("list_response.json")
        svc = MockCalendarService(responses={("events", "list"): response})
        result = calendar_list(
            CalendarListInput(
                calendar_id="primary",
                time_min="2026-06-20T09:00:00Z",
                time_max="2026-06-20T17:00:00Z",
            ),
            service=svc,
        )
        for event in result.data.events:
            for att in event.attendees:
                assert att.email == "[redacted]", f"Email not redacted: {att.email}"

    def test_single_events_and_order_params(self) -> None:
        from google_kit.services.calendar.core import calendar_list
        from google_kit.services.calendar.models import CalendarListInput

        svc = MockCalendarService(responses={("events", "list"): {"items": []}})
        calendar_list(
            CalendarListInput(
                calendar_id="primary",
                time_min="2026-06-20T09:00:00Z",
                time_max="2026-06-20T17:00:00Z",
            ),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.kwargs.get("singleEvents") is True
        assert req.kwargs.get("orderBy") == "startTime"

    def test_empty_events(self) -> None:
        from google_kit.services.calendar.core import calendar_list
        from google_kit.services.calendar.models import CalendarListInput

        svc = MockCalendarService(responses={("events", "list"): {"items": []}})
        result = calendar_list(
            CalendarListInput(
                calendar_id="primary",
                time_min="2026-06-20T09:00:00Z",
                time_max="2026-06-20T17:00:00Z",
            ),
            service=svc,
        )
        assert result.data.count == 0
        assert result.data.events == []

    def test_calendar_id_forwarded(self) -> None:
        from google_kit.services.calendar.core import calendar_list
        from google_kit.services.calendar.models import CalendarListInput

        svc = MockCalendarService(responses={("events", "list"): {"items": []}})
        calendar_list(
            CalendarListInput(
                calendar_id="work@example.com",
                time_min="2026-06-20T09:00:00Z",
                time_max="2026-06-20T17:00:00Z",
            ),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.kwargs.get("calendarId") == "work@example.com"


class TestCalendarCreate:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.calendar.core import calendar_create
        from google_kit.services.calendar.models import CalendarCreateInput

        expected_body = _load("create_expected_body.json")
        canned_response = {
            "id": "evt-new-001",
            "summary": "Team Meeting",
            "htmlLink": "https://www.google.com/calendar/event?eid=xxx",
            "start": {"dateTime": "2026-06-20T10:00:00Z", "timeZone": "America/New_York"},
        }
        svc = MockCalendarService(responses={("events", "insert"): canned_response})
        calendar_create(
            CalendarCreateInput(
                summary="Team Meeting",
                start="2026-06-20T10:00:00",
                end="2026-06-20T11:00:00",
                attendees=["alice@example.com"],
                meet=True,
                conference_request_id="test-req-001",
                timezone="America/New_York",
                calendar_id="primary",
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_conference_data_version_when_meet(self) -> None:
        from google_kit.services.calendar.core import calendar_create
        from google_kit.services.calendar.models import CalendarCreateInput

        svc = MockCalendarService(
            responses={("events", "insert"): {"id": "x", "start": {}, "summary": "t"}}
        )
        calendar_create(
            CalendarCreateInput(
                summary="t",
                start="2026-06-20T10:00:00",
                end="2026-06-20T11:00:00",
                meet=True,
                conference_request_id="r1",
            ),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.kwargs.get("conferenceDataVersion") == 1

    def test_no_meet_conference_data_version_zero(self) -> None:
        from google_kit.services.calendar.core import calendar_create
        from google_kit.services.calendar.models import CalendarCreateInput

        svc = MockCalendarService(
            responses={("events", "insert"): {"id": "x", "start": {}, "summary": "t"}}
        )
        calendar_create(
            CalendarCreateInput(
                summary="t",
                start="2026-06-20T10:00:00",
                end="2026-06-20T11:00:00",
            ),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.kwargs.get("conferenceDataVersion") == 0

    def test_send_updates_all_with_attendees(self) -> None:
        from google_kit.services.calendar.core import calendar_create
        from google_kit.services.calendar.models import CalendarCreateInput

        svc = MockCalendarService(
            responses={("events", "insert"): {"id": "x", "start": {}, "summary": "t"}}
        )
        calendar_create(
            CalendarCreateInput(
                summary="t",
                start="2026-06-20T10:00:00",
                end="2026-06-20T11:00:00",
                attendees=["a@example.com"],
            ),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.kwargs.get("sendUpdates") == "all"

    def test_send_updates_none_without_attendees(self) -> None:
        from google_kit.services.calendar.core import calendar_create
        from google_kit.services.calendar.models import CalendarCreateInput

        svc = MockCalendarService(
            responses={("events", "insert"): {"id": "x", "start": {}, "summary": "t"}}
        )
        calendar_create(
            CalendarCreateInput(
                summary="t",
                start="2026-06-20T10:00:00",
                end="2026-06-20T11:00:00",
            ),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.kwargs.get("sendUpdates") == "none"

    def test_duration_fallback_when_no_end(self) -> None:
        from google_kit.services.calendar.core import calendar_create
        from google_kit.services.calendar.models import CalendarCreateInput

        svc = MockCalendarService(
            responses={("events", "insert"): {"id": "x", "start": {}, "summary": "t"}}
        )
        calendar_create(
            CalendarCreateInput(
                summary="t",
                start="2026-06-20T10:00:00",
                duration=60,
            ),
            service=svc,
        )
        body = svc.last_request_body()
        assert body is not None
        assert "end" in body


class TestCalendarFreebusy:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.calendar.core import calendar_freebusy
        from google_kit.services.calendar.models import CalendarFreebusyInput

        response = _load("freebusy_response.json")
        expected = _load("freebusy_expected.json")

        svc = MockCalendarService(responses={("freebusy", "query"): response})
        result = calendar_freebusy(
            CalendarFreebusyInput(
                emails=["alice@example.com", "bob@example.com"],
                time_min="2026-06-20T09:00:00Z",
                time_max="2026-06-20T17:00:00Z",
            ),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_request_body_shape(self) -> None:
        from google_kit.services.calendar.core import calendar_freebusy
        from google_kit.services.calendar.models import CalendarFreebusyInput

        svc = MockCalendarService(
            responses={("freebusy", "query"): {"timeMin": "x", "timeMax": "y", "calendars": {}}}
        )
        calendar_freebusy(
            CalendarFreebusyInput(
                emails=["alice@example.com"],
                time_min="2026-06-20T09:00:00Z",
                time_max="2026-06-20T17:00:00Z",
            ),
            service=svc,
        )
        body = svc.last_request_body()
        assert body is not None
        assert body["timeMin"] == "2026-06-20T09:00:00Z"
        assert body["timeMax"] == "2026-06-20T17:00:00Z"
        assert body["items"] == [{"id": "alice@example.com"}]

    def test_empty_busy(self) -> None:
        from google_kit.services.calendar.core import calendar_freebusy
        from google_kit.services.calendar.models import CalendarFreebusyInput

        svc = MockCalendarService(
            responses={
                ("freebusy", "query"): {
                    "timeMin": "2026-06-20T09:00:00Z",
                    "timeMax": "2026-06-20T17:00:00Z",
                    "calendars": {"free@example.com": {"busy": []}},
                }
            }
        )
        result = calendar_freebusy(
            CalendarFreebusyInput(
                emails=["free@example.com"],
                time_min="2026-06-20T09:00:00Z",
                time_max="2026-06-20T17:00:00Z",
            ),
            service=svc,
        )
        assert result.data.calendars[0].calendar_id == "free@example.com"
        assert result.data.calendars[0].busy == []


class TestCalendarUpdate:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.calendar.core import calendar_update
        from google_kit.services.calendar.models import CalendarUpdateInput

        expected_body = _load("update_expected_body.json")
        existing_event = _raw_event_stub()
        canned_updated = {**existing_event, "summary": "Existing Meeting"}
        svc = MockCalendarService(responses={
            ("events", "get"): existing_event,
            ("events", "patch"): canned_updated,
        })
        calendar_update(
            CalendarUpdateInput(
                event_id="evt001",
                calendar_id="primary",
                add_attendees=["bob@example.com"],
            ),
            service=svc,
        )
        patch_reqs = svc.requests_for("events", "patch")
        assert patch_reqs, "No patch request recorded"
        actual_body = patch_reqs[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_get_then_patch_two_calls(self) -> None:
        from google_kit.services.calendar.core import calendar_update
        from google_kit.services.calendar.models import CalendarUpdateInput

        ev = _raw_event_stub()
        svc = MockCalendarService(responses={
            ("events", "get"): ev,
            ("events", "patch"): ev,
        })
        calendar_update(
            CalendarUpdateInput(event_id="evt001", add_attendees=["bob@example.com"]),
            service=svc,
        )
        assert len(svc.requests_for("events", "get")) == 1
        assert len(svc.requests_for("events", "patch")) == 1

    def test_send_updates_all_when_add_attendees(self) -> None:
        from google_kit.services.calendar.core import calendar_update
        from google_kit.services.calendar.models import CalendarUpdateInput

        ev = _raw_event_stub()
        svc = MockCalendarService(responses={
            ("events", "get"): ev,
            ("events", "patch"): ev,
        })
        calendar_update(
            CalendarUpdateInput(event_id="evt001", add_attendees=["bob@example.com"]),
            service=svc,
        )
        patch_req = svc.requests_for("events", "patch")[0]
        assert patch_req.kwargs.get("sendUpdates") == "all"

    def test_send_updates_none_without_attendees(self) -> None:
        from google_kit.services.calendar.core import calendar_update
        from google_kit.services.calendar.models import CalendarUpdateInput

        svc = MockCalendarService(responses={("events", "patch"): {"id": "evt001"}})
        calendar_update(
            CalendarUpdateInput(event_id="evt001", summary="New Title"),
            service=svc,
        )
        patch_req = svc.requests_for("events", "patch")[0]
        assert patch_req.kwargs.get("sendUpdates") == "none"

    def test_summary_only_patch(self) -> None:
        from google_kit.services.calendar.core import calendar_update
        from google_kit.services.calendar.models import CalendarUpdateInput

        svc = MockCalendarService(responses={("events", "patch"): {"id": "evt001", "summary": "New Title"}})
        result = calendar_update(
            CalendarUpdateInput(event_id="evt001", summary="New Title"),
            service=svc,
        )
        body = svc.requests_for("events", "patch")[0].body
        assert body == {"summary": "New Title"}
        assert result.data.summary == "New Title"


class TestCalendarDelete:
    def test_mutation_request_recorded(self) -> None:
        from google_kit.services.calendar.core import calendar_delete
        from google_kit.services.calendar.models import CalendarDeleteInput

        svc = MockCalendarService(responses={("events", "delete"): None})
        result = calendar_delete(
            CalendarDeleteInput(event_id="evt001", calendar_id="primary"),
            service=svc,
        )
        assert result.data.deleted is True
        assert result.data.event_id == "evt001"

        delete_reqs = svc.requests_for("events", "delete")
        assert len(delete_reqs) == 1
        assert delete_reqs[0].kwargs.get("eventId") == "evt001"
        assert delete_reqs[0].kwargs.get("calendarId") == "primary"

    def test_send_updates_all(self) -> None:
        from google_kit.services.calendar.core import calendar_delete
        from google_kit.services.calendar.models import CalendarDeleteInput

        svc = MockCalendarService(responses={("events", "delete"): None})
        calendar_delete(CalendarDeleteInput(event_id="evt001"), service=svc)
        req = svc.requests_for("events", "delete")[0]
        assert req.kwargs.get("sendUpdates") == "all"

    def test_custom_calendar_id(self) -> None:
        from google_kit.services.calendar.core import calendar_delete
        from google_kit.services.calendar.models import CalendarDeleteInput

        svc = MockCalendarService(responses={("events", "delete"): None})
        calendar_delete(
            CalendarDeleteInput(event_id="evt002", calendar_id="work@example.com"),
            service=svc,
        )
        req = svc.requests_for("events", "delete")[0]
        assert req.kwargs["calendarId"] == "work@example.com"


class TestParseDatetime:
    def test_date_string_appends_midnight_utc(self) -> None:
        from google_kit.services.calendar.core import _parse_datetime

        assert _parse_datetime("2026-06-20") == "2026-06-20T00:00:00Z"

    def test_date_string_end_of_day(self) -> None:
        from google_kit.services.calendar.core import _parse_datetime

        assert _parse_datetime("2026-06-20", end_of_day=True) == "2026-06-20T23:59:59Z"

    def test_datetime_with_z_returned_unchanged(self) -> None:
        from google_kit.services.calendar.core import _parse_datetime

        assert _parse_datetime("2026-06-20T10:00:00Z") == "2026-06-20T10:00:00Z"

    def test_datetime_without_z_appends_z(self) -> None:
        from google_kit.services.calendar.core import _parse_datetime

        assert _parse_datetime("2026-06-20T10:00:00") == "2026-06-20T10:00:00Z"

    def test_datetime_with_offset_returned_unchanged(self) -> None:
        from google_kit.services.calendar.core import _parse_datetime

        result = _parse_datetime("2026-06-20T10:00:00+05:00")
        assert result == "2026-06-20T10:00:00+05:00"


class TestRegistryIntegration:
    def test_all_five_ops_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        expected = {
            "calendar.list",
            "calendar.create",
            "calendar.freebusy",
            "calendar.update",
            "calendar.delete",
        }
        assert expected.issubset(names), f"Missing ops: {expected - names}"

    def test_calendar_postures(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["calendar.list"].posture == "read"
        assert specs["calendar.create"].posture == "write"
        assert specs["calendar.freebusy"].posture == "read"
        assert specs["calendar.update"].posture == "write"
        assert specs["calendar.delete"].posture == "destructive"

    def test_calendar_scopes(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        # Writes/eventing hold the read-write scope.
        for name in ("calendar.create", "calendar.update", "calendar.delete", "calendar.watch"):
            assert "https://www.googleapis.com/auth/calendar" in specs[name].scopes
        # Pure reads tightened to calendar.readonly (gate c).
        for name in ("calendar.list", "calendar.freebusy"):
            assert "https://www.googleapis.com/auth/calendar.readonly" in specs[name].scopes

    def test_watch_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        assert "calendar.watch" in names

    def test_watch_posture_plane_capability_flag(self) -> None:
        import google_kit.registry as reg

        spec = reg.get("calendar.watch")
        assert spec.posture == "write"
        assert spec.plane == "eventing"
        assert spec.capability == "eventing.watch"
        assert spec.flag == "GOOGLE_KIT_ENABLE_CALENDAR_WRITE"


class TestCalendarWatch:
    def test_mutation_request_parity_with_expiration(self) -> None:
        from google_kit.services.calendar.core import calendar_watch
        from google_kit.services.calendar.models import CalendarWatchInput

        expected_body = _load("watch_expected_body.json")
        channel_response = _load("watch_channel_response.json")
        svc = MockCalendarService(responses={("events", "watch"): channel_response})
        calendar_watch(
            CalendarWatchInput(
                calendar_id="primary",
                channel_id="test-channel-001",
                address="https://example.com/webhook",
                expiration_ms=1750000000000,
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_body_without_expiration(self) -> None:
        from google_kit.services.calendar.core import calendar_watch
        from google_kit.services.calendar.models import CalendarWatchInput

        channel_response = _load("watch_channel_response.json")
        svc = MockCalendarService(responses={("events", "watch"): channel_response})
        calendar_watch(
            CalendarWatchInput(
                calendar_id="primary",
                channel_id="test-channel-001",
                address="https://example.com/webhook",
            ),
            service=svc,
        )
        body = svc.last_request_body()
        assert "expiration" not in body
        assert body["id"] == "test-channel-001"
        assert body["type"] == "web_hook"
        assert body["address"] == "https://example.com/webhook"

    def test_calendar_id_forwarded(self) -> None:
        from google_kit.services.calendar.core import calendar_watch
        from google_kit.services.calendar.models import CalendarWatchInput

        channel_response = _load("watch_channel_response.json")
        svc = MockCalendarService(responses={("events", "watch"): channel_response})
        calendar_watch(
            CalendarWatchInput(
                calendar_id="work@example.com",
                channel_id="test-channel-001",
                address="https://example.com/webhook",
            ),
            service=svc,
        )
        req = svc.requests_for("events", "watch")[0]
        assert req.kwargs.get("calendarId") == "work@example.com"

    def test_default_calendar_id_is_primary(self) -> None:
        from google_kit.services.calendar.core import calendar_watch
        from google_kit.services.calendar.models import CalendarWatchInput

        channel_response = _load("watch_channel_response.json")
        svc = MockCalendarService(responses={("events", "watch"): channel_response})
        calendar_watch(
            CalendarWatchInput(
                channel_id="test-channel-001",
                address="https://example.com/webhook",
            ),
            service=svc,
        )
        req = svc.requests_for("events", "watch")[0]
        assert req.kwargs.get("calendarId") == "primary"

    def test_normalization(self) -> None:
        from google_kit.services.calendar.core import calendar_watch
        from google_kit.services.calendar.models import CalendarWatchInput

        channel_response = _load("watch_channel_response.json")
        svc = MockCalendarService(responses={("events", "watch"): channel_response})
        result = calendar_watch(
            CalendarWatchInput(
                channel_id="test-channel-001",
                address="https://example.com/webhook",
            ),
            service=svc,
        )
        assert result.data.id == "test-channel-001"
        assert result.data.resource_id == "res-xyz-001"
        assert result.data.resource_uri == "https://www.googleapis.com/calendar/v3/calendars/primary/events?alt=json"
        assert result.data.expiration == "1750000000000"
