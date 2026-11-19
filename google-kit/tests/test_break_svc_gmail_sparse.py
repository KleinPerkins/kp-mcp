from __future__ import annotations

from typing import Any

from google_kit.services.gmail.core import (
    gmail_history,
    gmail_labels,
    gmail_list,
    gmail_search,
)
from google_kit.services.gmail.models import (
    GmailHistoryInput,
    GmailLabelsInput,
    GmailListInput,
    GmailSearchInput,
)


class _Exec:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _Resource:
    def __init__(self, resource: str, responses: dict[tuple[str, str], Any]) -> None:
        self._resource = resource
        self._responses = responses

    def list(self, **kwargs: Any) -> _Exec:
        return _Exec(self._responses.get((self._resource, "list")))


class _Users:
    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self._responses = responses

    def messages(self) -> _Resource:
        return _Resource("messages", self._responses)

    def labels(self) -> _Resource:
        return _Resource("labels", self._responses)

    def history(self) -> _Resource:
        return _Resource("history", self._responses)


class _GmailSvc:
    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self._responses = responses

    def users(self) -> _Users:
        return _Users(self._responses)


def test_gmail_list_tolerates_sparse_message_records() -> None:
    svc = _GmailSvc({("messages", "list"): {"messages": [{"threadId": "t1"}, {}]}})

    result = gmail_list(GmailListInput(), service=svc)

    assert result.data.count == 2
    assert [m.id for m in result.data.messages] == ["", ""]


def test_gmail_search_tolerates_sparse_message_records() -> None:
    svc = _GmailSvc({("messages", "list"): {"messages": [{"threadId": "t1"}, {}]}})

    result = gmail_search(GmailSearchInput(q="subject:test"), service=svc)

    assert result.data.count == 2
    assert [m.id for m in result.data.messages] == ["", ""]


def test_gmail_history_tolerates_sparse_history_and_messages() -> None:
    svc = _GmailSvc({
        ("history", "list"): {
            "history": [{"messages": [{"threadId": "t1"}, {}]}, {}],
            "historyId": "9000",
        }
    })

    result = gmail_history(GmailHistoryInput(start_history_id="1"), service=svc)

    assert [h.id for h in result.data.history] == ["", ""]
    assert result.data.history[0].messages[0].id == ""


def test_gmail_labels_tolerates_sparse_label_records() -> None:
    svc = _GmailSvc({("labels", "list"): {"labels": [{"name": "OnlyName"}, {}]}})

    result = gmail_labels(GmailLabelsInput(), service=svc)

    assert result.data.count == 2
    assert [label.id for label in result.data.labels] == ["", ""]
