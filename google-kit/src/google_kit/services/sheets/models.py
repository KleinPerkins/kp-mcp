"""Pydantic input / output models for all Sheets service operations."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from google_kit.core.normalize import OutputEnvelope


class SheetGridRange(BaseModel):
    """Grid range for chart data sources (start inclusive, end exclusive row/col indices)."""

    start_row: int
    end_row: int
    start_col: int
    end_col: int

    @model_validator(mode="after")
    def _validate_non_empty_range(self) -> "SheetGridRange":
        if min(self.start_row, self.end_row, self.start_col, self.end_col) < 0:
            raise ValueError("grid range indices must be non-negative")
        if self.end_row <= self.start_row:
            raise ValueError("end_row must be greater than start_row")
        if self.end_col <= self.start_col:
            raise ValueError("end_col must be greater than start_col")
        return self


# ─── sheets.create ────────────────────────────────────────────────────────────


class SheetsCreateInput(BaseModel):
    """Input for ``sheets.create``: create a new spreadsheet."""

    title: str
    sheet_names: list[str] = Field(default_factory=list)
    folder_id: str | None = None


class SheetsCreateData(BaseModel):
    """Data payload for ``sheets.create``."""

    spreadsheet_id: str
    url: str
    title: str
    sheets: list[str]


SheetsCreateOutput = OutputEnvelope[SheetsCreateData]


# ─── sheets.read ──────────────────────────────────────────────────────────────


class SheetsReadInput(BaseModel):
    """Input for ``sheets.read``: read cell values from a range."""

    spreadsheet_id: str
    range: str = Field(default="Sheet1")
    fmt: Literal["text", "json", "csv"] = "json"


class SheetsReadData(BaseModel):
    """Data payload for ``sheets.read``."""

    range: str | None = None
    rows: int
    values: list[list[Any]]


SheetsReadOutput = OutputEnvelope[SheetsReadData]


# ─── sheets.write ─────────────────────────────────────────────────────────────


class SheetsWriteInput(BaseModel):
    """Input for ``sheets.write``: write cell values to a range.

    Note: ``clear_first=True`` issues a separate ``values.clear`` call before
    the write.  The two operations are NOT atomic — a failure between them
    leaves the range cleared but un-written.
    """

    spreadsheet_id: str
    range: str = Field(default="Sheet1!A1")
    values: list[list[Any]]
    clear_first: bool = False
    value_input_option: Literal["RAW", "USER_ENTERED"] = "USER_ENTERED"


class SheetsWriteData(BaseModel):
    """Data payload for ``sheets.write``."""

    updated_rows: int
    updated_columns: int
    updated_range: str | None = None


SheetsWriteOutput = OutputEnvelope[SheetsWriteData]


# ─── sheets.add_sheet ─────────────────────────────────────────────────────────


class SheetsAddSheetInput(BaseModel):
    """Input for ``sheets.add_sheet``: add a new tab to a spreadsheet."""

    spreadsheet_id: str
    title: str


class SheetsAddSheetData(BaseModel):
    """Data payload for ``sheets.add_sheet``."""

    sheet_id: int
    title: str


SheetsAddSheetOutput = OutputEnvelope[SheetsAddSheetData]


# ─── sheets.info ──────────────────────────────────────────────────────────────


class SheetsInfoInput(BaseModel):
    """Input for ``sheets.info``: get spreadsheet metadata."""

    spreadsheet_id: str


class SheetInfo(BaseModel):
    """Metadata for one sheet tab."""

    sheet_id: int
    title: str
    row_count: int = 0
    col_count: int = 0


class SheetsInfoData(BaseModel):
    """Data payload for ``sheets.info``."""

    title: str
    spreadsheet_id: str
    url: str
    sheets: list[SheetInfo]


SheetsInfoOutput = OutputEnvelope[SheetsInfoData]


# ─── sheets.chart ─────────────────────────────────────────────────────────────

_ChartType = Literal["bar", "column", "line", "area", "pie", "scatter", "combo"]


class SheetsChartInput(BaseModel):
    """Input for ``sheets.chart``: create an embedded chart."""

    spreadsheet_id: str
    title: str
    chart_type: _ChartType = "bar"
    sheet_id: int
    x_range: SheetGridRange
    y_ranges: list[SheetGridRange]
    stacked: bool = False

    @model_validator(mode="after")
    def _validate_y_ranges(self) -> "SheetsChartInput":
        if not self.y_ranges:
            raise ValueError("y_ranges must contain at least one range")
        return self


class SheetsChartData(BaseModel):
    """Data payload for ``sheets.chart``."""

    chart_id: int


SheetsChartOutput = OutputEnvelope[SheetsChartData]


# ─── sheets.append ────────────────────────────────────────────────────────────


class SheetsAppendInput(BaseModel):
    """Input for ``sheets.append``: append rows to a spreadsheet range."""

    spreadsheet_id: str
    range: str
    values: list[list[Any]]
    value_input_option: Literal["RAW", "USER_ENTERED"] = "USER_ENTERED"
    insert_data_option: Literal["OVERWRITE", "INSERT_ROWS"] = "INSERT_ROWS"


class SheetsAppendData(BaseModel):
    """Data payload for ``sheets.append``."""

    updated_range: str | None = None
    updated_rows: int
    updated_columns: int
    updated_cells: int


SheetsAppendOutput = OutputEnvelope[SheetsAppendData]


# ─── sheets.pivot ─────────────────────────────────────────────────────────────


class SheetsPivotValueSpec(BaseModel):
    """One value summary for a pivot table."""

    source_column_offset: int
    summarize_function: str


class SheetsPivotInput(BaseModel):
    """Input for ``sheets.pivot``: create a pivot table via batchUpdate/updateCells."""

    spreadsheet_id: str
    source_sheet_id: int
    source_range: SheetGridRange
    target_sheet_id: int
    target_row: int
    target_col: int
    rows: list[int] = Field(default_factory=list)
    columns: list[int] = Field(default_factory=list)
    values: list[SheetsPivotValueSpec] = Field(default_factory=list)


class SheetsPivotData(BaseModel):
    """Data payload for ``sheets.pivot``."""

    spreadsheet_id: str
    replies_count: int


SheetsPivotOutput = OutputEnvelope[SheetsPivotData]


# ─── sheets.conditional_format ────────────────────────────────────────────────


class SheetsColorSpec(BaseModel):
    """RGB color (0.0–1.0 per channel)."""

    red: float = 0.0
    green: float = 0.0
    blue: float = 0.0


class SheetsConditionalFormatInput(BaseModel):
    """Input for ``sheets.conditional_format``: add a conditional format rule."""

    spreadsheet_id: str
    sheet_id: int
    range: SheetGridRange
    condition_type: str
    condition_values: list[str]
    background_color: SheetsColorSpec | None = None
    bold: bool | None = None
    index: int = 0


class SheetsConditionalFormatData(BaseModel):
    """Data payload for ``sheets.conditional_format``."""

    spreadsheet_id: str
    replies_count: int


SheetsConditionalFormatOutput = OutputEnvelope[SheetsConditionalFormatData]


# ─── sheets.metadata ──────────────────────────────────────────────────────────


class SheetsMetadataInput(BaseModel):
    """Input for ``sheets.metadata``: create developer metadata on a spreadsheet or sheet."""

    spreadsheet_id: str
    metadata_key: str
    metadata_value: str
    visibility: str = "DOCUMENT"
    location_sheet_id: int | None = None


class SheetsMetadataData(BaseModel):
    """Data payload for ``sheets.metadata``."""

    spreadsheet_id: str
    replies_count: int


SheetsMetadataOutput = OutputEnvelope[SheetsMetadataData]
