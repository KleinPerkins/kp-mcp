"""Structured observability for google-kit core (R24).

- StructuredLogger: emits JSON log records to stderr.
- _MetricsSink:     in-process counters + latency histograms.
- observe_op:       context manager that times, logs, and metrics an operation.
- OTel:             lazily imported only if opentelemetry is present AND
                    GOOGLE_KIT_OTLP_ENDPOINT is configured; otherwise no-op.

Redaction applied to all log/metric/span attributes via redact_dict.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Generator

from google_kit.core import run_id as _run_id_mod
from google_kit.core.redaction import redact_dict

_OTEL_TRACER: Any = None
_OTEL_TRACER_INIT: bool = False
#: Guards the lazy, once-per-process OTel tracer init against concurrent worker
#: threads (the MCP server now runs tool calls in threads).
_OTEL_LOCK = threading.Lock()


def _get_otel_tracer() -> Any:
    """Return an OTel tracer if opentelemetry is installed AND endpoint is configured.

    Lazy singleton — attempted only once per process. Returns None (no-op) otherwise.
    Thread-safe: concurrent first calls cannot double-initialize the provider.
    """
    from .personal_runtime import current
    if current() is not None:
        return None
    global _OTEL_TRACER, _OTEL_TRACER_INIT
    if _OTEL_TRACER_INIT:
        return _OTEL_TRACER
    with _OTEL_LOCK:
        if _OTEL_TRACER_INIT:
            return _OTEL_TRACER
        _OTEL_TRACER_INIT = True
        endpoint = os.environ.get("GOOGLE_KIT_OTLP_ENDPOINT", "").strip()
        if not endpoint:
            return None
        try:
            from opentelemetry import trace  # type: ignore[import]
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import]
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import]
            from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import]

            provider = TracerProvider()
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            trace.set_tracer_provider(provider)
            _OTEL_TRACER = trace.get_tracer("google-kit")
        except Exception:
            pass
        return _OTEL_TRACER


class _MetricsSink:
    """In-process metric counters and latency histograms.

    Thread-safe: a lock guards every read-modify-write so concurrent worker
    threads (the MCP server runs tool calls in threads) cannot lose updates or
    trip a dict-resize race.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, int] = {}
        self._errors: dict[str, int] = {}
        self._retries: dict[str, int] = {}
        self._quota_hits: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}

    def record_call(self, op: str) -> None:
        with self._lock:
            self._calls[op] = self._calls.get(op, 0) + 1

    def record_error(self, op: str, error_class: str) -> None:
        key = f"{op}:{error_class}"
        with self._lock:
            self._errors[key] = self._errors.get(key, 0) + 1

    def record_retry(self, op: str, attempt: int = 0, delay_s: float = 0.0) -> None:
        with self._lock:
            self._retries[op] = self._retries.get(op, 0) + 1

    def record_quota_hit(self, op: str) -> None:
        with self._lock:
            self._quota_hits[op] = self._quota_hits.get(op, 0) + 1

    def record_latency(self, op: str, latency_ms: float) -> None:
        with self._lock:
            self._latencies.setdefault(op, []).append(latency_ms)

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of all current metric state."""
        with self._lock:
            return {
                "calls": dict(self._calls),
                "errors": dict(self._errors),
                "retries": dict(self._retries),
                "quota_hits": dict(self._quota_hits),
                "latency_histograms": {k: list(v) for k, v in self._latencies.items()},
            }

    def reset(self) -> None:
        """Clear all counters and histograms."""
        with self._lock:
            self._calls.clear()
            self._errors.clear()
            self._retries.clear()
            self._quota_hits.clear()
            self._latencies.clear()


_GLOBAL_METRICS = _MetricsSink()


def get_metrics() -> _MetricsSink:
    """Return the global in-process metrics sink."""
    return _GLOBAL_METRICS


class StructuredLogger:
    """Emit structured JSON log records to stderr.

    All records are redacted before emission.
    """

    def __init__(
        self,
        *,
        surface: str = "cli",
        profile: str = "default",
    ) -> None:
        self._surface = surface
        self._profile = profile

    def _emit(self, record: dict[str, Any]) -> None:
        safe = redact_dict(record)
        # Single write (message + newline together) so concurrent worker-thread
        # log lines never interleave on stderr.
        sys.stderr.write(json.dumps(safe, sort_keys=True) + "\n")

    def log_op(
        self,
        op: str,
        *,
        outcome: str,
        latency_ms: float | None = None,
        error_class: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit a structured log record for a completed operation."""
        record: dict[str, Any] = {
            "run_id": _run_id_mod.get_run_id(),
            "op": op,
            "surface": self._surface,
            "profile": self._profile,
            "outcome": outcome,
        }
        if latency_ms is not None:
            record["latency_ms"] = round(latency_ms, 3)
        if error_class:
            record["error_class"] = error_class
        if extra:
            record.update(extra)
        self._emit(record)


@contextmanager
def observe_op(
    op: str,
    *,
    surface: str = "cli",
    profile: str = "default",
    logger: StructuredLogger | None = None,
    metrics: _MetricsSink | None = None,
) -> Generator[None, None, None]:
    """Context manager that times, logs, and metrics one operation.

    Ensures a run_id exists (generates one if absent). Records structured log
    and metrics on both success and error paths.

    Usage::

        with observe_op("drive.fetch"):
            result = _call_api()
    """
    _run_id_mod.ensure_run_id()
    from .personal_runtime import current
    runtime = current()
    if runtime is not None:
        runtime.active()
        profile = runtime.profile
    _logger = logger or StructuredLogger(surface=surface, profile=profile)
    _metrics = metrics or _GLOBAL_METRICS
    _metrics.record_call(op)
    start = time.monotonic()
    tracer = _get_otel_tracer()
    span_ctx: Any = None
    span: Any = None
    if tracer is not None:
        try:
            span_ctx = tracer.start_as_current_span(op)
            span = span_ctx.__enter__()
        except Exception:
            span_ctx = None
            span = None
    try:
        yield
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000.0
        error_class = type(exc).__name__
        _metrics.record_latency(op, latency)
        _metrics.record_error(op, error_class)
        _logger.log_op(op, outcome="error", latency_ms=latency, error_class=error_class)
        if span is not None:
            try:
                span.set_attribute("outcome", "error")
                span.set_attribute("error_class", error_class)
            except Exception:
                pass
        raise
    else:
        latency = (time.monotonic() - start) * 1000.0
        _metrics.record_latency(op, latency)
        _logger.log_op(op, outcome="ok", latency_ms=latency)
        if span is not None:
            try:
                span.set_attribute("outcome", "ok")
                span.set_attribute("latency_ms", latency)
            except Exception:
                pass
    finally:
        if span_ctx is not None:
            try:
                span_ctx.__exit__(None, None, None)
            except Exception:
                pass
