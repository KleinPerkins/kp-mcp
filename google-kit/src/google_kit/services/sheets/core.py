"""Core functions for the Sheets service (cutover-minimum: 6 ops).

Parity coverage per op:

  sheets_create    — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  sheets_read      — mock-read DONE; sandbox-e2e DEFERRED(P6)
  sheets_write     — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  sheets_add_sheet — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  sheets_info      — mock-read DONE; sandbox-e2e DEFERRED(P6)
  sheets_chart     — mutation-request DONE; sandbox-e2e DEFERRED(P6)

Legacy quirks preserved:
  - sheets_create: optional folder move is a SEPARATE ``drive.files.update``
    call after spreadsheet creation (two distinct API calls, not atomic).
    ``drive_service`` is a second injectable; defaults to None (Phase 5 wires).
  - sheets_write: ``clear_first=True`` issues ``values.clear`` BEFORE
    ``values.update``. The two calls are NOT atomic — a partial failure
    leaves the range cleared but un-written. Matches legacy behaviour.
  - sheets_chart: anchor column auto-calculated as
    ``max(r.end_col for r in y_ranges) + 1`` at row 0 (matches legacy).
    PIE chart uses ``pieChart`` spec; all others use ``basicChart`` spec.
    ``stacked=True`` adds ``stackedType: STACKED`` to ``basicChart``.
"""
from __future__ import annotations

from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope

from .models import (
    SheetGridRange,
    SheetInfo,
    SheetsAddSheetData,
    SheetsAddSheetInput,
    SheetsAddSheetOutput,
    SheetsAppendData,
    SheetsAppendInput,
    SheetsAppendOutput,
    SheetsChartData,
    SheetsChartInput,
    SheetsChartOutput,
    SheetsConditionalFormatData,
    SheetsConditionalFormatInput,
    SheetsConditionalFormatOutput,
    SheetsCreateData,
    SheetsCreateInput,
    SheetsCreateOutput,
    SheetsInfoData,
    SheetsInfoInput,
    SheetsInfoOutput,
    SheetsMetadataData,
    SheetsMetadataInput,
    SheetsMetadataOutput,
    SheetsPivotData,
    SheetsPivotInput,
    SheetsPivotOutput,
    SheetsReadData,
    SheetsReadInput,
    SheetsReadOutput,
    SheetsWriteData,
    SheetsWriteInput,
    SheetsWriteOutput,
)

_CHART_TYPE_MAP: dict[str, str] = {
    "bar": "BAR",
    "column": "COLUMN",
    "line": "LINE",
    "area": "AREA",
    "pie": "PIE",
    "scatter": "SCATTER",
    "combo": "COMBO",
}


def _wrap(data: Any, op: str) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, meta=Meta(op=op))


def _grid(r: SheetGridRange, sheet_id: int) -> dict[str, Any]:
    return {
        "sheetId": sheet_id,
        "startRowIndex": r.start_row,
        "endRowIndex": r.end_row,
        "startColumnIndex": r.start_col,
        "endColumnIndex": r.end_col,
    }


def sheets_create(
    inp: SheetsCreateInput,
    *,
    service: Any = None,
    drive_service: Any = None,
) -> SheetsCreateOutput:
    """Create a new spreadsheet; optionally move it to a Drive folder.

    The folder move (when ``folder_id`` is provided) is a SEPARATE
    ``drive.files.update`` call — not atomic with spreadsheet creation.
    ``drive_service`` defaults to None; Phase 5 wires real Keychain auth.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    body: dict[str, Any] = {"properties": {"title": inp.title}}
    if inp.sheet_names:
        body["sheets"] = [{"properties": {"title": name}} for name in inp.sheet_names]

    raw = execute_api_call(
        lambda: service.spreadsheets().create(body=body).execute(),
        op="sheets.create",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    created = raw or {}
    ss_id = created.get("spreadsheetId", "")

    if inp.folder_id and drive_service is not None:
        folder_id = inp.folder_id
        execute_api_call(
            lambda: drive_service.files().update(
                fileId=ss_id,
                addParents=folder_id,
                removeParents="root",
                fields="id,parents",
            ).execute(),
            op="sheets.create.move",
            posture="write",
            normalized_request={"spreadsheet_id": ss_id, "folder_id": folder_id},
            target_ids=[ss_id],
        )

    sheets_titles = [
        s["properties"]["title"] for s in created.get("sheets", [])
    ]
    return _wrap(
        SheetsCreateData(
            spreadsheet_id=ss_id,
            url=f"https://docs.google.com/spreadsheets/d/{ss_id}",
            title=created.get("properties", {}).get("title", inp.title),
            sheets=sheets_titles,
        ),
        "sheets.create",
    )


def sheets_read(
    inp: SheetsReadInput,
    *,
    service: Any = None,
) -> SheetsReadOutput:
    """Read cell values from a spreadsheet range (A1 notation).

    The ``range`` is passed as-is; the API normalizes it in the response.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.spreadsheets().values().get(
            spreadsheetId=inp.spreadsheet_id,
            range=inp.range,
        ).execute(),
        op="sheets.read",
        posture="read",
    )
    result = raw or {}
    values: list[list[Any]] = result.get("values", [])
    return _wrap(
        SheetsReadData(
            range=result.get("range"),
            rows=len(values),
            values=values,
        ),
        "sheets.read",
    )


def sheets_write(
    inp: SheetsWriteInput,
    *,
    service: Any = None,
) -> SheetsWriteOutput:
    """Write cell values to a spreadsheet range.

    When ``clear_first=True``, a ``values.clear`` call is issued before the
    write.  The two calls are NOT atomic — a failure between them leaves the
    range cleared but un-written.  Matches legacy ``--clear-first`` behaviour.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    if inp.clear_first:
        execute_api_call(
            lambda: service.spreadsheets().values().clear(
                spreadsheetId=inp.spreadsheet_id,
                range=inp.range,
                body={},
            ).execute(),
            op="sheets.write.clear",
            posture="write",
            normalized_request={"spreadsheet_id": inp.spreadsheet_id, "range": inp.range},
            target_ids=[inp.spreadsheet_id],
        )

    write_body: dict[str, Any] = {"values": inp.values}
    raw = execute_api_call(
        lambda: service.spreadsheets().values().update(
            spreadsheetId=inp.spreadsheet_id,
            range=inp.range,
            valueInputOption=inp.value_input_option,
            body=write_body,
        ).execute(),
        op="sheets.write",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.spreadsheet_id],
    )
    result = raw or {}
    return _wrap(
        SheetsWriteData(
            updated_rows=result.get("updatedRows", 0),
            updated_columns=result.get("updatedColumns", 0),
            updated_range=result.get("updatedRange"),
        ),
        "sheets.write",
    )


def sheets_add_sheet(
    inp: SheetsAddSheetInput,
    *,
    service: Any = None,
) -> SheetsAddSheetOutput:
    """Add a new tab to an existing spreadsheet via batchUpdate/addSheet.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    batch_body: dict[str, Any] = {
        "requests": [{"addSheet": {"properties": {"title": inp.title}}}]
    }
    raw = execute_api_call(
        lambda: service.spreadsheets().batchUpdate(
            spreadsheetId=inp.spreadsheet_id,
            body=batch_body,
        ).execute(),
        op="sheets.add_sheet",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.spreadsheet_id],
    )
    result = raw or {}
    new_sheet = (
        result.get("replies", [{}])[0]
        .get("addSheet", {})
        .get("properties", {})
    )
    return _wrap(
        SheetsAddSheetData(
            sheet_id=new_sheet.get("sheetId", 0),
            title=new_sheet.get("title", inp.title),
        ),
        "sheets.add_sheet",
    )


def sheets_info(
    inp: SheetsInfoInput,
    *,
    service: Any = None,
) -> SheetsInfoOutput:
    """Get spreadsheet metadata (title, sheet list, row/column counts).

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.spreadsheets().get(
            spreadsheetId=inp.spreadsheet_id,
        ).execute(),
        op="sheets.info",
        posture="read",
    )
    sp = raw or {}
    ss_id = sp.get("spreadsheetId", inp.spreadsheet_id)
    sheet_items: list[SheetInfo] = []
    for s in sp.get("sheets", []):
        props = s.get("properties", {})
        grid = props.get("gridProperties", {})
        sheet_items.append(
            SheetInfo(
                sheet_id=props.get("sheetId", 0),
                title=props.get("title", ""),
                row_count=grid.get("rowCount", 0),
                col_count=grid.get("columnCount", 0),
            )
        )
    return _wrap(
        SheetsInfoData(
            title=sp.get("properties", {}).get("title", ""),
            spreadsheet_id=ss_id,
            url=f"https://docs.google.com/spreadsheets/d/{ss_id}",
            sheets=sheet_items,
        ),
        "sheets.info",
    )


def sheets_chart(
    inp: SheetsChartInput,
    *,
    service: Any = None,
) -> SheetsChartOutput:
    """Create an embedded chart via batchUpdate/addChart.

    Anchor column is auto-calculated as ``max(r.end_col for r in y_ranges) + 1``
    at row 0 (matches legacy behaviour).
    PIE charts use ``pieChart`` spec; all other types use ``basicChart``.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    chart_type = _CHART_TYPE_MAP.get(inp.chart_type.lower(), inp.chart_type.upper())

    domain = {
        "sourceRange": {"sources": [_grid(inp.x_range, inp.sheet_id)]}
    }
    series = [
        {
            "series": {"sourceRange": {"sources": [_grid(yr, inp.sheet_id)]}},
            "targetAxis": "LEFT_AXIS",
        }
        for yr in inp.y_ranges
    ]

    if chart_type == "PIE":
        spec: dict[str, Any] = {
            "title": inp.title,
            "pieChart": {
                "legendPosition": "RIGHT_LEGEND",
                "domain": domain,
                "series": series[0]["series"],
            },
        }
    else:
        basic: dict[str, Any] = {
            "chartType": chart_type,
            "legendPosition": "BOTTOM_LEGEND",
            "axis": [{"position": "BOTTOM_AXIS"}, {"position": "LEFT_AXIS"}],
            "domains": [{"domain": domain}],
            "series": series,
            "headerCount": 1,
        }
        if inp.stacked:
            basic["stackedType"] = "STACKED"
        spec = {"title": inp.title, "basicChart": basic}

    anchor_col = max(r.end_col for r in inp.y_ranges) + 1
    anchor: dict[str, Any] = {
        "sheetId": inp.sheet_id,
        "rowIndex": 0,
        "columnIndex": anchor_col,
    }

    chart_body: dict[str, Any] = {
        "requests": [
            {
                "addChart": {
                    "chart": {
                        "spec": spec,
                        "position": {
                            "overlayPosition": {"anchorCell": anchor}
                        },
                    }
                }
            }
        ]
    }

    raw = execute_api_call(
        lambda: service.spreadsheets().batchUpdate(
            spreadsheetId=inp.spreadsheet_id,
            body=chart_body,
        ).execute(),
        op="sheets.chart",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.spreadsheet_id],
    )
    result = raw or {}
    chart_id = (
        result.get("replies", [{}])[0]
        .get("addChart", {})
        .get("chart", {})
        .get("chartId", 0)
    )
    return _wrap(SheetsChartData(chart_id=chart_id), "sheets.chart")


def sheets_append(
    inp: SheetsAppendInput,
    *,
    service: Any = None,
) -> SheetsAppendOutput:
    """Append rows to a spreadsheet range via values.append.

    Parity: mutation-request DONE; sandbox-e2e live-PASS 2026-06-17
    """
    append_body: dict[str, Any] = {"values": inp.values}
    raw = execute_api_call(
        lambda: service.spreadsheets().values().append(
            spreadsheetId=inp.spreadsheet_id,
            range=inp.range,
            valueInputOption=inp.value_input_option,
            insertDataOption=inp.insert_data_option,
            body=append_body,
        ).execute(),
        op="sheets.append",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.spreadsheet_id],
    )
    updates = (raw or {}).get("updates", {})
    return _wrap(
        SheetsAppendData(
            updated_range=updates.get("updatedRange"),
            updated_rows=updates.get("updatedRows", 0),
            updated_columns=updates.get("updatedColumns", 0),
            updated_cells=updates.get("updatedCells", 0),
        ),
        "sheets.append",
    )


def sheets_pivot(
    inp: SheetsPivotInput,
    *,
    service: Any = None,
) -> SheetsPivotOutput:
    """Create a pivot table via batchUpdate/updateCells with pivotTable field.

    Parity: mutation-request DONE; sandbox-e2e live-PASS 2026-06-17
    """
    r = inp.source_range
    pivot_table: dict[str, Any] = {
        "source": {
            "sheetId": inp.source_sheet_id,
            "startRowIndex": r.start_row,
            "endRowIndex": r.end_row,
            "startColumnIndex": r.start_col,
            "endColumnIndex": r.end_col,
        },
    }
    if inp.rows:
        pivot_table["rows"] = [
            {"sourceColumnOffset": offset, "sortOrder": "ASCENDING", "showTotals": True}
            for offset in inp.rows
        ]
    if inp.columns:
        pivot_table["columns"] = [
            {"sourceColumnOffset": offset, "sortOrder": "ASCENDING", "showTotals": True}
            for offset in inp.columns
        ]
    if inp.values:
        pivot_table["values"] = [
            {
                "sourceColumnOffset": v.source_column_offset,
                "summarizeFunction": v.summarize_function,
            }
            for v in inp.values
        ]

    batch_body: dict[str, Any] = {
        "requests": [
            {
                "updateCells": {
                    "rows": [{"values": [{"pivotTable": pivot_table}]}],
                    "start": {
                        "sheetId": inp.target_sheet_id,
                        "rowIndex": inp.target_row,
                        "columnIndex": inp.target_col,
                    },
                    "fields": "pivotTable",
                }
            }
        ]
    }
    raw = execute_api_call(
        lambda: service.spreadsheets().batchUpdate(
            spreadsheetId=inp.spreadsheet_id,
            body=batch_body,
        ).execute(),
        op="sheets.pivot",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.spreadsheet_id],
    )
    result = raw or {}
    return _wrap(
        SheetsPivotData(
            spreadsheet_id=inp.spreadsheet_id,
            replies_count=len(result.get("replies", [])),
        ),
        "sheets.pivot",
    )


def sheets_conditional_format(
    inp: SheetsConditionalFormatInput,
    *,
    service: Any = None,
) -> SheetsConditionalFormatOutput:
    """Add a conditional format rule via batchUpdate/addConditionalFormatRule.

    Parity: mutation-request DONE; sandbox-e2e live-PASS 2026-06-17
    """
    r = inp.range
    grid_range: dict[str, Any] = {
        "sheetId": inp.sheet_id,
        "startRowIndex": r.start_row,
        "endRowIndex": r.end_row,
        "startColumnIndex": r.start_col,
        "endColumnIndex": r.end_col,
    }
    condition: dict[str, Any] = {
        "type": inp.condition_type,
        "values": [{"userEnteredValue": v} for v in inp.condition_values],
    }
    fmt: dict[str, Any] = {}
    if inp.background_color is not None:
        fmt["backgroundColor"] = {
            "red": inp.background_color.red,
            "green": inp.background_color.green,
            "blue": inp.background_color.blue,
        }
    if inp.bold is not None:
        fmt["textFormat"] = {"bold": inp.bold}

    batch_body: dict[str, Any] = {
        "requests": [
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [grid_range],
                        "booleanRule": {
                            "condition": condition,
                            "format": fmt,
                        },
                    },
                    "index": inp.index,
                }
            }
        ]
    }
    raw = execute_api_call(
        lambda: service.spreadsheets().batchUpdate(
            spreadsheetId=inp.spreadsheet_id,
            body=batch_body,
        ).execute(),
        op="sheets.conditional_format",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.spreadsheet_id],
    )
    result = raw or {}
    return _wrap(
        SheetsConditionalFormatData(
            spreadsheet_id=inp.spreadsheet_id,
            replies_count=len(result.get("replies", [])),
        ),
        "sheets.conditional_format",
    )


def sheets_metadata(
    inp: SheetsMetadataInput,
    *,
    service: Any = None,
) -> SheetsMetadataOutput:
    """Create developer metadata on a spreadsheet or sheet via batchUpdate/createDeveloperMetadata.

    Parity: mutation-request DONE; sandbox-e2e live-PASS 2026-06-17
    """
    if inp.location_sheet_id is not None:
        location: dict[str, Any] = {"sheetId": inp.location_sheet_id}
    else:
        location = {"spreadsheet": True}

    batch_body: dict[str, Any] = {
        "requests": [
            {
                "createDeveloperMetadata": {
                    "developerMetadata": {
                        "metadataKey": inp.metadata_key,
                        "metadataValue": inp.metadata_value,
                        "visibility": inp.visibility,
                        "location": location,
                    }
                }
            }
        ]
    }
    raw = execute_api_call(
        lambda: service.spreadsheets().batchUpdate(
            spreadsheetId=inp.spreadsheet_id,
            body=batch_body,
        ).execute(),
        op="sheets.metadata",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.spreadsheet_id],
    )
    result = raw or {}
    return _wrap(
        SheetsMetadataData(
            spreadsheet_id=inp.spreadsheet_id,
            replies_count=len(result.get("replies", [])),
        ),
        "sheets.metadata",
    )
