"""Per-profile, per-tool write authorization (the 1/0 config model).

Covers the :mod:`google_kit.core.authz` store, the profile-aware gate in
:func:`google_kit.core.flags.ensure_enabled` (per-profile grant OR env override),
the ``google-kit auth grant/revoke/authorizations`` CLI commands and login
seeding, and end-to-end enforcement through both the CLI and the MCP adapter.

Hermetic: ``conftest._isolate_config_dir`` points ``GOOGLE_KIT_CONFIG_DIR`` at a
fresh tmp dir per test, so authz always starts empty (default-deny) and never
touches the developer's real grants. Module-level CRUD tests pass an explicit
``config_dir`` for full independence from the environment.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any

import pytest

import google_kit  # noqa: F401 - triggers op registration
from google_kit.cli import main as cli_main
from google_kit.cli.auth import (
    cmd_authorizations,
    cmd_grant,
    cmd_login,
    cmd_revoke,
)
from google_kit.core import authz
from google_kit.core.errors import GoogleKitError
from google_kit.core.flags import ENABLE_WRITES_FLAG, FlagDisabledError, ensure_enabled
from google_kit.mcp import build_mcp_server
from google_kit.registry import all_specs


def _spec(name: str, flag: str | None):
    """Minimal duck-typed OpSpec stand-in (name + flag)."""
    return SimpleNamespace(name=name, flag=flag)


def _a_read_op() -> str:
    return next(s.name for s in all_specs() if not s.flag)


def _drive_watch_op() -> str:
    return next(s.name for s in all_specs() if s.flag == "GOOGLE_KIT_ENABLE_DRIVE_WATCH")


@pytest.fixture(autouse=True)
def _deterministic_profile_env(monkeypatch):
    """Pin these tests to the 'default' profile with no ambient env override.

    The active profile resolves via the sandbox guardrail -> GOOGLE_KIT_PROFILE ->
    'default', and the GOOGLE_KIT_ENABLE_* flags are a runtime override path.
    Clear them all so the tests are hermetic regardless of the developer's / CI
    shell (e.g. a `GOOGLE_KIT_SANDBOX=1` or `GOOGLE_KIT_ENABLE_WRITES=1` export
    would otherwise skew the resolved profile or bypass default-deny).
    """
    for var in ("GOOGLE_KIT_PROFILE", "GOOGLE_KIT_SANDBOX", "GOOGLE_KIT_SANDBOX_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    for key in list(os.environ):
        if key.startswith("GOOGLE_KIT_ENABLE_"):
            monkeypatch.delenv(key, raising=False)


# ─── core.authz store ────────────────────────────────────────────────────────


class TestAuthzStore:
    def test_default_deny_when_no_file(self, tmp_path) -> None:
        assert authz.is_authorized("default", "gmail.send", config_dir=tmp_path) is False
        assert authz.load_authorizations("default", config_dir=tmp_path) == {}

    def test_set_and_read_roundtrip(self, tmp_path) -> None:
        authz.set_authorization("default", "gmail.send", 1, config_dir=tmp_path)
        assert authz.is_authorized("default", "gmail.send", config_dir=tmp_path) is True
        authz.set_authorization("default", "gmail.send", 0, config_dir=tmp_path)
        assert authz.is_authorized("default", "gmail.send", config_dir=tmp_path) is False

    def test_set_preserves_other_entries(self, tmp_path) -> None:
        authz.set_authorization("default", "gmail.send", 1, config_dir=tmp_path)
        authz.set_authorization("default", "tasks.create", 1, config_dir=tmp_path)
        grants = authz.load_authorizations("default", config_dir=tmp_path)
        assert grants["gmail.send"] == 1
        assert grants["tasks.create"] == 1

    def test_profiles_are_isolated(self, tmp_path) -> None:
        authz.set_authorization("work", "gmail.send", 1, config_dir=tmp_path)
        assert authz.is_authorized("work", "gmail.send", config_dir=tmp_path) is True
        assert authz.is_authorized("default", "gmail.send", config_dir=tmp_path) is False

    def test_file_shape_is_versioned_json(self, tmp_path) -> None:
        path = authz.set_authorization("default", "gmail.send", 1, config_dir=tmp_path)
        assert path == authz.authz_path("default", config_dir=tmp_path)
        doc = json.loads(path.read_text())
        assert doc["schema"] == authz.SCHEMA_VERSION
        assert doc["tools"]["gmail.send"] == 1

    def test_seed_profile_creates_all_zero(self, tmp_path) -> None:
        authz.seed_profile("default", config_dir=tmp_path)
        view = authz.authorization_view("default", config_dir=tmp_path)
        assert view == {name: 0 for name in authz.required_tool_names()}

    def test_seed_is_idempotent_and_preserves_grants(self, tmp_path) -> None:
        authz.set_authorization("default", "gmail.send", 1, config_dir=tmp_path)
        authz.seed_profile("default", config_dir=tmp_path)
        view = authz.authorization_view("default", config_dir=tmp_path)
        assert view["gmail.send"] == 1
        assert sum(view.values()) == 1  # only the explicit grant

    def test_seed_overwrite_resets_to_zero(self, tmp_path) -> None:
        authz.set_authorization("default", "gmail.send", 1, config_dir=tmp_path)
        authz.seed_profile("default", config_dir=tmp_path, overwrite=True)
        assert authz.is_authorized("default", "gmail.send", config_dir=tmp_path) is False

    def test_corrupt_file_defaults_deny(self, tmp_path) -> None:
        path = authz.authz_path("default", config_dir=tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json")
        assert authz.load_authorizations("default", config_dir=tmp_path) == {}
        assert authz.is_authorized("default", "gmail.send", config_dir=tmp_path) is False

    def test_invalid_profile_rejected(self, tmp_path) -> None:
        """A profile that could escape the config dir is refused at every entry
        point (fail closed) — authz must never read/write an arbitrary grant file
        outside its dir. ``../x`` escapes; ``/abs`` resets the path join."""
        for name in ("", ".", "..", "../etc/passwd", "a/b", "a\\b", "/abs", "p\x00x"):
            with pytest.raises(GoogleKitError):
                authz.authz_path(name, config_dir=tmp_path)
            with pytest.raises(GoogleKitError):
                authz.is_authorized(name, "gmail.send", config_dir=tmp_path)
            with pytest.raises(GoogleKitError):
                authz.set_authorization(name, "gmail.send", 1, config_dir=tmp_path)
            with pytest.raises(GoogleKitError):
                authz.seed_profile(name, config_dir=tmp_path)
        # Plain segments — including non-traversing dots/dashes — are accepted.
        for name in ("default", "work", "work.test", "a-b_1", "sandbox"):
            authz.set_authorization(name, "gmail.send", 1, config_dir=tmp_path)
            assert authz.is_authorized(name, "gmail.send", config_dir=tmp_path) is True

    def test_requires_authorization(self) -> None:
        assert authz.requires_authorization(_spec("gmail.send", "X")) is True
        assert authz.requires_authorization(_spec("gmail.list", None)) is False

    def test_requires_authorization_matches_mutating_posture(self) -> None:
        """Gate trigger (``OpSpec.flag``) must coincide exactly with write/
        destructive posture — no mutating op left ungated, no read/admin op
        gated. Pins the invariant that "requires authorization" derives from
        posture, now that the ``OpSpec.write_permission`` field is gone: a future
        mutating op registered without a flag would otherwise be silently ungated.
        """
        mutating = {s.name for s in all_specs() if s.posture in {"write", "destructive"}}
        requires = {s.name for s in all_specs() if authz.requires_authorization(s)}
        assert requires == mutating

    def test_required_tool_names_matches_flagged_specs(self) -> None:
        expected = sorted(s.name for s in all_specs() if s.flag)
        assert authz.required_tool_names() == expected

    def test_resolve_active_profile_precedence(self, monkeypatch) -> None:
        monkeypatch.delenv("GOOGLE_KIT_SANDBOX", raising=False)
        monkeypatch.setenv("GOOGLE_KIT_PROFILE", "envprof")
        assert authz.resolve_active_profile("explicit") == "explicit"  # explicit wins
        assert authz.resolve_active_profile(None) == "envprof"  # else env
        monkeypatch.setenv("GOOGLE_KIT_SANDBOX", "1")
        assert authz.resolve_active_profile(None) == "sandbox"  # sandbox guardrail


# ─── the gate: ensure_enabled ────────────────────────────────────────────────


class TestEnsureEnabledAuthorization:
    def test_no_flag_always_passes(self) -> None:
        ensure_enabled(_spec("svc.read", None))  # no raise

    def test_denied_without_grant_or_env(self, monkeypatch) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        with pytest.raises(FlagDisabledError, match="not authorized"):
            ensure_enabled(_spec("gmail.send", "GOOGLE_KIT_ENABLE_GMAIL_WRITE"))

    def test_allowed_by_per_profile_grant(self, monkeypatch) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        authz.set_authorization("default", "gmail.send", 1)
        ensure_enabled(_spec("gmail.send", "GOOGLE_KIT_ENABLE_GMAIL_WRITE"))  # no raise

    def test_env_override_bypasses_without_grant(self, monkeypatch) -> None:
        monkeypatch.setenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", "1")
        ensure_enabled(_spec("gmail.send", "GOOGLE_KIT_ENABLE_GMAIL_WRITE"))  # no raise

    def test_umbrella_override_bypasses_write_gate(self, monkeypatch) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", raising=False)
        monkeypatch.setenv(ENABLE_WRITES_FLAG, "1")
        ensure_enabled(_spec("gmail.send", "GOOGLE_KIT_ENABLE_GMAIL_WRITE"))  # no raise

    def test_grant_is_per_profile(self, monkeypatch) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        authz.set_authorization("work", "gmail.send", 1)
        ensure_enabled(_spec("gmail.send", "GOOGLE_KIT_ENABLE_GMAIL_WRITE"), profile="work")
        with pytest.raises(FlagDisabledError):
            ensure_enabled(_spec("gmail.send", "GOOGLE_KIT_ENABLE_GMAIL_WRITE"), profile="default")

    def test_elevated_gate_not_satisfied_by_umbrella_but_by_grant(self, monkeypatch) -> None:
        # Drive watch flag does not end in _WRITE → umbrella never satisfies it;
        # a per-profile grant must.
        op = _drive_watch_op()
        monkeypatch.setenv(ENABLE_WRITES_FLAG, "1")
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_DRIVE_WATCH", raising=False)
        with pytest.raises(FlagDisabledError):
            ensure_enabled(_spec(op, "GOOGLE_KIT_ENABLE_DRIVE_WATCH"))
        authz.set_authorization("default", op, 1)
        ensure_enabled(_spec(op, "GOOGLE_KIT_ENABLE_DRIVE_WATCH"))  # no raise

    def test_invalid_profile_fails_closed(self, monkeypatch) -> None:
        """An escaping profile makes the gate refuse (raise), never default-allow:
        authz rejects the name before any grant lookup can be consulted."""
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        with pytest.raises(GoogleKitError, match="invalid profile"):
            ensure_enabled(
                _spec("gmail.send", "GOOGLE_KIT_ENABLE_GMAIL_WRITE"), profile="../evil"
            )


# ─── CLI: auth grant / revoke / authorizations ───────────────────────────────


class TestAuthCli:
    def test_grant_authorizes(self, capsys) -> None:
        assert cmd_grant(None, "gmail.send") == 0
        assert authz.is_authorized("default", "gmail.send") is True
        assert "Authorized gmail.send" in capsys.readouterr().out

    def test_grant_unknown_op_fails(self, capsys) -> None:
        assert cmd_grant(None, "nope.bad") == 1
        assert "unknown operation" in capsys.readouterr().err

    def test_grant_read_op_rejected(self, capsys) -> None:
        assert cmd_grant(None, _a_read_op()) == 1
        assert "does not require authorization" in capsys.readouterr().err

    def test_grant_accepts_dash_form(self) -> None:
        # gmail.batch_modify is registered with an underscore; accept the dash form.
        assert cmd_grant(None, "gmail.batch-modify") == 0
        assert authz.is_authorized("default", "gmail.batch_modify") is True

    def test_revoke(self, capsys) -> None:
        cmd_grant(None, "gmail.send")
        assert cmd_revoke(None, "gmail.send") == 0
        assert authz.is_authorized("default", "gmail.send") is False
        assert "Revoked gmail.send" in capsys.readouterr().out

    def test_grant_revoke_target_profile(self) -> None:
        cmd_grant("work", "gmail.send")
        assert authz.is_authorized("work", "gmail.send") is True
        assert authz.is_authorized("default", "gmail.send") is False

    def test_grant_under_sandbox_targets_enforced_profile(self, monkeypatch) -> None:
        """Under GOOGLE_KIT_SANDBOX=1, `auth grant` (no --profile) must target the
        SAME profile the gate enforces (the sandbox guardrail), not literal
        'default' — otherwise the grant silently fails to take effect."""
        monkeypatch.setenv("GOOGLE_KIT_SANDBOX", "1")
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        active = authz.resolve_active_profile(None)
        assert active != "default"  # the guardrail moved the active profile
        assert cmd_grant(None, "tasks.create") == 0
        assert authz.is_authorized(active, "tasks.create") is True
        assert authz.is_authorized("default", "tasks.create") is False
        # the gate (also no explicit profile) now agrees and passes
        ensure_enabled(_spec("tasks.create", "GOOGLE_KIT_ENABLE_TASKS_WRITE"))

    def test_authorizations_json(self, capsys) -> None:
        cmd_grant(None, "gmail.send")
        capsys.readouterr()  # drain the grant confirmation line
        assert cmd_authorizations(None, fmt="json") == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["profile"] == "default"
        assert doc["tools"]["gmail.send"] == 1
        assert doc["tools"]["tasks.create"] == 0
        assert len(doc["tools"]) == len(authz.required_tool_names())

    def test_authorizations_text(self, capsys) -> None:
        cmd_grant(None, "gmail.send")
        assert cmd_authorizations(None, fmt="text") == 0
        out = capsys.readouterr().out
        assert "[1] gmail.send" in out
        assert "[0] tasks.create" in out

    def test_login_seeds_authorizations(self) -> None:
        store = _InMemoryStore({"client_id": "cid", "client_secret": "sec"})
        rc = cmd_login(
            "default",
            _store_factory=lambda profile: store,
            _flow_factory=lambda s, cid, *, headless=False: _FakeFlow(store),
        )
        assert rc == 0
        view = authz.authorization_view("default")
        assert view == {name: 0 for name in authz.required_tool_names()}


# ─── end-to-end enforcement: CLI ─────────────────────────────────────────────

_TASKS_CREATE_ARGV = ["tasks", "create", "--title", "Task"]


class TestCliEndToEnd:
    def test_blocked_without_grant(self, monkeypatch, capsys) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        factory = _Factory()
        with pytest.raises(SystemExit) as exc:
            cli_main(_TASKS_CREATE_ARGV, _service_factory=factory)
        assert exc.value.code != 0
        assert not factory.calls
        assert "auth grant tasks.create" in capsys.readouterr().err

    def test_allowed_after_grant_without_any_env_flag(self, monkeypatch, capsys) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        cmd_grant(None, "tasks.create")
        capsys.readouterr()  # drain the grant confirmation line
        factory = _Factory()
        cli_main(_TASKS_CREATE_ARGV, _service_factory=factory)
        out = json.loads(capsys.readouterr().out)
        assert out["data"]["id"] == "task-1"
        assert any(method == "insert" for _, method in factory.calls)

    def test_grant_for_other_profile_does_not_authorize_default(self, monkeypatch) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        cmd_grant("work", "tasks.create")  # grant a different profile
        factory = _Factory()
        with pytest.raises(SystemExit):
            cli_main(_TASKS_CREATE_ARGV, _service_factory=factory)  # default still denied
        assert not factory.calls

    def test_auth_grant_invalid_profile_clean_error(self, capsys) -> None:
        """`auth grant --profile <escaping>` exits nonzero with a clean error
        envelope — the auth dispatch surfaces the domain error, not a traceback
        (an unhandled raise would surface as a non-SystemExit exception here)."""
        with pytest.raises(SystemExit) as exc:
            cli_main(["auth", "grant", "gmail.send", "--profile", "../evil"])
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "error:" in err
        assert "invalid profile" in err


# ─── end-to-end enforcement: MCP ─────────────────────────────────────────────


class TestMcpEndToEnd:
    def test_denied_without_grant_returns_payload(self, monkeypatch) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        server = build_mcp_server(_service_factory=lambda op_name: _FakeService())
        payload = _mcp_call(server, "tasks_create", {"title": "T"})
        assert payload["error"] == "FlagDisabledError"
        assert "not authorized" in payload["message"]

    def test_allowed_after_grant(self, monkeypatch) -> None:
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        authz.set_authorization("default", "tasks.create", 1)  # MCP server profile == default
        fake = _FakeService()
        server = build_mcp_server(_service_factory=lambda op_name: fake)
        payload = _mcp_call(server, "tasks_create", {"title": "T"})
        assert payload["data"]["id"] == "task-1"
        assert any(method == "insert" for _, method in fake.calls)

    def test_grant_for_other_profile_does_not_authorize_default(self, monkeypatch) -> None:
        """A grant on a different profile must NOT authorize the MCP server's
        active profile (which resolves to 'default' here)."""
        monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
        monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
        authz.set_authorization("work", "tasks.create", 1)  # other profile only
        server = build_mcp_server(_service_factory=lambda op_name: _FakeService())
        payload = _mcp_call(server, "tasks_create", {"title": "T"})
        assert payload["error"] == "FlagDisabledError"
        assert "not authorized" in payload["message"]


# ─── test doubles ────────────────────────────────────────────────────────────


class _InMemoryStore:
    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data = dict(data or {})

    def get(self, key: str) -> str:
        return self._data[key]

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def has(self, key: str) -> bool:
        return key in self._data


class _FakeFlow:
    def __init__(self, store: _InMemoryStore) -> None:
        self._store = store

    def authorize(self, scopes: list[str]) -> str:
        return "code"

    def exchange(self, code: str) -> dict[str, str]:
        self._store.set("access_token", "a")
        self._store.set("refresh_token", "r")
        return {"access_token": "a", "refresh_token": "r"}


class _Executable:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _Node:
    _RESOURCES = {"tasks", "tasklists", "users", "messages"}

    def __init__(self, root: "_FakeService", path: list[str]) -> None:
        self._root = root
        self._path = path

    def __getattr__(self, name: str) -> Any:
        def _method(**kwargs: Any) -> Any:
            if name in self._RESOURCES:
                return _Node(self._root, [*self._path, name])
            self._root.calls.append((".".join(self._path), name))
            return _Executable(self._root.response_for(name, kwargs))

        return _method


class _FakeService(_Node):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        super().__init__(self, [])

    def response_for(self, method: str, kwargs: dict[str, Any]) -> Any:
        body = kwargs.get("body") or {}
        if method == "insert":  # tasks.create
            return {"id": "task-1", "title": body.get("title", "Task"), "status": "needsAction"}
        return {}


class _Factory:
    def __init__(self) -> None:
        self.svc = _FakeService()

    def __call__(self, op_name: str, *, profile: str | None = None) -> _FakeService:
        del op_name, profile
        return self.svc

    @property
    def calls(self) -> list[tuple[str, str]]:
        return self.svc.calls


def _mcp_call(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=arguments),
        )
        return await handler(req)

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    return json.loads(root.content[0].text)
