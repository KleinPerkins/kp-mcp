"""Core functions for the People service (5 read ops).

Parity coverage per op:

  people_get              — mock-read DONE; sandbox-e2e DEFERRED(P6)
  people_batch_get        — mock-read DONE; sandbox-e2e DEFERRED(P6)
  people_search_directory — mock-read DONE; sandbox-e2e DEFERRED(P6)
  people_list_directory   — mock-read DONE; sandbox-e2e DEFERRED(P6)
  people_connections      — mock-read DONE; sandbox-e2e DEFERRED(P6)
"""
from __future__ import annotations

from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope, PageInfo

from .models import (
    PeopleBatchGetData,
    PeopleBatchGetInput,
    PeopleBatchGetOutput,
    PeopleConnectionsData,
    PeopleConnectionsInput,
    PeopleConnectionsOutput,
    PeopleGetInput,
    PeopleGetOutput,
    PeopleListDirectoryData,
    PeopleListDirectoryInput,
    PeopleListDirectoryOutput,
    PeopleSearchDirectoryData,
    PeopleSearchDirectoryInput,
    PeopleSearchDirectoryOutput,
    PersonEmail,
    PersonEntry,
    PersonName,
)


def _norm_person(raw: dict[str, Any]) -> PersonEntry:
    names = [
        PersonName(
            display_name=n.get("displayName", ""),
            family_name=n.get("familyName", ""),
            given_name=n.get("givenName", ""),
        )
        for n in raw.get("names", [])
    ]
    emails = [
        PersonEmail(
            value=e.get("value", ""),
            type=e.get("type", ""),
            formatted_type=e.get("formattedType", ""),
        )
        for e in raw.get("emailAddresses", [])
    ]
    return PersonEntry(
        resource_name=raw.get("resourceName", ""),
        names=names,
        email_addresses=emails,
    )


def _wrap(data: Any, op: str, *, page: PageInfo | None = None) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, page=page, meta=Meta(op=op))


def people_get(
    inp: PeopleGetInput,
    *,
    service: Any = None,
) -> PeopleGetOutput:
    """Fetch a single person by resource name.

    Calls people.get; returns normalized names + emailAddresses.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.people().get(
            resourceName=inp.resource_name,
            personFields=inp.person_fields,
        ).execute(),
        op="people.get",
        posture="read",
    )
    return _wrap(_norm_person(raw or {}), "people.get")


def people_batch_get(
    inp: PeopleBatchGetInput,
    *,
    service: Any = None,
) -> PeopleBatchGetOutput:
    """Fetch multiple people by resource names in a single API call.

    Calls people.getBatchGet; returns a list of normalized person entries.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.people().getBatchGet(
            resourceNames=inp.resource_names,
            personFields=inp.person_fields,
        ).execute(),
        op="people.batch_get",
        posture="read",
    )
    responses = (raw or {}).get("responses", [])
    people = [_norm_person(r.get("person") or {}) for r in responses]
    return _wrap(PeopleBatchGetData(count=len(people), people=people), "people.batch_get")


def people_search_directory(
    inp: PeopleSearchDirectoryInput,
    *,
    service: Any = None,
) -> PeopleSearchDirectoryOutput:
    """Search the domain directory for people matching a query.

    Calls people.searchDirectoryPeople; returns matched entries. Continuation
    is surfaced via the envelope ``page.next_page_token``.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    kwargs: dict[str, Any] = {
        "query": inp.query,
        "readMask": inp.read_mask,
        "sources": inp.sources,
        "pageSize": inp.page_size,
    }
    if inp.page_token:
        kwargs["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda: service.people().searchDirectoryPeople(**kwargs).execute(),
        op="people.search_directory",
        posture="read",
    )
    payload = raw or {}
    people = [_norm_person(p) for p in payload.get("people", [])]
    data = PeopleSearchDirectoryData(
        count=len(people),
        people=people,
    )
    return _wrap(
        data,
        "people.search_directory",
        page=PageInfo(next_page_token=payload.get("nextPageToken")),
    )


def people_list_directory(
    inp: PeopleListDirectoryInput,
    *,
    service: Any = None,
) -> PeopleListDirectoryOutput:
    """List all people in the domain directory.

    Calls people.listDirectoryPeople; returns entries. Continuation is surfaced
    via the envelope ``page.next_page_token``.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    kwargs: dict[str, Any] = {
        "readMask": inp.read_mask,
        "sources": inp.sources,
        "pageSize": inp.page_size,
    }
    if inp.page_token:
        kwargs["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda: service.people().listDirectoryPeople(**kwargs).execute(),
        op="people.list_directory",
        posture="read",
    )
    payload = raw or {}
    people = [_norm_person(p) for p in payload.get("people", [])]
    data = PeopleListDirectoryData(
        count=len(people),
        people=people,
    )
    return _wrap(
        data,
        "people.list_directory",
        page=PageInfo(next_page_token=payload.get("nextPageToken")),
    )


def people_connections(
    inp: PeopleConnectionsInput,
    *,
    service: Any = None,
) -> PeopleConnectionsOutput:
    """List the authenticated user's personal contacts.

    Calls people.connections.list with resourceName='people/me'; returns
    contacts. Continuation is surfaced via the envelope ``page.next_page_token``.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    kwargs: dict[str, Any] = {
        "resourceName": "people/me",
        "personFields": inp.person_fields,
        "pageSize": inp.page_size,
    }
    if inp.page_token:
        kwargs["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda: service.people().connections().list(**kwargs).execute(),
        op="people.connections",
        posture="read",
    )
    payload = raw or {}
    connections = [_norm_person(p) for p in payload.get("connections", [])]
    data = PeopleConnectionsData(
        count=len(connections),
        connections=connections,
    )
    return _wrap(
        data,
        "people.connections",
        page=PageInfo(next_page_token=payload.get("nextPageToken")),
    )
