"""Drive Activity service — registers 1 read op (drive_activity.query)."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import drive_activity_query
from .models import DriveActivityQueryInput, DriveActivityQueryOutput

_DRIVE_ACTIVITY_SCOPES = ["https://www.googleapis.com/auth/drive.activity.readonly"]

register(OpSpec(
    name="drive_activity.query",
    fn=drive_activity_query,
    input_model=DriveActivityQueryInput,
    output_model=DriveActivityQueryOutput,
    posture="read",
    scopes=_DRIVE_ACTIVITY_SCOPES,
    perf={"api": "Drive Activity v2", "method": "activity.query", "quota": "1000 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Query activity for a specific file",
        "input": {"item_name": "items/FILE_ID"},
        "cli": "google-kit drive_activity query --item-name items/FILE_ID",
    }],
    plane="history",
    capability="history.read",
))
