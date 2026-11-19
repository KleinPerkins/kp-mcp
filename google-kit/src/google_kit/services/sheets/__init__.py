"""Sheets service — registers 10 ops (6 cutover-minimum + 4 §7 capability ops) in the google-kit registry."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    sheets_add_sheet,
    sheets_append,
    sheets_chart,
    sheets_conditional_format,
    sheets_create,
    sheets_info,
    sheets_metadata,
    sheets_pivot,
    sheets_read,
    sheets_write,
)
from .models import (
    SheetsAddSheetInput,
    SheetsAddSheetOutput,
    SheetsAppendInput,
    SheetsAppendOutput,
    SheetsChartInput,
    SheetsChartOutput,
    SheetsConditionalFormatInput,
    SheetsConditionalFormatOutput,
    SheetsCreateInput,
    SheetsCreateOutput,
    SheetsInfoInput,
    SheetsInfoOutput,
    SheetsMetadataInput,
    SheetsMetadataOutput,
    SheetsPivotInput,
    SheetsPivotOutput,
    SheetsReadInput,
    SheetsReadOutput,
    SheetsWriteInput,
    SheetsWriteOutput,
)

_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

#: Per-service F5 write gate (off by default). Satisfied by the
#: ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. See core/flags.py.
_SHEETS_WRITE_FLAG = "GOOGLE_KIT_ENABLE_SHEETS_WRITE"

register(OpSpec(
    name="sheets.create",
    fn=sheets_create,
    input_model=SheetsCreateInput,
    output_model=SheetsCreateOutput,
    posture="write",
    scopes=_SHEETS_SCOPES,
    perf={"api": "Sheets v4 + Drive v3", "method": "spreadsheets.create [+ files.update]", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a spreadsheet with two tabs in a folder",
        "input": {"title": "My Sheet", "sheet_names": ["Data", "Summary"], "folder_id": "<folder-id>"},
        "cli": "google-kit sheets create 'My Sheet' --sheet-names Data,Summary --folder-id <folder-id>",
    }],
    flag=_SHEETS_WRITE_FLAG,
))

register(OpSpec(
    name="sheets.read",
    fn=sheets_read,
    input_model=SheetsReadInput,
    output_model=SheetsReadOutput,
    posture="read",
    scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    perf={"api": "Sheets v4", "method": "spreadsheets.values.get", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Read a range from a spreadsheet",
        "input": {"spreadsheet_id": "<id>", "range": "Sheet1!A1:C10", "fmt": "json"},
        "cli": "google-kit sheets read <id> --range Sheet1!A1:C10",
    }],
))

register(OpSpec(
    name="sheets.write",
    fn=sheets_write,
    input_model=SheetsWriteInput,
    output_model=SheetsWriteOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
    perf={"api": "Sheets v4", "method": "spreadsheets.values.update [+ values.clear]", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Write data to a range",
        "input": {"spreadsheet_id": "<id>", "range": "Sheet1!A1", "values": [["A", "B"], [1, 2]], "value_input_option": "USER_ENTERED"},
        "cli": "google-kit sheets write <id> --range Sheet1!A1 --data '[[\"A\",\"B\"],[1,2]]'",
    }],
    aliases=["put data in a sheet"],
    keywords=["set", "values"],
    flag=_SHEETS_WRITE_FLAG,
))

register(OpSpec(
    name="sheets.add_sheet",
    fn=sheets_add_sheet,
    input_model=SheetsAddSheetInput,
    output_model=SheetsAddSheetOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
    perf={"api": "Sheets v4", "method": "spreadsheets.batchUpdate (addSheet)", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Add a new tab to an existing spreadsheet",
        "input": {"spreadsheet_id": "<id>", "title": "NewTab"},
        "cli": "google-kit sheets add-sheet <id> NewTab",
    }],
    flag=_SHEETS_WRITE_FLAG,
))

register(OpSpec(
    name="sheets.info",
    fn=sheets_info,
    input_model=SheetsInfoInput,
    output_model=SheetsInfoOutput,
    posture="read",
    scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    perf={"api": "Sheets v4", "method": "spreadsheets.get", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get spreadsheet metadata",
        "input": {"spreadsheet_id": "<id>"},
        "cli": "google-kit sheets info <id>",
    }],
))

register(OpSpec(
    name="sheets.chart",
    fn=sheets_chart,
    input_model=SheetsChartInput,
    output_model=SheetsChartOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
    perf={"api": "Sheets v4", "method": "spreadsheets.batchUpdate (addChart)", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a bar chart from a data range",
        "input": {
            "spreadsheet_id": "<id>",
            "title": "Sales Chart",
            "chart_type": "bar",
            "sheet_id": 0,
            "x_range": {"start_row": 0, "end_row": 10, "start_col": 0, "end_col": 1},
            "y_ranges": [{"start_row": 0, "end_row": 10, "start_col": 1, "end_col": 2}],
        },
        "cli": "google-kit sheets chart <id> --title 'Sales Chart' --chart-type bar --sheet-id 0 --x-range '...' --y-ranges '[...]'",
    }],
    flag=_SHEETS_WRITE_FLAG,
))

register(OpSpec(
    name="sheets.append",
    fn=sheets_append,
    input_model=SheetsAppendInput,
    output_model=SheetsAppendOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
    perf={"api": "Sheets v4", "method": "spreadsheets.values.append", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="content",
    capability="sheet.append",
    aliases=["add a row to a sheet"],
    examples=[{
        "description": "Append rows below existing data in a sheet",
        "input": {
            "spreadsheet_id": "<id>",
            "range": "Sheet1!A1",
            "values": [["Alice", 92], ["Bob", 78]],
            "value_input_option": "USER_ENTERED",
            "insert_data_option": "INSERT_ROWS",
        },
        "cli": "google-kit sheets append <id> --range Sheet1!A1 --data '[[\"Alice\",92]]'",
    }],
    flag=_SHEETS_WRITE_FLAG,
))

register(OpSpec(
    name="sheets.pivot",
    fn=sheets_pivot,
    input_model=SheetsPivotInput,
    output_model=SheetsPivotOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
    perf={"api": "Sheets v4", "method": "spreadsheets.batchUpdate (updateCells/pivotTable)", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="content",
    capability="sheet.pivot",
    examples=[{
        "description": "Create a pivot table from a data range on another sheet",
        "input": {
            "spreadsheet_id": "<id>",
            "source_sheet_id": 0,
            "source_range": {"start_row": 0, "end_row": 10, "start_col": 0, "end_col": 3},
            "target_sheet_id": 1,
            "target_row": 0,
            "target_col": 0,
            "rows": [0],
            "columns": [1],
            "values": [{"source_column_offset": 2, "summarize_function": "SUM"}],
        },
        "cli": "google-kit sheets pivot <id> --source-sheet-id 0 ...",
    }],
    flag=_SHEETS_WRITE_FLAG,
))

register(OpSpec(
    name="sheets.conditional_format",
    fn=sheets_conditional_format,
    input_model=SheetsConditionalFormatInput,
    output_model=SheetsConditionalFormatOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
    perf={"api": "Sheets v4", "method": "spreadsheets.batchUpdate (addConditionalFormatRule)", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="content",
    capability="sheet.conditional_format",
    examples=[{
        "description": "Highlight cells greater than 100 in red with bold text",
        "input": {
            "spreadsheet_id": "<id>",
            "sheet_id": 0,
            "range": {"start_row": 1, "end_row": 100, "start_col": 2, "end_col": 3},
            "condition_type": "NUMBER_GREATER",
            "condition_values": ["100"],
            "background_color": {"red": 1.0, "green": 0.0, "blue": 0.0},
            "bold": True,
        },
        "cli": "google-kit sheets conditional-format <id> --sheet-id 0 ...",
    }],
    flag=_SHEETS_WRITE_FLAG,
))

register(OpSpec(
    name="sheets.metadata",
    fn=sheets_metadata,
    input_model=SheetsMetadataInput,
    output_model=SheetsMetadataOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
    perf={"api": "Sheets v4", "method": "spreadsheets.batchUpdate (createDeveloperMetadata)", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    plane="content",
    capability="sheet.developer_metadata",
    examples=[{
        "description": "Attach a key-value metadata tag to a spreadsheet",
        "input": {
            "spreadsheet_id": "<id>",
            "metadata_key": "project",
            "metadata_value": "alpha",
            "visibility": "DOCUMENT",
        },
        "cli": "google-kit sheets metadata <id> --key project --value alpha",
    }],
    flag=_SHEETS_WRITE_FLAG,
))
