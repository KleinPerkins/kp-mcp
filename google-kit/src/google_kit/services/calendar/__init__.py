"""Calendar service — registers 6 ops in the google-kit registry."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    calendar_create,
    calendar_delete,
    calendar_freebusy,
    calendar_list,
    calendar_update,
    calendar_watch,
)
from .models import (
    CalendarCreateInput,
    CalendarCreateOutput,
    CalendarDeleteInput,
    CalendarDeleteOutput,
    CalendarFreebusyInput,
    CalendarFreebusyOutput,
    CalendarListInput,
    CalendarListOutput,
    CalendarUpdateInput,
    CalendarUpdateOutput,
    CalendarWatchInput,
    CalendarWatchOutput,
)

_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_CALENDAR_READONLY_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

#: Per-service F5 write gate (off by default). Satisfied by the
#: ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. See core/flags.py.
_CALENDAR_WRITE_FLAG = "GOOGLE_KIT_ENABLE_CALENDAR_WRITE"

register(OpSpec(
    name="calendar.list",
    fn=calendar_list,
    input_model=CalendarListInput,
    output_model=CalendarListOutput,
    posture="read",
    scopes=_CALENDAR_READONLY_SCOPES,
    perf={"api": "Calendar v3", "method": "events.list", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List events for the next 7 days",
        "input": {"calendar_id": "primary", "days": 7, "max_results": 50},
        "cli": "google-kit calendar list --days 7",
    }],
    keywords=["show"],
))

register(OpSpec(
    name="calendar.create",
    fn=calendar_create,
    input_model=CalendarCreateInput,
    output_model=CalendarCreateOutput,
    posture="write",
    scopes=_CALENDAR_SCOPES,
    perf={"api": "Calendar v3", "method": "events.insert", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a 1-hour meeting with a Meet link",
        "input": {"summary": "Team Meeting", "start": "2026-06-20T10:00:00", "end": "2026-06-20T11:00:00", "meet": True},
        "cli": "google-kit calendar create 'Team Meeting' --start 2026-06-20T10:00:00 --end 2026-06-20T11:00:00 --meet",
    }],
    flag=_CALENDAR_WRITE_FLAG,
))

register(OpSpec(
    name="calendar.freebusy",
    fn=calendar_freebusy,
    input_model=CalendarFreebusyInput,
    output_model=CalendarFreebusyOutput,
    posture="read",
    scopes=_CALENDAR_READONLY_SCOPES,
    perf={"api": "Calendar v3", "method": "freebusy.query", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Check availability for two people",
        "input": {"emails": ["alice@example.com", "bob@example.com"], "time_min": "2026-06-20T09:00:00Z", "time_max": "2026-06-20T17:00:00Z"},
        "cli": "google-kit calendar freebusy --emails alice@example.com,bob@example.com --start 2026-06-20T09:00:00 --end 2026-06-20T17:00:00",
    }],
))

register(OpSpec(
    name="calendar.update",
    fn=calendar_update,
    input_model=CalendarUpdateInput,
    output_model=CalendarUpdateOutput,
    posture="write",
    scopes=_CALENDAR_SCOPES,
    perf={"api": "Calendar v3", "method": "events.get + events.patch", "quota": "1000 req/day (2 calls)"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Add an attendee to an existing event",
        "input": {"event_id": "<event-id>", "add_attendees": ["bob@example.com"]},
        "cli": "google-kit calendar update <event-id> --add-attendees bob@example.com",
    }],
    aliases=["reschedule a meeting", "change an event time", "update an event"],
    keywords=["reschedule"],
    flag=_CALENDAR_WRITE_FLAG,
))

register(OpSpec(
    name="calendar.delete",
    fn=calendar_delete,
    input_model=CalendarDeleteInput,
    output_model=CalendarDeleteOutput,
    posture="destructive",
    scopes=_CALENDAR_SCOPES,
    perf={"api": "Calendar v3", "method": "events.delete", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Delete a calendar event",
        "input": {"event_id": "<event-id>", "calendar_id": "primary"},
        "cli": "google-kit calendar delete <event-id>",
    }],
    aliases=["cancel a meeting", "remove an event"],
    keywords=["cancel", "remove"],
    flag=_CALENDAR_WRITE_FLAG,
))

register(OpSpec(
    name="calendar.watch",
    fn=calendar_watch,
    input_model=CalendarWatchInput,
    output_model=CalendarWatchOutput,
    posture="write",
    plane="eventing",
    capability="eventing.watch",
    scopes=_CALENDAR_SCOPES,
    perf={"api": "Calendar v3", "method": "events.watch", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Register a webhook channel for calendar push notifications",
        "input": {"calendar_id": "primary", "channel_id": "my-channel-001", "address": "https://example.com/webhook"},
        "cli": "google-kit calendar watch --channel-id my-channel-001 --address https://example.com/webhook",
    }],
    flag=_CALENDAR_WRITE_FLAG,
))
