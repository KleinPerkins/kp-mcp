"""Tests for google-kit auth CLI subcommand.

All tests use FakeSecretStore (in-memory) and FakePKCEFlow — no real Keychain,
no network, no browser. Injection via _store_factory / _flow_factory seams.
"""
from __future__ import annotations

import pytest

from google_kit.cli import main
from google_kit.cli.auth import cmd_login, cmd_logout, cmd_status
from google_kit.core.auth import GOOGLE_KIT_SCOPES


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeSecretStore:
    """In-memory SecretStore for tests."""

    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(data or {})

    def get(self, key: str) -> str:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def has(self, key: str) -> bool:
        return key in self._data


class FakePKCEFlow:
    """In-memory PKCE flow: persists fake tokens to the store on exchange()."""

    def __init__(self, store: FakeSecretStore) -> None:
        self._store = store
        self.authorized_scopes: list[str] = []
        self.exchanged_codes: list[str] = []

    def authorize(self, scopes: list[str]) -> str:
        self.authorized_scopes = list(scopes)
        return "fake-auth-code"

    def exchange(self, code: str) -> dict[str, str]:
        self.exchanged_codes.append(code)
        tokens = {"access_token": "fake-access", "refresh_token": "fake-refresh"}
        self._store.set("access_token", tokens["access_token"])
        self._store.set("refresh_token", tokens["refresh_token"])
        return tokens

    def refresh(self) -> str:
        return "fake-access"


def _make_store_with_creds(extra: dict[str, str] | None = None) -> FakeSecretStore:
    """Return a store pre-populated with client credentials."""
    data = {"client_id": "fake-client-id", "client_secret": "fake-client-secret"}
    if extra:
        data.update(extra)
    return FakeSecretStore(data)


def _store_factory_for(store: FakeSecretStore):
    def factory(profile: str) -> FakeSecretStore:
        return store
    return factory


def _flow_factory_for(store: FakeSecretStore):
    flow = FakePKCEFlow(store)

    def factory(s, client_id: str, *, headless: bool = False):
        return flow

    return factory, flow


@pytest.fixture(autouse=True)
def _clear_extra_scopes_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep login tests hermetic: the GOOGLE_KIT_EXTRA_SCOPES opt-in env var must
    not leak in from the ambient environment (it would change the requested scope
    set and break the byte-identical-default invariant)."""
    monkeypatch.delenv("GOOGLE_KIT_EXTRA_SCOPES", raising=False)


# New-API extra scopes from docs/dev/LIVE-E2E-NEW-APIS.md §1a (People directory +
# Drive Activity + Apps Script). The userinfo.profile self-read scope is requested
# separately; here this list is representative test data for the login union/sort.
_NEW_API_SCOPES = [
    "https://www.googleapis.com/auth/directory.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/drive.activity.readonly",
    "https://www.googleapis.com/auth/script.projects",
    "https://www.googleapis.com/auth/script.projects.readonly",
    "https://www.googleapis.com/auth/script.deployments.readonly",
    "https://www.googleapis.com/auth/script.external_request",
    "https://www.googleapis.com/auth/script.metrics",
]


# ---------------------------------------------------------------------------
# GOOGLE_KIT_SCOPES
# ---------------------------------------------------------------------------


class TestGoogleKitScopes:
    def test_exactly_10_scopes(self) -> None:
        assert len(GOOGLE_KIT_SCOPES) == 10

    def test_all_full_https_urls(self) -> None:
        for scope in GOOGLE_KIT_SCOPES:
            assert scope.startswith("https://www.googleapis.com/auth/"), scope

    def test_expected_scopes_present(self) -> None:
        scope_set = set(GOOGLE_KIT_SCOPES)
        expected = {
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/presentations",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/tasks",
            "https://www.googleapis.com/auth/forms.body",
            "https://www.googleapis.com/auth/forms.responses.readonly",
        }
        assert scope_set == expected

    def test_keep_excluded(self) -> None:
        scope_set = set(GOOGLE_KIT_SCOPES)
        assert "https://www.googleapis.com/auth/keep" not in scope_set
        assert not any("keep" in s for s in scope_set)

    def test_no_duplicates(self) -> None:
        assert len(GOOGLE_KIT_SCOPES) == len(set(GOOGLE_KIT_SCOPES))


# ---------------------------------------------------------------------------
# cmd_login
# ---------------------------------------------------------------------------


class TestCmdLogin:
    def test_login_persists_tokens(self) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)

        rc = cmd_login(
            "testprofile",
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert rc == 0
        assert store.has("access_token")
        assert store.has("refresh_token")
        assert store.get("access_token") == "fake-access"
        assert store.get("refresh_token") == "fake-refresh"

    def test_login_calls_authorize_with_correct_scopes(self) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)

        cmd_login(
            "testprofile",
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert set(flow.authorized_scopes) == set(GOOGLE_KIT_SCOPES)

    def test_login_fails_loud_when_client_secret_absent(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = FakeSecretStore({"client_id": "only-id"})
        flow_factory, _ = _flow_factory_for(store)

        rc = cmd_login(
            "testprofile",
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert rc == 1
        err = capsys.readouterr().err
        assert "client_secret" in err
        assert "Keychain" in err

    def test_login_fails_loud_when_client_id_absent(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = FakeSecretStore({"client_secret": "only-secret"})
        flow_factory, _ = _flow_factory_for(store)

        rc = cmd_login(
            "testprofile",
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert rc == 1
        err = capsys.readouterr().err
        assert "client_id" in err

    def test_login_fails_loud_when_both_credentials_absent(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = FakeSecretStore()
        flow_factory, _ = _flow_factory_for(store)

        rc = cmd_login(
            "testprofile",
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert rc == 1
        err = capsys.readouterr().err
        assert "client_id" in err
        assert "client_secret" in err

    def test_login_skips_when_already_logged_in(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = _make_store_with_creds({"access_token": "existing"})
        flow_factory, flow = _flow_factory_for(store)

        rc = cmd_login(
            "testprofile",
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert rc == 0
        assert flow.exchanged_codes == []
        out = capsys.readouterr().out
        assert "Already logged in" in out

    def test_login_force_re_consents(self) -> None:
        store = _make_store_with_creds({"access_token": "existing"})
        flow_factory, flow = _flow_factory_for(store)

        rc = cmd_login(
            "testprofile",
            force=True,
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert rc == 0
        assert flow.exchanged_codes == ["fake-auth-code"]

    def test_login_success_message_never_prints_secret_values(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = _make_store_with_creds()
        flow_factory, _ = _flow_factory_for(store)

        cmd_login(
            "testprofile",
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "fake-access" not in combined
        assert "fake-refresh" not in combined
        assert "fake-client-id" not in combined
        assert "fake-client-secret" not in combined


# ---------------------------------------------------------------------------
# cmd_login — extra scopes (--scopes flag + GOOGLE_KIT_EXTRA_SCOPES env)
# ---------------------------------------------------------------------------


class TestLoginExtraScopes:
    """Opt-in extra scopes unioned with GOOGLE_KIT_SCOPES for a single login.

    Default behavior (no extras) must stay byte-identical: request exactly the
    10-scope GOOGLE_KIT_SCOPES, in order. Extras are validated, deduped, and the
    new ones appended in sorted order.
    """

    def test_no_extra_scopes_requests_exactly_base_in_order(self) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)

        rc = cmd_login(
            "testprofile",
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert rc == 0
        # Exact list AND order — not merely set-equal — proving the default
        # request set is unchanged (no re-consent risk for existing profiles).
        assert flow.authorized_scopes == list(GOOGLE_KIT_SCOPES)

    def test_empty_extra_scopes_list_is_treated_as_no_extras(self) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)

        cmd_login(
            "testprofile",
            extra_scopes=[],
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert flow.authorized_scopes == list(GOOGLE_KIT_SCOPES)

    def test_scopes_flag_comma_separated_unions_with_base(self) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)

        cmd_login(
            "testprofile",
            extra_scopes=[",".join(_NEW_API_SCOPES)],
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert flow.authorized_scopes == list(GOOGLE_KIT_SCOPES) + sorted(_NEW_API_SCOPES)

    def test_env_var_space_separated_unions_with_base(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)
        monkeypatch.setenv("GOOGLE_KIT_EXTRA_SCOPES", " ".join(_NEW_API_SCOPES))

        cmd_login(
            "testprofile",
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert flow.authorized_scopes == list(GOOGLE_KIT_SCOPES) + sorted(_NEW_API_SCOPES)

    def test_flag_and_env_are_unioned_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)
        flag_part, env_part = _NEW_API_SCOPES[:3], _NEW_API_SCOPES[3:]
        monkeypatch.setenv("GOOGLE_KIT_EXTRA_SCOPES", ",".join(env_part))

        cmd_login(
            "testprofile",
            extra_scopes=[" ".join(flag_part)],
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert flow.authorized_scopes == list(GOOGLE_KIT_SCOPES) + sorted(_NEW_API_SCOPES)

    def test_extra_equal_to_existing_base_scope_is_not_duplicated(self) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)
        dup = GOOGLE_KIT_SCOPES[0]
        new = "https://www.googleapis.com/auth/script.projects"

        cmd_login(
            "testprofile",
            extra_scopes=[f"{dup},{new}"],
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        # Duplicate dropped; base order preserved; only the genuinely-new scope appended.
        assert flow.authorized_scopes == list(GOOGLE_KIT_SCOPES) + [new]
        assert len(flow.authorized_scopes) == len(set(flow.authorized_scopes))

    def test_repeated_scopes_flag_values_are_unioned(self) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)

        cmd_login(
            "testprofile",
            extra_scopes=[" ".join(_NEW_API_SCOPES[:4]), ",".join(_NEW_API_SCOPES[4:])],
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert flow.authorized_scopes == list(GOOGLE_KIT_SCOPES) + sorted(_NEW_API_SCOPES)

    def test_malformed_extra_scope_fails_loud_nonzero_no_leak(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)
        bad = "not-a-valid-scope-zzz"

        rc = cmd_login(
            "testprofile",
            extra_scopes=[bad],
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert rc == 1
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "scope" in combined.lower()  # clear, fail-loud message
        assert bad not in combined  # provided value never leaked
        # No authorization / token exchange happened, no tokens persisted.
        assert flow.authorized_scopes == []
        assert flow.exchanged_codes == []
        assert not store.has("access_token")

    def test_malformed_extra_scope_wrong_host_rejected(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = _make_store_with_creds()
        flow_factory, flow = _flow_factory_for(store)
        bad = "https://evil.example/not-a-google-scope"

        rc = cmd_login(
            "testprofile",
            extra_scopes=[f"{_NEW_API_SCOPES[0]},{bad}"],
            _store_factory=_store_factory_for(store),
            _flow_factory=flow_factory,
        )

        assert rc == 1
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert bad not in combined
        assert flow.authorized_scopes == []


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------


class TestCmdStatus:
    def test_status_absent_when_no_keys(self, capsys: pytest.CaptureFixture) -> None:
        store = FakeSecretStore()

        rc = cmd_status("testprofile", _store_factory=_store_factory_for(store))

        assert rc == 1
        out = capsys.readouterr().out
        assert "absent" in out

    def test_status_present_when_tokens_exist(self, capsys: pytest.CaptureFixture) -> None:
        store = _make_store_with_creds({"access_token": "tok", "refresh_token": "ref"})

        rc = cmd_status("testprofile", _store_factory=_store_factory_for(store))

        assert rc == 0
        out = capsys.readouterr().out
        assert "present" in out

    def test_status_shows_profile_name(self, capsys: pytest.CaptureFixture) -> None:
        store = FakeSecretStore()

        cmd_status("myprofile", _store_factory=_store_factory_for(store))

        out = capsys.readouterr().out
        assert "myprofile" in out

    def test_status_reports_all_four_keys(self, capsys: pytest.CaptureFixture) -> None:
        store = _make_store_with_creds({"access_token": "tok", "refresh_token": "ref"})

        cmd_status("testprofile", _store_factory=_store_factory_for(store))

        out = capsys.readouterr().out
        for key in ("client_id", "client_secret", "access_token", "refresh_token"):
            assert key in out

    def test_status_hint_when_not_logged_in(self, capsys: pytest.CaptureFixture) -> None:
        store = FakeSecretStore()

        rc = cmd_status("testprofile", _store_factory=_store_factory_for(store))

        assert rc == 1
        out = capsys.readouterr().out
        assert "login" in out.lower()

    def test_status_no_secret_values_printed(self, capsys: pytest.CaptureFixture) -> None:
        store = FakeSecretStore({
            "client_id": "cid-val",
            "client_secret": "csec-val",
            "access_token": "atk-val",
            "refresh_token": "rtk-val",
        })

        cmd_status("testprofile", _store_factory=_store_factory_for(store))

        combined = capsys.readouterr().out
        for secret in ("cid-val", "csec-val", "atk-val", "rtk-val"):
            assert secret not in combined

    def test_status_exits_nonzero_when_only_client_creds(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = _make_store_with_creds()

        rc = cmd_status("testprofile", _store_factory=_store_factory_for(store))

        assert rc == 1


# ---------------------------------------------------------------------------
# cmd_logout
# ---------------------------------------------------------------------------


class TestCmdLogout:
    def test_logout_deletes_tokens(self) -> None:
        store = _make_store_with_creds({"access_token": "tok", "refresh_token": "ref"})

        rc = cmd_logout("testprofile", _store_factory=_store_factory_for(store))

        assert rc == 0
        assert not store.has("access_token")
        assert not store.has("refresh_token")

    def test_logout_preserves_credentials_by_default(self) -> None:
        store = _make_store_with_creds({"access_token": "tok", "refresh_token": "ref"})

        cmd_logout("testprofile", _store_factory=_store_factory_for(store))

        assert store.has("client_id")
        assert store.has("client_secret")

    def test_logout_all_deletes_credentials_too(self) -> None:
        store = _make_store_with_creds({"access_token": "tok", "refresh_token": "ref"})

        cmd_logout("testprofile", all_=True, _store_factory=_store_factory_for(store))

        for key in ("client_id", "client_secret", "access_token", "refresh_token"):
            assert not store.has(key)

    def test_logout_reports_removed_key_names(self, capsys: pytest.CaptureFixture) -> None:
        store = _make_store_with_creds({"access_token": "tok", "refresh_token": "ref"})

        cmd_logout("testprofile", _store_factory=_store_factory_for(store))

        out = capsys.readouterr().out
        assert "access_token" in out
        assert "refresh_token" in out

    def test_logout_no_op_when_already_logged_out(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = FakeSecretStore()

        rc = cmd_logout("testprofile", _store_factory=_store_factory_for(store))

        assert rc == 0
        out = capsys.readouterr().out
        assert "Nothing to remove" in out

    def test_logout_no_secret_values_printed(self, capsys: pytest.CaptureFixture) -> None:
        store = FakeSecretStore({
            "client_id": "cid-val",
            "client_secret": "csec-val",
            "access_token": "atk-val",
            "refresh_token": "rtk-val",
        })

        cmd_logout("testprofile", all_=True, _store_factory=_store_factory_for(store))

        combined = capsys.readouterr().out
        for secret in ("cid-val", "csec-val", "atk-val", "rtk-val"):
            assert secret not in combined


# ---------------------------------------------------------------------------
# main() integration via CLI dispatch
# ---------------------------------------------------------------------------


class TestAuthCLIDispatch:
    def _make_seams(self, store: FakeSecretStore):
        flow_factory, flow = _flow_factory_for(store)
        return _store_factory_for(store), flow_factory, flow

    def test_auth_help_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["auth", "--help"])
        assert exc.value.code == 0

    def test_auth_login_help_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["auth", "login", "--help"])
        assert exc.value.code == 0

    def test_auth_status_help_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["auth", "status", "--help"])
        assert exc.value.code == 0

    def test_auth_logout_help_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["auth", "logout", "--help"])
        assert exc.value.code == 0

    def test_auth_login_via_main_persists_tokens(self) -> None:
        store = _make_store_with_creds()
        sf, ff, flow = self._make_seams(store)

        with pytest.raises(SystemExit) as exc:
            main(["auth", "login"], _store_factory=sf, _flow_factory=ff)
        assert exc.value.code == 0
        assert store.has("access_token")
        assert store.has("refresh_token")

    def test_auth_status_via_main_exits_nonzero_when_not_logged_in(self) -> None:
        store = FakeSecretStore()
        sf, ff, _ = self._make_seams(store)

        with pytest.raises(SystemExit) as exc:
            main(["auth", "status"], _store_factory=sf)
        assert exc.value.code != 0

    def test_auth_status_via_main_exits_zero_when_logged_in(self) -> None:
        store = FakeSecretStore({"access_token": "tok", "refresh_token": "ref"})
        sf, ff, _ = self._make_seams(store)

        with pytest.raises(SystemExit) as exc:
            main(["auth", "status"], _store_factory=sf)
        assert exc.value.code == 0

    def test_auth_logout_via_main_removes_tokens(self) -> None:
        store = _make_store_with_creds({"access_token": "tok", "refresh_token": "ref"})
        sf, ff, _ = self._make_seams(store)

        with pytest.raises(SystemExit) as exc:
            main(["auth", "logout"], _store_factory=sf)
        assert exc.value.code == 0
        assert not store.has("access_token")
        assert not store.has("refresh_token")

    def test_auth_logout_all_via_main_removes_credentials(self) -> None:
        store = _make_store_with_creds({"access_token": "tok", "refresh_token": "ref"})
        sf, ff, _ = self._make_seams(store)

        with pytest.raises(SystemExit) as exc:
            main(["auth", "logout", "--all"], _store_factory=sf)
        assert exc.value.code == 0
        for key in ("client_id", "client_secret", "access_token", "refresh_token"):
            assert not store.has(key)

    def test_auth_without_subcommand_exits_nonzero(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["auth"])
        assert exc.value.code != 0

    def test_auth_login_force_flag(self) -> None:
        store = _make_store_with_creds({"access_token": "old-token"})
        sf, ff, flow = self._make_seams(store)

        with pytest.raises(SystemExit) as exc:
            main(["auth", "login", "--force"], _store_factory=sf, _flow_factory=ff)
        assert exc.value.code == 0
        assert flow.exchanged_codes == ["fake-auth-code"]
        assert store.get("access_token") == "fake-access"

    def test_auth_login_profile_flag(self) -> None:
        profiles_seen: list[str] = []
        store = _make_store_with_creds()
        flow_factory, _ = _flow_factory_for(store)

        def tracking_store_factory(profile: str) -> FakeSecretStore:
            profiles_seen.append(profile)
            return store

        with pytest.raises(SystemExit):
            main(
                ["auth", "login", "--profile", "work"],
                _store_factory=tracking_store_factory,
                _flow_factory=flow_factory,
            )
        assert "work" in profiles_seen

    def test_auth_login_scopes_flag_unions_via_main(self) -> None:
        store = _make_store_with_creds()
        sf, ff, flow = self._make_seams(store)
        new = "https://www.googleapis.com/auth/script.projects"

        with pytest.raises(SystemExit) as exc:
            main(["auth", "login", "--scopes", new], _store_factory=sf, _flow_factory=ff)

        assert exc.value.code == 0
        assert flow.authorized_scopes == list(GOOGLE_KIT_SCOPES) + [new]

    def test_auth_login_no_scopes_flag_requests_base_via_main(self) -> None:
        store = _make_store_with_creds()
        sf, ff, flow = self._make_seams(store)

        with pytest.raises(SystemExit) as exc:
            main(["auth", "login"], _store_factory=sf, _flow_factory=ff)

        assert exc.value.code == 0
        assert flow.authorized_scopes == list(GOOGLE_KIT_SCOPES)

    def test_auth_login_malformed_scope_exits_nonzero_via_main(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        store = _make_store_with_creds()
        sf, ff, flow = self._make_seams(store)
        bad = "https://evil.example/not-a-google-scope"

        with pytest.raises(SystemExit) as exc:
            main(["auth", "login", "--scopes", bad], _store_factory=sf, _flow_factory=ff)

        assert exc.value.code != 0
        captured = capsys.readouterr()
        assert bad not in (captured.out + captured.err)
        assert flow.exchanged_codes == []
