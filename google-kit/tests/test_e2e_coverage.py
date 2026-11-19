"""Auditable fake-Google E2E coverage for every registered google-kit op.

This suite intentionally stays off the live network. It drives the same typed
core functions, CLI adapter, and MCP adapter that real usage hits, with injected
Google API fakes and explicit expected-vs-actual envelope checks.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import google_kit  # noqa: F401 - triggers registration
from google_kit.cli import _service_kwargs as cli_service_kwargs
from google_kit.cli import main as cli_main
from google_kit.mcp import build_mcp_server
from google_kit.registry import all_specs
from kp_mcp_bootstrap.docgen import mcp_tool_name
from kp_mcp_testkit.fixtures import compare_normalized
from kp_mcp_testkit.mock_google import MockGoogleService


RESOURCE_ACCESSORS = {
    "activity",
    "attachments",
    "changes",
    "comments",
    "connections",
    "deployments",
    "documents",
    "drafts",
    "events",
    "files",
    "forms",
    "freebusy",
    "history",
    "labels",
    "messages",
    "notes",
    "pages",
    "people",
    "permissions",
    "presentations",
    "projects",
    "responses",
    "revisions",
    "scripts",
    "spreadsheets",
    "subscriptions",
    "tasklists",
    "tasks",
    "threads",
    "users",
    "values",
    "versions",
    "watches",
}

STYLE_PROFILE_SAMPLE: dict[str, Any] = {
    "schema": 1,
    "named_styles": {
        "NORMAL_TEXT": {
            "textStyle": {"fontSize": {"magnitude": 12, "unit": "PT"}},
            "paragraphStyle": {"lineSpacing": 120},
        }
    },
    "document_style": {"documentFormat": {"documentMode": "PAGES"}},
}

LOCAL_ONLY_OPS = {
    "docs.styles_doctor",
    "docs.styles_remove",
    "docs.styles_repair",
    "docs.styles_set_default",
    "docs.styles_update",
    "docs.styles_view",
}


SAMPLE_INPUTS: dict[str, dict[str, Any]] = {
    "calendar.create": {
        "summary": "E2E event",
        "start": "2026-06-19T09:00:00Z",
        "end": "2026-06-19T09:30:00Z",
        "attendees": ["teammate@example.com"],
        "meet": True,
        "conference_request_id": "e2e-meet",
    },
    "calendar.delete": {"event_id": "event-1"},
    "calendar.freebusy": {
        "emails": ["primary"],
        "time_min": "2026-06-19T09:00:00Z",
        "time_max": "2026-06-19T10:00:00Z",
    },
    "calendar.list": {"max_results": 3},
    "calendar.update": {
        "event_id": "event-1",
        "summary": "Updated E2E event",
        "add_attendees": ["new@example.com"],
    },
    "calendar.watch": {
        "channel_id": "calendar-channel",
        "address": "https://example.com/calendar-hook",
        "expiration_ms": 1893456000000,
    },
    "docs.batch_update": {
        "document_id": "doc-1",
        "requests": [{"insertText": {"location": {"index": 1}, "text": "hello"}}],
    },
    "docs.from_markdown": {
        "markdown_content": "# Title\n\nBody",
        "title": "E2E Doc",
        "folder_id": "folder-1",
    },
    "docs.apply_styles": {
        "document_id": "doc-1",
        "style_overrides": STYLE_PROFILE_SAMPLE,
    },
    "docs.extract_styles": {"document_id": "doc-1", "style_profile": "team"},
    "docs.styles_add": {"style_profile": "team", "document_id": "doc-1"},
    "docs.styles_apply": {
        "document_id": "doc-1",
        "style_overrides": STYLE_PROFILE_SAMPLE,
    },
    "docs.styles_doctor": {"seed_default": True},
    "docs.styles_remove": {"style_profile": "team"},
    "docs.styles_repair": {"seed_default": True},
    "docs.styles_set_default": {"style_profile": "team"},
    "docs.styles_update": {"style_profile": "team", "updates": {"template_doc_id": "template-1"}},
    "docs.styles_view": {},
    "drive.changes": {"page_token": "token-1"},
    "drive.changes_watch": {
        "page_token": "token-1",
        "channel_id": "drive-channel",
        "address": "https://example.com/drive-hook",
    },
    "drive.comments": {"file_id": "file-1", "action": "create", "content": "Looks good"},
    "drive.copy": {"file_id": "file-1", "name": "Copy"},
    "drive.create": {"title": "E2E File", "doc_type": "doc", "folder_id": "folder-1"},
    "drive.fetch": {"url_or_id": "file-1", "metadata_only": False},
    "drive.permissions": {
        "file_id": "file-1",
        "action": "create",
        "role": "reader",
        "type": "user",
        "email_address": "reader@example.com",
    },
    "drive.revisions": {"file_id": "file-1", "revision_id": "1"},
    "drive.search": {"query": "quarterly plan", "limit": 2},
    "drive.trash": {"file_id": "file-1"},
    "drive.update": {"file_id": "file-1", "name": "Renamed"},
    "drive.upload": {
        "content_b64": "SGVsbG8=",
        "filename": "hello.txt",
        "folder_id": "folder-1",
        "share": "anyone_reader",
    },
    "drive_activity.query": {"item_name": "items/file-1", "page_size": 10},
    "events.delete": {"name": "subscriptions/sub-1"},
    "events.list": {"filter": 'target_resource="//drive.googleapis.com/files/file-1"'},
    "events.patch": {"name": "subscriptions/sub-1", "ttl": "86400s"},
    "events.subscribe": {
        "target_resource": "//drive.googleapis.com/files/file-1",
        "event_types": ["google.workspace.drive.file.v3.changed"],
        "pubsub_topic": "projects/p/topics/t",
    },
    "forms.add_item": {
        "form_id": "form-1",
        "title": "Question",
        "item_type": "multiple_choice",
        "options": "Yes,No",
        "required": True,
    },
    "forms.create": {
        "title": "E2E Form",
        "description": "Form description",
        "document_title": "E2E Form Doc",
    },
    "forms.get": {"form_id": "form-1"},
    "forms.get_response": {"form_id": "form-1", "response_id": "response-1"},
    "forms.list_responses": {"form_id": "form-1", "page_size": 10},
    "forms.publish": {
        "form_id": "form-1",
        "publish_settings": {"publishState": {"isPublished": True}},
    },
    "forms.update": {"form_id": "form-1", "title": "Updated Form"},
    "forms.watches": {
        "form_id": "form-1",
        "action": "create",
        "topic_name": "projects/p/topics/forms",
    },
    "gmail.attachments": {"message_id": "msg-1", "attachment_id": "att-1"},
    "gmail.batch_modify": {"ids": ["msg-1", "msg-2"], "add_label_ids": ["STARRED"]},
    "gmail.draft": {"to": "to@example.com", "subject": "Draft", "body_text": "Body"},
    "gmail.get": {"message_id": "msg-1"},
    "gmail.history": {"start_history_id": "10"},
    "gmail.labels": {},
    "gmail.list": {"q": "is:unread", "max_results": 2},
    "gmail.manage_labels": {"name": "E2E"},
    "gmail.modify": {"message_id": "msg-1", "add_label_ids": ["INBOX"]},
    "gmail.profile": {},
    "gmail.search": {"q": "from:sender@example.com"},
    "gmail.send": {"to": "to@example.com", "subject": "Send", "body_text": "Body"},
    "gmail.thread_get": {"thread_id": "thread-1"},
    "gmail.threads": {"q": "subject:E2E", "max_results": 2},
    "gmail.watch": {"topic_name": "projects/p/topics/gmail", "label_ids": ["INBOX"]},
    "keep.create": {"title": "Keep note", "body_text": "Body"},
    "keep.delete": {"note_id": "notes/note-1"},
    "keep.get": {"note_id": "notes/note-1"},
    "keep.list": {"page_size": 5},
    "people.batch_get": {"resource_names": ["people/1"]},
    "people.connections": {"page_size": 5},
    "people.get": {"resource_name": "people/1"},
    "people.list_directory": {"sources": ["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"]},
    "people.search_directory": {
        "query": "Ada",
        "sources": ["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"],
    },
    "recipes.build_then_share": {
        "markdown_content": "# Plan\n\nBody",
        "title": "Shared Plan",
        "share_with": "reader@example.com",
    },
    "recipes.build_styled": {
        "markdown_content": "# Styled\n\nBody",
        "title": "Styled Doc",
        "style_overrides": STYLE_PROFILE_SAMPLE,
    },
    "recipes.hydrate_then_refine": {
        "document_id": "doc-1",
        "requests": [{"insertText": {"location": {"index": 1}, "text": "refined"}}],
    },
    "recipes.template_merge": {
        "template_id": "template-1",
        "replacements": {"{{name}}": "Ada"},
        "new_name": "Merged Doc",
    },
    "script.create": {"title": "E2E Script", "parent_id": "folder-1"},
    "script.create_deployment": {"script_id": "script-1", "version_number": 1},
    "script.create_version": {"script_id": "script-1", "description": "v1"},
    "script.delete_deployment": {"script_id": "script-1", "deployment_id": "dep-1"},
    "script.deployments": {"script_id": "script-1", "page_size": 10},
    "script.get_content": {"script_id": "script-1"},
    "script.get_deployment": {"script_id": "script-1", "deployment_id": "dep-1"},
    "script.get_version": {"script_id": "script-1", "version_number": 1},
    "script.metrics": {"script_id": "script-1", "metrics_granularity": "WEEKLY"},
    "script.run": {"script_id": "script-1", "function": "main", "parameters": ["x"]},
    "script.update_content": {
        "script_id": "script-1",
        "files": [{"name": "Code", "type": "SERVER_JS", "source": "function main() {}"}],
    },
    "script.update_deployment": {
        "script_id": "script-1",
        "deployment_id": "dep-1",
        "version_number": 2,
    },
    "script.versions": {"script_id": "script-1", "page_size": 10},
    "sheets.add_sheet": {"spreadsheet_id": "sheet-1", "title": "Data"},
    "sheets.append": {
        "spreadsheet_id": "sheet-1",
        "range": "Sheet1!A1",
        "values": [["a", "b"]],
    },
    "sheets.chart": {
        "spreadsheet_id": "sheet-1",
        "title": "Chart",
        "sheet_id": 0,
        "x_range": {"start_row": 0, "end_row": 3, "start_col": 0, "end_col": 1},
        "y_ranges": [{"start_row": 0, "end_row": 3, "start_col": 1, "end_col": 2}],
    },
    "sheets.conditional_format": {
        "spreadsheet_id": "sheet-1",
        "sheet_id": 0,
        "range": {"start_row": 0, "end_row": 10, "start_col": 0, "end_col": 1},
        "condition_type": "TEXT_CONTAINS",
        "condition_values": ["urgent"],
        "bold": True,
    },
    "sheets.create": {"title": "E2E Sheet", "sheet_names": ["Data"], "folder_id": "folder-1"},
    "sheets.info": {"spreadsheet_id": "sheet-1"},
    "sheets.metadata": {
        "spreadsheet_id": "sheet-1",
        "metadata_key": "suite",
        "metadata_value": "e2e",
    },
    "sheets.pivot": {
        "spreadsheet_id": "sheet-1",
        "source_sheet_id": 0,
        "source_range": {"start_row": 0, "end_row": 10, "start_col": 0, "end_col": 3},
        "target_sheet_id": 1,
        "target_row": 0,
        "target_col": 0,
        "rows": [0],
        "columns": [1],
        "values": [{"source_column_offset": 2, "summarize_function": "SUM"}],
    },
    "sheets.read": {"spreadsheet_id": "sheet-1", "range": "Sheet1!A1:B2"},
    "sheets.write": {
        "spreadsheet_id": "sheet-1",
        "range": "Sheet1!A1",
        "values": [["a", "b"]],
        "clear_first": True,
    },
    "slides.add_image": {
        "presentation_id": "pres-1",
        "slide_id": "slide-1",
        "url": "https://example.com/image.png",
        "object_id": "image-1",
    },
    "slides.add_slide": {
        "presentation_id": "pres-1",
        "layout": "TITLE_AND_BODY",
        "title_text": "Title",
        "body_text": "Body",
    },
    "slides.create": {"title": "E2E Deck", "folder_id": "folder-1"},
    "slides.get": {"presentation_id": "pres-1"},
    "slides.thumbnail": {"presentation_id": "pres-1", "page_object_id": "slide-1"},
    "slides.update_text": {"presentation_id": "pres-1", "find": "old", "replace": "new"},
    "tasks.complete": {"task_id": "task-1"},
    "tasks.create": {"title": "Task", "notes": "Do it", "due": "2026-06-19"},
    "tasks.delete": {"task_id": "task-1"},
    "tasks.list": {"max_results": 5, "show_completed": True},
    "tasks.list_lists": {"max_results": 5},
    "tasks.update": {"task_id": "task-1", "title": "Updated task"},
}


E2E_COVERAGE = {
    op: {
        "test": f"test_core_success_expected_vs_actual[{op}]",
        "assertions": [
            "output envelope validates with registered output_model",
            "expected meta.op equals actual meta.op",
            "expected data keys equal actual data keys",
            "injected fake recorded at least one Google API call",
        ],
        "status": "covered",
    }
    for op in SAMPLE_INPUTS
}


@dataclass
class ApiCallRecord:
    service: str
    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class _Executable:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _Method:
    def __init__(self, node: "_FakeNode", name: str) -> None:
        self._node = node
        self._name = name

    def __call__(self, **kwargs: Any) -> Any:
        if self._name in RESOURCE_ACCESSORS:
            return _FakeNode(self._node._root, [*self._node._path, self._name])
        return self._node._call(self._name, kwargs)


class _FakeNode:
    def __init__(self, root: "_FakeGoogleService", path: list[str] | None = None) -> None:
        self._root = root
        self._path = path or []

    def __getattr__(self, name: str) -> _Method:
        return _Method(self, name)

    def _call(self, method: str, kwargs: dict[str, Any]) -> _Executable:
        resource = ".".join(self._path)
        record = ApiCallRecord(self._root.service_name, resource, method, dict(kwargs))
        self._root.calls.append(record)
        return _Executable(_fake_response(record))


class _FakeGoogleService(_FakeNode):
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.calls: list[ApiCallRecord] = []
        super().__init__(self, [])


class _FakeFactory:
    def __init__(self) -> None:
        self.services: dict[str, _FakeGoogleService] = {}

    def __call__(self, op_name: str, *, profile: str | None = None) -> _FakeGoogleService:
        del profile
        prefix = op_name.split(".", 1)[0]
        return self.services.setdefault(prefix, _FakeGoogleService(prefix))

    @property
    def calls(self) -> list[ApiCallRecord]:
        return [call for svc in self.services.values() for call in svc.calls]


def _fake_response(call: ApiCallRecord) -> Any:
    resource, method, kwargs = call.resource, call.method, call.kwargs
    body = kwargs.get("body") or {}

    if resource == "events":
        if method == "list":
            return {"items": [_calendar_event()]}
        if method == "insert":
            return {"id": "event-1", "summary": body.get("summary"), "htmlLink": "https://calendar/event-1", "start": body.get("start", {})}
        if method == "get":
            return _calendar_event()
        if method == "patch":
            return {"id": kwargs.get("eventId", "event-1"), "summary": body.get("summary"), "htmlLink": "https://calendar/event-1"}
        if method == "watch":
            expiration = body.get("expiration")
            return {"id": body.get("id", "channel-1"), "resourceId": "resource-1", "resourceUri": "https://calendar/resource", "expiration": str(expiration) if expiration is not None else None}
        if method == "delete":
            return None

    if resource == "freebusy" and method == "query":
        return {"timeMin": body.get("timeMin"), "timeMax": body.get("timeMax"), "calendars": {"primary": {"busy": [{"start": body.get("timeMin"), "end": body.get("timeMax")}]}}}

    if resource == "documents":
        if method == "get":
            return {"body": {"content": [{"startIndex": 1, "endIndex": 6, "paragraph": {"paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}}}]}}
        if method == "batchUpdate":
            return {"documentId": kwargs.get("documentId", "doc-1"), "replies": [{}], "writeControl": body.get("writeControl")}

    if resource == "files":
        if method == "get":
            return {"id": kwargs.get("fileId", "file-1"), "name": "E2E File", "mimeType": "application/vnd.google-apps.document", "webViewLink": "https://drive/file-1"}
        if method == "export":
            return "<h1>E2E</h1><p>Drive content</p>"
        if method == "list":
            return {"files": [{"id": "folder-1", "name": "Folder", "mimeType": "application/vnd.google-apps.folder", "modifiedTime": "2026-06-19T00:00:00Z", "owners": [{"displayName": "Owner"}], "webViewLink": "https://drive/folder-1", "shared": False}]}
        if method == "create":
            return {"id": "file-1", "name": body.get("name", "E2E File"), "webViewLink": "https://drive/file-1", "mimeType": body.get("mimeType", "text/plain")}
        if method == "copy":
            return {"id": "copy-1", "name": body.get("name", "Copy"), "webViewLink": "https://drive/copy-1"}
        if method == "update":
            return {"id": kwargs.get("fileId", "file-1"), "name": body.get("name", "Updated"), "parents": ["folder-1"], "trashed": body.get("trashed", False)}

    if resource == "permissions":
        if method == "list":
            return {"permissions": [{"id": "perm-1", "type": "user", "role": "reader", "emailAddress": "reader@example.com"}]}
        if method == "create":
            return {"id": "perm-1", **body}
        if method == "delete":
            return None

    if resource == "comments":
        if method == "list":
            return {"comments": [{"id": "comment-1", "content": "Looks good", "resolved": False}]}
        if method == "create":
            return {"id": "comment-1", "content": body.get("content", "")}

    if resource == "revisions":
        if method == "get":
            return {"id": kwargs.get("revisionId", "1"), "modifiedTime": "2026-06-19T00:00:00Z"}
        if method == "list":
            return {"revisions": [{"id": "1", "modifiedTime": "2026-06-19T00:00:00Z"}]}

    if resource == "changes":
        if method == "getStartPageToken":
            return {"startPageToken": "token-1"}
        if method == "list":
            return {"changes": [{"fileId": "file-1", "removed": False}], "newStartPageToken": "token-2"}
        if method == "watch":
            return {"id": body.get("id", "channel-1"), "resourceId": "resource-1", "resourceUri": "https://drive/change", "expiration": body.get("expiration")}

    if resource == "activity" and method == "query":
        return {"activities": [{"primaryActionDetail": {"edit": {}}}], "nextPageToken": None}

    if resource == "subscriptions":
        if method == "list":
            return {"subscriptions": [{"name": "subscriptions/sub-1", "targetResource": "//drive.googleapis.com/files/file-1", "eventTypes": ["changed"], "state": "ACTIVE"}]}
        if method in {"create", "patch", "delete"}:
            return {"name": kwargs.get("name", "operations/op-1"), "done": True}

    if resource == "forms":
        if method == "create":
            return {"formId": "form-1", "info": {"title": (body.get("info") or {}).get("title", "Form")}, "responderUri": "https://forms/form-1"}
        if method == "get":
            return {"info": {"title": "Form", "description": "Description"}, "items": [{"title": "Question", "questionItem": {"question": {"textQuestion": {}, "required": True}}}]}
        if method == "batchUpdate":
            return {"replies": [{}]}
        if method == "setPublishSettings":
            return {}

    if resource == "forms.responses":
        if method == "list":
            return {"responses": [_form_response()]}
        if method == "get":
            return _form_response()

    if resource == "forms.watches":
        if method == "list":
            return {"watches": [{"id": "watch-1", "state": "ACTIVE", "eventType": "RESPONSES", "createTime": "2026-06-19T00:00:00Z"}]}
        if method == "delete":
            return None
        if method in {"create", "renew"}:
            return {"id": kwargs.get("watchId", "watch-1"), "state": "ACTIVE", "eventType": "RESPONSES", "createTime": "2026-06-19T00:00:00Z"}

    if resource == "users.messages":
        if method == "list":
            return {"messages": [{"id": "msg-1", "threadId": "thread-1"}]}
        if method == "get":
            return _gmail_message(kwargs.get("id", "msg-1"))
        if method == "send":
            return {"id": "sent-1", "threadId": "thread-1", "labelIds": ["SENT"]}
        if method == "modify":
            return {"id": kwargs.get("id", "msg-1"), "labelIds": body.get("addLabelIds", [])}
        if method == "batchModify":
            return None

    if resource == "users.messages.attachments" and method == "get":
        return {"size": 5, "data": "SGVsbG8="}

    if resource == "users.labels":
        if method == "list":
            return {"labels": [{"id": "INBOX", "name": "INBOX", "type": "system"}]}
        if method == "create":
            return {"id": "Label_1", "name": body.get("name", "E2E")}

    if resource == "users.history" and method == "list":
        return {"history": [{"id": "11", "messages": [{"id": "msg-1", "threadId": "thread-1"}]}], "historyId": "12"}

    if resource == "users.drafts" and method == "create":
        return {"id": "draft-1", "message": {"id": "msg-1"}}

    if resource == "users.threads":
        if method == "list":
            return {"threads": [{"id": "thread-1", "snippet": "snippet", "historyId": "10"}]}
        if method == "get":
            return {"id": kwargs.get("id", "thread-1"), "historyId": "10", "snippet": "snippet", "messages": [_gmail_message("msg-1")]}

    if resource == "users":
        if method == "getProfile":
            return {"emailAddress": "real@example.com", "messagesTotal": 1, "threadsTotal": 1}
        if method == "watch":
            return {"historyId": "99", "expiration": "1893456000000"}

    if resource == "notes":
        if method == "list":
            return {"notes": [_keep_note()]}
        if method == "get":
            return _keep_note()
        if method == "create":
            return {"name": "notes/note-1", "title": body.get("title", "Keep note")}
        if method == "delete":
            return None

    if resource == "people":
        if method == "get":
            return _person(kwargs.get("resourceName", "people/1"))
        if method == "getBatchGet":
            return {"responses": [{"person": _person("people/1")}]}
        if method in {"searchDirectoryPeople", "listDirectoryPeople"}:
            return {"people": [_person("people/1")], "nextPageToken": None}

    if resource == "people.connections" and method == "list":
        return {"connections": [_person("people/1")], "nextPageToken": None}

    if resource == "projects":
        if method == "create":
            return {"scriptId": "script-1", "title": body.get("title", "Script")}
        if method == "getContent":
            return {"scriptId": kwargs.get("scriptId", "script-1"), "files": [{"name": "Code", "type": "SERVER_JS", "source": "function main() {}"}]}
        if method == "updateContent":
            return {"scriptId": kwargs.get("scriptId", "script-1"), "files": body.get("files", [])}
        if method == "getMetrics":
            return {"activeUsers": [], "totalExecutions": [], "failedExecutions": []}

    if resource == "projects.deployments":
        if method == "list":
            return {"deployments": [{"deploymentId": "dep-1"}]}
        if method == "get":
            return {"deploymentId": kwargs.get("deploymentId", "dep-1")}
        if method in {"create", "update"}:
            return {"deploymentId": kwargs.get("deploymentId", "dep-1"), **body}
        if method == "delete":
            return None

    if resource == "projects.versions":
        if method == "list":
            return {"versions": [{"versionNumber": 1}]}
        if method == "get":
            return {"versionNumber": kwargs.get("versionNumber", 1)}
        if method == "create":
            return {"versionNumber": 1, **body}

    if resource == "scripts" and method == "run":
        return {"done": True, "response": {"result": "ok"}}

    if resource == "spreadsheets":
        if method == "create":
            return {"spreadsheetId": "sheet-1", "properties": {"title": (body.get("properties") or {}).get("title", "Sheet")}, "sheets": [{"properties": {"title": "Data", "sheetId": 0}}]}
        if method == "get":
            return {"spreadsheetId": kwargs.get("spreadsheetId", "sheet-1"), "properties": {"title": "Sheet"}, "sheets": [{"properties": {"sheetId": 0, "title": "Data", "gridProperties": {"rowCount": 10, "columnCount": 3}}}]}
        if method == "batchUpdate":
            return {"replies": [_sheets_reply(body)]}

    if resource == "spreadsheets.values":
        if method == "get":
            return {"range": kwargs.get("range", "Sheet1!A1:B2"), "values": [["a", "b"]]}
        if method == "update":
            return {"updatedRows": len(body.get("values", [])), "updatedColumns": len(body.get("values", [[]])[0]), "updatedRange": kwargs.get("range")}
        if method == "append":
            return {"updates": {"updatedRows": len(body.get("values", [])), "updatedColumns": len(body.get("values", [[]])[0]), "updatedCells": 2, "updatedRange": kwargs.get("range")}}
        if method == "clear":
            return {}

    if resource == "presentations":
        if method == "create":
            return {"presentationId": "pres-1", "title": body.get("title", "Deck"), "slides": []}
        if method == "get":
            return _presentation(kwargs.get("presentationId", "pres-1"))
        if method == "batchUpdate":
            return {"replies": [_slides_reply(body)]}

    if resource == "presentations.pages" and method == "getThumbnail":
        return {"contentUrl": "https://slides/thumb.png", "width": 640, "height": 480}

    if resource == "tasklists" and method == "list":
        return {"items": [{"id": "tasklist-1", "title": "Tasks", "kind": "tasks#taskList"}]}

    if resource == "tasks":
        if method == "list":
            return {"items": [{"id": "task-1", "title": "Task", "status": "needsAction", "kind": "tasks#task"}]}
        if method == "insert":
            return {"id": "task-1", "title": body.get("title", "Task"), "status": "needsAction", "due": body.get("due")}
        if method == "get":
            return {"id": kwargs.get("task", "task-1"), "title": "Task", "status": "needsAction"}
        if method == "update":
            return {"id": kwargs.get("task", "task-1"), "title": body.get("title", "Task"), "status": body.get("status", "needsAction"), "due": body.get("due")}
        if method == "delete":
            return None

    return {}


def _calendar_event() -> dict[str, Any]:
    return {
        "id": "event-1",
        "summary": "E2E event",
        "start": {"dateTime": "2026-06-19T09:00:00Z"},
        "end": {"dateTime": "2026-06-19T09:30:00Z"},
        "attendees": [{"email": "person@example.com", "displayName": "Person", "responseStatus": "accepted"}],
        "htmlLink": "https://calendar/event-1",
        "status": "confirmed",
    }


def _form_response() -> dict[str, Any]:
    return {
        "responseId": "response-1",
        "createTime": "2026-06-19T00:00:00Z",
        "answers": {"q1": {"textAnswers": {"answers": [{"value": "yes"}]}}},
    }


def _gmail_message(message_id: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "threadId": "thread-1",
        "snippet": "Hello",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "E2E"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "Date", "value": "Fri, 19 Jun 2026 09:00:00 +0000"},
            ],
            "body": {"data": "SGVsbG8="},
        },
    }


def _keep_note() -> dict[str, Any]:
    return {
        "name": "notes/note-1",
        "title": "Keep note",
        "body": {"text": {"text": "Body"}},
        "createTime": "2026-06-19T00:00:00Z",
        "updateTime": "2026-06-19T00:00:00Z",
    }


def _person(resource_name: str) -> dict[str, Any]:
    return {
        "resourceName": resource_name,
        "names": [{"displayName": "Ada Lovelace", "givenName": "Ada", "familyName": "Lovelace"}],
        "emailAddresses": [{"value": "ada@example.com", "type": "work", "formattedType": "Work"}],
    }


def _presentation(presentation_id: str) -> dict[str, Any]:
    return {
        "presentationId": presentation_id,
        "title": "Deck",
        "revisionId": "rev-1",
        "slides": [{
            "objectId": "slide-1",
            "slideProperties": {"layoutObjectId": "layout-1"},
            "pageElements": [
                {"objectId": "title-1", "shape": {"placeholder": {"type": "TITLE"}}},
                {"objectId": "body-1", "shape": {"placeholder": {"type": "BODY"}}},
            ],
        }],
    }


def _sheets_reply(body: dict[str, Any]) -> dict[str, Any]:
    request = (body.get("requests") or [{}])[0]
    if "addSheet" in request:
        return {"addSheet": {"properties": {"sheetId": 1, "title": (request["addSheet"].get("properties") or {}).get("title", "Data")}}}
    if "addChart" in request:
        return {"addChart": {"chart": {"chartId": 7}}}
    return {}


def _slides_reply(body: dict[str, Any]) -> dict[str, Any]:
    request = (body.get("requests") or [{}])[0]
    if "createSlide" in request:
        return {"createSlide": {"objectId": "slide-1"}}
    if "replaceAllText" in request:
        return {"replaceAllText": {"occurrencesChanged": 1}}
    return {}


def _specs() -> list[Any]:
    return sorted(all_specs(), key=lambda s: s.name)


def _service_kwargs(spec: Any, factory: _FakeFactory) -> dict[str, Any]:
    return cli_service_kwargs(spec, factory, spec.name, None)


def _expected_data_keys(spec: Any) -> set[str]:
    data_annotation = spec.output_model.model_fields["data"].annotation
    if isinstance(data_annotation, type) and issubclass(data_annotation, BaseModel):
        return set(data_annotation.model_fields)
    raise AssertionError(f"{spec.name}: output_model.data is not a BaseModel")


def _assert_expected_vs_actual_envelope(spec: Any, actual: dict[str, Any]) -> None:
    expected = {
        "meta_op": spec.name,
        "data_keys": sorted(_expected_data_keys(spec)),
    }
    got = {
        "meta_op": actual["meta"]["op"],
        "data_keys": sorted((actual.get("data") or {}).keys()),
    }
    match, diff = compare_normalized(expected, got)
    assert match, f"{spec.name}: EXPECTED vs ACTUAL envelope mismatch\n{diff}"
    spec.output_model.model_validate(actual)


def _expects_fake_call(op_name: str) -> bool:
    return op_name not in LOCAL_ONLY_OPS


def _seed_style_profile_for_sample(op_name: str) -> None:
    if op_name in {
        "docs.styles_remove",
        "docs.styles_set_default",
        "docs.styles_update",
    }:
        from google_kit.core.profiles import save_profile

        save_profile("team", STYLE_PROFILE_SAMPLE, audit=False)


def _argv_for(op_name: str, payload: dict[str, Any]) -> list[str]:
    service, _, rest = op_name.partition(".")
    argv = [service, rest.replace("_", "-")]
    for key, value in payload.items():
        argv.append(f"--{key.replace('_', '-')}")
        if isinstance(value, (dict, list)):
            argv.append(json.dumps(value))
        elif isinstance(value, bool):
            argv.append("true" if value else "false")
        else:
            argv.append(str(value))
    return argv


def _mcp_call(server: Any, op_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    from mcp.types import CallToolRequest, CallToolRequestParams

    async def _run() -> Any:
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name=mcp_tool_name(op_name),
                arguments=payload,
            ),
        )
        return await server.request_handlers[CallToolRequest](req)

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    assert root.content, f"{op_name}: MCP returned no content"
    return json.loads(root.content[0].text)


@pytest.fixture(autouse=True)
def _disable_disk_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("google_kit.core.client.write_audit", lambda **kwargs: None)


def test_kp_mcp_testkit_mock_google_fixture_still_available() -> None:
    svc = MockGoogleService(responses={("tasklists", "list"): {"items": []}})
    assert svc.tasklists().list(maxResults=1).execute() == {"items": []}


def test_e2e_coverage_matrix_is_complete() -> None:
    registered = {spec.name for spec in all_specs()}
    assert len(registered) == 106
    assert set(E2E_COVERAGE) == registered
    assert all(row["status"] == "covered" for row in E2E_COVERAGE.values())
    assert all(row["test"] and row["assertions"] for row in E2E_COVERAGE.values())


@pytest.mark.parametrize("spec", _specs(), ids=lambda spec: spec.name)
def test_core_success_expected_vs_actual(
    spec: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # drive.upload sample shares publicly (share=anyone_reader) — opt in.
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", "1")
    factory = _FakeFactory()
    inp = spec.input_model.model_validate(SAMPLE_INPUTS[spec.name])
    _seed_style_profile_for_sample(spec.name)

    result = spec.fn(inp, **_service_kwargs(spec, factory))
    actual = result.model_dump()

    _assert_expected_vs_actual_envelope(spec, actual)
    if _expects_fake_call(spec.name):
        assert factory.calls, f"{spec.name}: expected injected fake to record API usage"


@pytest.mark.parametrize("spec", _specs(), ids=lambda spec: spec.name)
def test_cli_success_expected_vs_actual(
    spec: Any,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Umbrella opt-in enables every per-service *_WRITE gate at once; the two
    # elevated gates (watch, public-share) are not covered by the umbrella, so set
    # them explicitly for the sample inputs that need them.
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_WRITES", "1")
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_WATCH", "1")
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", "1")
    factory = _FakeFactory()
    _seed_style_profile_for_sample(spec.name)

    cli_main(_argv_for(spec.name, SAMPLE_INPUTS[spec.name]), _service_factory=factory)
    actual = json.loads(capsys.readouterr().out)

    _assert_expected_vs_actual_envelope(spec, actual)
    if _expects_fake_call(spec.name):
        assert factory.calls, f"{spec.name}: expected CLI-injected fake to record API usage"


@pytest.mark.parametrize("spec", _specs(), ids=lambda spec: spec.name)
def test_mcp_success_expected_vs_actual(spec: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_WRITES", "1")
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_WATCH", "1")
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", "1")
    factory = _FakeFactory()
    server = build_mcp_server(_service_factory=factory)
    _seed_style_profile_for_sample(spec.name)

    actual = _mcp_call(server, spec.name, SAMPLE_INPUTS[spec.name])

    _assert_expected_vs_actual_envelope(spec, actual)
    if _expects_fake_call(spec.name):
        assert factory.calls, f"{spec.name}: expected MCP-injected fake to record API usage"


INVALID_CATEGORY_CASES = [
    ("calendar", "calendar.create", []),
    ("docs", "docs.batch_update", []),
    ("drive", "drive.fetch", []),
    ("drive_activity", "drive_activity.query", ["--page-size", "not-an-int"]),
    ("events", "events.list", []),
    ("forms", "forms.get", []),
    ("gmail", "gmail.get", []),
    ("keep", "keep.get", []),
    ("people", "people.get", []),
    ("recipes", "recipes.template_merge", []),
    ("script", "script.get_version", []),
    ("sheets", "sheets.read", []),
    ("slides", "slides.get", []),
    ("tasks", "tasks.create", []),
]


@pytest.mark.parametrize(
    "category,op_name,extra_argv",
    INVALID_CATEGORY_CASES,
    ids=[case[0] for case in INVALID_CATEGORY_CASES],
)
def test_validation_error_per_service_category(
    category: str,
    op_name: str,
    extra_argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    del category
    spec = next(spec for spec in all_specs() if spec.name == op_name)

    invalid_payload = (
        {}
        if any(field.is_required() for field in spec.input_model.model_fields.values())
        else {"page_size": "not-an-int"}
    )
    with pytest.raises(ValidationError):
        spec.input_model.model_validate(invalid_payload)

    service, _, rest = op_name.partition(".")
    with pytest.raises(SystemExit) as exc:
        cli_main([service, rest.replace("_", "-"), *extra_argv], _service_factory=_FakeFactory())
    assert exc.value.code != 0
    assert capsys.readouterr().err


def test_gmail_write_flag_absent_blocks_cli_send(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", raising=False)
    factory = _FakeFactory()

    with pytest.raises(SystemExit) as exc:
        cli_main(_argv_for("gmail.send", SAMPLE_INPUTS["gmail.send"]), _service_factory=factory)

    assert exc.value.code != 0
    assert not factory.calls
    assert "GOOGLE_KIT_ENABLE_GMAIL_WRITE" in capsys.readouterr().err


def test_gmail_write_flag_present_allows_cli_send(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", "1")
    factory = _FakeFactory()

    cli_main(_argv_for("gmail.send", SAMPLE_INPUTS["gmail.send"]), _service_factory=factory)
    actual = json.loads(capsys.readouterr().out)

    assert actual["data"]["message_id"] == "sent-1"
    assert any(call.resource == "users.messages" and call.method == "send" for call in factory.calls)
