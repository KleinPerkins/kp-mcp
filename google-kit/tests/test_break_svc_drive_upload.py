from __future__ import annotations

import pytest

from google_kit.services.drive.core import drive_upload
from google_kit.services.drive.models import DriveUploadInput


class _NoDispatchService:
    def files(self):  # type: ignore[no-untyped-def]
        raise AssertionError("invalid upload content must not dispatch to Drive")

    def permissions(self):  # type: ignore[no-untyped-def]
        raise AssertionError("invalid upload content must not dispatch to Drive")


def test_drive_upload_rejects_invalid_base64_before_api_dispatch() -> None:
    with pytest.raises(ValueError, match="Invalid base64"):
        drive_upload(
            DriveUploadInput(
                content_b64="!!!!",
                filename="payload.txt",
                folder_id="folder123",
            ),
            service=_NoDispatchService(),
        )
