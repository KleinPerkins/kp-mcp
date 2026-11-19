"""Load / performance characteristics of the core engine and key services (QA #5).

These tests exercise the *methodology* large operations use — streaming vs.
in-memory load, pagination bounding, and request batching against documented
API caps — using fakes and simulated large payloads. No live network.

What is asserted (and why it is a load/perf property, not just a parity check):

  core.batch primitives
    - byte_chunks  is a lazy generator that yields bounded-size chunks and never
      materializes the whole file at once (resumable/chunked transfer).
    - chunk_requests splits an arbitrarily large request list into bounded
      sub-batches (batchUpdate / batchModify aggregation).
    - paginate streams items across pages without buffering every page.

  drive.upload
    - path source streams from disk via MediaFileUpload(resumable=True): a
      multi-MB file is uploaded with PEAK traced allocation far below the file
      size — the bytes are never slurped into memory by core.
    - inline content_b64 is capped at the 10 MiB boundary: exactly-at-cap is
      accepted (MediaIoBaseUpload, resumable), one byte over is rejected with a
      clear "use 'path'" ValueError before any API call.

  sheets.write
    - a many-row update forwards a single values.update call and references the
      caller's row list directly (no per-row copy / no quadratic blow-up).

  drive.search
    - pagination is bounded by ``limit``: against an effectively infinite page
      source the loop stops after enough pages to satisfy the limit, retains at
      most ``limit`` rows, and flags truncation — it does not drain all pages.

  gmail.batch_modify
    - an id list larger than Gmail's 1000-per-call batchModify cap is split into
      sequential <=1000-id API calls (correct chunking flag/body per call), with
      per-chunk audit target_ids and an accurate aggregate modified_count.
"""
from __future__ import annotations

import base64
import importlib
import tracemalloc
from dataclasses import dataclass, field
from typing import Any

import pytest

from google_kit.core import audit as _audit_mod
from google_kit.core.batch import byte_chunks, chunk_requests, paginate


@pytest.fixture(autouse=True)
def _isolate_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Redirect the mutation audit log to a temp file.

    ``_DEFAULT_AUDIT_PATH`` is resolved at import time, so writes from
    write-posture ops would otherwise append to the operator's real audit
    JSONL. The many-id batch_modify test below produces several records; keep
    them out of the real log.
    """
    monkeypatch.setattr(_audit_mod, "_DEFAULT_AUDIT_PATH", tmp_path / "audit.jsonl")


# ─── Shared fake-service plumbing (records calls; no network) ─────────────────


@dataclass
class _Call:
    resource: str
    method: str
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> Any:
        return self.kwargs.get("body")


class _Exec:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


# ===========================================================================
# core.batch primitives — streaming / chunking methodology
# ===========================================================================


class TestByteChunksStreaming:
    def test_is_lazy_iterator_not_a_list(self) -> None:
        gen = byte_chunks(b"abcdef", 2)
        # A generator does not pre-compute or hold all chunks.
        assert not isinstance(gen, (list, tuple))
        assert hasattr(gen, "__next__")

    def test_chunks_are_bounded_and_reconstruct_exactly(self) -> None:
        data = bytes(5 * 1024 * 1024 + 7)  # 5 MiB + tail, exercises last partial chunk
        chunk_size = 256 * 1024
        seen = bytearray()
        last_end = 0
        for start, end, chunk in byte_chunks(data, chunk_size):
            assert len(chunk) <= chunk_size
            assert start == last_end
            assert end == start + len(chunk)
            seen.extend(chunk)
            last_end = end
        assert bytes(seen) == data
        assert last_end == len(data)

    def test_peak_memory_per_chunk_not_whole_payload(self) -> None:
        # Streaming a large payload one chunk at a time must not retain the whole
        # thing: peak *additional* allocation while iterating is ~one chunk.
        data = bytes(16 * 1024 * 1024)  # 16 MiB
        chunk_size = 512 * 1024
        tracemalloc.start()
        before = tracemalloc.get_traced_memory()[0]
        max_live = 0
        for _start, _end, chunk in byte_chunks(data, chunk_size):
            live = tracemalloc.get_traced_memory()[0] - before
            max_live = max(max_live, live)
            del chunk
        tracemalloc.stop()
        # Generous ceiling (a few chunks of slack) but far below the 16 MiB total.
        assert max_live < 4 * chunk_size, f"per-chunk peak {max_live} too high"

    def test_invalid_chunk_size_rejected(self) -> None:
        with pytest.raises(ValueError):
            list(byte_chunks(b"x", 0))


class TestChunkRequests:
    def test_splits_into_bounded_subbatches(self) -> None:
        reqs = list(range(2500))
        batches = list(chunk_requests(reqs, 1000))
        assert [len(b) for b in batches] == [1000, 1000, 500]
        assert [x for b in batches for x in b] == reqs

    def test_exact_multiple(self) -> None:
        assert [len(b) for b in chunk_requests(list(range(2000)), 1000)] == [1000, 1000]

    def test_single_short_batch(self) -> None:
        assert list(chunk_requests([1, 2, 3], 1000)) == [[1, 2, 3]]

    def test_invalid_chunk_size_rejected(self) -> None:
        with pytest.raises(ValueError):
            list(chunk_requests([1], 0))


class TestPaginateStreaming:
    def test_streams_across_pages_without_buffering_all(self) -> None:
        pages = {
            None: ([0, 1], "p1"),
            "p1": ([2, 3], "p2"),
            "p2": ([4], None),
        }
        fetched: list[str | None] = []

        def fetch(token: str | None) -> tuple[list[int], str | None]:
            fetched.append(token)
            return pages[token]

        # paginate yields lazily — pull items one at a time.
        it = paginate(fetch)
        assert next(it) == 0
        # Only the first page has been fetched at this point.
        assert fetched == [None]
        assert list(it) == [1, 2, 3, 4]
        assert fetched == [None, "p1", "p2"]


# ===========================================================================
# drive.upload — streaming (path) vs. capped inline (content_b64)
# ===========================================================================


class _FilesProxy:
    def __init__(self, responses: dict, log: list[_Call]) -> None:
        self._responses = responses
        self._log = log

    def list(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("files", "list", dict(kwargs)))
        return _Exec(self._responses.get(("files", "list"), {"files": [{"id": "folderX"}]}))

    def create(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("files", "create", dict(kwargs)))
        return _Exec(self._responses.get(("files", "create")))


class FakeDriveService:
    def __init__(self, responses: dict | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[_Call] = []

    def files(self) -> _FilesProxy:
        return _FilesProxy(self._responses, self.calls)

    def calls_for(self, resource: str, method: str) -> list[_Call]:
        return [c for c in self.calls if c.resource == resource and c.method == method]


_UPLOAD_CREATE_RESP = {
    "id": "file001",
    "name": "upload",
    "webViewLink": "https://drive.google.com/file/d/file001/view",
    "mimeType": "application/octet-stream",
}


def _drive_svc() -> FakeDriveService:
    return FakeDriveService({("files", "create"): dict(_UPLOAD_CREATE_RESP)})


class TestDriveUploadStreaming:
    def test_large_path_upload_streams_without_loading_into_memory(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from googleapiclient.http import MediaFileUpload

        from google_kit.services.drive.core import drive_upload
        from google_kit.services.drive.models import DriveUploadInput

        monkeypatch.setenv("GOOGLE_KIT_UPLOAD_ROOT", str(tmp_path))

        size = 12 * 1024 * 1024  # 12 MiB on disk
        big = tmp_path / "big.bin"
        big.write_bytes(b"\0" * size)

        svc = _drive_svc()
        tracemalloc.start()
        before = tracemalloc.get_traced_memory()[0]
        result = drive_upload(
            DriveUploadInput(path=str(big), folder_id="folder001"),
            service=svc,
        )
        peak_extra = tracemalloc.get_traced_memory()[1] - before
        tracemalloc.stop()

        creates = svc.calls_for("files", "create")
        assert len(creates) == 1
        media = creates[0].kwargs.get("media_body")
        assert isinstance(media, MediaFileUpload)
        assert media.resumable() is True
        # The 12 MiB file is streamed from disk — core never slurps it. Peak
        # extra allocation must be a tiny fraction of the file size.
        assert peak_extra < size // 4, f"path upload allocated {peak_extra} bytes"
        assert result.data.id == "file001"

    def test_inline_b64_accepted_exactly_at_10mib_cap(self, tmp_path: Any) -> None:
        from googleapiclient.http import MediaIoBaseUpload

        from google_kit.services.drive.core import MAX_INLINE_UPLOAD_BYTES, drive_upload
        from google_kit.services.drive.models import DriveUploadInput

        assert MAX_INLINE_UPLOAD_BYTES == 10 * 1024 * 1024
        payload = b"\0" * MAX_INLINE_UPLOAD_BYTES
        content_b64 = base64.b64encode(payload).decode()

        svc = _drive_svc()
        result = drive_upload(
            DriveUploadInput(content_b64=content_b64, filename="cap.bin", folder_id="folder001"),
            service=svc,
        )
        media = svc.calls_for("files", "create")[0].kwargs.get("media_body")
        assert isinstance(media, MediaIoBaseUpload)
        assert media.resumable() is True
        assert result.data.id == "file001"

    def test_inline_b64_one_byte_over_cap_rejected_before_api(self) -> None:
        from google_kit.services.drive.core import MAX_INLINE_UPLOAD_BYTES, drive_upload
        from google_kit.services.drive.models import DriveUploadInput

        payload = b"\0" * (MAX_INLINE_UPLOAD_BYTES + 1)
        content_b64 = base64.b64encode(payload).decode()

        svc = _drive_svc()
        with pytest.raises(ValueError, match="inline cap|use 'path'"):
            drive_upload(
                DriveUploadInput(content_b64=content_b64, filename="over.bin", folder_id="folder001"),
                service=svc,
            )
        # Rejected before any network call.
        assert svc.calls_for("files", "create") == []


# ===========================================================================
# sheets.write — many-row update forwards one call, no row duplication
# ===========================================================================


class _SheetsValuesProxy:
    def __init__(self, responses: dict, log: list[_Call]) -> None:
        self._responses = responses
        self._log = log

    def update(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("values", "update", dict(kwargs)))
        return _Exec(self._responses.get(("values", "update")))

    def clear(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("values", "clear", dict(kwargs)))
        return _Exec(self._responses.get(("values", "clear")))


class _SheetsSpreadsheetsProxy:
    def __init__(self, responses: dict, log: list[_Call]) -> None:
        self._responses = responses
        self._log = log

    def values(self) -> _SheetsValuesProxy:
        return _SheetsValuesProxy(self._responses, self._log)


class FakeSheetsService:
    def __init__(self, responses: dict | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[_Call] = []

    def spreadsheets(self) -> _SheetsSpreadsheetsProxy:
        return _SheetsSpreadsheetsProxy(self._responses, self.calls)

    def calls_for(self, resource: str, method: str) -> list[_Call]:
        return [c for c in self.calls if c.resource == resource and c.method == method]


class TestSheetsManyRowWrite:
    def test_many_rows_single_update_no_row_copy(self) -> None:
        from google_kit.services.sheets.core import sheets_write
        from google_kit.services.sheets.models import SheetsWriteInput

        n_rows = 50_000
        values = [[r, f"row-{r}"] for r in range(n_rows)]
        resp = {"updatedRows": n_rows, "updatedColumns": 2, "updatedRange": "Sheet1!A1:B50000"}
        svc = FakeSheetsService({("values", "update"): resp})

        inp = SheetsWriteInput(spreadsheet_id="sheet001", range="Sheet1!A1", values=values)
        result = sheets_write(inp, service=svc)

        updates = svc.calls_for("values", "update")
        assert len(updates) == 1, "many-row write must be a single values.update call"
        body = updates[0].body
        assert len(body["values"]) == n_rows
        # Core forwards the validated rows by reference — no per-row duplication.
        assert body["values"] is inp.values
        assert result.data.updated_rows == n_rows

    def test_value_input_option_forwarded(self) -> None:
        from google_kit.services.sheets.core import sheets_write
        from google_kit.services.sheets.models import SheetsWriteInput

        svc = FakeSheetsService({("values", "update"): {}})
        sheets_write(
            SheetsWriteInput(
                spreadsheet_id="s1", range="Sheet1!A1", values=[[1]], value_input_option="RAW"
            ),
            service=svc,
        )
        assert svc.calls_for("values", "update")[0].kwargs["valueInputOption"] == "RAW"


# ===========================================================================
# drive.search — pagination bounded by limit (does not drain all pages)
# ===========================================================================


class _InfinitePageFilesProxy:
    """files().list that always returns a full page plus a next token (infinite)."""

    def __init__(self, page_size: int, log: list[_Call]) -> None:
        self._page_size = page_size
        self._log = log
        self._counter = 0

    def list(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("files", "list", dict(kwargs)))
        requested = kwargs.get("pageSize", self._page_size)
        files = []
        for _ in range(requested):
            self._counter += 1
            files.append(
                {
                    "id": f"f{self._counter}",
                    "name": f"file{self._counter}",
                    "mimeType": "application/pdf",
                    "modifiedTime": "2026-01-01T00:00:00Z",
                    "owners": [],
                    "webViewLink": "https://x",
                    "shared": False,
                }
            )
        return _Exec({"files": files, "nextPageToken": f"tok{self._counter}"})


class FakeInfiniteDriveService:
    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self._files = _InfinitePageFilesProxy(100, self.calls)

    def files(self) -> _InfinitePageFilesProxy:
        return self._files

    def calls_for(self, resource: str, method: str) -> list[_Call]:
        return [c for c in self.calls if c.resource == resource and c.method == method]


class TestDriveSearchPaginationBounded:
    def test_stops_at_limit_against_infinite_pages(self) -> None:
        from google_kit.services.drive.core import drive_search
        from google_kit.services.drive.models import DriveSearchInput

        svc = FakeInfiniteDriveService()
        result = drive_search(
            DriveSearchInput(name="report", limit=250, scope="user"),
            service=svc,
        )

        list_calls = svc.calls_for("files", "list")
        # 100 + 100 + 100 = 300 >= 250 → exactly 3 pages, then stop.
        assert len(list_calls) == 3
        # Every page request is bounded to <= 100 rows.
        assert all(c.kwargs["pageSize"] <= 100 for c in list_calls)
        # Retains at most `limit` rows even though pages are infinite.
        assert result.data.count == 250
        assert len(result.data.results) == 250
        assert result.data.truncated is True


# ===========================================================================
# gmail.batch_modify — chunk id list to <=1000-per-call cap
# ===========================================================================


class _GmailMessagesProxy:
    def __init__(self, log: list[_Call]) -> None:
        self._log = log

    def batchModify(self, **kwargs: Any) -> _Exec:
        self._log.append(_Call("messages", "batchModify", dict(kwargs)))
        return _Exec(None)  # API returns 204 / empty body


class _GmailUsersProxy:
    def __init__(self, log: list[_Call]) -> None:
        self._log = log

    def messages(self) -> _GmailMessagesProxy:
        return _GmailMessagesProxy(self._log)


class FakeGmailService:
    def __init__(self) -> None:
        self.calls: list[_Call] = []

    def users(self) -> _GmailUsersProxy:
        return _GmailUsersProxy(self.calls)

    def calls_for(self, resource: str, method: str) -> list[_Call]:
        return [c for c in self.calls if c.resource == resource and c.method == method]


@pytest.fixture(autouse=True, scope="module")
def _ensure_gmail() -> None:
    import google_kit.registry as reg
    import google_kit.services.gmail as gmail_mod

    if "gmail.batch_modify" not in {s.name for s in reg.all_specs()}:
        importlib.reload(gmail_mod)


class TestGmailBatchModifyChunking:
    def test_many_ids_split_into_1000_id_calls(self) -> None:
        from google_kit.services.gmail.core import gmail_batch_modify
        from google_kit.services.gmail.models import GmailBatchModifyInput

        ids = [f"m{i}" for i in range(2500)]
        svc = FakeGmailService()
        result = gmail_batch_modify(
            GmailBatchModifyInput(ids=ids, add_label_ids=["IMPORTANT"], remove_label_ids=["UNREAD"]),
            service=svc,
        )

        calls = svc.calls_for("messages", "batchModify")
        assert [len(c.body["ids"]) for c in calls] == [1000, 1000, 500]
        # Chunks partition the id list in order with no overlap or loss.
        recombined = [mid for c in calls for mid in c.body["ids"]]
        assert recombined == ids
        # Labels are repeated on every chunk; userId is set per call.
        for c in calls:
            assert c.body["addLabelIds"] == ["IMPORTANT"]
            assert c.body["removeLabelIds"] == ["UNREAD"]
            assert c.kwargs["userId"] == "me"
        # Aggregate envelope reflects the full id set.
        assert result.data.modified_count == 2500
        assert result.data.ids == ids

    def test_exactly_at_cap_is_single_call(self) -> None:
        from google_kit.services.gmail.core import gmail_batch_modify
        from google_kit.services.gmail.models import GmailBatchModifyInput

        ids = [f"m{i}" for i in range(1000)]
        svc = FakeGmailService()
        gmail_batch_modify(
            GmailBatchModifyInput(ids=ids, add_label_ids=["INBOX"]),
            service=svc,
        )
        assert len(svc.calls_for("messages", "batchModify")) == 1

    def test_one_over_cap_splits_into_two_calls(self) -> None:
        from google_kit.services.gmail.core import gmail_batch_modify
        from google_kit.services.gmail.models import GmailBatchModifyInput

        ids = [f"m{i}" for i in range(1001)]
        svc = FakeGmailService()
        gmail_batch_modify(
            GmailBatchModifyInput(ids=ids, add_label_ids=["INBOX"]),
            service=svc,
        )
        calls = svc.calls_for("messages", "batchModify")
        assert [len(c.body["ids"]) for c in calls] == [1000, 1]

    def test_per_chunk_audit_records_scoped_ids(self, tmp_path: Any) -> None:
        from google_kit.core.audit import read_audit
        from google_kit.services.gmail.core import gmail_batch_modify
        from google_kit.services.gmail.models import GmailBatchModifyInput

        audit_file = tmp_path / "batch_audit.jsonl"
        # Patch the default path so execute_api_call (audit_file=None) writes here.
        ids = [f"m{i}" for i in range(1500)]
        svc = FakeGmailService()

        import google_kit.core.audit as audit_mod

        orig = audit_mod._DEFAULT_AUDIT_PATH
        audit_mod._DEFAULT_AUDIT_PATH = audit_file
        try:
            gmail_batch_modify(
                GmailBatchModifyInput(ids=ids, add_label_ids=["INBOX"]),
                service=svc,
            )
        finally:
            audit_mod._DEFAULT_AUDIT_PATH = orig

        records = read_audit(op="gmail.batch_modify", audit_file=audit_file)
        assert len(records) == 2  # 1000 + 500
        assert [len(r["target_ids"]) for r in records] == [1000, 500]
