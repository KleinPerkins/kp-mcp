"""Tests for the Sheets service.

Coverage:
  sheets_create             — mutation-request parity (spreadsheets.create body; drive folder-move body)
  sheets_read               — mock-read parity (normalized-json)
  sheets_write              — mutation-request parity (values.update body; clear+write two-call)
  sheets_add_sheet          — mutation-request parity (batchUpdate/addSheet body)
  sheets_info               — mock-read parity (normalized-json)
  sheets_chart              — mutation-request parity (batchUpdate/addChart body; anchor auto-calc)
  sheets_append             — mutation-request parity (values.append body)
  sheets_pivot              — mutation-request parity (batchUpdate/updateCells/pivotTable body)
  sheets_conditional_format — mutation-request parity (batchUpdate/addConditionalFormatRule body)
  sheets_metadata           — mutation-request parity (batchUpdate/createDeveloperMetadata body)

Parity status per op:
  sheets_create             — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  sheets_read               — mock-read DONE; sandbox-e2e DEFERRED(P6)
  sheets_write              — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  sheets_add_sheet          — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  sheets_info               — mock-read DONE; sandbox-e2e DEFERRED(P6)
  sheets_chart              — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  sheets_append             — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  sheets_pivot              — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  sheets_conditional_format — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)
  sheets_metadata           — mutation-request DONE; sandbox-e2e DEFERRED(E2/E4)

Test-local mock classes (MockSheetsService, MockDriveService) are required
because the Sheets API uses nested resource chains (spreadsheets().values().get())
that the shared MockGoogleService does not model.  They follow the same
RequestRecord / last_request_body / requests_for contract.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.parity import compare

FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "sheets"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# ─── Test-local mock infrastructure ──────────────────────────────────────────


@dataclass
class _SheetsRecord:
    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> dict[str, Any] | None:
        return self.kwargs.get("body")


class _FakeExec:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _FakeValuesProxy:
    def __init__(self, responses: dict, log: list[_SheetsRecord]) -> None:
        self._responses = responses
        self._log = log

    def get(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_SheetsRecord("values", "get", dict(kwargs)))
        return _FakeExec(self._responses.get(("values", "get")))

    def update(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_SheetsRecord("values", "update", dict(kwargs)))
        return _FakeExec(self._responses.get(("values", "update")))

    def clear(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_SheetsRecord("values", "clear", dict(kwargs)))
        return _FakeExec(self._responses.get(("values", "clear")))

    def append(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_SheetsRecord("values", "append", dict(kwargs)))
        return _FakeExec(self._responses.get(("values", "append")))


class _FakeSpreadsheetsProxy:
    def __init__(self, responses: dict, log: list[_SheetsRecord]) -> None:
        self._responses = responses
        self._log = log

    def create(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_SheetsRecord("spreadsheets", "create", dict(kwargs)))
        return _FakeExec(self._responses.get(("spreadsheets", "create")))

    def get(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_SheetsRecord("spreadsheets", "get", dict(kwargs)))
        return _FakeExec(self._responses.get(("spreadsheets", "get")))

    def batchUpdate(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_SheetsRecord("spreadsheets", "batchUpdate", dict(kwargs)))
        return _FakeExec(self._responses.get(("spreadsheets", "batchUpdate")))

    def values(self) -> _FakeValuesProxy:
        return _FakeValuesProxy(self._responses, self._log)


class MockSheetsService:
    """Test-local mock for the Google Sheets API service (sheets v4)."""

    def __init__(self, responses: dict | None = None) -> None:
        self._responses: dict = responses or {}
        self._log: list[_SheetsRecord] = []

    def spreadsheets(self) -> _FakeSpreadsheetsProxy:
        return _FakeSpreadsheetsProxy(self._responses, self._log)

    def last_request_body(self) -> dict[str, Any] | None:
        for rec in reversed(self._log):
            if rec.body is not None:
                return rec.body
        return None

    def requests_for(self, resource: str, method: str) -> list[_SheetsRecord]:
        return [r for r in self._log if r.resource == resource and r.method == method]

    def reset(self) -> None:
        self._log.clear()


class _FakeFilesProxy:
    def __init__(self, responses: dict, log: list[_SheetsRecord]) -> None:
        self._responses = responses
        self._log = log

    def update(self, **kwargs: Any) -> _FakeExec:
        self._log.append(_SheetsRecord("files", "update", dict(kwargs)))
        return _FakeExec(self._responses.get(("files", "update")))


class MockDriveService:
    """Test-local mock for the Google Drive API service (files.update only)."""

    def __init__(self, responses: dict | None = None) -> None:
        self._responses: dict = responses or {}
        self._log: list[_SheetsRecord] = []

    def files(self) -> _FakeFilesProxy:
        return _FakeFilesProxy(self._responses, self._log)

    def last_request_kwargs(self) -> dict[str, Any] | None:
        if self._log:
            return self._log[-1].kwargs
        return None

    def requests_for(self, resource: str, method: str) -> list[_SheetsRecord]:
        return [r for r in self._log if r.resource == resource and r.method == method]


# ─── Registry isolation fixture ──────────────────────────────────────────────


@pytest.fixture(autouse=True, scope="module")
def _ensure_sheets() -> None:
    """Re-register Sheets ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.sheets as sheets_mod

    if not {"sheets.create", "sheets.append", "sheets.pivot"}.issubset(
        {s.name for s in reg.all_specs()}
    ):
        importlib.reload(sheets_mod)


# ─── sheets.create ────────────────────────────────────────────────────────────


class TestSheetsCreate:
    def test_mutation_request_parity_body(self) -> None:
        from google_kit.services.sheets.core import sheets_create
        from google_kit.services.sheets.models import SheetsCreateInput

        expected_body = _load("create_expected_body.json")
        canned_response = {
            "spreadsheetId": "ss001",
            "properties": {"title": "Test Sheet"},
            "sheets": [
                {"properties": {"title": "Tab1"}},
                {"properties": {"title": "Tab2"}},
            ],
        }
        svc = MockSheetsService(responses={("spreadsheets", "create"): canned_response})
        sheets_create(
            SheetsCreateInput(title="Test Sheet", sheet_names=["Tab1", "Tab2"]),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_folder_move_drive_call(self) -> None:
        from google_kit.services.sheets.core import sheets_create
        from google_kit.services.sheets.models import SheetsCreateInput

        canned_ss = {
            "spreadsheetId": "ss001",
            "properties": {"title": "Moved Sheet"},
            "sheets": [],
        }
        svc = MockSheetsService(responses={("spreadsheets", "create"): canned_ss})
        drive_svc = MockDriveService(responses={("files", "update"): {"id": "ss001", "parents": ["folder123"]}})

        sheets_create(
            SheetsCreateInput(title="Moved Sheet", folder_id="folder123"),
            service=svc,
            drive_service=drive_svc,
        )

        file_reqs = drive_svc.requests_for("files", "update")
        assert len(file_reqs) == 1
        kw = file_reqs[0].kwargs
        assert kw["fileId"] == "ss001"
        assert kw["addParents"] == "folder123"
        assert kw["removeParents"] == "root"
        assert kw["fields"] == "id,parents"

    def test_no_folder_no_drive_call(self) -> None:
        from google_kit.services.sheets.core import sheets_create
        from google_kit.services.sheets.models import SheetsCreateInput

        canned_ss = {
            "spreadsheetId": "ss002",
            "properties": {"title": "No Folder"},
            "sheets": [],
        }
        svc = MockSheetsService(responses={("spreadsheets", "create"): canned_ss})
        drive_svc = MockDriveService()

        sheets_create(SheetsCreateInput(title="No Folder"), service=svc, drive_service=drive_svc)
        assert drive_svc.requests_for("files", "update") == []

    def test_no_sheet_names_no_sheets_field(self) -> None:
        from google_kit.services.sheets.core import sheets_create
        from google_kit.services.sheets.models import SheetsCreateInput

        canned_ss = {"spreadsheetId": "ss003", "properties": {"title": "Plain"}, "sheets": []}
        svc = MockSheetsService(responses={("spreadsheets", "create"): canned_ss})
        sheets_create(SheetsCreateInput(title="Plain"), service=svc)
        body = svc.last_request_body()
        assert body is not None
        assert "sheets" not in body

    def test_output_envelope(self) -> None:
        from google_kit.services.sheets.core import sheets_create
        from google_kit.services.sheets.models import SheetsCreateInput

        canned_ss = {
            "spreadsheetId": "ss004",
            "properties": {"title": "Out"},
            "sheets": [{"properties": {"title": "Tab1"}}],
        }
        svc = MockSheetsService(responses={("spreadsheets", "create"): canned_ss})
        result = sheets_create(SheetsCreateInput(title="Out", sheet_names=["Tab1"]), service=svc)
        assert result.data.spreadsheet_id == "ss004"
        assert result.data.url == "https://docs.google.com/spreadsheets/d/ss004"
        assert result.data.sheets == ["Tab1"]


# ─── sheets.read ──────────────────────────────────────────────────────────────


class TestSheetsRead:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.sheets.core import sheets_read
        from google_kit.services.sheets.models import SheetsReadInput

        response = _load("read_response.json")
        expected = _load("read_expected.json")

        svc = MockSheetsService(responses={("values", "get"): response})
        result = sheets_read(
            SheetsReadInput(spreadsheet_id="ss001", range="Sheet1!A1:C3"),
            service=svc,
        )
        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_empty_range(self) -> None:
        from google_kit.services.sheets.core import sheets_read
        from google_kit.services.sheets.models import SheetsReadInput

        svc = MockSheetsService(responses={("values", "get"): {"range": "Sheet1!A1"}})
        result = sheets_read(SheetsReadInput(spreadsheet_id="ss001", range="Sheet1!A1"), service=svc)
        assert result.data.rows == 0
        assert result.data.values == []

    def test_range_passed_to_api(self) -> None:
        from google_kit.services.sheets.core import sheets_read
        from google_kit.services.sheets.models import SheetsReadInput

        svc = MockSheetsService(responses={("values", "get"): {}})
        sheets_read(SheetsReadInput(spreadsheet_id="ss001", range="Data!B2:D5"), service=svc)
        reqs = svc.requests_for("values", "get")
        assert len(reqs) == 1
        assert reqs[0].kwargs["range"] == "Data!B2:D5"
        assert reqs[0].kwargs["spreadsheetId"] == "ss001"


# ─── sheets.write ─────────────────────────────────────────────────────────────


class TestSheetsWrite:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.sheets.core import sheets_write
        from google_kit.services.sheets.models import SheetsWriteInput

        expected_body = _load("write_expected_body.json")
        canned_update = {
            "updatedRange": "Sheet1!A1:B3",
            "updatedRows": 3,
            "updatedColumns": 2,
        }
        svc = MockSheetsService(responses={("values", "update"): canned_update})
        sheets_write(
            SheetsWriteInput(
                spreadsheet_id="ss001",
                range="Sheet1!A1",
                values=[["Name", "Score"], ["Alice", 92], ["Bob", 78]],
                value_input_option="USER_ENTERED",
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_clear_first_issues_two_calls(self) -> None:
        from google_kit.services.sheets.core import sheets_write
        from google_kit.services.sheets.models import SheetsWriteInput

        canned_update = {"updatedRows": 1, "updatedColumns": 1}
        svc = MockSheetsService(responses={
            ("values", "clear"): {"clearedRange": "Sheet1!A1:B2"},
            ("values", "update"): canned_update,
        })
        sheets_write(
            SheetsWriteInput(
                spreadsheet_id="ss001",
                range="Sheet1!A1",
                values=[["X"]],
                clear_first=True,
            ),
            service=svc,
        )
        assert len(svc.requests_for("values", "clear")) == 1
        assert len(svc.requests_for("values", "update")) == 1

    def test_clear_body_is_empty_dict(self) -> None:
        from google_kit.services.sheets.core import sheets_write
        from google_kit.services.sheets.models import SheetsWriteInput

        svc = MockSheetsService(responses={
            ("values", "clear"): {},
            ("values", "update"): {"updatedRows": 1, "updatedColumns": 1},
        })
        sheets_write(
            SheetsWriteInput(
                spreadsheet_id="ss001",
                range="Sheet1!A1",
                values=[["X"]],
                clear_first=True,
            ),
            service=svc,
        )
        clear_reqs = svc.requests_for("values", "clear")
        assert clear_reqs[0].body == {}

    def test_no_clear_first_no_clear_call(self) -> None:
        from google_kit.services.sheets.core import sheets_write
        from google_kit.services.sheets.models import SheetsWriteInput

        svc = MockSheetsService(responses={("values", "update"): {"updatedRows": 1, "updatedColumns": 1}})
        sheets_write(
            SheetsWriteInput(spreadsheet_id="ss001", range="A1", values=[["X"]]),
            service=svc,
        )
        assert svc.requests_for("values", "clear") == []

    def test_value_input_option_passed(self) -> None:
        from google_kit.services.sheets.core import sheets_write
        from google_kit.services.sheets.models import SheetsWriteInput

        svc = MockSheetsService(responses={("values", "update"): {"updatedRows": 1, "updatedColumns": 1}})
        sheets_write(
            SheetsWriteInput(
                spreadsheet_id="ss001",
                range="A1",
                values=[["X"]],
                value_input_option="RAW",
            ),
            service=svc,
        )
        req = svc.requests_for("values", "update")[0]
        assert req.kwargs["valueInputOption"] == "RAW"


# ─── sheets.add_sheet ─────────────────────────────────────────────────────────


class TestSheetsAddSheet:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.sheets.core import sheets_add_sheet
        from google_kit.services.sheets.models import SheetsAddSheetInput

        expected_body = _load("add_sheet_expected_body.json")
        canned_response = {
            "replies": [
                {"addSheet": {"properties": {"sheetId": 999, "title": "NewTab"}}}
            ]
        }
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        sheets_add_sheet(
            SheetsAddSheetInput(spreadsheet_id="ss001", title="NewTab"),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_output_sheet_id_and_title(self) -> None:
        from google_kit.services.sheets.core import sheets_add_sheet
        from google_kit.services.sheets.models import SheetsAddSheetInput

        canned_response = {
            "replies": [
                {"addSheet": {"properties": {"sheetId": 42, "title": "Reports"}}}
            ]
        }
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        result = sheets_add_sheet(
            SheetsAddSheetInput(spreadsheet_id="ss001", title="Reports"),
            service=svc,
        )
        assert result.data.sheet_id == 42
        assert result.data.title == "Reports"


# ─── sheets.info ──────────────────────────────────────────────────────────────


class TestSheetsInfo:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.sheets.core import sheets_info
        from google_kit.services.sheets.models import SheetsInfoInput

        response = _load("info_response.json")
        expected = _load("info_expected.json")

        svc = MockSheetsService(responses={("spreadsheets", "get"): response})
        result = sheets_info(SheetsInfoInput(spreadsheet_id="ss001"), service=svc)
        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_empty_sheets_list(self) -> None:
        from google_kit.services.sheets.core import sheets_info
        from google_kit.services.sheets.models import SheetsInfoInput

        response = {
            "spreadsheetId": "ss002",
            "properties": {"title": "Empty"},
            "sheets": [],
        }
        svc = MockSheetsService(responses={("spreadsheets", "get"): response})
        result = sheets_info(SheetsInfoInput(spreadsheet_id="ss002"), service=svc)
        assert result.data.sheets == []
        assert result.data.title == "Empty"

    def test_url_construction(self) -> None:
        from google_kit.services.sheets.core import sheets_info
        from google_kit.services.sheets.models import SheetsInfoInput

        response = {"spreadsheetId": "abc123", "properties": {"title": "T"}, "sheets": []}
        svc = MockSheetsService(responses={("spreadsheets", "get"): response})
        result = sheets_info(SheetsInfoInput(spreadsheet_id="abc123"), service=svc)
        assert result.data.url == "https://docs.google.com/spreadsheets/d/abc123"


# ─── sheets.chart ─────────────────────────────────────────────────────────────


class TestSheetsChart:
    def test_mutation_request_parity_bar(self) -> None:
        from google_kit.services.sheets.core import sheets_chart
        from google_kit.services.sheets.models import SheetGridRange, SheetsChartInput

        expected_body = _load("chart_expected_body.json")
        canned_response = {
            "replies": [{"addChart": {"chart": {"chartId": 7}}}]
        }
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        sheets_chart(
            SheetsChartInput(
                spreadsheet_id="ss001",
                title="Sales Chart",
                chart_type="bar",
                sheet_id=0,
                x_range=SheetGridRange(start_row=0, end_row=10, start_col=0, end_col=1),
                y_ranges=[SheetGridRange(start_row=0, end_row=10, start_col=1, end_col=2)],
                stacked=False,
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_anchor_auto_calc_max_end_col_plus_one(self) -> None:
        from google_kit.services.sheets.core import sheets_chart
        from google_kit.services.sheets.models import SheetGridRange, SheetsChartInput

        canned_response = {"replies": [{"addChart": {"chart": {"chartId": 1}}}]}
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        sheets_chart(
            SheetsChartInput(
                spreadsheet_id="ss001",
                title="T",
                chart_type="line",
                sheet_id=0,
                x_range=SheetGridRange(start_row=0, end_row=5, start_col=0, end_col=1),
                y_ranges=[
                    SheetGridRange(start_row=0, end_row=5, start_col=1, end_col=3),
                    SheetGridRange(start_row=0, end_row=5, start_col=3, end_col=5),
                ],
            ),
            service=svc,
        )
        body = svc.last_request_body()
        assert body is not None
        anchor = body["requests"][0]["addChart"]["chart"]["position"]["overlayPosition"]["anchorCell"]
        assert anchor["columnIndex"] == 6  # max(3, 5) + 1

    def test_pie_chart_uses_pie_spec(self) -> None:
        from google_kit.services.sheets.core import sheets_chart
        from google_kit.services.sheets.models import SheetGridRange, SheetsChartInput

        canned_response = {"replies": [{"addChart": {"chart": {"chartId": 2}}}]}
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        sheets_chart(
            SheetsChartInput(
                spreadsheet_id="ss001",
                title="Pie",
                chart_type="pie",
                sheet_id=0,
                x_range=SheetGridRange(start_row=0, end_row=5, start_col=0, end_col=1),
                y_ranges=[SheetGridRange(start_row=0, end_row=5, start_col=1, end_col=2)],
            ),
            service=svc,
        )
        body = svc.last_request_body()
        assert body is not None
        spec = body["requests"][0]["addChart"]["chart"]["spec"]
        assert "pieChart" in spec
        assert "basicChart" not in spec

    def test_stacked_adds_stacked_type(self) -> None:
        from google_kit.services.sheets.core import sheets_chart
        from google_kit.services.sheets.models import SheetGridRange, SheetsChartInput

        canned_response = {"replies": [{"addChart": {"chart": {"chartId": 3}}}]}
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        sheets_chart(
            SheetsChartInput(
                spreadsheet_id="ss001",
                title="Stacked",
                chart_type="bar",
                sheet_id=0,
                x_range=SheetGridRange(start_row=0, end_row=5, start_col=0, end_col=1),
                y_ranges=[SheetGridRange(start_row=0, end_row=5, start_col=1, end_col=2)],
                stacked=True,
            ),
            service=svc,
        )
        body = svc.last_request_body()
        basic = body["requests"][0]["addChart"]["chart"]["spec"]["basicChart"]
        assert basic["stackedType"] == "STACKED"

    def test_non_stacked_no_stacked_type(self) -> None:
        from google_kit.services.sheets.core import sheets_chart
        from google_kit.services.sheets.models import SheetGridRange, SheetsChartInput

        canned_response = {"replies": [{"addChart": {"chart": {"chartId": 4}}}]}
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        sheets_chart(
            SheetsChartInput(
                spreadsheet_id="ss001",
                title="Not Stacked",
                chart_type="column",
                sheet_id=0,
                x_range=SheetGridRange(start_row=0, end_row=5, start_col=0, end_col=1),
                y_ranges=[SheetGridRange(start_row=0, end_row=5, start_col=1, end_col=2)],
                stacked=False,
            ),
            service=svc,
        )
        body = svc.last_request_body()
        basic = body["requests"][0]["addChart"]["chart"]["spec"]["basicChart"]
        assert "stackedType" not in basic


# ─── sheets.append ────────────────────────────────────────────────────────────


class TestSheetsAppend:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.sheets.core import sheets_append
        from google_kit.services.sheets.models import SheetsAppendInput

        expected_body = _load("append_expected_body.json")
        canned_response = {
            "spreadsheetId": "ss001",
            "updates": {
                "updatedRange": "Sheet1!A4:B6",
                "updatedRows": 3,
                "updatedColumns": 2,
                "updatedCells": 6,
            },
        }
        svc = MockSheetsService(responses={("values", "append"): canned_response})
        sheets_append(
            SheetsAppendInput(
                spreadsheet_id="ss001",
                range="Sheet1!A1",
                values=[["Name", "Score"], ["Alice", 92], ["Bob", 78]],
                value_input_option="USER_ENTERED",
                insert_data_option="INSERT_ROWS",
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_output_envelope(self) -> None:
        from google_kit.services.sheets.core import sheets_append
        from google_kit.services.sheets.models import SheetsAppendInput

        canned_response = {
            "updates": {
                "updatedRange": "Sheet1!A2:B3",
                "updatedRows": 2,
                "updatedColumns": 2,
                "updatedCells": 4,
            }
        }
        svc = MockSheetsService(responses={("values", "append"): canned_response})
        result = sheets_append(
            SheetsAppendInput(spreadsheet_id="ss001", range="Sheet1!A1", values=[["X", "Y"]]),
            service=svc,
        )
        assert result.data.updated_rows == 2
        assert result.data.updated_columns == 2
        assert result.data.updated_cells == 4
        assert result.data.updated_range == "Sheet1!A2:B3"

    def test_kwargs_passed_to_api(self) -> None:
        from google_kit.services.sheets.core import sheets_append
        from google_kit.services.sheets.models import SheetsAppendInput

        svc = MockSheetsService(responses={("values", "append"): {"updates": {}}})
        sheets_append(
            SheetsAppendInput(
                spreadsheet_id="ss001",
                range="Data!B2",
                values=[["X"]],
                value_input_option="RAW",
                insert_data_option="OVERWRITE",
            ),
            service=svc,
        )
        reqs = svc.requests_for("values", "append")
        assert len(reqs) == 1
        assert reqs[0].kwargs["spreadsheetId"] == "ss001"
        assert reqs[0].kwargs["range"] == "Data!B2"
        assert reqs[0].kwargs["valueInputOption"] == "RAW"
        assert reqs[0].kwargs["insertDataOption"] == "OVERWRITE"


# ─── sheets.pivot ─────────────────────────────────────────────────────────────


class TestSheetsPivot:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.sheets.core import sheets_pivot
        from google_kit.services.sheets.models import (
            SheetGridRange,
            SheetsPivotInput,
            SheetsPivotValueSpec,
        )

        expected_body = _load("pivot_expected_body.json")
        canned_response = {"replies": [{}]}
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        sheets_pivot(
            SheetsPivotInput(
                spreadsheet_id="ss001",
                source_sheet_id=0,
                source_range=SheetGridRange(start_row=0, end_row=10, start_col=0, end_col=3),
                target_sheet_id=1,
                target_row=0,
                target_col=0,
                rows=[0],
                columns=[1],
                values=[SheetsPivotValueSpec(source_column_offset=2, summarize_function="SUM")],
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_output_envelope(self) -> None:
        from google_kit.services.sheets.core import sheets_pivot
        from google_kit.services.sheets.models import SheetGridRange, SheetsPivotInput

        canned_response = {"replies": [{}]}
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        result = sheets_pivot(
            SheetsPivotInput(
                spreadsheet_id="ss001",
                source_sheet_id=0,
                source_range=SheetGridRange(start_row=0, end_row=5, start_col=0, end_col=2),
                target_sheet_id=0,
                target_row=0,
                target_col=5,
            ),
            service=svc,
        )
        assert result.data.spreadsheet_id == "ss001"
        assert result.data.replies_count == 1

    def test_empty_rows_columns_values_omitted(self) -> None:
        from google_kit.services.sheets.core import sheets_pivot
        from google_kit.services.sheets.models import SheetGridRange, SheetsPivotInput

        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): {"replies": []}})
        sheets_pivot(
            SheetsPivotInput(
                spreadsheet_id="ss001",
                source_sheet_id=0,
                source_range=SheetGridRange(start_row=0, end_row=5, start_col=0, end_col=2),
                target_sheet_id=0,
                target_row=0,
                target_col=5,
            ),
            service=svc,
        )
        body = svc.last_request_body()
        pivot_table = body["requests"][0]["updateCells"]["rows"][0]["values"][0]["pivotTable"]
        assert "rows" not in pivot_table
        assert "columns" not in pivot_table
        assert "values" not in pivot_table


# ─── sheets.conditional_format ────────────────────────────────────────────────


class TestSheetsConditionalFormat:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.sheets.core import sheets_conditional_format
        from google_kit.services.sheets.models import (
            SheetGridRange,
            SheetsColorSpec,
            SheetsConditionalFormatInput,
        )

        expected_body = _load("conditional_format_expected_body.json")
        canned_response = {"replies": [{}]}
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        sheets_conditional_format(
            SheetsConditionalFormatInput(
                spreadsheet_id="ss001",
                sheet_id=0,
                range=SheetGridRange(start_row=1, end_row=10, start_col=2, end_col=3),
                condition_type="NUMBER_GREATER",
                condition_values=["100"],
                background_color=SheetsColorSpec(red=1.0, green=0.0, blue=0.0),
                bold=True,
                index=0,
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_output_envelope(self) -> None:
        from google_kit.services.sheets.core import sheets_conditional_format
        from google_kit.services.sheets.models import SheetGridRange, SheetsConditionalFormatInput

        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): {"replies": [{}]}})
        result = sheets_conditional_format(
            SheetsConditionalFormatInput(
                spreadsheet_id="ss001",
                sheet_id=0,
                range=SheetGridRange(start_row=0, end_row=5, start_col=0, end_col=1),
                condition_type="TEXT_EQ",
                condition_values=["done"],
            ),
            service=svc,
        )
        assert result.data.spreadsheet_id == "ss001"
        assert result.data.replies_count == 1

    def test_no_color_no_bold_empty_format(self) -> None:
        from google_kit.services.sheets.core import sheets_conditional_format
        from google_kit.services.sheets.models import SheetGridRange, SheetsConditionalFormatInput

        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): {"replies": []}})
        sheets_conditional_format(
            SheetsConditionalFormatInput(
                spreadsheet_id="ss001",
                sheet_id=0,
                range=SheetGridRange(start_row=0, end_row=5, start_col=0, end_col=1),
                condition_type="TEXT_EQ",
                condition_values=["x"],
            ),
            service=svc,
        )
        body = svc.last_request_body()
        rule = body["requests"][0]["addConditionalFormatRule"]["rule"]
        fmt = rule["booleanRule"]["format"]
        assert fmt == {}


# ─── sheets.metadata ──────────────────────────────────────────────────────────


class TestSheetsMetadata:
    def test_mutation_request_parity_spreadsheet_level(self) -> None:
        from google_kit.services.sheets.core import sheets_metadata
        from google_kit.services.sheets.models import SheetsMetadataInput

        expected_body = _load("metadata_expected_body.json")
        canned_response = {"replies": [{}]}
        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): canned_response})
        sheets_metadata(
            SheetsMetadataInput(
                spreadsheet_id="ss001",
                metadata_key="project",
                metadata_value="alpha",
                visibility="DOCUMENT",
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_sheet_level_location(self) -> None:
        from google_kit.services.sheets.core import sheets_metadata
        from google_kit.services.sheets.models import SheetsMetadataInput

        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): {"replies": [{}]}})
        sheets_metadata(
            SheetsMetadataInput(
                spreadsheet_id="ss001",
                metadata_key="tab",
                metadata_value="raw",
                location_sheet_id=5,
            ),
            service=svc,
        )
        body = svc.last_request_body()
        loc = body["requests"][0]["createDeveloperMetadata"]["developerMetadata"]["location"]
        assert loc == {"sheetId": 5}
        assert "spreadsheet" not in loc

    def test_spreadsheet_level_location(self) -> None:
        from google_kit.services.sheets.core import sheets_metadata
        from google_kit.services.sheets.models import SheetsMetadataInput

        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): {"replies": [{}]}})
        sheets_metadata(
            SheetsMetadataInput(
                spreadsheet_id="ss001",
                metadata_key="env",
                metadata_value="prod",
            ),
            service=svc,
        )
        body = svc.last_request_body()
        loc = body["requests"][0]["createDeveloperMetadata"]["developerMetadata"]["location"]
        assert loc == {"spreadsheet": True}

    def test_output_envelope(self) -> None:
        from google_kit.services.sheets.core import sheets_metadata
        from google_kit.services.sheets.models import SheetsMetadataInput

        svc = MockSheetsService(responses={("spreadsheets", "batchUpdate"): {"replies": [{}]}})
        result = sheets_metadata(
            SheetsMetadataInput(
                spreadsheet_id="ss_xyz",
                metadata_key="k",
                metadata_value="v",
            ),
            service=svc,
        )
        assert result.data.spreadsheet_id == "ss_xyz"
        assert result.data.replies_count == 1


# ─── Registry integration ─────────────────────────────────────────────────────


class TestRegistryIntegration:
    def test_all_ops_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        expected = {
            "sheets.create",
            "sheets.read",
            "sheets.write",
            "sheets.add_sheet",
            "sheets.info",
            "sheets.chart",
            "sheets.append",
            "sheets.pivot",
            "sheets.conditional_format",
            "sheets.metadata",
        }
        assert expected.issubset(names), f"Missing ops: {expected - names}"

    def test_postures(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["sheets.create"].posture == "write"
        assert specs["sheets.read"].posture == "read"
        assert specs["sheets.write"].posture == "write"
        assert specs["sheets.add_sheet"].posture == "write"
        assert specs["sheets.info"].posture == "read"
        assert specs["sheets.chart"].posture == "write"
        assert specs["sheets.append"].posture == "write"
        assert specs["sheets.pivot"].posture == "write"
        assert specs["sheets.conditional_format"].posture == "write"
        assert specs["sheets.metadata"].posture == "write"

    def test_capability_and_plane(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["sheets.append"].capability == "sheet.append"
        assert specs["sheets.append"].plane == "content"
        assert specs["sheets.pivot"].capability == "sheet.pivot"
        assert specs["sheets.pivot"].plane == "content"
        assert specs["sheets.conditional_format"].capability == "sheet.conditional_format"
        assert specs["sheets.conditional_format"].plane == "content"
        assert specs["sheets.metadata"].capability == "sheet.developer_metadata"
        assert specs["sheets.metadata"].plane == "content"

