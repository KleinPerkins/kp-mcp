"""Forms service — registers 8 ops (5 cutover-minimum + 2 §7 coverage + 1 eventing)."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    forms_add_item,
    forms_create,
    forms_get,
    forms_get_response,
    forms_list_responses,
    forms_publish,
    forms_update,
    forms_watches,
)
from .models import (
    FormsAddItemInput,
    FormsAddItemOutput,
    FormsCreateInput,
    FormsCreateOutput,
    FormsGetInput,
    FormsGetOutput,
    FormsGetResponseInput,
    FormsGetResponseOutput,
    FormsListResponsesInput,
    FormsListResponsesOutput,
    FormsPublishInput,
    FormsPublishOutput,
    FormsUpdateInput,
    FormsUpdateOutput,
    FormsWatchesInput,
    FormsWatchesOutput,
)

_FORMS_BODY_SCOPE = "https://www.googleapis.com/auth/forms.body"
_FORMS_BODY_READONLY_SCOPE = "https://www.googleapis.com/auth/forms.body.readonly"
_FORMS_RESPONSES_SCOPE = "https://www.googleapis.com/auth/forms.responses.readonly"

#: Per-service F5 write gate (off by default). Satisfied by the
#: ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. See core/flags.py.
_FORMS_WRITE_FLAG = "GOOGLE_KIT_ENABLE_FORMS_WRITE"

register(OpSpec(
    name="forms.create",
    fn=forms_create,
    input_model=FormsCreateInput,
    output_model=FormsCreateOutput,
    posture="write",
    scopes=[_FORMS_BODY_SCOPE],
    perf={
        "api": "Forms v1",
        "method": "forms.create + forms.batchUpdate",
        "quota": "300 req/min",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a feedback form with description",
        "input": {"title": "Feedback Form", "description": "Share your thoughts"},
        "cli": "google-kit forms create 'Feedback Form' --description 'Share your thoughts'",
    }],
    keywords=["new"],
    flag=_FORMS_WRITE_FLAG,
))

register(OpSpec(
    name="forms.get",
    fn=forms_get,
    input_model=FormsGetInput,
    output_model=FormsGetOutput,
    posture="read",
    scopes=[_FORMS_BODY_READONLY_SCOPE],
    perf={"api": "Forms v1", "method": "forms.get", "quota": "300 req/min"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get form metadata and items",
        "input": {"form_id": "<form-id>"},
        "cli": "google-kit forms get <form-id>",
    }],
))

register(OpSpec(
    name="forms.list_responses",
    fn=forms_list_responses,
    input_model=FormsListResponsesInput,
    output_model=FormsListResponsesOutput,
    posture="read",
    scopes=[_FORMS_RESPONSES_SCOPE],
    perf={"api": "Forms v1", "method": "forms.responses.list", "quota": "300 req/min"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List all responses for a form",
        "input": {"form_id": "<form-id>"},
        "cli": "google-kit forms list-responses <form-id>",
    }],
    aliases=["get survey responses"],
))

register(OpSpec(
    name="forms.add_item",
    fn=forms_add_item,
    input_model=FormsAddItemInput,
    output_model=FormsAddItemOutput,
    posture="write",
    scopes=[_FORMS_BODY_SCOPE],
    perf={"api": "Forms v1", "method": "forms.batchUpdate (createItem)", "quota": "300 req/min"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Add a scale (1–5) question",
        "input": {
            "form_id": "<form-id>",
            "title": "Rate your experience",
            "item_type": "scale",
        },
        "cli": "google-kit forms add-item <form-id> 'Rate your experience' --type scale",
    }],
    keywords=["question", "field"],
    flag=_FORMS_WRITE_FLAG,
))

register(OpSpec(
    name="forms.update",
    fn=forms_update,
    input_model=FormsUpdateInput,
    output_model=FormsUpdateOutput,
    posture="write",
    scopes=[_FORMS_BODY_SCOPE],
    perf={
        "api": "Forms v1",
        "method": "forms.batchUpdate (updateFormInfo)",
        "quota": "300 req/min",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Update form title and description",
        "input": {
            "form_id": "<form-id>",
            "title": "Updated Title",
            "description": "New description",
        },
        "cli": "google-kit forms update <form-id> --title 'Updated Title'",
    }],
    flag=_FORMS_WRITE_FLAG,
))

register(OpSpec(
    name="forms.publish",
    fn=forms_publish,
    input_model=FormsPublishInput,
    output_model=FormsPublishOutput,
    posture="write",
    scopes=[_FORMS_BODY_SCOPE],
    perf={
        "api": "Forms v1",
        "method": "forms.setPublishSettings",
        "quota": "300 req/min",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Publish a form and enable response collection",
        "input": {
            "form_id": "<form-id>",
            "publish_settings": {"publishState": "PUBLISHED", "isAcceptingResponses": True},
        },
        "cli": "google-kit forms publish <form-id> --publish-settings '{\"publishState\": \"PUBLISHED\"}'",
    }],
    flag=_FORMS_WRITE_FLAG,
))

register(OpSpec(
    name="forms.get_response",
    fn=forms_get_response,
    input_model=FormsGetResponseInput,
    output_model=FormsGetResponseOutput,
    posture="read",
    scopes=[_FORMS_RESPONSES_SCOPE],
    perf={"api": "Forms v1", "method": "forms.responses.get", "quota": "300 req/min"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Fetch a single form response",
        "input": {"form_id": "<form-id>", "response_id": "<response-id>"},
        "cli": "google-kit forms get-response <form-id> <response-id>",
    }],
))

register(OpSpec(
    name="forms.watches",
    fn=forms_watches,
    input_model=FormsWatchesInput,
    output_model=FormsWatchesOutput,
    posture="write",
    plane="eventing",
    capability="eventing.watch",
    flag=_FORMS_WRITE_FLAG,
    scopes=[_FORMS_BODY_READONLY_SCOPE, _FORMS_RESPONSES_SCOPE],
    perf={
        "api": "Forms v1",
        "method": "forms.watches.create|list|delete|renew",
        "quota": "300 req/min",
        "note": (
            "Create requires operator-provisioned Cloud Pub/Sub topic; "
            "watches expire and must be renewed."
        ),
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[
        {
            "description": "Watch a form for new responses via Cloud Pub/Sub",
            "input": {
                "form_id": "<form-id>",
                "action": "create",
                "topic_name": "projects/<project>/topics/<topic>",
                "event_type": "RESPONSES",
            },
            "cli": (
                "google-kit forms watches <form-id> "
                "projects/<project>/topics/<topic> --action create"
            ),
            "notes": (
                "Requires Pub/Sub topic provisioning and publish permissions "
                "for the Forms service."
            ),
        },
        {
            "description": "List watches for a form",
            "input": {"form_id": "<form-id>", "action": "list"},
            "cli": "google-kit forms watches <form-id> --action list",
        },
        {
            "description": "Delete a form watch",
            "input": {
                "form_id": "<form-id>",
                "action": "delete",
                "watch_id": "<watch-id>",
            },
            "cli": (
                "google-kit forms watches <form-id> "
                "--action delete --watch-id <watch-id>"
            ),
        },
        {
            "description": "Renew a form watch before it expires",
            "input": {
                "form_id": "<form-id>",
                "action": "renew",
                "watch_id": "<watch-id>",
            },
            "cli": (
                "google-kit forms watches <form-id> "
                "--action renew --watch-id <watch-id>"
            ),
        },
    ],
))
