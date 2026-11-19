"""Authorized Google API client builder and call pipeline for google-kit core.

Builds an authorized ``googleapiclient`` service from tokens stored in a
``SecretStore`` (macOS Keychain).  On token refresh, the new access token is
persisted back to the store — no plaintext ever written to disk.

``execute_api_call`` wraps every Google API call with:
  retry    — Transient / QuotaRateLimit; respects Retry-After
  classify — googleapiclient.errors.HttpError → taxonomy error
  observe  — structured log + metrics (run_id, op, latency)
  audit    — append-only JSONL record for mutations (write/destructive)
  normalize— returns the raw API dict; callers wrap in OutputEnvelope
"""
from __future__ import annotations

import contextlib
import os
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

from kp_mcp_bootstrap.secrets import SecretStore

from google_kit.core import observability as _obs_mod
from google_kit.core import run_id as _run_id_mod
from google_kit.core.audit import get_actor, write_audit
from google_kit.core.errors import GoogleKitError, classify
from google_kit.core.observability import observe_op
from google_kit.core.retry import with_retry

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

_POSTURES_THAT_AUDIT: frozenset[str] = frozenset({"write", "destructive"})

#: Serializes OAuth token refresh across worker threads in ONE process. The MCP
#: server runs each tool call in its own thread, so two calls can hit an expired
#: access token at the same instant; without this both would refresh and — under
#: Google refresh-token rotation — the slower one would be left holding an
#: invalidated refresh token, failing every subsequent call (a chat that
#: "loses connectivity"). Paired with the cross-process file lock below for the
#: case where two chats each spawn their own google-kit server process.
_REFRESH_THREAD_LOCK = threading.Lock()

#: Guards the one-time lazy creation of the _PersistingCredentials subclass so
#: concurrent worker threads cannot build two competing class objects.
_CLS_LOCK = threading.Lock()


@contextlib.contextmanager
def _refresh_file_lock(store: SecretStore) -> Iterator[None]:
    """Best-effort cross-process exclusive lock held around a token refresh.

    Serializes refresh across separate MCP server processes (e.g. two Cursor
    chats each running their own google-kit server) that share the single
    Keychain token store, keyed per profile. Degrades to a no-op — relying on
    the in-process thread lock alone — when no real profile is known (injected
    test stores), when the config dir is unwritable, or when ``fcntl`` is
    unavailable, so it never blocks or fails a refresh.
    """
    # `profile` is part of the SecretStore contract (KeychainSecretStore exposes
    # it); injected/fake stores that omit it have no real Keychain and no
    # cross-process peer, so the in-process thread lock already held is enough.
    from .personal_runtime import current, held
    if current() is not None:
        held("legacy_refresh_lock_refused")
    profile = getattr(store, "profile", None)
    if profile is None:
        yield
        return
    # Defense-in-depth: the profile is interpolated into the lock filename, so a
    # name that could escape the config dir (separator / NUL / dot-dot / absolute)
    # must never form a path. A real Keychain profile is always a plain segment;
    # degrade to the in-process lock rather than touch an arbitrary path.
    if (
        profile in (".", "..")
        or "/" in profile
        or "\\" in profile
        or "\x00" in profile
        or os.path.isabs(profile)
    ):
        yield
        return
    try:
        import fcntl
    except Exception:
        yield
        return
    # Resolve the config dir the same way the rest of the kit does (honoring
    # GOOGLE_KIT_CONFIG_DIR / CHAOS_LABS_ROOT / macOS default) so this lock lands
    # in the SAME directory as every peer process — otherwise the cross-process
    # exclusion silently no-ops. Fall back to the SAME precedence by hand if the
    # config load fails (e.g. an empty GOOGLE_KIT_PROFILE makes load_config raise,
    # though the dir itself doesn't depend on the profile).
    try:
        from kp_mcp_bootstrap.config import load_config

        config_dir = str(load_config().config_dir)
    except Exception:
        chaos_root = os.environ.get("CHAOS_LABS_ROOT")
        config_dir = (
            os.environ.get("GOOGLE_KIT_CONFIG_DIR")
            or (os.path.join(chaos_root, "data", "google-kit") if chaos_root else None)
            or os.path.join(
                os.path.expanduser("~"), "Library", "Application Support", "google-kit"
            )
        )
    try:
        os.makedirs(config_dir, exist_ok=True)
        lock_path = os.path.join(config_dir, f"refresh-{profile}.lock")
        handle = open(lock_path, "w", encoding="utf-8")
    except OSError:
        yield
        return
    try:
        # The blocking acquire itself can fail on filesystems without lock
        # support (e.g. some NFS/SMB mounts → ENOLCK). Degrade to the in-process
        # thread lock rather than failing the refresh.
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError:
        handle.close()
        yield
        return
    try:
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

#: Top-level result keys that are NOT resource identifiers despite matching the
#: id-key heuristic — excluded so they never pollute the audit ``target_ids``.
_NON_ID_RESULT_KEYS: frozenset[str] = frozenset({"kind", "etag"})


def _extract_target_ids(result: Any) -> list[str]:
    """Best-effort extraction of mutated-resource identifiers from an API result.

    Scans the top level of a result dict for id-like keys (``id`` or any
    ``*Id`` / ``*_id`` key, e.g. ``fileId``, ``messageId``, ``scriptId``,
    ``spreadsheetId``, ``threadId``) whose value is a non-empty string. The
    display-``name`` key is deliberately NOT treated as an identifier — for most
    Google APIs it is a human-readable title (redacted as PII elsewhere) rather
    than a resource id, and ``target_ids`` is written without redaction. Callers
    whose identifier lives in a resource-path ``name`` (Keep, Workspace Events)
    pass ``target_ids`` explicitly. Returns a de-duplicated, order-stable list.
    Never raises.
    """
    if not isinstance(result, dict):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for key, value in result.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            continue
        if key in _NON_ID_RESULT_KEYS:
            continue
        is_id_key = key == "id" or key.endswith("Id") or key.endswith("_id")
        if is_id_key and value not in seen:
            seen.add(value)
            ids.append(value)
    return ids


class _PersistingCredentials:
    """Subclass of google.oauth2.credentials.Credentials that persists refreshed tokens.

    Inherits directly from ``google.oauth2.credentials.Credentials`` so that
    ``isinstance(creds, google.auth.credentials.Credentials)`` is True and
    ``googleapiclient`` routes through the modern auth path (not the legacy
    oauth2client ``credentials.authorize(http)`` branch).

    Overrides ``refresh()`` to persist the new ``access_token`` (and
    ``refresh_token`` if rotated) back to the ``SecretStore`` after every
    successful refresh.  No plaintext is ever written to disk.
    """

    # Populated lazily at first construction to avoid a module-level import of
    # google.oauth2 before the package is guaranteed to be available.
    _base_cls: type | None = None

    def __class_getitem__(cls, item: Any) -> Any:  # pragma: no cover
        return cls

    def __init_subclass__(cls, **kwargs: Any) -> None:  # pragma: no cover
        super().__init_subclass__(**kwargs)


def _make_persisting_credentials(
    *,
    token: str,
    refresh_token: str,
    token_uri: str,
    client_id: str,
    client_secret: str,
    store: SecretStore,
) -> Any:
    """Construct a ``_PersistingCredentials`` instance.

    The actual class is built once and cached on the module so that the
    ``google.oauth2`` import happens only when first needed (mirrors the
    existing lazy-import pattern in ``build_authorized_service``).
    """
    from .personal_runtime import current, held
    if current() is not None:
        held("legacy_credentials_refused")
    from google.oauth2.credentials import Credentials as _GCreds

    if not hasattr(_make_persisting_credentials, "_cls"):
        with _CLS_LOCK:
            if not hasattr(_make_persisting_credentials, "_cls"):

                class _Impl(_GCreds):
                    def __init__(self, *args: Any, _store: SecretStore, **kwargs: Any) -> None:
                        super().__init__(*args, **kwargs)
                        self._store = _store

                    def refresh(self, request: Any) -> None:
                        # Serialize refresh across threads AND processes so two
                        # concurrent chats never race a refresh-token rotation that
                        # would invalidate one of them (rotation-safe — not deduped:
                        # a serialized waiter still refreshes, but only after
                        # re-reading the latest token below). Under the lock, re-read
                        # the latest refresh token first: a peer may have just
                        # rotated it, and refreshing with our stale in-memory copy
                        # would fail with invalid_grant.
                        with _REFRESH_THREAD_LOCK:
                            with _refresh_file_lock(self._store):
                                try:
                                    latest_refresh = self._store.get("refresh_token")
                                except Exception:
                                    latest_refresh = None
                                if latest_refresh and latest_refresh != self.refresh_token:
                                    self._refresh_token = latest_refresh
                                super().refresh(request)
                                self._store.set("access_token", self.token)
                                if self.refresh_token:
                                    self._store.set("refresh_token", self.refresh_token)

                _make_persisting_credentials._cls = _Impl  # type: ignore[attr-defined]

    cls = _make_persisting_credentials._cls  # type: ignore[attr-defined]
    return cls(
        token=token,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        _store=store,
    )


def build_authorized_service(
    service_name: str,
    version: str,
    store: SecretStore,
    *,
    client_id: str,
    token_uri: str = _GOOGLE_TOKEN_ENDPOINT,
    build_fn: Callable[..., Any] | None = None,
) -> Any:
    """Build an authorized ``googleapiclient`` service from tokens in the SecretStore.

    Args:
        service_name: Google API name, e.g. ``"tasks"``.
        version:      API version string, e.g. ``"v1"``.
        store:        SecretStore holding ``access_token``, ``refresh_token``,
                      and ``client_secret``.  All reads fail-loud if absent.
        client_id:    OAuth 2.0 client ID (not secret; safe to log).
        token_uri:    Token refresh endpoint (default: Google's).
        build_fn:     Override ``googleapiclient.discovery.build`` for tests.

    Returns:
        Authorized ``Resource`` object from ``googleapiclient``.
    """
    from .personal_runtime import current, held
    if current() is not None:
        held("legacy_service_builder_refused")
    access_token = store.get("access_token")
    refresh_token = store.get("refresh_token")
    client_secret = store.get("client_secret")

    creds = _make_persisting_credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        store=store,
    )

    if build_fn is not None:
        return build_fn(service_name, version, credentials=creds)

    from googleapiclient.discovery import build as _build

    return _build(service_name, version, credentials=creds)


def execute_api_call(
    api_fn: Callable[[], Any],
    *,
    op: str,
    posture: str,
    actor: str | None = None,
    surface: str = "cli",
    profile: str = "default",
    audit_file: Path | None = None,
    max_attempts: int = 4,
    normalized_request: dict[str, Any] | None = None,
    target_ids: list[str] | Callable[[Any], list[str]] | None = None,
) -> Any:
    """Execute a googleapiclient API call through the full core pipeline.

    Pipeline (in order):
      1. Ensure run_id exists.
      2. observe_op: time, log, and metric the call.
      3. HttpError → classify() → taxonomy exception.
      4. with_retry: back-off on Transient / QuotaRateLimit.
      5. write_audit: append-only record for mutations (write/destructive only) —
         ``result="ok"`` on success, ``result="error"`` with a redacted summary
         when the API call fails (after retries) or is denied by the server.

    Args:
        api_fn:       Zero-arg callable that performs the API call and returns
                      the raw response dict (or None for empty responses).
        op:           Dotted operation name, e.g. ``"tasks.list_lists"``.
        posture:      One of ``"read"`` | ``"write"`` | ``"destructive"``.
        actor:        Identity string (profile name); written to audit log. When
                      omitted (the common case for service core fns), it is read
                      from the ``actor`` contextvar set by the CLI/MCP boundary,
                      falling back to ``"default"``.
        surface:      ``"cli"`` or ``"mcp"`` (for structured logs).
        profile:      Config profile name.
        audit_file:   Override audit JSONL path (for tests).
        max_attempts: Max retry attempts for retryable errors.
        normalized_request: Validated op input (typically ``inp.model_dump()``)
                      recorded in the mutation audit record. PII/secrets are
                      redacted by ``write_audit`` via ``redact_dict`` before it is
                      written — pass the raw model dump, never pre-redact secrets
                      out of existence. Ignored for read-posture calls.
        target_ids:   Explicit resource ids mutated by the call. When omitted (the
                      common case), ids are auto-extracted from the API result via
                      :func:`_extract_target_ids`. Pass a ``list[str]`` for ops
                      whose target is known from the input (e.g. a delete by id),
                      or a ``Callable[[result], list[str]]`` for create ops whose
                      identifier is only known post-call and is not a top-level
                      ``*Id`` field (e.g. a resource-path ``name`` — Keep,
                      Workspace Events).

    Returns:
        Raw API response dict (or None for empty responses like delete).

    Raises:
        GoogleKitError subclass on any API failure after retries exhausted.
    """
    from .personal_runtime import current, held
    runtime = current()
    if runtime is not None:
        runtime.active()
        if actor is not None and actor != runtime.profile:
            held("actor_override_refused")
        if profile not in ("default", runtime.profile):
            held("profile_override_refused")
        if audit_file is not None and Path(audit_file) != runtime.directory.path / "personal-audit.jsonl":
            held("audit_override_refused")
        actor = profile = runtime.profile
    _run_id_mod.ensure_run_id()

    def _classified_call() -> Any:
        try:
            return api_fn()
        except Exception as exc:
            classified = _classify_exception(exc, op=op)
            if classified is not None:
                raise classified from exc
            raise

    result: Any = None
    audits = posture in _POSTURES_THAT_AUDIT

    try:
        with observe_op(op, surface=surface, profile=profile):
            result = with_retry(_classified_call, max_attempts=max_attempts, op=op)
    except GoogleKitError as exc:
        # Failed mutation: emit an ``error`` audit record so denied/failed writes
        # are not silently absent from the append-only log. Boundary: this audits
        # API-call failures for write/destructive postures (e.g. a 403 Permission
        # or a 5xx Transient after retries are exhausted). Pre-call denials that
        # never reach ``execute_api_call`` — flag gates and input validation that
        # raise in the service core before the API call — are out of scope here
        # and audited (or refused) by the caller. The redacted exception summary
        # records WHY the mutation failed without leaking secrets.
        if audits:
            ids = target_ids if isinstance(target_ids, list) else []
            write_audit(
                actor=actor if actor is not None else get_actor(),
                op=op,
                normalized_request=normalized_request or {},
                target_ids=ids,
                result="error",
                error=f"{type(exc).__name__}: {exc.message}",
                audit_file=audit_file,
            )
        raise

    if audits:
        if callable(target_ids):
            ids = target_ids(result) or []
        elif target_ids is not None:
            ids = target_ids
        else:
            ids = _extract_target_ids(result)
        write_audit(
            actor=actor if actor is not None else get_actor(),
            op=op,
            normalized_request=normalized_request or {},
            target_ids=ids,
            result="ok",
            audit_file=audit_file,
        )

    return result


def _classify_exception(exc: Exception, *, op: str) -> GoogleKitError | None:
    """Translate a googleapiclient HttpError to a taxonomy error, or None.

    Returns None for non-Http exceptions (let them propagate as-is).
    """
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        return None

    if not isinstance(exc, HttpError):
        return None

    status = int(exc.resp.status)
    try:
        import json as _json

        details = _json.loads(exc.content or b"{}").get("error", {}).get("message", "")
    except Exception:
        details = str(exc)

    # Propagate the server's Retry-After header (seconds or HTTP-date) into the
    # error context so with_retry honors it instead of falling back to jitter
    # backoff. httplib2.Response lowercases header keys and behaves as a dict.
    context: dict[str, Any] | None = None
    resp = getattr(exc, "resp", None)
    if resp is not None:
        try:
            retry_after = resp.get("retry-after")
        except Exception:
            retry_after = None
        if retry_after is not None:
            context = {"retry_after": retry_after}

    return classify(status, details or f"HTTP {status}", op=op, context=context)
