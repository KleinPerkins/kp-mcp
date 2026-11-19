from __future__ import annotations

import pytest
from pydantic import ValidationError

from google_kit.services.sheets.models import SheetGridRange, SheetsChartInput


def test_sheet_grid_range_rejects_negative_indices() -> None:
    with pytest.raises(ValidationError):
        SheetGridRange(start_row=-1, end_row=10, start_col=0, end_col=2)


def test_sheet_grid_range_rejects_empty_row_span() -> None:
    with pytest.raises(ValidationError):
        SheetGridRange(start_row=5, end_row=5, start_col=0, end_col=2)


def test_sheet_grid_range_rejects_reversed_col_span() -> None:
    with pytest.raises(ValidationError):
        SheetGridRange(start_row=0, end_row=5, start_col=3, end_col=2)


def test_sheets_chart_requires_at_least_one_y_range() -> None:
    with pytest.raises(ValidationError):
        SheetsChartInput(
            spreadsheet_id="ss1",
            title="Chart",
            sheet_id=0,
            x_range=SheetGridRange(start_row=0, end_row=5, start_col=0, end_col=1),
            y_ranges=[],
        )
