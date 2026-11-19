"""Core functions for the Gmail service (cutover-minimum: 5 read ops + 2 E1 ops + 5 write ops).

Parity coverage per op:

  gmail_list          — mock-read DONE; sandbox-e2e DEFERRED(P6)
  gmail_get           — mock-read DONE; sandbox-e2e DEFERRED(P6)
  gmail_search        — mock-read DONE; sandbox-e2e DEFERRED(P6)
  gmail_labels        — mock-read DONE; sandbox-e2e DEFERRED(P6)
  gmail_profile       — mock-read DONE; sandbox-e2e DEFERRED(P6)
  gmail_history       — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
  gmail_attachments   — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
  gmail_draft         — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  gmail_send          — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  gmail_modify        — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  gmail_manage_labels — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  gmail_watch         — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)

Legacy quirks preserved:
  - Body decoding: text/plain preferred; text/html stripped of tags as fallback;
    multipart recursed depth-first.  Matches _decode_body in legacy gmail.py.
  - Body truncated at 500 chars (body[:500] + "...") matching legacy
    _format_thread_markdown max_body_chars=500.
  - emailAddress from getProfile is NEVER emitted to logs or output; replaced
    with the literal string '[REDACTED]' in the OutputEnvelope data.
  - messages.list returns id + threadId only (no snippet); the API does not
    return snippets in list responses without per-message get calls.
"""
from __future__ import annotations

import base64
import re
from email.mime.text import MIMEText
from typing import Any

from google_kit.core.batch import chunk_requests
from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope, PageInfo

from .models import (
    GmailAttachmentsData,
    GmailAttachmentsInput,
    GmailAttachmentsOutput,
    GmailBatchModifyData,
    GmailBatchModifyInput,
    GmailBatchModifyOutput,
    GmailDraftData,
    GmailDraftInput,
    GmailDraftOutput,
    GmailGetData,
    GmailGetInput,
    GmailGetOutput,
    GmailHistoryData,
    GmailHistoryInput,
    GmailHistoryMessageRef,
    GmailHistoryOutput,
    GmailHistoryRecord,
    GmailLabelItem,
    GmailLabelsData,
    GmailLabelsInput,
    GmailLabelsOutput,
    GmailListData,
    GmailListInput,
    GmailListOutput,
    GmailManageLabelData,
    GmailManageLabelsInput,
    GmailManageLabelOutput,
    GmailMessageRef,
    GmailModifyData,
    GmailModifyInput,
    GmailModifyOutput,
    GmailProfileData,
    GmailProfileInput,
    GmailProfileOutput,
    GmailSearchData,
    GmailSearchInput,
    GmailSearchOutput,
    GmailSendData,
    GmailSendInput,
    GmailSendOutput,
    GmailThreadGetData,
    GmailThreadGetInput,
    GmailThreadGetOutput,
    GmailThreadMessage,
    GmailThreadRef,
    GmailThreadsData,
    GmailThreadsInput,
    GmailThreadsOutput,
    GmailWatchData,
    GmailWatchInput,
    GmailWatchOutput,
)

_BODY_MAX_CHARS = 500
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_REDACTED = "[REDACTED]"

#: Gmail's users.messages.batchModify accepts at most 1000 message ids per
#: request (https://developers.google.com/gmail/api/reference/rest/v1/users.messages/batchModify).
#: Requests above this are split into sequential ≤1000-id API calls so callers
#: can pass an unbounded id list without tripping a server-side 400.
_BATCH_MODIFY_MAX_IDS = 1000


def _strip_html(html: str) -> str:
    html = html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    html = html.replace("</p>", "\n").replace("</div>", "\n")
    return _HTML_TAG_RE.sub("", html).strip()


def _decode_body(payload: dict[str, Any]) -> str:
    """Extract plain-text body from a message payload, handling multipart.

    Matches legacy ``_decode_body`` in ``gmail.py``:
      - text/plain: decode base64 data directly.
      - text/html (no parts): decode + strip HTML tags.
      - multipart: recurse depth-first through parts.
    """
    mime = payload.get("mimeType", "")

    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    if mime == "text/html" and not payload.get("parts"):
        data = payload.get("body", {}).get("data", "")
        if data:
            raw = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return _strip_html(raw)

    for part in payload.get("parts", []):
        text = _decode_body(part)
        if text:
            return text

    return ""


def _get_header(headers: list[dict[str, Any]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _wrap(data: Any, op: str, *, page: PageInfo | None = None) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, page=page, meta=Meta(op=op))


def gmail_list(
    inp: GmailListInput,
    *,
    service: Any = None,
) -> GmailListOutput:
    """List recent Gmail messages (ids + thread_ids).

    Calls users.messages.list; returns message id + threadId pairs.
    Snippets require per-message get calls and are deferred to P6.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    kwargs: dict[str, Any] = {
        "userId": "me",
        "maxResults": inp.max_results,
    }
    if inp.q:
        kwargs["q"] = inp.q
    if inp.label_ids:
        kwargs["labelIds"] = inp.label_ids

    raw = execute_api_call(
        lambda: service.users().messages().list(**kwargs).execute(),
        op="gmail.list",
        posture="read",
    )
    items = (raw or {}).get("messages", [])
    messages = [
        GmailMessageRef(id=m.get("id", ""), thread_id=m.get("threadId", ""))
        for m in items
    ]
    return _wrap(GmailListData(count=len(messages), messages=messages), "gmail.list")


def gmail_get(
    inp: GmailGetInput,
    *,
    service: Any = None,
) -> GmailGetOutput:
    """Get a full Gmail message by ID; decodes body and truncates to 500 chars.

    Body decoding order: text/plain > text/html (stripped) > multipart recursive.
    Matches legacy _decode_body / _format_thread_markdown behavior.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.users().messages().get(
            userId="me", id=inp.message_id, format="full"
        ).execute(),
        op="gmail.get",
        posture="read",
    )
    msg = raw or {}
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])

    body = _decode_body(payload)
    if len(body) > _BODY_MAX_CHARS:
        body = body[:_BODY_MAX_CHARS] + "..."

    data = GmailGetData(
        id=msg.get("id", inp.message_id),
        thread_id=msg.get("threadId", ""),
        snippet=msg.get("snippet", ""),
        subject=_get_header(headers, "Subject"),
        from_=_get_header(headers, "From"),
        date=_get_header(headers, "Date"),
        body=body,
        label_ids=msg.get("labelIds", []),
    )
    return _wrap(data, "gmail.get")


def gmail_search(
    inp: GmailSearchInput,
    *,
    service: Any = None,
) -> GmailSearchOutput:
    """Search Gmail messages with Gmail query syntax.

    Calls users.messages.list with q param; returns id + thread_id pairs.
    Matches legacy cmd_search behaviour (id + snippet recorded per thread).

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.users().messages().list(
            userId="me",
            q=inp.q,
            maxResults=inp.max_results,
        ).execute(),
        op="gmail.search",
        posture="read",
    )
    items = (raw or {}).get("messages", [])
    messages = [
        GmailMessageRef(id=m.get("id", ""), thread_id=m.get("threadId", ""))
        for m in items
    ]
    return _wrap(
        GmailSearchData(query=inp.q, count=len(messages), messages=messages),
        "gmail.search",
    )


def gmail_labels(
    inp: GmailLabelsInput,
    *,
    service: Any = None,
) -> GmailLabelsOutput:
    """List all Gmail labels (system and user-defined).

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.users().labels().list(userId="me").execute(),
        op="gmail.labels",
        posture="read",
    )
    items = (raw or {}).get("labels", [])
    labels = [
        GmailLabelItem(
            id=lbl.get("id", ""),
            name=lbl.get("name", ""),
            label_type=lbl.get("type", "user"),
        )
        for lbl in items
    ]
    return _wrap(GmailLabelsData(count=len(labels), labels=labels), "gmail.labels")


def gmail_profile(
    inp: GmailProfileInput,
    *,
    service: Any = None,
) -> GmailProfileOutput:
    """Get the authenticated user's Gmail profile (emailAddress redacted).

    emailAddress is replaced with '[REDACTED]' in all output — PII must not
    be emitted to logs, audit records, or the OutputEnvelope data payload.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.users().getProfile(userId="me").execute(),
        op="gmail.profile",
        posture="read",
    )
    profile = raw or {}
    data = GmailProfileData(
        email_address=_REDACTED,
        messages_total=profile.get("messagesTotal", 0),
        threads_total=profile.get("threadsTotal", 0),
    )
    return _wrap(data, "gmail.profile")


def gmail_history(
    inp: GmailHistoryInput,
    *,
    service: Any = None,
) -> GmailHistoryOutput:
    """List mailbox history events since a given history ID.

    Parity: mock-read DONE; sandbox-e2e live-PASS 2026-06-17
    """
    raw = execute_api_call(
        lambda: service.users().history().list(
            userId="me",
            startHistoryId=inp.start_history_id,
            historyTypes=inp.history_types or None,
            labelId=inp.label_id or None,
            maxResults=inp.max_results,
            pageToken=inp.page_token or None,
        ).execute(),
        op="gmail.history",
        posture="read",
    )
    payload = raw or {}
    records: list[GmailHistoryRecord] = []
    for entry in payload.get("history", []):
        msgs = [
            GmailHistoryMessageRef(id=m.get("id", ""), thread_id=m.get("threadId", ""))
            for m in entry.get("messages", [])
        ]
        extra = {k: v for k, v in entry.items() if k not in ("id", "messages")}
        records.append(GmailHistoryRecord(id=str(entry.get("id", "")), messages=msgs, extra=extra))
    data = GmailHistoryData(
        history=records,
        history_id=payload.get("historyId"),
    )
    return _wrap(
        data,
        "gmail.history",
        page=PageInfo(next_page_token=payload.get("nextPageToken")),
    )


def gmail_attachments(
    inp: GmailAttachmentsInput,
    *,
    service: Any = None,
) -> GmailAttachmentsOutput:
    """Get a Gmail message attachment by message ID and attachment ID.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    raw = execute_api_call(
        lambda: service.users().messages().attachments().get(
            userId="me",
            messageId=inp.message_id,
            id=inp.attachment_id,
        ).execute(),
        op="gmail.attachments",
        posture="read",
    )
    payload = raw or {}
    data = GmailAttachmentsData(
        attachment_id=inp.attachment_id,
        size=payload.get("size", 0),
        data_b64=payload.get("data", ""),
    )
    return _wrap(data, "gmail.attachments")


def gmail_threads(
    inp: GmailThreadsInput,
    *,
    service: Any = None,
) -> GmailThreadsOutput:
    """List (or search) Gmail threads.

    Calls users.threads.list; returns thread id + snippet + history_id refs.
    Providing ``q`` makes this op a thread-level search (Gmail query syntax),
    so a single op covers both threads.list and threads.list(query).
    Pagination is surfaced via ``page.next_page_token``.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    kwargs: dict[str, Any] = {
        "userId": "me",
        "maxResults": inp.max_results,
    }
    if inp.q:
        kwargs["q"] = inp.q
    if inp.label_ids:
        kwargs["labelIds"] = inp.label_ids
    if inp.page_token:
        kwargs["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda: service.users().threads().list(**kwargs).execute(),
        op="gmail.threads",
        posture="read",
    )
    payload = raw or {}
    items = payload.get("threads", [])
    threads = [
        GmailThreadRef(
            id=t.get("id", ""),
            snippet=t.get("snippet", ""),
            history_id=str(t.get("historyId", "")),
        )
        for t in items
    ]
    return OutputEnvelope(
        data=GmailThreadsData(count=len(threads), threads=threads),
        page=PageInfo(next_page_token=payload.get("nextPageToken")),
        meta=Meta(op="gmail.threads"),
    )


def gmail_thread_get(
    inp: GmailThreadGetInput,
    *,
    service: Any = None,
) -> GmailThreadGetOutput:
    """Get a full Gmail thread (with its messages) by thread ID.

    Calls users.threads.get with format="full".  Each message body is decoded
    (text/plain > text/html stripped > multipart recursive) and truncated at
    500 chars to match gmail.get's BD-8 behavior.  Missing/sparse fields are
    tolerated and default to empty.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    raw = execute_api_call(
        lambda: service.users().threads().get(
            userId="me", id=inp.thread_id, format="full"
        ).execute(),
        op="gmail.thread_get",
        posture="read",
    )
    thread = raw or {}
    messages: list[GmailThreadMessage] = []
    for msg in thread.get("messages", []):
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        body = _decode_body(payload)
        if len(body) > _BODY_MAX_CHARS:
            body = body[:_BODY_MAX_CHARS] + "..."
        messages.append(
            GmailThreadMessage(
                id=msg.get("id", ""),
                thread_id=msg.get("threadId", thread.get("id", inp.thread_id)),
                snippet=msg.get("snippet", ""),
                subject=_get_header(headers, "Subject"),
                from_=_get_header(headers, "From"),
                date=_get_header(headers, "Date"),
                body=body,
                label_ids=msg.get("labelIds", []),
            )
        )
    data = GmailThreadGetData(
        id=thread.get("id", inp.thread_id),
        history_id=str(thread.get("historyId", "")),
        snippet=thread.get("snippet", ""),
        message_count=len(messages),
        messages=messages,
    )
    return _wrap(data, "gmail.thread_get")


# ---------------------------------------------------------------------------
# Write ops (F5-gated: GOOGLE_KIT_ENABLE_GMAIL_WRITE)
# ---------------------------------------------------------------------------


def _build_raw_message(to: str, subject: str, body_text: str, cc: str | None = None) -> str:
    """Build a deterministic RFC822 message and return base64url-encoded raw string.

    Uses email.mime.text.MIMEText with explicit To/Subject/Cc headers.  No
    Date or Message-ID headers are added so the encoding is reproducible.
    """
    msg = MIMEText(body_text, "plain", "utf-8")
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def gmail_draft(
    inp: GmailDraftInput,
    *,
    service: Any = None,
) -> GmailDraftOutput:
    """Create a Gmail draft message.

    Builds a deterministic RFC822 MIME message and calls users.drafts.create.
    Gate: GOOGLE_KIT_ENABLE_GMAIL_WRITE must be set to 1 (ADR F5).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    raw = _build_raw_message(inp.to, inp.subject, inp.body_text, inp.cc)
    resp = execute_api_call(
        lambda: service.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute(),
        op="gmail.draft",
        posture="write",
        # body_text is message content, not a mutation target — keep it out of the
        # audit record (recipient/subject are still recorded, redacted as PII).
        normalized_request=inp.model_dump(exclude={"body_text"}),
    )
    resp = resp or {}
    data = GmailDraftData(
        draft_id=resp.get("id", ""),
        message_id=(resp.get("message") or {}).get("id", ""),
    )
    return _wrap(data, "gmail.draft")


def gmail_send(
    inp: GmailSendInput,
    *,
    service: Any = None,
) -> GmailSendOutput:
    """Send a Gmail message immediately.

    Builds a deterministic RFC822 MIME message and calls users.messages.send.
    Gate: GOOGLE_KIT_ENABLE_GMAIL_WRITE must be set to 1 (ADR F5).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    raw = _build_raw_message(inp.to, inp.subject, inp.body_text, inp.cc)
    resp = execute_api_call(
        lambda: service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute(),
        op="gmail.send",
        posture="write",
        normalized_request=inp.model_dump(exclude={"body_text"}),
    )
    resp = resp or {}
    data = GmailSendData(
        message_id=resp.get("id", ""),
        thread_id=resp.get("threadId", ""),
        label_ids=resp.get("labelIds", []),
    )
    return _wrap(data, "gmail.send")


def gmail_modify(
    inp: GmailModifyInput,
    *,
    service: Any = None,
) -> GmailModifyOutput:
    """Modify labels on a Gmail message (add and/or remove).

    Calls users.messages.modify with addLabelIds / removeLabelIds.
    Gate: GOOGLE_KIT_ENABLE_GMAIL_WRITE must be set to 1 (ADR F5).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    resp = execute_api_call(
        lambda: service.users().messages().modify(
            userId="me",
            id=inp.message_id,
            body={
                "addLabelIds": inp.add_label_ids,
                "removeLabelIds": inp.remove_label_ids,
            },
        ).execute(),
        op="gmail.modify",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    resp = resp or {}
    data = GmailModifyData(
        message_id=resp.get("id", inp.message_id),
        label_ids=resp.get("labelIds", []),
    )
    return _wrap(data, "gmail.modify")


def gmail_batch_modify(
    inp: GmailBatchModifyInput,
    *,
    service: Any = None,
) -> GmailBatchModifyOutput:
    """Add/remove labels across multiple Gmail messages.

    Calls users.messages.batchModify with body {ids, addLabelIds, removeLabelIds}.
    The id list is split into sequential ≤``_BATCH_MODIFY_MAX_IDS`` (1000) chunks
    so an arbitrarily large id list never trips Gmail's per-request id cap; each
    chunk is one API call and one audit record scoped to that chunk's ids. The
    API returns HTTP 204 with an empty body on success, so the envelope is built
    from the validated request inputs (modified count + ids + labels).
    Input validation (non-empty ids; at least one label list) is enforced by
    GmailBatchModifyInput.
    Gate: GOOGLE_KIT_ENABLE_GMAIL_WRITE must be set to 1 (ADR F5).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    for id_chunk in chunk_requests(list(inp.ids), _BATCH_MODIFY_MAX_IDS):
        execute_api_call(
            lambda c=id_chunk: service.users().messages().batchModify(
                userId="me",
                body={
                    "ids": c,
                    "addLabelIds": inp.add_label_ids,
                    "removeLabelIds": inp.remove_label_ids,
                },
            ).execute(),
            op="gmail.batch_modify",
            posture="write",
            normalized_request={
                "ids": id_chunk,
                "add_label_ids": inp.add_label_ids,
                "remove_label_ids": inp.remove_label_ids,
            },
            target_ids=id_chunk,
        )
    data = GmailBatchModifyData(
        modified_count=len(inp.ids),
        ids=inp.ids,
        add_label_ids=inp.add_label_ids,
        remove_label_ids=inp.remove_label_ids,
    )
    return _wrap(data, "gmail.batch_modify")


def gmail_manage_labels(
    inp: GmailManageLabelsInput,
    *,
    service: Any = None,
) -> GmailManageLabelOutput:
    """Create a new Gmail label.

    Calls users.labels.create.
    Gate: GOOGLE_KIT_ENABLE_GMAIL_WRITE must be set to 1 (ADR F5).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    resp = execute_api_call(
        lambda: service.users().labels().create(
            userId="me",
            body={
                "name": inp.name,
                "labelListVisibility": inp.label_list_visibility,
                "messageListVisibility": inp.message_list_visibility,
            },
        ).execute(),
        op="gmail.manage_labels",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    resp = resp or {}
    data = GmailManageLabelData(
        label_id=resp.get("id", ""),
        name=resp.get("name", inp.name),
    )
    return _wrap(data, "gmail.manage_labels")


def gmail_watch(
    inp: GmailWatchInput,
    *,
    service: Any = None,
) -> GmailWatchOutput:
    """Start Gmail push notifications via a Cloud Pub/Sub topic.

    Calls users.watch.  Requires an operator-provisioned Cloud Pub/Sub topic
    with the Gmail service account granted publish access.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    body: dict[str, Any] = {"topicName": inp.topic_name}
    if inp.label_ids:
        body["labelIds"] = inp.label_ids
    if inp.label_filter_behavior:
        body["labelFilterBehavior"] = inp.label_filter_behavior

    resp = execute_api_call(
        lambda: service.users().watch(
            userId="me", body=body
        ).execute(),
        op="gmail.watch",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    resp = resp or {}
    data = GmailWatchData(
        history_id=str(resp.get("historyId", "")),
        expiration=str(resp.get("expiration", "")),
    )
    return _wrap(data, "gmail.watch")
