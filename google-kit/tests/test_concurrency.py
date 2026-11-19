"""Concurrency regression tests for the shared MCP server and token refresh.

Reproduces (and pins the fix for) the reported failure: two concurrent chats
sharing one google-kit MCP server collided and one lost connectivity. Two root
causes are covered:

  1. Event-loop starvation — the MCP SDK dispatches every ``call_tool`` request
     as its own task on a SINGLE asyncio loop. The handler must offload the
     synchronous core fn (Keychain subprocess, googleapiclient network I/O,
     retry back-off sleeps, audit file write) to a worker thread; otherwise one
     slow/blocking call freezes the loop and every other chat's calls — and the
     protocol pings — time out. See ``google_kit.mcp._call_tool``.

  2. Refresh-token rotation race — two callers hitting an expired access token at
     once must not both refresh: under Google refresh-token rotation the slower
     refresh would invalidate the faster one's token. The persisting-credentials
     ``refresh`` must be single-flight AND re-read the latest refresh token under
     the lock. See ``google_kit.core.client._make_persisting_credentials``.

No live network and no Keychain — a fake service / fake store is injected.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

import google_kit  # noqa: F401 — triggers service auto-registration
from google_kit.mcp import build_mcp_server


def _call_tool_handler(server: Any) -> Any:
    from mcp.types import CallToolRequest

    return server.request_handlers[CallToolRequest]


def _tasks_list_request() -> Any:
    from mcp.types import CallToolRequest, CallToolRequestParams

    return CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="tasks_list_lists", arguments={"max_results": 1}),
    )


def test_slow_tool_call_does_not_block_concurrent_call_on_shared_loop() -> None:
    """A blocking tool call in one chat must not stall a second concurrent call.

    Two ``call_tool`` requests are dispatched as concurrent tasks on one loop
    (exactly how the SDK runs them). The first resolves a service whose
    ``execute()`` blocks until the second's ``execute()`` releases it. If the
    blocking work runs inline on the event-loop thread (the bug), the loop is
    frozen, the second call can never run, and the first waits out its full
    timeout — recording ``slow_saw_release is False``. With the work offloaded to
    a worker thread (the fix), the second call runs concurrently and releases the
    first almost immediately — ``slow_saw_release is True``.
    """
    started = threading.Event()
    release = threading.Event()
    slow_saw_release: dict[str, bool | None] = {"v": None}
    counter = {"n": 0}
    counter_lock = threading.Lock()

    class _SlowExec:
        def execute(self) -> Any:
            started.set()
            # True iff the *other* concurrent call ran and released us — only
            # possible if the event loop was not blocked by this call.
            slow_saw_release["v"] = release.wait(timeout=10)
            return {"items": []}

    class _FastExec:
        def execute(self) -> Any:
            release.set()
            return {"items": []}

    class _Proxy:
        def __init__(self, exec_obj: Any) -> None:
            self._exec = exec_obj

        def list(self, **_kwargs: Any) -> Any:
            return self._exec

    class _Svc:
        def __init__(self, exec_obj: Any) -> None:
            self._exec = exec_obj

        def tasklists(self) -> Any:
            return _Proxy(self._exec)

    def factory(op_name: str, *, profile: str | None = None) -> Any:
        del op_name, profile
        with counter_lock:
            n = counter["n"]
            counter["n"] += 1
        return _Svc(_SlowExec()) if n == 0 else _Svc(_FastExec())

    server = build_mcp_server(_service_factory=factory)
    handler = _call_tool_handler(server)

    async def _run() -> None:
        t1 = asyncio.create_task(handler(_tasks_list_request()))
        t2 = asyncio.create_task(handler(_tasks_list_request()))
        await asyncio.wait_for(asyncio.gather(t1, t2), timeout=15)

    asyncio.run(_run())

    assert slow_saw_release["v"] is True, (
        "the second concurrent tool call did not run while the first was blocked — "
        "the synchronous core fn is blocking the shared event loop"
    )


def test_persisting_credentials_refresh_is_single_flight_and_rereads_rotated_token(
    monkeypatch: Any,
) -> None:
    """Concurrent ``refresh()`` calls serialize and pick up a peer's rotated token.

    * **Single-flight** — the underlying ``Credentials.refresh`` never runs in two
      threads at once (``max_concurrent == 1``), so concurrent callers can't race
      a refresh-token rotation.
    * **Rotation-safe** — under the lock, the latest ``refresh_token`` is re-read
      from the store before refreshing, so a stale in-memory copy (already rotated
      by a peer) is replaced rather than sent to Google as an ``invalid_grant``.
    * **Persisted** — the new access token is written back to the store.
    """
    import time

    from google.oauth2.credentials import Credentials as _GCreds

    from google_kit.core import client as client_mod

    class _FakeStore:
        # Deliberately no ``_profile`` attr → the cross-process file lock degrades
        # to a no-op; the in-process thread lock alone is exercised here.
        def __init__(self) -> None:
            self.data = {
                "access_token": "old-access",
                "refresh_token": "rotated-by-peer",  # store is AHEAD of memory
                "client_secret": "secret",
            }
            self.set_calls: list[tuple[str, str]] = []

        def get(self, key: str) -> str:
            return self.data[key]

        def set(self, key: str, value: str) -> None:
            self.set_calls.append((key, value))
            self.data[key] = value

    store = _FakeStore()
    creds = client_mod._make_persisting_credentials(
        token="old-access",
        refresh_token="stale-in-memory",  # behind the store (peer rotated it)
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="secret",
        store=store,
    )
    assert creds.refresh_token == "stale-in-memory"

    in_flight = 0
    max_concurrent = 0
    state_lock = threading.Lock()

    def _fake_super_refresh(self: Any, request: Any) -> None:
        nonlocal in_flight, max_concurrent
        with state_lock:
            in_flight += 1
            max_concurrent = max(max_concurrent, in_flight)
        time.sleep(0.02)  # widen the window for a race to manifest if unlocked
        self.token = "new-access"  # Google sets a fresh access token on refresh
        with state_lock:
            in_flight -= 1

    monkeypatch.setattr(_GCreds, "refresh", _fake_super_refresh)

    threads = [
        threading.Thread(target=lambda: creds.refresh(object())) for _ in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_concurrent == 1, "token refresh is not single-flight across threads"
    assert creds.refresh_token == "rotated-by-peer", "did not re-read the rotated token under the lock"
    assert ("access_token", "new-access") in store.set_calls, "refreshed access token not persisted"


def test_refresh_cross_process_lock_engages_for_real_profile_and_degrades_without(
    monkeypatch: Any, tmp_path: Any
) -> None:
    """The cross-process refresh lock — the fix for the two-server-process bug —
    engages when the store exposes ``profile`` (the public contract attribute),
    creating a per-profile lock file under the config dir, and degrades to a no-op
    (no lock file) for an injected store that lacks it. This exercises the real
    ``fcntl.flock`` branch of ``_refresh_file_lock`` that the single-flight test
    above deliberately skips.
    """
    from google.oauth2.credentials import Credentials as _GCreds

    from google_kit.core import client as client_mod

    config_dir = tmp_path / "lockdir"
    monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(_GCreds, "refresh", lambda self, request: setattr(self, "token", "new"))

    def _mk(store: Any) -> Any:
        return client_mod._make_persisting_credentials(
            token="a",
            refresh_token="r",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="c",
            client_secret="s",
            store=store,
        )

    class _ProfiledStore:
        profile = "p-test"  # public contract attr → cross-process lock engages

        def __init__(self) -> None:
            self.data = {"access_token": "a", "refresh_token": "r", "client_secret": "s"}

        def get(self, key: str) -> str:
            return self.data[key]

        def set(self, key: str, value: str) -> None:
            self.data[key] = value

    class _NoProfileStore(_ProfiledStore):
        profile = None  # type: ignore[assignment]  # → degrade to thread lock only

    _mk(_ProfiledStore()).refresh(object())
    assert (config_dir / "refresh-p-test.lock").exists(), (
        "cross-process refresh lock did not engage for a store exposing `profile`"
    )

    locks_before = set(config_dir.glob("refresh-*.lock"))
    _mk(_NoProfileStore()).refresh(object())
    assert set(config_dir.glob("refresh-*.lock")) == locks_before, (
        "a store without `profile` must NOT create a cross-process lock file"
    )
