"""Core functions for the Forms service (9 ops: 5 cutover-minimum + 3 §7 coverage + 1 eventing).

Parity coverage per op:

  forms_create         — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  forms_get            — mock-read DONE; semantic refine DEFERRED(P6); sandbox-e2e DEFERRED(P6)
  forms_list_responses — mock-read DONE (+ pagination §7); sandbox-e2e DEFERRED(P6)
  forms_add_item       — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  forms_update         — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  forms_publish        — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  forms_get_response   — mock-read DONE; sandbox-e2e DEFERRED(P6)
  forms_watches        — mutation-request DONE; sandbox-e2e DEFERRED(P6)

Legacy quirks preserved:
  - forms.create uses a two-call sequence: forms().create() for title/documentTitle,
    then forms().batchUpdate(updateFormInfo) for description — the Forms API does not
    accept description in the initial create body (Forms API v1 quirk).
  - forms.add_item: scale question hardcodes low=1, high=5, lowLabel="Low",
    highLabel="High" (matches legacy gforms.py).
  - forms.list_responses: page_size/page_token forwarded when provided;
    continuation surfaced via envelope page.next_page_token. No pagination
    params = single-call legacy behaviour.
  - forms.update: dynamic updateMask built from provided fields only.
  - forms.publish: updateMask derived automatically from keys present in publish_settings.
"""
from __future__ import annotations

from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.errors import Validation
from google_kit.core.normalize import Meta, OutputEnvelope, PageInfo

from .models import (
    FormsAddItemData,
    FormsAddItemInput,
    FormsAddItemOutput,
    FormsAnswer,
    FormsCreateData,
    FormsCreateInput,
    FormsCreateOutput,
    FormsGetData,
    FormsGetInput,
    FormsGetOutput,
    FormsGetResponseData,
    FormsGetResponseInput,
    FormsGetResponseOutput,
    FormsItem,
    FormsListResponsesData,
    FormsListResponsesInput,
    FormsListResponsesOutput,
    FormsPublishData,
    FormsPublishInput,
    FormsPublishOutput,
    FormsResponseRecord,
    FormsUpdateData,
    FormsUpdateInput,
    FormsUpdateOutput,
    FormsWatchesData,
    FormsWatchesInput,
    FormsWatchesOutput,
    FormsWatchRecord,
)


def _wrap(data: Any, op: str, *, page: PageInfo | None = None) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, page=page, meta=Meta(op=op))


def _parse_item_type(item: dict[str, Any]) -> str:
    """Infer a canonical item-type string from a raw Forms API item dict.

    Matches legacy gforms.py display logic (cmd_get).
    """
    if "questionItem" in item:
        q = item["questionItem"].get("question", {})
        if "choiceQuestion" in q:
            t = q["choiceQuestion"].get("type", "RADIO")
            return {
                "RADIO": "multiple_choice",
                "CHECKBOX": "checkbox",
                "DROP_DOWN": "dropdown",
            }.get(t, t.lower())
        if "scaleQuestion" in q:
            return "scale"
        if "dateQuestion" in q:
            return "date"
        if "timeQuestion" in q:
            return "time"
        if "textQuestion" in q:
            return "paragraph" if q["textQuestion"].get("paragraph") else "short_text"
    if "questionGroupItem" in item:
        return "grid"
    return "text"


def _build_question(item_type: str, options: str | None, required: bool) -> dict[str, Any]:
    """Build the ``question`` sub-dict for a batchUpdate createItem request.

    Mirrors legacy ``_QUESTION_TYPES`` dispatch in gforms.py.
    """
    if item_type == "short_text":
        question: dict[str, Any] = {"textQuestion": {}}
    elif item_type == "paragraph":
        question = {"textQuestion": {"paragraph": True}}
    elif item_type in ("multiple_choice", "checkbox", "dropdown"):
        type_map = {
            "multiple_choice": "RADIO",
            "checkbox": "CHECKBOX",
            "dropdown": "DROP_DOWN",
        }
        opts = [{"value": o.strip()} for o in (options or "").split(",") if o.strip()]
        question = {"choiceQuestion": {"type": type_map[item_type], "options": opts}}
    elif item_type == "scale":
        question = {
            "scaleQuestion": {"low": 1, "high": 5, "lowLabel": "Low", "highLabel": "High"}
        }
    elif item_type == "date":
        question = {"dateQuestion": {}}
    elif item_type == "time":
        question = {"timeQuestion": {}}
    else:
        question = {"textQuestion": {}}

    question["required"] = required
    return question


def forms_create(
    inp: FormsCreateInput,
    *,
    service: Any = None,
) -> FormsCreateOutput:
    """Create a new Google Form (title only); set description via separate batchUpdate.

    The Forms API v1 does not accept description in the initial create body.
    This function replicates the legacy two-call sequence from gforms.py:
      1. forms().create(body={"info": {"title": ...}}) — creates the form.
      2. forms().batchUpdate(updateFormInfo, updateMask="description") — sets description.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    create_body: dict[str, Any] = {"info": {"title": inp.title}}
    if inp.document_title:
        create_body["info"]["documentTitle"] = inp.document_title

    created = execute_api_call(
        lambda: service.forms().create(body=create_body).execute(),
        op="forms.create",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    created = created or {}
    form_id: str = created.get("formId", "")
    title: str = (created.get("info") or {}).get("title", inp.title)
    responder_uri: str = created.get(
        "responderUri",
        f"https://docs.google.com/forms/d/{form_id}/viewform",
    )

    if inp.description:
        description_body: dict[str, Any] = {
            "requests": [{
                "updateFormInfo": {
                    "info": {"description": inp.description},
                    "updateMask": "description",
                }
            }]
        }
        execute_api_call(
            lambda: service.forms().batchUpdate(
                formId=form_id, body=description_body
            ).execute(),
            op="forms.create.set_description",
            posture="write",
            normalized_request={"form_id": form_id},
            target_ids=[form_id],
        )

    return _wrap(
        FormsCreateData(form_id=form_id, title=title, responder_uri=responder_uri),
        "forms.create",
    )


def forms_get(
    inp: FormsGetInput,
    *,
    service: Any = None,
) -> FormsGetOutput:
    """Retrieve form metadata and items (nondeterministic fields excluded).

    Excluded nondeterministic fields: formId, responderUri, revisionId, item itemIds.
    Semantic refine DEFERRED(P6) — full round-trip fidelity requires a sandbox.

    Parity: mock-read DONE; semantic refine DEFERRED(P6); sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.forms().get(formId=inp.form_id).execute(),
        op="forms.get",
        posture="read",
    )
    raw = raw or {}
    info = raw.get("info") or {}
    raw_items = raw.get("items") or []

    items = [
        FormsItem(
            title=it.get("title", ""),
            item_type=_parse_item_type(it),
            required=(
                (it.get("questionItem") or {})
                .get("question", {})
                .get("required", False)
            ),
        )
        for it in raw_items
    ]

    return _wrap(
        FormsGetData(
            title=info.get("title", ""),
            description=info.get("description"),
            item_count=len(items),
            items=items,
        ),
        "forms.get",
    )


def forms_list_responses(
    inp: FormsListResponsesInput,
    *,
    service: Any = None,
) -> FormsListResponsesOutput:
    """List responses for a form.

    Forwards page_size/page_token to the API when provided; surfaces
    continuation via the envelope ``page.next_page_token``. No pagination
    params = single-call legacy behaviour.

    Parity: mock-read DONE (+ pagination §7); sandbox-e2e live-PASS 2026-06-17
    """
    list_kwargs: dict[str, Any] = {"formId": inp.form_id}
    if inp.page_size is not None:
        list_kwargs["pageSize"] = inp.page_size
    if inp.page_token is not None:
        list_kwargs["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda: service.forms().responses().list(**list_kwargs).execute(),
        op="forms.list_responses",
        posture="read",
    )
    raw = raw or {}
    raw_responses = raw.get("responses", [])
    next_page_token: str | None = raw.get("nextPageToken")

    records = []
    for r in raw_responses:
        raw_answers = r.get("answers") or {}
        answers = [
            FormsAnswer(
                question_id=qid,
                text_values=[
                    a.get("value", "")
                    for a in ans.get("textAnswers", {}).get("answers", [])
                ],
            )
            for qid, ans in raw_answers.items()
        ]
        records.append(
            FormsResponseRecord(
                response_id=r.get("responseId", ""),
                create_time=r.get("createTime", ""),
                answer_count=len(answers),
                answers=answers,
            )
        )

    return _wrap(
        FormsListResponsesData(
            count=len(records),
            responses=records,
        ),
        "forms.list_responses",
        page=PageInfo(next_page_token=next_page_token),
    )


def forms_add_item(
    inp: FormsAddItemInput,
    *,
    service: Any = None,
) -> FormsAddItemOutput:
    """Add a question item to a form via batchUpdate (createItem).

    Supported item_types: short_text, paragraph, multiple_choice, checkbox,
    dropdown, scale (1–5 hardcoded), date, time — matches legacy gforms.py.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    question = _build_question(inp.item_type, inp.options, inp.required)
    request_body: dict[str, Any] = {
        "requests": [{
            "createItem": {
                "item": {
                    "title": inp.title,
                    "questionItem": {"question": question},
                },
                "location": {"index": inp.index},
            }
        }]
    }

    execute_api_call(
        lambda: service.forms().batchUpdate(
            formId=inp.form_id, body=request_body
        ).execute(),
        op="forms.add_item",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.form_id],
    )

    return _wrap(
        FormsAddItemData(form_id=inp.form_id, item_type=inp.item_type, index=inp.index),
        "forms.add_item",
    )


def forms_update(
    inp: FormsUpdateInput,
    *,
    service: Any = None,
) -> FormsUpdateOutput:
    """Update form info (title and/or description) via batchUpdate (updateFormInfo).

    Builds a dynamic updateMask from the provided fields only — matches legacy
    gforms.py cmd_update behaviour.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    update_mask_parts: list[str] = []
    info: dict[str, Any] = {}

    if inp.title is not None:
        update_mask_parts.append("title")
        info["title"] = inp.title
    if inp.description is not None:
        update_mask_parts.append("description")
        info["description"] = inp.description

    if not update_mask_parts:
        raise Validation(
            "forms.update: at least one of title or description must be provided",
            op="forms.update",
        )

    request_body: dict[str, Any] = {
        "requests": [{
            "updateFormInfo": {
                "info": info,
                "updateMask": ",".join(update_mask_parts),
            }
        }]
    }

    execute_api_call(
        lambda: service.forms().batchUpdate(
            formId=inp.form_id, body=request_body
        ).execute(),
        op="forms.update",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.form_id],
    )

    return _wrap(
        FormsUpdateData(form_id=inp.form_id, updated_fields=update_mask_parts),
        "forms.update",
    )


def forms_publish(
    inp: FormsPublishInput,
    *,
    service: Any = None,
) -> FormsPublishOutput:
    """Set publish state / accepting-responses via forms.setPublishSettings.

    The updateMask is derived automatically from the keys present in
    publish_settings, so the caller only needs to supply the fields they
    want to change.

    Parity: mutation-request DONE; sandbox-e2e live-PASS 2026-06-17
    """
    update_mask = ",".join(inp.publish_settings.keys())
    body: dict[str, Any] = {
        "publishSettings": inp.publish_settings,
        "updateMask": update_mask,
    }

    execute_api_call(
        lambda: service.forms().setPublishSettings(
            formId=inp.form_id, body=body
        ).execute(),
        op="forms.publish",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.form_id],
    )

    return _wrap(
        FormsPublishData(form_id=inp.form_id, publish_settings=inp.publish_settings),
        "forms.publish",
    )


def forms_get_response(
    inp: FormsGetResponseInput,
    *,
    service: Any = None,
) -> FormsGetResponseOutput:
    """Fetch a single form response by id.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.forms().responses().get(
            formId=inp.form_id, responseId=inp.response_id
        ).execute(),
        op="forms.get_response",
        posture="read",
    )
    raw = raw or {}
    raw_answers = raw.get("answers") or {}
    answers = [
        FormsAnswer(
            question_id=qid,
            text_values=[
                a.get("value", "")
                for a in ans.get("textAnswers", {}).get("answers", [])
            ],
        )
        for qid, ans in raw_answers.items()
    ]

    return _wrap(
        FormsGetResponseData(
            response_id=raw.get("responseId", ""),
            create_time=raw.get("createTime", ""),
            answer_count=len(answers),
            answers=answers,
        ),
        "forms.get_response",
    )


def forms_watches(
    inp: FormsWatchesInput,
    *,
    service: Any = None,
) -> FormsWatchesOutput:
    """Create, list, delete, or renew watches for a form.

    Create requires an operator-provisioned Cloud Pub/Sub topic; delete and renew
    require a watch id. Delete returns no body from the API and is normalized to
    ``deleted=True``.

    Parity: mutation-request DONE (create/delete/renew); mock-read DONE (list);
    sandbox-e2e DEFERRED(P6)
    """
    if inp.action == "list":
        raw = execute_api_call(
            lambda: service.forms().watches().list(formId=inp.form_id).execute(),
            op="forms.watches",
            posture="read",
        )
        raw = raw or {}
        watches = [
            FormsWatchRecord(
                watch_id=w.get("id", ""),
                state=w.get("state", ""),
                event_type=w.get("eventType", ""),
                create_time=w.get("createTime", ""),
                expire_time=w.get("expireTime"),
            )
            for w in raw.get("watches", [])
        ]
        return _wrap(
            FormsWatchesData(action="list", watches=watches, count=len(watches)),
            "forms.watches",
        )

    if inp.action == "delete":
        if not inp.watch_id:
            raise Validation("forms.watches: watch_id is required for delete", op="forms.watches")
        execute_api_call(
            lambda: service.forms().watches().delete(
                formId=inp.form_id, watchId=inp.watch_id
            ).execute(),
            op="forms.watches",
            posture="destructive",
            normalized_request=inp.model_dump(),
            target_ids=[inp.form_id],
        )
        return _wrap(
            FormsWatchesData(action="delete", watch_id=inp.watch_id, deleted=True),
            "forms.watches",
        )

    if inp.action == "renew":
        if not inp.watch_id:
            raise Validation("forms.watches: watch_id is required for renew", op="forms.watches")
        raw = execute_api_call(
            lambda: service.forms().watches().renew(
                formId=inp.form_id, watchId=inp.watch_id
            ).execute(),
            op="forms.watches",
            posture="write",
            normalized_request=inp.model_dump(),
            target_ids=[inp.form_id],
        )
        raw = raw or {}
        return _wrap(
            FormsWatchesData(
                action="renew",
                watch_id=raw.get("id", inp.watch_id),
                state=raw.get("state", ""),
                event_type=raw.get("eventType", ""),
                create_time=raw.get("createTime", ""),
                expire_time=raw.get("expireTime"),
            ),
            "forms.watches",
        )

    if not inp.topic_name:
        raise Validation("forms.watches: topic_name is required for create", op="forms.watches")

    body: dict[str, Any] = {
        "watch": {
            "eventType": inp.event_type,
            "target": {
                "topic": {
                    "topicName": inp.topic_name,
                }
            },
        }
    }

    raw = execute_api_call(
        lambda: service.forms().watches().create(formId=inp.form_id, body=body).execute(),
        op="forms.watches",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.form_id],
    )
    raw = raw or {}

    return _wrap(
        FormsWatchesData(
            action="create",
            watch_id=raw.get("id", ""),
            state=raw.get("state", ""),
            event_type=raw.get("eventType", ""),
            create_time=raw.get("createTime", ""),
            expire_time=raw.get("expireTime"),
        ),
        "forms.watches",
    )
