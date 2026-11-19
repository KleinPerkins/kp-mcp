"""Pydantic input / output models for all Forms service operations."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope




FormsItemType = Literal[
    "short_text",
    "paragraph",
    "multiple_choice",
    "checkbox",
    "dropdown",
    "scale",
    "date",
    "time",
]


class FormsCreateInput(BaseModel):
    """Input for ``forms.create``: create a new Google Form."""

    title: str
    description: str | None = None
    document_title: str | None = None


class FormsCreateData(BaseModel):
    """Data payload for ``forms.create``."""

    form_id: str
    title: str
    responder_uri: str


FormsCreateOutput = OutputEnvelope[FormsCreateData]


class FormsGetInput(BaseModel):
    """Input for ``forms.get``: retrieve form metadata and items."""

    form_id: str


class FormsItem(BaseModel):
    """One form item (question or text block)."""

    title: str
    item_type: str
    required: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class FormsGetData(BaseModel):
    """Data payload for ``forms.get``.

    Nondeterministic fields (formId, responderUri, revisionId, item itemIds)
    are excluded; semantic refine DEFERRED(P6).
    """

    title: str
    description: str | None
    item_count: int
    items: list[FormsItem]


FormsGetOutput = OutputEnvelope[FormsGetData]


class FormsListResponsesInput(BaseModel):
    """Input for ``forms.list_responses``: list responses to a form (paginated)."""

    form_id: str
    page_size: int | None = Field(default=None, ge=1, description="Max responses per page")
    page_token: str | None = Field(default=None, description="Continuation token from a prior call")


class FormsAnswer(BaseModel):
    """One answer within a form response."""

    question_id: str
    text_values: list[str]


class FormsResponseRecord(BaseModel):
    """One submitted form response."""

    response_id: str
    create_time: str
    answer_count: int
    answers: list[FormsAnswer]


class FormsListResponsesData(BaseModel):
    """Data payload for ``forms.list_responses``."""

    count: int
    responses: list[FormsResponseRecord]


FormsListResponsesOutput = OutputEnvelope[FormsListResponsesData]


class FormsAddItemInput(BaseModel):
    """Input for ``forms.add_item``: add a question item via batchUpdate."""

    form_id: str
    title: str
    item_type: FormsItemType = "short_text"
    options: str | None = Field(
        default=None,
        description="Comma-separated option values (required for multiple_choice, checkbox, dropdown)",
    )
    required: bool = False
    index: int = Field(default=0, ge=0, description="Position index (0 = first)")


class FormsAddItemData(BaseModel):
    """Data payload for ``forms.add_item``."""

    form_id: str
    item_type: str
    index: int


FormsAddItemOutput = OutputEnvelope[FormsAddItemData]


class FormsUpdateInput(BaseModel):
    """Input for ``forms.update``: update form info via batchUpdate."""

    form_id: str
    title: str | None = None
    description: str | None = None


class FormsUpdateData(BaseModel):
    """Data payload for ``forms.update``."""

    form_id: str
    updated_fields: list[str]


FormsUpdateOutput = OutputEnvelope[FormsUpdateData]


# ── forms.publish ──────────────────────────────────────────────────────────────

class FormsPublishInput(BaseModel):
    """Input for ``forms.publish``: set publish state / accepting-responses via setPublishSettings."""

    form_id: str
    publish_settings: dict[str, Any] = Field(
        description=(
            "Passthrough publishSettings body: keys may include publishState "
            "(PUBLISHED|UNPUBLISHED), isAcceptingResponses (bool). "
            "An updateMask is derived automatically from the provided keys."
        )
    )


class FormsPublishData(BaseModel):
    """Data payload for ``forms.publish``."""

    form_id: str
    publish_settings: dict[str, Any]


FormsPublishOutput = OutputEnvelope[FormsPublishData]


# ── forms.get_response ─────────────────────────────────────────────────────────

class FormsGetResponseInput(BaseModel):
    """Input for ``forms.get_response``: fetch a single response by id."""

    form_id: str
    response_id: str


class FormsGetResponseData(BaseModel):
    """Data payload for ``forms.get_response``."""

    response_id: str
    create_time: str
    answer_count: int
    answers: list[FormsAnswer]


FormsGetResponseOutput = OutputEnvelope[FormsGetResponseData]


# ── forms.watches ──────────────────────────────────────────────────────────────

FormsWatchEventType = Literal[
    "EVENT_TYPE_UNSPECIFIED",
    "SCHEMA",
    "RESPONSES",
]


class FormsWatchesInput(BaseModel):
    """Input for ``forms.watches``: create, list, delete, or renew form watches.

    ``action=create`` requires an operator-provisioned Cloud Pub/Sub topic.
    ``action=delete`` and ``action=renew`` require ``watch_id``.
    """

    form_id: str = Field(description="Google Forms form ID that owns the watch")
    action: Literal["create", "list", "delete", "renew"] = Field(
        default="create",
        description="Watch operation to perform: create, list, delete, or renew",
    )
    topic_name: str | None = Field(
        default=None,
        description=(
            "Fully-qualified Cloud Pub/Sub topic name, "
            "e.g. projects/<project>/topics/<topic>"
        ),
    )
    watch_id: str | None = Field(
        default=None,
        description="Watch ID required for delete and renew actions",
    )
    event_type: FormsWatchEventType = Field(
        default="RESPONSES",
        description="Watch event type: EVENT_TYPE_UNSPECIFIED | SCHEMA | RESPONSES",
    )


class FormsWatchRecord(BaseModel):
    """One Forms watch returned by the Forms API."""

    watch_id: str = Field(description="Forms API watch ID")
    state: str = Field(default="", description="Watch lifecycle state returned by the API")
    event_type: str = Field(
        default="",
        description="Watched event type, such as RESPONSES or SCHEMA",
    )
    create_time: str = Field(default="", description="RFC3339 watch creation time")
    expire_time: str | None = Field(
        default=None,
        description="RFC3339 watch expiration time",
    )


class FormsWatchesData(BaseModel):
    """Data payload for ``forms.watches``."""

    action: str = Field(description="Watch action that was executed")
    watch_id: str | None = Field(
        default=None,
        description="Watch ID for create, delete, and renew actions",
    )
    state: str | None = Field(
        default=None,
        description="Watch state for create and renew actions",
    )
    event_type: str | None = Field(
        default=None,
        description="Watch event type for create and renew actions",
    )
    create_time: str | None = Field(
        default=None,
        description="Watch creation time for create and renew actions",
    )
    expire_time: str | None = Field(
        default=None,
        description="Watch expiration time for create and renew actions",
    )
    watches: list[FormsWatchRecord] | None = Field(
        default=None,
        description="Watches returned by list",
    )
    count: int | None = Field(default=None, description="Number of watches returned by list")
    deleted: bool | None = Field(
        default=None,
        description="True when delete completed successfully",
    )


FormsWatchesOutput = OutputEnvelope[FormsWatchesData]
