"""Pydantic input / output models for all People service operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope


class PersonName(BaseModel):
    """One name entry from a Person resource."""

    display_name: str
    family_name: str
    given_name: str


class PersonEmail(BaseModel):
    """One email-address entry from a Person resource."""

    value: str
    type: str
    formatted_type: str


class PersonEntry(BaseModel):
    """Normalized representation of a People API Person resource."""

    resource_name: str
    names: list[PersonName] = Field(default_factory=list)
    email_addresses: list[PersonEmail] = Field(default_factory=list)


# --- people.get ---


class PeopleGetInput(BaseModel):
    """Input for ``people.get``: fetch a single person by resource name."""

    resource_name: str = Field(description="Resource name of the person, e.g. 'people/me'")
    person_fields: str = Field(
        default="names,emailAddresses",
        description="Comma-separated fields to return",
    )


PeopleGetData = PersonEntry

PeopleGetOutput = OutputEnvelope[PeopleGetData]


# --- people.batch_get ---


class PeopleBatchGetInput(BaseModel):
    """Input for ``people.batch_get``: fetch multiple people by resource names."""

    resource_names: list[str] = Field(description="Resource names to fetch")
    person_fields: str = Field(
        default="names,emailAddresses",
        description="Comma-separated fields to return",
    )


class PeopleBatchGetData(BaseModel):
    """Data payload for ``people.batch_get``."""

    count: int
    people: list[PersonEntry]


PeopleBatchGetOutput = OutputEnvelope[PeopleBatchGetData]


# --- people.search_directory ---


class PeopleSearchDirectoryInput(BaseModel):
    """Input for ``people.search_directory``: search the domain directory."""

    query: str = Field(description="Search query string")
    read_mask: str = Field(
        default="names,emailAddresses",
        description="Comma-separated fields to return",
    )
    sources: list[str] = Field(
        default_factory=lambda: ["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"],
        description="Directory sources to search",
    )
    page_size: int = Field(default=10, ge=1, le=1000)
    page_token: str | None = Field(default=None, description="Page token for continuation")


class PeopleSearchDirectoryData(BaseModel):
    """Data payload for ``people.search_directory``."""

    count: int
    people: list[PersonEntry]


PeopleSearchDirectoryOutput = OutputEnvelope[PeopleSearchDirectoryData]


# --- people.list_directory ---


class PeopleListDirectoryInput(BaseModel):
    """Input for ``people.list_directory``: list all directory people."""

    read_mask: str = Field(
        default="names,emailAddresses",
        description="Comma-separated fields to return",
    )
    sources: list[str] = Field(
        default_factory=lambda: ["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"],
        description="Directory sources to list",
    )
    page_size: int = Field(default=10, ge=1, le=1000)
    page_token: str | None = Field(default=None, description="Page token for continuation")


class PeopleListDirectoryData(BaseModel):
    """Data payload for ``people.list_directory``."""

    count: int
    people: list[PersonEntry]


PeopleListDirectoryOutput = OutputEnvelope[PeopleListDirectoryData]


# --- people.connections ---


class PeopleConnectionsInput(BaseModel):
    """Input for ``people.connections``: list the authenticated user's contacts."""

    person_fields: str = Field(
        default="names,emailAddresses",
        description="Comma-separated fields to return",
    )
    page_size: int = Field(default=10, ge=1, le=1000)
    page_token: str | None = Field(default=None, description="Page token for continuation")


class PeopleConnectionsData(BaseModel):
    """Data payload for ``people.connections``."""

    count: int
    connections: list[PersonEntry]


PeopleConnectionsOutput = OutputEnvelope[PeopleConnectionsData]
