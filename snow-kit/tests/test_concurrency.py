"""Concurrency regression tests for the shared snow-kit MCP server and session."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import pytest

from snow_kit.core.connection import QueryResult, SnowflakeSession, default_session
from snow_kit.mcp import build_mcp_server


def _call_tool_handler(server: Any) -> Any:
    from mcp.types import CallToolRequest

    return server.request_handlers[CallToolRequest]


def _query_execute_request() -> Any:
    from mcp.types import CallToolRequest, CallToolRequestParams

    return CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="query_execute",
            arguments={"query": "SELECT 1"},
        ),
    )


def test_slow_tool_call_does_not_block_concurrent_call_on_shared_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blocking work must run off the shared asyncio loop (google-kit parity)."""
    started = threading.Event()
    release = threading.Event()
    slow_saw_release: dict[str, bool | None] = {"v": None}
    counter = {"n": 0}
    counter_lock = threading.Lock()

    class _BlockingSession:
        def execute(self, sql: str, params: tuple[Any, ...] | None = None, *, op: str, max_rows: int | None = None) -> QueryResult:
            del sql, params, op, max_rows
            with counter_lock:
                n = counter["n"]
                counter["n"] += 1
            if n == 0:
                started.set()
                slow_saw_release["v"] = release.wait(timeout=10)
                return QueryResult([{"ONE": 1}], ["ONE"], 1, False, 1.0)
            release.set()
            return QueryResult([{"ONE": 2}], ["ONE"], 1, False, 1.0)

    monkeypatch.setattr("snow_kit.services.query.core.default_session", lambda: _BlockingSession())

    server = build_mcp_server()
    handler = _call_tool_handler(server)

    async def _run() -> None:
        t1 = asyncio.create_task(handler(_query_execute_request()))
        t2 = asyncio.create_task(handler(_query_execute_request()))
        await asyncio.wait_for(asyncio.gather(t1, t2), timeout=15)

    asyncio.run(_run())

    assert slow_saw_release["v"] is True


def test_session_execute_serializes_concurrent_threads() -> None:
    """One shared Snowflake session must not interleave cursor I/O across threads."""
    active = 0
    max_active = 0
    state_lock = threading.Lock()
    gate = threading.Event()

    class _FakeConn:
        def cursor(self) -> "_FakeCursor":
            return _FakeCursor()

        def close(self) -> None:
            return None

    class _FakeCursor:
        description = [("ONE",)]
        rowcount = 1

        def __enter__(self) -> "_FakeCursor":
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            gate.wait(timeout=5)
            return self

        def __exit__(self, *_args: Any) -> None:
            nonlocal active
            with state_lock:
                active -= 1

        def execute(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def fetchmany(self, _limit: int) -> list[tuple[int]]:
            return [(1,)]

        def fetchone(self) -> None:
            return None

    session = SnowflakeSession()
    session._conn = _FakeConn()  # noqa: SLF001 - test seam

    def _worker() -> None:
        session.execute("SELECT 1", op="query.execute", max_rows=1)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    time.sleep(0.05)
    gate.set()
    for thread in threads:
        thread.join(timeout=10)

    assert max_active == 1


def test_default_session_singleton_is_thread_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    import snow_kit.core.connection as connection_mod

    monkeypatch.setattr(connection_mod, "_DEFAULT_SESSION", None, raising=False)
    workers = 8
    start = threading.Barrier(workers)
    seen: list[int] = []
    seen_lock = threading.Lock()
    construction_count = 0
    construction_lock = threading.Lock()

    class _Session:
        pass

    def _construct_session() -> _Session:
        nonlocal construction_count
        with construction_lock:
            construction_count += 1
        time.sleep(0.05)
        return _Session()

    monkeypatch.setattr(connection_mod, "SnowflakeSession", _construct_session)

    def _worker() -> None:
        start.wait(timeout=5)
        session = default_session()
        with seen_lock:
            seen.append(id(session))

    threads = [threading.Thread(target=_worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert construction_count == 1
    assert len(seen) == workers
    assert len({*seen}) == 1
