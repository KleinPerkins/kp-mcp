"""Pydantic input / output models for all Calendar service operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope


class CalendarListInput(BaseModel):
    """Input for ``calendar.list``: list upcoming events in a calendar."""

    calendar_id: str = Field(default="primary")
    time_min: str | None = None
    time_max: str | None = None
    max_results: int = Field(default=50, ge=1, le=2500)
    days: int = Field(default=7, ge=1)


class CalendarAttendeeOutput(BaseModel):
    """One attendee entry with email redacted."""

    email: str = "[redacted]"
    display_name: str | None = None
    response_status: str | None = None


class CalendarEventItem(BaseModel):
    """One calendar event entry."""

    id: str
    summary: str | None = None
    start: dict[str, Any]
    end: dict[str, Any]
    location: str | None = None
    hangout_link: str | None = None
    status: str | None = None
    attendees: list[CalendarAttendeeOutput] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class CalendarListData(BaseModel):
    """Data payload for ``calendar.list``."""

    count: int
    events: list[CalendarEventItem]


CalendarListOutput = OutputEnvelope[CalendarListData]


class CalendarCreateInput(BaseModel):
    """Input for ``calendar.create``: create a new calendar event."""

    summary: str
    start: str
    end: str | None = None
    duration: int = Field(default=30, ge=1)
    description: str | None = None
    location: str | None = None
    attendees: list[str] = Field(default_factory=list)
    meet: bool = False
    all_day: bool = False
    timezone: str = Field(default="America/New_York")
    calendar_id: str = Field(default="primary")
    conference_request_id: str | None = None


class CalendarCreateData(BaseModel):
    """Data payload for ``calendar.create``."""

    id: str
    summary: str | None = None
    html_link: str | None = None
    hangout_link: str | None = None
    start: dict[str, Any]


CalendarCreateOutput = OutputEnvelope[CalendarCreateData]


class CalendarFreebusyInput(BaseModel):
    """Input for ``calendar.freebusy``: query free/busy for a set of calendars."""

    emails: list[str]
    time_min: str
    time_max: str


class CalendarBusySlot(BaseModel):
    """One busy time slot."""

    start: str
    end: str


class CalendarCalendarBusy(BaseModel):
    """Free/busy info for one calendar."""

    calendar_id: str
    busy: list[CalendarBusySlot]


class CalendarFreebusyData(BaseModel):
    """Data payload for ``calendar.freebusy``."""

    time_min: str
    time_max: str
    calendars: list[CalendarCalendarBusy]


CalendarFreebusyOutput = OutputEnvelope[CalendarFreebusyData]


class CalendarUpdateInput(BaseModel):
    """Input for ``calendar.update``: patch fields on an existing event."""

    event_id: str
    calendar_id: str = Field(default="primary")
    summary: str | None = None
    description: str | None = None
    location: str | None = None
    start: str | None = None
    end: str | None = None
    add_attendees: list[str] = Field(default_factory=list)
    timezone: str = Field(default="America/New_York")


class CalendarUpdateData(BaseModel):
    """Data payload for ``calendar.update``."""

    id: str
    summary: str | None = None
    html_link: str | None = None


CalendarUpdateOutput = OutputEnvelope[CalendarUpdateData]


class CalendarDeleteInput(BaseModel):
    """Input for ``calendar.delete``: delete a calendar event."""

    event_id: str
    calendar_id: str = Field(default="primary")


class CalendarDeleteData(BaseModel):
    """Data payload for ``calendar.delete``."""

    deleted: bool
    event_id: str


CalendarDeleteOutput = OutputEnvelope[CalendarDeleteData]


class CalendarWatchInput(BaseModel):
    """Input for ``calendar.watch``: register a push-notification channel."""

    calendar_id: str = Field(default="primary")
    channel_id: str
    address: str
    expiration_ms: int | None = None


class CalendarWatchData(BaseModel):
    """Data payload for ``calendar.watch``."""

    id: str
    resource_id: str
    resource_uri: str
    expiration: str | None = None


CalendarWatchOutput = OutputEnvelope[CalendarWatchData]
