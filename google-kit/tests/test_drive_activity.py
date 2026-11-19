"""Tests for the Drive Activity service.

Coverage:
  drive_activity_query — mock-read parity (normalized-json)

Parity status:
  drive_activity_query — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.parity import compare


@pytest.fixture(autouse=True, scope="module")
def _ensure_drive_activity() -> None:
    """Re-register Drive Activity ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.drive_activity as da_mod

    if "drive_activity.query" not in {s.name for s in reg.all_specs()}:
        importlib.reload(da_mod)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "drive_activity"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@dataclass
class _ActivityRequestRecord:
    """One recorded outgoing Drive Activity API call."""

    method: str
    body: dict[str, Any] = field(default_factory=dict)


class _ActivityExecutable:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _ActivityResourceProxy:
    """Proxy for ``service.activity()``."""

    def __init__(
        self,
        response: Any,
        requests: list[_ActivityRequestRecord],
    ) -> None:
        self._response = response
        self._requests = requests

    def query(self, body: dict[str, Any] | None = None) -> _ActivityExecutable:
        self._requests.append(
            _ActivityRequestRecord(method="query", body=dict(body or {}))
        )
        return _ActivityExecutable(self._response)


class MockDriveActivityService:
    """Test-local fake Drive Activity service for mock-read parity tests."""

    def __init__(self, response: Any = None) -> None:
        self._response = response
        self._requests: list[_ActivityRequestRecord] = []

    def activity(self) -> _ActivityResourceProxy:
        return _ActivityResourceProxy(self._response, self._requests)

    def get_requests(self) -> list[_ActivityRequestRecord]:
        return list(self._requests)

    def reset(self) -> None:
        self._requests.clear()


class TestDriveActivityQuery:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        response = _load("query_response.json")
        expected = _load("query_expected.json")

        svc = MockDriveActivityService(response=response)
        result = drive_activity_query(
            DriveActivityQueryInput(item_name="items/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_activities_count(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        response = _load("query_response.json")
        svc = MockDriveActivityService(response=response)
        result = drive_activity_query(
            DriveActivityQueryInput(item_name="items/FILE_ID"),
            service=svc,
        )
        assert len(result.data.activities) == 2

    def test_item_name_body_construction(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response={"activities": []})
        drive_activity_query(
            DriveActivityQueryInput(item_name="items/FILE_XYZ"),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.body.get("itemName") == "items/FILE_XYZ"
        assert "ancestorName" not in req.body

    def test_ancestor_name_body_construction(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response={"activities": []})
        drive_activity_query(
            DriveActivityQueryInput(ancestor_name="items/FOLDER_ID"),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.body.get("ancestorName") == "items/FOLDER_ID"
        assert "itemName" not in req.body

    def test_consolidation_strategy_legacy(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response={"activities": []})
        drive_activity_query(
            DriveActivityQueryInput(
                item_name="items/F1",
                consolidation_strategy="legacy",
            ),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.body.get("consolidationStrategy") == {"legacy": {}}

    def test_consolidation_strategy_none(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response={"activities": []})
        drive_activity_query(
            DriveActivityQueryInput(
                item_name="items/F1",
                consolidation_strategy="none",
            ),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.body.get("consolidationStrategy") == {"none": {}}

    def test_pagination_token_surfaced(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(
            response={"activities": [], "nextPageToken": "tok_page2"}
        )
        result = drive_activity_query(
            DriveActivityQueryInput(item_name="items/F1"),
            service=svc,
        )
        assert result.page is not None
        assert result.page.next_page_token == "tok_page2"

    def test_page_token_forwarded_in_body(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response={"activities": []})
        drive_activity_query(
            DriveActivityQueryInput(item_name="items/F1", page_token="tok_page2"),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.body.get("pageToken") == "tok_page2"

    def test_no_next_page_token_when_absent(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response={"activities": []})
        result = drive_activity_query(
            DriveActivityQueryInput(item_name="items/F1"),
            service=svc,
        )
        assert result.page is not None
        assert result.page.next_page_token is None

    def test_null_response_handled(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response=None)
        result = drive_activity_query(
            DriveActivityQueryInput(item_name="items/F1"),
            service=svc,
        )
        assert result.data.activities == []
        assert result.page is not None
        assert result.page.next_page_token is None

    def test_filter_forwarded_in_body(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response={"activities": []})
        drive_activity_query(
            DriveActivityQueryInput(
                item_name="items/F1",
                filter="detail.action_detail_case:EDIT",
            ),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.body.get("filter") == "detail.action_detail_case:EDIT"

    def test_page_size_forwarded_in_body(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response={"activities": []})
        drive_activity_query(
            DriveActivityQueryInput(item_name="items/F1", page_size=50),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.body.get("pageSize") == 50

    def test_optional_fields_absent_when_none(self) -> None:
        from google_kit.services.drive_activity.core import drive_activity_query
        from google_kit.services.drive_activity.models import DriveActivityQueryInput

        svc = MockDriveActivityService(response={"activities": []})
        drive_activity_query(
            DriveActivityQueryInput(item_name="items/F1"),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert "filter" not in req.body
        assert "consolidationStrategy" not in req.body
        assert "pageSize" not in req.body
        assert "pageToken" not in req.body


class TestDriveActivityRegistryIntegration:
    def test_op_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        assert "drive_activity.query" in names

    def test_posture_is_read(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["drive_activity.query"].posture == "read"

    def test_scope_is_drive_activity_readonly(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        scope = "https://www.googleapis.com/auth/drive.activity.readonly"
        assert scope in specs["drive_activity.query"].scopes

    def test_plane_and_capability(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["drive_activity.query"].plane == "history"
        assert specs["drive_activity.query"].capability == "history.read"
