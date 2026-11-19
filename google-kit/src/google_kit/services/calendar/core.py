"""Core functions for the Calendar service (cutover-minimum: 5 ops + watch).

Parity coverage per op:

  calendar_list      — mock-read DONE; sandbox-e2e DEFERRED(P6)
  calendar_create    — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  calendar_freebusy  — mock-read DONE; sandbox-e2e DEFERRED(P6)
  calendar_update    — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  calendar_delete    — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  calendar_watch     — mutation-request DONE; sandbox-e2e DEFERRED(P6)

Legacy quirks preserved:
  - singleEvents=True and orderBy=startTime hardcoded for list (matches legacy).
  - sendUpdates='all' when attendees present for create; 'none' otherwise.
  - sendUpdates='all' when add_attendees present for update; 'none' otherwise.
  - sendUpdates='all' hardcoded for delete (matches legacy gcalendar delete).
  - Attendee emails are redacted to '[redacted]' in list output (PII).
  - conferenceDataVersion=1 when meet=True; 0 otherwise.
  - GET-then-PATCH for update when add_attendees provided; merges existing + new.
  - _parse_datetime port of legacy gcalendar._parse_datetime: pass-through if
    'T' present with tz info; append 'Z' if bare datetime; 'T00:00:00Z' for dates.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope

from .models import (
    CalendarAttendeeOutput,
    CalendarBusySlot,
    CalendarCalendarBusy,
    CalendarCreateData,
    CalendarCreateInput,
    CalendarCreateOutput,
    CalendarDeleteData,
    CalendarDeleteInput,
    CalendarDeleteOutput,
    CalendarEventItem,
    CalendarFreebusyData,
    CalendarFreebusyInput,
    CalendarFreebusyOutput,
    CalendarListData,
    CalendarListInput,
    CalendarListOutput,
    CalendarUpdateData,
    CalendarUpdateInput,
    CalendarUpdateOutput,
    CalendarWatchData,
    CalendarWatchInput,
    CalendarWatchOutput,
)

_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _parse_datetime(value: str, end_of_day: bool = False) -> str:
    """Normalise a user-supplied date or datetime into RFC 3339.

    Port of legacy gcalendar._parse_datetime:
      - If 'T' present and already has tz info (Z or +/-), return as-is.
      - If 'T' present but no tz marker, append 'Z'.
      - If date-only and end_of_day, append 'T23:59:59Z'.
      - If date-only, append 'T00:00:00Z'.
    """
    value = value.strip()
    if "T" in value:
        if not value.endswith("Z") and "+" not in value and "-" not in value[10:]:
            value += "Z"
        return value
    if end_of_day:
        return f"{value}T23:59:59Z"
    return f"{value}T00:00:00Z"


def _wrap(data: Any, op: str) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, meta=Meta(op=op))


def calendar_list(
    inp: CalendarListInput,
    *,
    service: Any = None,
) -> CalendarListOutput:
    """List upcoming calendar events with attendee emails redacted.

    singleEvents=True and orderBy=startTime match legacy gcalendar list behaviour.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    now = datetime.now(timezone.utc)
    time_min = _parse_datetime(inp.time_min) if inp.time_min else now.isoformat()
    time_max = (
        _parse_datetime(inp.time_max, end_of_day=True)
        if inp.time_max
        else (now + timedelta(days=inp.days)).isoformat()
    )

    raw = execute_api_call(
        lambda: service.events().list(
            calendarId=inp.calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=inp.max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute(),
        op="calendar.list",
        posture="read",
    )
    items = (raw or {}).get("items", [])
    events = [
        CalendarEventItem(
            id=ev.get("id", ""),
            summary=ev.get("summary"),
            start=ev.get("start", {}),
            end=ev.get("end", {}),
            location=ev.get("location"),
            hangout_link=ev.get("hangoutLink"),
            status=ev.get("status"),
            attendees=[
                CalendarAttendeeOutput(
                    email="[redacted]",
                    display_name=a.get("displayName"),
                    response_status=a.get("responseStatus"),
                )
                for a in ev.get("attendees", [])
            ],
        )
        for ev in items
    ]
    return _wrap(CalendarListData(count=len(events), events=events), "calendar.list")


def calendar_create(
    inp: CalendarCreateInput,
    *,
    service: Any = None,
) -> CalendarCreateOutput:
    """Create a calendar event with optional Google Meet link and attendees.

    Supports conferenceData (Meet via conferenceDataVersion=1) and attendees.
    sendUpdates='all' when attendees provided, 'none' otherwise (matches legacy).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    body: dict[str, Any] = {"summary": inp.summary}
    if inp.description:
        body["description"] = inp.description
    if inp.location:
        body["location"] = inp.location

    if inp.all_day:
        body["start"] = {"date": inp.start[:10]}
        body["end"] = {"date": inp.end[:10] if inp.end else inp.start[:10]}
    else:
        start_dt = _parse_datetime(inp.start)
        if inp.end:
            end_dt = _parse_datetime(inp.end)
        else:
            parsed = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
            end_iso = (parsed + timedelta(minutes=inp.duration)).isoformat()
            end_dt = end_iso.replace("+00:00", "Z")
        body["start"] = {"dateTime": start_dt, "timeZone": inp.timezone}
        body["end"] = {"dateTime": end_dt, "timeZone": inp.timezone}

    if inp.attendees:
        body["attendees"] = [{"email": e.strip()} for e in inp.attendees]

    if inp.meet:
        req_id = inp.conference_request_id or f"chaos-{datetime.now(timezone.utc).isoformat()}"
        body["conferenceData"] = {
            "createRequest": {
                "requestId": req_id,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    raw = execute_api_call(
        lambda: service.events().insert(
            calendarId=inp.calendar_id,
            body=body,
            conferenceDataVersion=1 if inp.meet else 0,
            sendUpdates="all" if inp.attendees else "none",
        ).execute(),
        op="calendar.create",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    created = raw or {}
    return _wrap(
        CalendarCreateData(
            id=created.get("id", ""),
            summary=created.get("summary"),
            html_link=created.get("htmlLink"),
            hangout_link=created.get("hangoutLink"),
            start=created.get("start", {}),
        ),
        "calendar.create",
    )


def calendar_freebusy(
    inp: CalendarFreebusyInput,
    *,
    service: Any = None,
) -> CalendarFreebusyOutput:
    """Query free/busy information for a set of calendars.

    POST body: {timeMin, timeMax, items: [{id: email}]} per legacy gcalendar freebusy.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    body: dict[str, Any] = {
        "timeMin": inp.time_min,
        "timeMax": inp.time_max,
        "items": [{"id": e} for e in inp.emails],
    }
    raw = execute_api_call(
        lambda: service.freebusy().query(body=body).execute(),
        op="calendar.freebusy",
        posture="read",
    )
    result = raw or {}
    calendars_raw = result.get("calendars", {})
    calendars = [
        CalendarCalendarBusy(
            calendar_id=cal_id,
            busy=[
                CalendarBusySlot(start=s["start"], end=s["end"])
                for s in info.get("busy", [])
            ],
        )
        for cal_id, info in calendars_raw.items()
    ]
    return _wrap(
        CalendarFreebusyData(
            time_min=result.get("timeMin", inp.time_min),
            time_max=result.get("timeMax", inp.time_max),
            calendars=calendars,
        ),
        "calendar.freebusy",
    )


def calendar_update(
    inp: CalendarUpdateInput,
    *,
    service: Any = None,
) -> CalendarUpdateOutput:
    """Update a calendar event via GET-then-PATCH.

    When add_attendees is provided, fetches the current event to merge
    existing attendees before patching. sendUpdates='all' when merging
    attendees, 'none' otherwise (matches legacy gcalendar update).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    patch_body: dict[str, Any] = {}
    if inp.summary is not None:
        patch_body["summary"] = inp.summary
    if inp.description is not None:
        patch_body["description"] = inp.description
    if inp.location is not None:
        patch_body["location"] = inp.location
    if inp.start is not None:
        patch_body["start"] = {
            "dateTime": _parse_datetime(inp.start),
            "timeZone": inp.timezone,
        }
    if inp.end is not None:
        patch_body["end"] = {
            "dateTime": _parse_datetime(inp.end),
            "timeZone": inp.timezone,
        }

    if inp.add_attendees:
        existing = execute_api_call(
            lambda: service.events().get(
                calendarId=inp.calendar_id,
                eventId=inp.event_id,
            ).execute(),
            op="calendar.update.get",
            posture="read",
        )
        current = (existing or {}).get("attendees", [])
        new_attendees = [{"email": e.strip()} for e in inp.add_attendees]
        patch_body["attendees"] = current + new_attendees

    raw = execute_api_call(
        lambda: service.events().patch(
            calendarId=inp.calendar_id,
            eventId=inp.event_id,
            body=patch_body,
            sendUpdates="all" if inp.add_attendees else "none",
        ).execute(),
        op="calendar.update",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.event_id],
    )
    updated = raw or {}
    return _wrap(
        CalendarUpdateData(
            id=updated.get("id", inp.event_id),
            summary=updated.get("summary"),
            html_link=updated.get("htmlLink"),
        ),
        "calendar.update",
    )


def calendar_delete(
    inp: CalendarDeleteInput,
    *,
    service: Any = None,
) -> CalendarDeleteOutput:
    """Delete a calendar event, notifying all attendees.

    sendUpdates='all' matches legacy gcalendar delete behaviour.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    execute_api_call(
        lambda: service.events().delete(
            calendarId=inp.calendar_id,
            eventId=inp.event_id,
            sendUpdates="all",
        ).execute(),
        op="calendar.delete",
        posture="destructive",
        normalized_request=inp.model_dump(),
        target_ids=[inp.event_id],
    )
    return _wrap(CalendarDeleteData(deleted=True, event_id=inp.event_id), "calendar.delete")


def calendar_watch(
    inp: CalendarWatchInput,
    *,
    service: Any = None,
) -> CalendarWatchOutput:
    """Register a push-notification channel for calendar events.

    Calendar push delivers to an HTTPS webhook; endpoint provisioned by the
    operator. Channel body includes expiration only when provided.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    body: dict[str, Any] = {
        "id": inp.channel_id,
        "type": "web_hook",
        "address": inp.address,
    }
    if inp.expiration_ms is not None:
        body["expiration"] = inp.expiration_ms

    raw = execute_api_call(
        lambda: service.events().watch(
            calendarId=inp.calendar_id,
            body=body,
        ).execute(),
        op="calendar.watch",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    result = raw or {}
    return _wrap(
        CalendarWatchData(
            id=result.get("id", ""),
            resource_id=result.get("resourceId", ""),
            resource_uri=result.get("resourceUri", ""),
            expiration=result.get("expiration"),
        ),
        "calendar.watch",
    )
