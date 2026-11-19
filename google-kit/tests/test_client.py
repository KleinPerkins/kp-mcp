"""Regression tests for google_kit.core.client._make_persisting_credentials.

Guards the exact production bug fixed in commit 3b58778:
  _PersistingCredentials was a plain __getattr__ delegation wrapper, NOT a
  subclass of google.oauth2.credentials.Credentials.
  isinstance(creds, google.auth.credentials.Credentials) was False →
  googleapiclient fell into the legacy credentials.authorize(http) path →
  AttributeError at runtime on every real authorized API call.

The bug was masked because all 691 unit tests inject a fake build_fn and
never hit real googleapiclient.discovery.build.

All tests here use FakeSecretStore (in-memory) + monkeypatching — no live
network, no Keychain, no real token exchange.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import google.auth.credentials


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeSecretStore:
    """In-memory SecretStore — mirrors the interface used throughout the suite."""

    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(data or {})

    def get(self, key: str) -> str:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def has(self, key: str) -> bool:
        return key in self._data


def _make_store() -> FakeSecretStore:
    return FakeSecretStore({
        "access_token": "old-access-token",
        "refresh_token": "old-refresh-token",
        "client_secret": "fake-client-secret",
    })


def _make_creds(store: FakeSecretStore | None = None) -> Any:
    from google_kit.core.client import _make_persisting_credentials

    return _make_persisting_credentials(
        token="old-access-token",
        refresh_token="old-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        store=store or _make_store(),
    )


@pytest.fixture(autouse=True)
def _reset_persisting_creds_cls() -> Any:
    """Reset the lazily-cached _Impl class so tests are order-independent."""
    from google_kit.core.client import _make_persisting_credentials

    _make_persisting_credentials.__dict__.pop("_cls", None)
    yield
    _make_persisting_credentials.__dict__.pop("_cls", None)


# ---------------------------------------------------------------------------
# Regression: isinstance must hold (primary guard for commit 3b58778)
# ---------------------------------------------------------------------------


class TestPersistingCredentialsIsInstance:
    def test_is_google_auth_credentials(self) -> None:
        """PRIMARY REGRESSION — guards commit 3b58778.

        Before the fix, isinstance(creds, google.auth.credentials.Credentials)
        was False → googleapiclient chose the legacy authorize() path → AttributeError.
        """
        creds = _make_creds()
        assert isinstance(creds, google.auth.credentials.Credentials), (
            "_make_persisting_credentials must return a google.auth.credentials.Credentials "
            "subclass; googleapiclient uses isinstance() to select the auth path"
        )

    def test_is_oauth2_credentials_subclass(self) -> None:
        from google.oauth2.credentials import Credentials as OAuth2Creds

        creds = _make_creds()
        assert isinstance(creds, OAuth2Creds)

    def test_build_authorized_service_passes_compliant_creds_to_build_fn(self) -> None:
        """build_authorized_service must forward isinstance-compliant creds into build_fn."""
        from google_kit.core.client import build_authorized_service

        store = FakeSecretStore({
            "access_token": "tok",
            "refresh_token": "ref",
            "client_secret": "sec",
        })
        captured: list[Any] = []

        def _fake_build(svc: str, ver: str, *, credentials: Any, **kw: Any) -> MagicMock:
            captured.append(credentials)
            return MagicMock()

        build_authorized_service(
            "drive",
            "v3",
            store,
            client_id="fake-client-id",
            build_fn=_fake_build,
        )

        assert captured, "build_fn was not called by build_authorized_service"
        assert isinstance(captured[0], google.auth.credentials.Credentials), (
            "build_authorized_service must pass a google.auth.credentials.Credentials "
            "instance to build_fn / googleapiclient.discovery.build"
        )


# ---------------------------------------------------------------------------
# Regression: refresh() must persist tokens to SecretStore
#
# Note: google-auth >=2.36 stores the bearer token as a plain instance
# attribute `self.token` (not `self._token`).  Refresh mocks must set
# `self_arg.token` to simulate what a real token-exchange updates.
# The refresh_token is still exposed via `self._refresh_token` / property.
# ---------------------------------------------------------------------------


class TestPersistingCredentialsRefresh:
    def test_refresh_persists_access_token(self) -> None:
        store = _make_store()
        creds = _make_creds(store)

        def _fake_super_refresh(self_arg: Any, request: Any) -> None:
            self_arg.token = "new-access-token"

        with patch("google.oauth2.credentials.Credentials.refresh", _fake_super_refresh):
            creds.refresh(MagicMock())

        assert store.get("access_token") == "new-access-token"

    def test_refresh_persists_refresh_token_when_rotated(self) -> None:
        store = _make_store()
        creds = _make_creds(store)

        def _fake_super_refresh(self_arg: Any, request: Any) -> None:
            self_arg.token = "new-access-token"
            self_arg._refresh_token = "new-refresh-token"

        with patch("google.oauth2.credentials.Credentials.refresh", _fake_super_refresh):
            creds.refresh(MagicMock())

        assert store.get("access_token") == "new-access-token"
        assert store.get("refresh_token") == "new-refresh-token"

    def test_refresh_skips_refresh_token_when_not_rotated(self) -> None:
        store = _make_store()
        creds = _make_creds(store)
        original_refresh_token = store.get("refresh_token")

        def _fake_super_refresh(self_arg: Any, request: Any) -> None:
            self_arg.token = "new-access-token"
            self_arg._refresh_token = None

        with patch("google.oauth2.credentials.Credentials.refresh", _fake_super_refresh):
            creds.refresh(MagicMock())

        assert store.get("access_token") == "new-access-token"
        assert store.get("refresh_token") == original_refresh_token
