"""Snowflake session connection behavior tests."""
from __future__ import annotations

import errno
import threading
import time
from unittest.mock import patch

import pytest

from snow_kit.core.config import SnowKitConfig
from snow_kit.core.connection import QueryResult, SnowflakeSession, _externalbrowser_connect_lock
from snow_kit.core.errors import Timeout


class _FakeCursor:
    description: list[tuple[str, ...]] = []
    rowcount = 0

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, *_args, **_kwargs) -> "_FakeCursor":
        return self


class _FakeConn:
    def cursor(self) -> _FakeCursor:
        return _FakeCursor()


def test_show_current_role_grants_uses_show_grants() -> None:
    session = SnowflakeSession.__new__(SnowflakeSession)
    captured: list[str] = []

    def fake_execute(sql: str, params=None, *, op: str, max_rows: int | None = None) -> QueryResult:
        del params, max_rows
        captured.append(sql)
        assert op == "catalog.check_write_access"
        return QueryResult(
            [{"privilege": "INSERT", "granted_on": "TABLE", "name": "EXAMPLE_DB.SCRATCH.DEMO"}],
            ["privilege", "granted_on", "name"],
            1,
            False,
            1.0,
        )

    session.execute = fake_execute  # type: ignore[method-assign]

    rows = session.show_current_role_grants()

    assert captured == ["SHOW GRANTS"]
    assert rows[0]["privilege"] == "INSERT"


def test_registered_user_is_migration_input_not_runtime_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SNOW_KIT_USER", raising=False)
    monkeypatch.delenv("SNOWFLAKE_USER", raising=False)
    monkeypatch.delenv("SNOW_KIT_LEGACY_CONFIG_PATH", raising=False)

    mcp_dir = tmp_path / ".cursor"
    mcp_dir.mkdir()
    cursor = mcp_dir / "mcp.json"
    cursor.write_text(
        '{"mcpServers": {"snow-kit": {"env": {"SNOW_KIT_USER": "kept@example.invalid"}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("snow_kit.core.config.Path.home", lambda: tmp_path)

    from snow_kit.core.config import SnowKitConfig, resolve_snowflake_user

    assert resolve_snowflake_user() == "kept@example.invalid"
    assert SnowKitConfig.from_env().user is None


def test_externalbrowser_connect_lock_serializes_connector_path(tmp_path, monkeypatch) -> None:
    import fcntl

    monkeypatch.setenv("SNOW_KIT_AUTH_LOCK_DIR", str(tmp_path / "locks"))
    lock = threading.Lock()
    state_lock = threading.Lock()
    in_flight = 0
    max_concurrent = 0
    errors: list[Exception] = []

    def fake_flock(_fd: int, flags: int) -> None:
        if flags & fcntl.LOCK_UN:
            lock.release()
            return
        if flags & fcntl.LOCK_EX and not lock.acquire(blocking=False):
            raise BlockingIOError(errno.EAGAIN, "locked")

    def fake_connect(**_kwargs) -> _FakeConn:
        nonlocal in_flight, max_concurrent
        with state_lock:
            in_flight += 1
            max_concurrent = max(max_concurrent, in_flight)
        time.sleep(0.08)
        with state_lock:
            in_flight -= 1
        return _FakeConn()

    monkeypatch.setattr(fcntl, "flock", fake_flock)
    monkeypatch.setattr("snowflake.connector.connect", fake_connect)
    config = SnowKitConfig(user="operator@example.invalid", auth_lock_timeout_seconds=5)

    def worker() -> None:
        try:
            SnowflakeSession(config)._connect()
        except Exception as exc:  # pragma: no cover - surfaced by assertion below.
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert max_concurrent == 1
    assert list((tmp_path / "locks").glob("externalbrowser-*.lock"))


def test_externalbrowser_connect_lock_timeout_maps_to_timeout(tmp_path, monkeypatch) -> None:
    import fcntl

    monkeypatch.setenv("SNOW_KIT_AUTH_LOCK_DIR", str(tmp_path / "locks"))

    def always_locked(_fd: int, flags: int) -> None:
        if flags & fcntl.LOCK_EX:
            raise BlockingIOError(errno.EAGAIN, "locked")

    monkeypatch.setattr(fcntl, "flock", always_locked)
    config = SnowKitConfig(user="operator@example.invalid", auth_lock_timeout_seconds=0)

    with pytest.raises(Timeout) as exc:
        with _externalbrowser_connect_lock(config):
            pass

    assert exc.value.op == "session.connect"
