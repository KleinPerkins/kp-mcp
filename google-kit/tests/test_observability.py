"""Tests for google_kit.core.observability."""
import json
import sys

import pytest

from google_kit.core.errors import Transient
from google_kit.core.observability import (
    StructuredLogger,
    _MetricsSink,
    get_metrics,
    observe_op,
)
from google_kit.core.run_id import get_run_id, set_run_id, reset_run_id


def test_structured_logger_emits_json(capsys: pytest.CaptureFixture) -> None:
    logger = StructuredLogger(surface="cli", profile="test")
    logger.log_op("drive.fetch", outcome="ok", latency_ms=42.1)
    captured = capsys.readouterr()
    record = json.loads(captured.err.strip())
    assert record["op"] == "drive.fetch"
    assert record["outcome"] == "ok"
    assert record["surface"] == "cli"
    assert record["profile"] == "test"
    assert record["latency_ms"] == 42.1


def test_structured_logger_error_class(capsys: pytest.CaptureFixture) -> None:
    logger = StructuredLogger()
    logger.log_op("drive.fetch", outcome="error", error_class="Transient")
    captured = capsys.readouterr()
    record = json.loads(captured.err.strip())
    assert record["error_class"] == "Transient"
    assert record["outcome"] == "error"


def test_structured_logger_run_id_included(capsys: pytest.CaptureFixture) -> None:
    token = set_run_id("abc12345abc12345")
    try:
        logger = StructuredLogger()
        logger.log_op("test.op", outcome="ok")
        captured = capsys.readouterr()
        record = json.loads(captured.err.strip())
        assert record["run_id"] == "abc12345abc12345"
    finally:
        reset_run_id(token)


def test_structured_logger_no_stdout(capsys: pytest.CaptureFixture) -> None:
    logger = StructuredLogger()
    logger.log_op("test.op", outcome="ok")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_structured_logger_email_redacted(capsys: pytest.CaptureFixture) -> None:
    logger = StructuredLogger()
    logger.log_op("test.op", outcome="ok", extra={"user": "alice@example.com"})
    captured = capsys.readouterr()
    assert "alice@example.com" not in captured.err


def test_metrics_sink_records_calls() -> None:
    sink = _MetricsSink()
    sink.record_call("drive.fetch")
    sink.record_call("drive.fetch")
    sink.record_call("drive.list")
    snap = sink.snapshot()
    assert snap["calls"]["drive.fetch"] == 2
    assert snap["calls"]["drive.list"] == 1


def test_metrics_sink_records_errors() -> None:
    sink = _MetricsSink()
    sink.record_error("drive.fetch", "Transient")
    sink.record_error("drive.fetch", "Transient")
    snap = sink.snapshot()
    assert snap["errors"]["drive.fetch:Transient"] == 2


def test_metrics_sink_records_retries() -> None:
    sink = _MetricsSink()
    sink.record_retry("drive.fetch", attempt=1, delay_s=1.0)
    snap = sink.snapshot()
    assert snap["retries"]["drive.fetch"] == 1


def test_metrics_sink_records_latency() -> None:
    sink = _MetricsSink()
    sink.record_latency("drive.fetch", 123.4)
    sink.record_latency("drive.fetch", 456.7)
    snap = sink.snapshot()
    assert sink.snapshot()["latency_histograms"]["drive.fetch"] == [123.4, 456.7]


def test_metrics_sink_reset() -> None:
    sink = _MetricsSink()
    sink.record_call("x")
    sink.reset()
    assert sink.snapshot() == {
        "calls": {},
        "errors": {},
        "retries": {},
        "quota_hits": {},
        "latency_histograms": {},
    }


def test_observe_op_success(capsys: pytest.CaptureFixture) -> None:
    sink = _MetricsSink()
    logger = StructuredLogger()
    with observe_op("drive.fetch", logger=logger, metrics=sink):
        pass
    captured = capsys.readouterr()
    record = json.loads(captured.err.strip())
    assert record["outcome"] == "ok"
    assert record["op"] == "drive.fetch"
    assert "latency_ms" in record
    snap = sink.snapshot()
    assert snap["calls"]["drive.fetch"] == 1
    assert "drive.fetch" in snap["latency_histograms"]


def test_observe_op_error(capsys: pytest.CaptureFixture) -> None:
    sink = _MetricsSink()
    logger = StructuredLogger()
    with pytest.raises(Transient):
        with observe_op("drive.fetch", logger=logger, metrics=sink):
            raise Transient("boom")
    captured = capsys.readouterr()
    record = json.loads(captured.err.strip())
    assert record["outcome"] == "error"
    assert record["error_class"] == "Transient"
    snap = sink.snapshot()
    assert "drive.fetch:Transient" in snap["errors"]


def test_observe_op_ensures_run_id(capsys: pytest.CaptureFixture) -> None:
    import contextvars
    from google_kit.core import run_id as rid_mod

    ctx = contextvars.copy_context()

    results = {}

    def _run():
        rid_mod._RUN_ID.set("")
        sink = _MetricsSink()
        logger = StructuredLogger()
        with observe_op("x", logger=logger, metrics=sink):
            pass
        results["rid"] = rid_mod.get_run_id()

    ctx.run(_run)
    assert len(results["rid"]) == 16


def test_observe_op_no_otel_no_crash(capsys: pytest.CaptureFixture) -> None:
    import os
    original = os.environ.pop("GOOGLE_KIT_OTLP_ENDPOINT", None)
    try:
        sink = _MetricsSink()
        with observe_op("test.op", metrics=sink):
            pass
    finally:
        if original is not None:
            os.environ["GOOGLE_KIT_OTLP_ENDPOINT"] = original
