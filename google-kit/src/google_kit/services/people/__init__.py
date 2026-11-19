"""People service — registers 5 read ops (People API v1)."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    people_batch_get,
    people_connections,
    people_get,
    people_list_directory,
    people_search_directory,
)
from .models import (
    PeopleBatchGetInput,
    PeopleBatchGetOutput,
    PeopleConnectionsInput,
    PeopleConnectionsOutput,
    PeopleGetInput,
    PeopleGetOutput,
    PeopleListDirectoryInput,
    PeopleListDirectoryOutput,
    PeopleSearchDirectoryInput,
    PeopleSearchDirectoryOutput,
)

_SCOPES_IDENTITY = [
    "https://www.googleapis.com/auth/directory.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
]
# people.get('people/me') reads the user's OWN profile (the PROFILE source).
# directory.readonly (domain) and contacts.readonly (contacts) do NOT authorize
# the self-profile, so names/emailAddresses for people/me require the profile
# scope — confirmed by the live 403 "Request requires one of the following
# scopes: [profile]". userinfo.profile is requested as an EXTRA per-login consent
# (GOOGLE_KIT_EXTRA_SCOPES / --scopes) for the sandbox profile; it is deliberately
# NOT added to the shared consent union core/auth.py:GOOGLE_KIT_SCOPES. See
# docs/dev/LIVE-E2E-NEW-APIS.md §1. (people.batch_get does not need it: getBatchGet
# returns a 200 envelope with per-entry status, so it does not hard-403.)
_SCOPES_IDENTITY_SELF = _SCOPES_IDENTITY + [
    "https://www.googleapis.com/auth/userinfo.profile",
]
_SCOPES_DIRECTORY = ["https://www.googleapis.com/auth/directory.readonly"]
_SCOPES_CONTACTS = ["https://www.googleapis.com/auth/contacts.readonly"]

register(OpSpec(
    name="people.get",
    fn=people_get,
    input_model=PeopleGetInput,
    output_model=PeopleGetOutput,
    posture="read",
    scopes=_SCOPES_IDENTITY_SELF,
    plane="identity",
    capability="identity.read",
    perf={"api": "People v1", "method": "people.get", "quota": "90 req/min"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get names and emails for the authenticated user",
        "input": {"resource_name": "people/me", "person_fields": "names,emailAddresses"},
        "cli": "google-kit people get --resource-name people/me",
    }],
))

register(OpSpec(
    name="people.batch_get",
    fn=people_batch_get,
    input_model=PeopleBatchGetInput,
    output_model=PeopleBatchGetOutput,
    posture="read",
    scopes=_SCOPES_IDENTITY,
    plane="identity",
    capability="identity.read",
    perf={"api": "People v1", "method": "people.getBatchGet", "quota": "90 req/min"},
    batching={"supported": True},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Fetch two people by resource name",
        "input": {"resource_names": ["people/p001", "people/p002"], "person_fields": "names,emailAddresses"},
        "cli": "google-kit people batch-get --resource-names '[\"people/p001\",\"people/p002\"]'",
    }],
))

register(OpSpec(
    name="people.search_directory",
    fn=people_search_directory,
    input_model=PeopleSearchDirectoryInput,
    output_model=PeopleSearchDirectoryOutput,
    posture="read",
    scopes=_SCOPES_DIRECTORY,
    plane="identity",
    capability="identity.search",
    perf={"api": "People v1", "method": "people.searchDirectoryPeople", "quota": "90 req/min"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Search the domain directory for 'Alice'",
        "input": {"query": "Alice"},
        "cli": "google-kit people search-directory --query Alice",
    }],
))

register(OpSpec(
    name="people.list_directory",
    fn=people_list_directory,
    input_model=PeopleListDirectoryInput,
    output_model=PeopleListDirectoryOutput,
    posture="read",
    scopes=_SCOPES_DIRECTORY,
    plane="identity",
    capability="identity.search",
    perf={"api": "People v1", "method": "people.listDirectoryPeople", "quota": "90 req/min"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List first page of domain directory people",
        "input": {"read_mask": "names,emailAddresses", "page_size": 10},
        "cli": "google-kit people list-directory --page-size 10",
    }],
))

register(OpSpec(
    name="people.connections",
    fn=people_connections,
    input_model=PeopleConnectionsInput,
    output_model=PeopleConnectionsOutput,
    posture="read",
    scopes=_SCOPES_CONTACTS,
    plane="identity",
    capability="identity.read",
    perf={"api": "People v1", "method": "people.connections.list", "quota": "90 req/min"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List personal contacts for the authenticated user",
        "input": {"person_fields": "names,emailAddresses", "page_size": 10},
        "cli": "google-kit people connections --page-size 10",
    }],
))
