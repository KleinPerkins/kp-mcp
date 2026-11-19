"""Lazy Snowflake session wrapper with MCP-safe browser SSO behavior."""
from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Iterator

from .config import SnowKitConfig
from .errors import Auth, SnowKitError, Timeout, classify_connector
from .sql import sanitize_identifier

logger = logging.getLogger("snow_kit")
logging.getLogger("snowflake.connector").setLevel(logging.WARNING)
logging.getLogger("snowflake.connector.vendored.urllib3").setLevel(logging.WARNING)

_AUTH_LOCK_OP = "session.connect"
_AUTH_LOCK_POLL_SECONDS = 0.05


@contextmanager
def suppress_stdout() -> Any:
    """Prevent externalbrowser login chatter from corrupting MCP stdio."""
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        yield
    finally:
        sys.stdout = old_stdout


def _auth_lock_dir(config: SnowKitConfig) -> Path:
    configured_lock = os.environ.get("SNOW_KIT_AUTH_LOCK_DIR")
    configured_state = os.environ.get("SNOW_KIT_STATE_DIR")
    if configured_lock:
        path = Path(configured_lock).expanduser()
    elif config.auth_lock_dir:
        path = config.auth_lock_dir
    else:
        if configured_state:
            path = Path(configured_state).expanduser() / "locks"
        elif config.state_dir:
            path = config.state_dir / "locks"
        else:
            state_home = os.environ.get("XDG_STATE_HOME")
            root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
            path = root / "snow-kit" / "locks"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _externalbrowser_lock_path(config: SnowKitConfig) -> Path:
    seed = json.dumps(
        {
            "account": config.account,
            "authenticator": config.authenticator,
            "user": config.user or "",
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return _auth_lock_dir(config) / f"externalbrowser-{digest}.lock"


@contextmanager
def _externalbrowser_connect_lock(config: SnowKitConfig) -> Iterator[None]:
    """Serialize browser SSO connect across snow-kit server processes on this host."""
    if config.authenticator.lower() != "externalbrowser":
        yield
        return
    try:
        import fcntl
    except Exception as exc:  # pragma: no cover - fcntl exists on supported macOS hosts.
        raise Auth("externalbrowser SSO serialization requires fcntl", op=_AUTH_LOCK_OP) from exc

    lock_path = _externalbrowser_lock_path(config)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.chmod(lock_path, 0o600)
        handle = os.fdopen(fd, "w", encoding="utf-8")
    except OSError as exc:
        raise Auth(f"could not create snow-kit SSO lock at {lock_path}: {exc}", op=_AUTH_LOCK_OP) from exc

    deadline = time.monotonic() + max(config.auth_lock_timeout_seconds, 0)
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                handle.close()
                raise Auth(f"could not acquire snow-kit SSO lock at {lock_path}: {exc}", op=_AUTH_LOCK_OP) from exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                handle.close()
                raise Timeout(
                    "timed out waiting for snow-kit externalbrowser SSO lock; "
                    "another process may still be completing browser authentication",
                    op=_AUTH_LOCK_OP,
                    context={"lock_path": str(lock_path)},
                )
            time.sleep(min(_AUTH_LOCK_POLL_SECONDS, remaining))
    try:
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


@dataclass
class QueryResult:
    rows: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    truncated: bool
    execution_time_ms: float


class SnowflakeSession:
    """Stateful, lazily connected Snowflake session."""

    def __init__(self, config: SnowKitConfig | None = None) -> None:
        self.config = config or SnowKitConfig.from_env()
        self._conn: Any | None = None
        self._lock = threading.RLock()
        logger.info("snow-kit config: %s", json.dumps(self.config.redacted(), sort_keys=True))

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

    def _connect(self) -> Any:
        import snowflake.connector

        with _externalbrowser_connect_lock(self.config), suppress_stdout():
            conn = snowflake.connector.connect(
                **self.config.connector_kwargs(),
                client_session_keep_alive=True,
                login_timeout=self.config.login_timeout_seconds,
                network_timeout=self.config.network_timeout_seconds,
                query_timeout=self.config.statement_timeout_seconds,
            )
        self._configure_session(conn)
        return conn

    def _configure_session(self, conn: Any) -> None:
        with conn.cursor() as cursor:
            tag = {
                "query_source": "kp-mcp.snow-kit",
                "account": self.config.account,
                "posture": "read-default",
            }
            try:
                cursor.execute("ALTER SESSION SET QUERY_TAG = %s", (json.dumps(tag, sort_keys=True),))
                cursor.execute("ALTER SESSION SET TIMEZONE = 'UTC'")
                cursor.execute(
                    f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {self.config.statement_timeout_seconds}"
                )
            except Exception as exc:  # noqa: BLE001 - non-fatal session hardening.
                logger.warning("failed to set session parameters: %s", exc)
            for keyword, value in (
                ("WAREHOUSE", self.config.warehouse),
                ("DATABASE", self.config.database),
                ("SCHEMA", self.config.schema),
            ):
                if value:
                    try:
                        cursor.execute(f"USE {keyword} {sanitize_identifier(value)}")
                    except Exception as exc:  # noqa: BLE001 - keep login usable if context is absent.
                        logger.warning("failed to use %s %s: %s", keyword.lower(), value, exc)

    def verify_link(self, retries: int = 0) -> Any:
        with self._lock:
            if self._conn is None:
                self._conn = self._connect()
            try:
                with self._conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()"
                    )
            except Exception as exc:  # noqa: BLE001 - connector errors vary by version.
                stale = self._conn
                self._conn = None
                if stale is not None:
                    try:
                        stale.close()
                    except Exception:  # noqa: BLE001 - best-effort close on stale handle.
                        pass
                if retries >= self.config.max_reconnect_retries:
                    raise ConnectionError("Failed to establish Snowflake connection after retries") from exc
                return self.verify_link(retries + 1)
            return self._conn

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | list[Any] | None = None,
        *,
        op: str,
        max_rows: int | None = None,
    ) -> QueryResult:
        with self._lock:
            try:
                conn = self.verify_link()
                return self._execute_locked(conn, sql, params, op=op, max_rows=max_rows)
            except SnowKitError:
                raise
            except Exception as exc:  # noqa: BLE001 - connector errors vary by version.
                raise classify_connector(exc, op=op) from exc

    def _execute_locked(
        self,
        conn: Any,
        sql: str,
        params: tuple[Any, ...] | list[Any] | None,
        *,
        op: str,
        max_rows: int | None,
    ) -> QueryResult:
        start = time.perf_counter()
        limit = min(max_rows or self.config.max_result_rows, self.config.max_result_rows)
        with conn.cursor() as cursor:
            cursor.execute(self._tagged(sql, op), tuple(params or ()))
            columns = [col[0] for col in (cursor.description or [])]
            rows: list[dict[str, Any]] = []
            truncated = False
            if columns:
                fetched = cursor.fetchmany(limit)
                rows = [dict(zip(columns, row)) for row in fetched]
                truncated = cursor.fetchone() is not None
            elapsed = (time.perf_counter() - start) * 1000
            return QueryResult(
                rows=rows,
                columns=columns,
                row_count=getattr(cursor, "rowcount", len(rows)) if not columns else len(rows),
                truncated=truncated,
                execution_time_ms=elapsed,
            )

    def scalar(self, sql: str) -> Any:
        result = self.execute(sql, op="session.scalar", max_rows=1)
        if not result.rows:
            return None
        return next(iter(result.rows[0].values()))

    def current_context(self) -> dict[str, Any]:
        result = self.execute(
            "SELECT CURRENT_USER() AS USER, CURRENT_ROLE() AS ROLE, CURRENT_DATABASE() AS DATABASE, CURRENT_SCHEMA() AS SCHEMA",
            op="session.context",
            max_rows=1,
        )
        return result.rows[0] if result.rows else {}

    def show_current_role_grants(self) -> list[dict[str, Any]]:
        """Return grants for the session's active role (not a literal role name)."""
        return self.execute("SHOW GRANTS", op="catalog.check_write_access").rows

    def _tagged(self, sql: str, op: str) -> str:
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:12]
        return f"/* snow-kit:{op}:{digest} */\n{sql}"


_DEFAULT_SESSION: SnowflakeSession | None = None
_SESSION_INIT_LOCK = threading.Lock()


def default_session() -> SnowflakeSession:
    """Return the process-wide Snowflake session (thread-safe lazy init)."""
    global _DEFAULT_SESSION
    if _DEFAULT_SESSION is not None:
        return _DEFAULT_SESSION
    with _SESSION_INIT_LOCK:
        if _DEFAULT_SESSION is None:
            _DEFAULT_SESSION = SnowflakeSession()
        return _DEFAULT_SESSION
