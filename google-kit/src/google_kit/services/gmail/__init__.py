"""Gmail service — 9 read ops (5 cutover-minimum + 2 E1 + 2 §7 coverage) + 6 write/eventing ops."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    gmail_attachments,
    gmail_batch_modify,
    gmail_draft,
    gmail_get,
    gmail_history,
    gmail_labels,
    gmail_list,
    gmail_manage_labels,
    gmail_modify,
    gmail_profile,
    gmail_search,
    gmail_send,
    gmail_thread_get,
    gmail_threads,
    gmail_watch,
)
from .models import (
    GmailAttachmentsInput,
    GmailAttachmentsOutput,
    GmailBatchModifyInput,
    GmailBatchModifyOutput,
    GmailDraftInput,
    GmailDraftOutput,
    GmailGetInput,
    GmailGetOutput,
    GmailHistoryInput,
    GmailHistoryOutput,
    GmailLabelsInput,
    GmailLabelsOutput,
    GmailListInput,
    GmailListOutput,
    GmailManageLabelOutput,
    GmailManageLabelsInput,
    GmailModifyInput,
    GmailModifyOutput,
    GmailProfileInput,
    GmailProfileOutput,
    GmailSearchInput,
    GmailSearchOutput,
    GmailSendInput,
    GmailSendOutput,
    GmailThreadGetInput,
    GmailThreadGetOutput,
    GmailThreadsInput,
    GmailThreadsOutput,
    GmailWatchInput,
    GmailWatchOutput,
)

_GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
_GMAIL_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
_GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"

_GMAIL_SCOPES = [_GMAIL_READONLY]
_GMAIL_WRITE_FLAG = "GOOGLE_KIT_ENABLE_GMAIL_WRITE"

register(OpSpec(
    name="gmail.list",
    fn=gmail_list,
    input_model=GmailListInput,
    output_model=GmailListOutput,
    posture="read",
    scopes=_GMAIL_SCOPES,
    perf={"api": "Gmail v1", "method": "users.messages.list", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List 10 most recent INBOX messages",
        "input": {"label_ids": ["INBOX"], "max_results": 10},
        "cli": "google-kit gmail list --label-ids '[\"INBOX\"]' --max-results 10",
    }],
    aliases=["what's in my inbox"],
))

register(OpSpec(
    name="gmail.get",
    fn=gmail_get,
    input_model=GmailGetInput,
    output_model=GmailGetOutput,
    posture="read",
    scopes=_GMAIL_SCOPES,
    perf={"api": "Gmail v1", "method": "users.messages.get", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get a full message by message ID (not thread ID). Body truncated to 500 chars.",
        "input": {"message_id": "<message-id>"},
        "cli": "google-kit gmail get --message-id <message-id>",
        "notes": "Takes a message ID (from gmail.list or gmail.search data.messages[].id). thread_id is also returned in the response. Body is truncated at 500 characters to match legacy behavior (BD-8).",
    }],
))

register(OpSpec(
    name="gmail.search",
    fn=gmail_search,
    input_model=GmailSearchInput,
    output_model=GmailSearchOutput,
    posture="read",
    scopes=_GMAIL_SCOPES,
    perf={"api": "Gmail v1", "method": "users.messages.list", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Search messages from a specific sender",
        "input": {"q": "from:boss@example.com", "max_results": 10},
        "cli": "google-kit gmail search 'from:boss@example.com'",
    }],
    keywords=["look"],
))

register(OpSpec(
    name="gmail.labels",
    fn=gmail_labels,
    input_model=GmailLabelsInput,
    output_model=GmailLabelsOutput,
    posture="read",
    scopes=_GMAIL_SCOPES,
    perf={"api": "Gmail v1", "method": "users.labels.list", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List all Gmail labels",
        "input": {},
        "cli": "google-kit gmail labels",
    }],
))

register(OpSpec(
    name="gmail.profile",
    fn=gmail_profile,
    input_model=GmailProfileInput,
    output_model=GmailProfileOutput,
    posture="read",
    scopes=_GMAIL_SCOPES,
    perf={"api": "Gmail v1", "method": "users.getProfile", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get authenticated user Gmail profile",
        "input": {},
        "cli": "google-kit gmail profile",
    }],
))

register(OpSpec(
    name="gmail.history",
    fn=gmail_history,
    input_model=GmailHistoryInput,
    output_model=GmailHistoryOutput,
    posture="read",
    scopes=_GMAIL_SCOPES,
    perf={"api": "Gmail v1", "method": "users.history.list", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List mailbox history events since history ID 12345",
        "input": {"start_history_id": "12345", "history_types": ["messageAdded"], "max_results": 50},
        "cli": "google-kit gmail history --start-history-id 12345 --history-types '[\"messageAdded\"]'",
    }],
    plane="messaging",
    capability="history.read",
))

register(OpSpec(
    name="gmail.attachments",
    fn=gmail_attachments,
    input_model=GmailAttachmentsInput,
    output_model=GmailAttachmentsOutput,
    posture="read",
    scopes=_GMAIL_SCOPES,
    perf={"api": "Gmail v1", "method": "users.messages.attachments.get", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Fetch an attachment from a Gmail message",
        "input": {"message_id": "msg001abc", "attachment_id": "ANGjdJ8abc123"},
        "cli": "google-kit gmail attachments --message-id msg001abc --attachment-id ANGjdJ8abc123",
    }],
    plane="messaging",
    capability="attachment.read",
))

register(OpSpec(
    name="gmail.threads",
    fn=gmail_threads,
    input_model=GmailThreadsInput,
    output_model=GmailThreadsOutput,
    posture="read",
    scopes=_GMAIL_SCOPES,
    perf={"api": "Gmail v1", "method": "users.threads.list", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[
        {
            "description": "List 10 most recent INBOX threads",
            "input": {"label_ids": ["INBOX"], "max_results": 10},
            "cli": "google-kit gmail threads --label-ids '[\"INBOX\"]' --max-results 10",
        },
        {
            "description": "Search threads by Gmail query (q makes this a thread search)",
            "input": {"q": "from:boss@example.com"},
            "cli": "google-kit gmail threads --q 'from:boss@example.com'",
            "notes": "Providing q runs users.threads.list with a query, covering thread-level search. Paginate with --page-token from the previous page.next_page_token.",
        },
    ],
    plane="messaging",
    capability="thread.read",
))

register(OpSpec(
    name="gmail.thread_get",
    fn=gmail_thread_get,
    input_model=GmailThreadGetInput,
    output_model=GmailThreadGetOutput,
    posture="read",
    scopes=_GMAIL_SCOPES,
    perf={"api": "Gmail v1", "method": "users.threads.get", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get a full thread (all messages) by thread ID",
        "input": {"thread_id": "<thread-id>"},
        "cli": "google-kit gmail thread-get --thread-id <thread-id>",
        "notes": "Takes a thread ID (from gmail.threads data.threads[].id or gmail.get data.thread_id). Returns messages[] with decoded bodies truncated at 500 chars (BD-8).",
    }],
    plane="messaging",
    capability="thread.read",
))

# ---------------------------------------------------------------------------
# Write ops (flag-gated F5: GOOGLE_KIT_ENABLE_GMAIL_WRITE)
# ---------------------------------------------------------------------------

register(OpSpec(
    name="gmail.draft",
    fn=gmail_draft,
    input_model=GmailDraftInput,
    output_model=GmailDraftOutput,
    posture="write",
    scopes=[_GMAIL_COMPOSE],
    perf={"api": "Gmail v1", "method": "users.drafts.create", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a draft to a recipient with subject and body",
        "input": {"to": "alice@example.com", "subject": "Hello", "body_text": "Hi Alice!"},
        "cli": "google-kit gmail draft --to alice@example.com --subject Hello --body-text 'Hi Alice!'",
    }],
    plane="messaging",
    capability="mail.compose",
    flag=_GMAIL_WRITE_FLAG,
))

register(OpSpec(
    name="gmail.send",
    fn=gmail_send,
    input_model=GmailSendInput,
    output_model=GmailSendOutput,
    posture="write",
    scopes=[_GMAIL_COMPOSE],
    perf={"api": "Gmail v1", "method": "users.messages.send", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Send an email to a recipient",
        "input": {"to": "bob@example.com", "subject": "Meeting", "body_text": "See you at 3pm."},
        "cli": "google-kit gmail send --to bob@example.com --subject Meeting --body-text 'See you at 3pm.'",
    }],
    plane="messaging",
    capability="mail.send",
    flag=_GMAIL_WRITE_FLAG,
))

register(OpSpec(
    name="gmail.modify",
    fn=gmail_modify,
    input_model=GmailModifyInput,
    output_model=GmailModifyOutput,
    posture="write",
    scopes=[_GMAIL_MODIFY],
    perf={"api": "Gmail v1", "method": "users.messages.modify", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Mark a message as read by removing UNREAD label",
        "input": {"message_id": "<msg-id>", "remove_label_ids": ["UNREAD"]},
        "cli": "google-kit gmail modify --message-id <msg-id> --remove-label-ids '[\"UNREAD\"]'",
    }],
    plane="messaging",
    capability="mail.modify",
    flag=_GMAIL_WRITE_FLAG,
))

register(OpSpec(
    name="gmail.batch_modify",
    fn=gmail_batch_modify,
    input_model=GmailBatchModifyInput,
    output_model=GmailBatchModifyOutput,
    posture="write",
    scopes=[_GMAIL_MODIFY],
    perf={"api": "Gmail v1", "method": "users.messages.batchModify", "quota": "250 req/day"},
    batching={"supported": True},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Mark several messages as read in one call (remove UNREAD)",
        "input": {"ids": ["<msg-id-1>", "<msg-id-2>"], "remove_label_ids": ["UNREAD"]},
        "cli": "google-kit gmail batch-modify --ids '[\"<msg-id-1>\",\"<msg-id-2>\"]' --remove-label-ids '[\"UNREAD\"]'",
        "notes": "Applies the same label change to every message ID in one request. The API returns HTTP 204 (empty body); the envelope reports modified_count and the ids/labels acted on.",
    }],
    plane="messaging",
    capability="mail.batch_modify",
    flag=_GMAIL_WRITE_FLAG,
))

register(OpSpec(
    name="gmail.manage_labels",
    fn=gmail_manage_labels,
    input_model=GmailManageLabelsInput,
    output_model=GmailManageLabelOutput,
    posture="write",
    scopes=[_GMAIL_MODIFY],
    perf={"api": "Gmail v1", "method": "users.labels.create", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a new user-defined label",
        "input": {"name": "ProjectX"},
        "cli": "google-kit gmail manage-labels --name ProjectX",
    }],
    plane="messaging",
    capability="mail.labels",
    flag=_GMAIL_WRITE_FLAG,
))

register(OpSpec(
    name="gmail.watch",
    fn=gmail_watch,
    input_model=GmailWatchInput,
    output_model=GmailWatchOutput,
    posture="write",
    scopes=[_GMAIL_READONLY],
    perf={"api": "Gmail v1", "method": "users.watch", "quota": "250 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Start push notifications for INBOX to a Pub/Sub topic",
        "input": {
            "topic_name": "projects/my-project/topics/gmail-watch",
            "label_ids": ["INBOX"],
        },
        "cli": (
            "google-kit gmail watch "
            "--topic-name projects/my-project/topics/gmail-watch "
            "--label-ids '[\"INBOX\"]'"
        ),
        "notes": "Requires an operator-provisioned Cloud Pub/Sub topic with Gmail service account publish access.",
    }],
    plane="eventing",
    capability="eventing.watch",
    flag=_GMAIL_WRITE_FLAG,
))
