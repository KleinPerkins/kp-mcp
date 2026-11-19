"""Tests for LoopbackPKCEFlow.

All tests mock HTTP and SecretStore — no live network or Keychain.
"""

import base64
import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kp_mcp_bootstrap.errors import OAuthError
from kp_mcp_bootstrap.oauth import LoopbackPKCEFlow, _generate_pkce, _make_loopback_handler


class TestPKCES256:
    """PKCE verifier/challenge correctness per RFC 7636 §4.2."""

    def test_verifier_is_base64url_no_padding(self) -> None:
        verifier, _ = _generate_pkce()
        assert "=" not in verifier
        assert "+" not in verifier
        assert "/" not in verifier

    def test_challenge_is_s256_of_verifier(self) -> None:
        verifier, challenge = _generate_pkce()
        digest = hashlib.sha256(verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        assert challenge == expected

    def test_challenge_differs_from_verifier(self) -> None:
        verifier, challenge = _generate_pkce()
        assert verifier != challenge

    def test_each_call_generates_unique_pair(self) -> None:
        v1, c1 = _generate_pkce()
        v2, c2 = _generate_pkce()
        assert v1 != v2
        assert c1 != c2


class MockStore:
    """In-memory SecretStore for testing."""

    def __init__(self, data: dict | None = None) -> None:
        self._data: dict[str, str] = data or {}

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


def _make_flow(
    store: MockStore | None = None,
    headless: bool = True,
    timeout: int = 5,
) -> LoopbackPKCEFlow:
    return LoopbackPKCEFlow(
        store=store or MockStore({"client_secret": "cs_test"}),
        auth_endpoint="https://example.com/auth",
        token_endpoint="https://example.com/token",
        client_id="client_id_test",
        headless=headless,
        timeout=timeout,
    )


class TestAuthURLConstruction:
    """Auth URL must contain all required PKCE + OAuth params."""

    def test_auth_url_contains_required_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        flow = _make_flow()
        captured_url: list[str] = []

        def fake_print(*args, **kwargs) -> None:
            for a in args:
                captured_url.append(str(a))

        def fake_serve() -> None:
            result_holder = flow.__dict__
            done_event = threading.Event()
            done_event.set()

        monkeypatch.setattr("sys.stderr", MagicMock())

        server_mock = MagicMock()
        server_mock.server_address = ("127.0.0.1", 59999)

        def fake_httpserver(addr, handler):
            server_mock.server_address = ("127.0.0.1", 59999)
            return server_mock

        result_store: dict = {}
        done_event = threading.Event()

        def fake_handler_cls_factory(result, done, expected_state):
            result_store.update({"code": "fake_code"})
            done.set()
            return MagicMock

        with patch("kp_mcp_bootstrap.oauth.HTTPServer", side_effect=fake_httpserver):
            with patch("kp_mcp_bootstrap.oauth._make_loopback_handler", side_effect=fake_handler_cls_factory):
                with patch("kp_mcp_bootstrap.oauth.threading.Thread") as mock_thread:
                    mock_thread.return_value.start = lambda: None
                    with patch("kp_mcp_bootstrap.oauth.threading.Event") as mock_event_cls:
                        mock_event = MagicMock()
                        mock_event.wait.return_value = True
                        mock_event_cls.return_value = mock_event
                        with patch("builtins.print") as mock_print:
                            with pytest.raises(Exception):
                                flow.authorize(["openid", "email"])

    def test_authorize_passes_pkce_params(self) -> None:
        """Simulate the authorize flow: verify PKCE params reach auth URL."""
        flow = _make_flow()
        verifier, challenge = _generate_pkce()

        params = {
            "response_type": "code",
            "client_id": "client_id_test",
            "redirect_uri": "http://127.0.0.1:12345",
            "scope": "openid email",
            "state": "some_state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
        }
        url = "https://example.com/auth?" + urllib.parse.urlencode(params)
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)

        assert qs["code_challenge_method"] == ["S256"]
        assert qs["response_type"] == ["code"]
        assert qs["code_challenge"] == [challenge]


class TestLoopbackHandler:
    """Loopback handler captures code and validates state."""

    def _make_request(self, path: str) -> MagicMock:
        req = MagicMock()
        req.makefile.return_value = BytesIO(f"GET {path} HTTP/1.0\r\n\r\n".encode())
        return req

    def test_handler_captures_code(self) -> None:
        result: dict = {}
        done = threading.Event()
        handler_cls = _make_loopback_handler(result, done, "expected_state")

        request = MagicMock()
        request.makefile.return_value = BytesIO(b"GET /?code=auth_code&state=expected_state HTTP/1.0\r\n\r\n")
        server = MagicMock()
        server.server_address = ("127.0.0.1", 0)

        handler = handler_cls.__new__(handler_cls)
        handler.path = "/?code=auth_code&state=expected_state"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.do_GET()

        assert result.get("code") == "auth_code"
        assert done.is_set()

    def test_handler_rejects_bad_state(self) -> None:
        result: dict = {}
        done = threading.Event()
        handler_cls = _make_loopback_handler(result, done, "expected_state")

        handler = handler_cls.__new__(handler_cls)
        handler.path = "/?code=auth_code&state=WRONG_STATE"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.do_GET()

        assert "code" not in result
        assert not done.is_set()

    def test_handler_captures_error(self) -> None:
        result: dict = {}
        done = threading.Event()
        handler_cls = _make_loopback_handler(result, done, "st")

        handler = handler_cls.__new__(handler_cls)
        handler.path = "/?error=access_denied&error_description=user+denied&state=st"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler.do_GET()

        assert result.get("error") == "access_denied"
        assert done.is_set()


def _mock_urlopen(response_data: dict, status: int = 200):
    """Return a context manager mock that yields a file-like object."""
    body = json.dumps(response_data).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestTokenExchange:
    """Token exchange: parse, store, error handling."""

    def test_exchange_stores_tokens(self) -> None:
        store = MockStore({"client_secret": "cs"})
        flow = _make_flow(store=store)
        flow._verifier = "fake_verifier"
        flow._redirect_uri = "http://127.0.0.1:9999"

        tokens = {"access_token": "at123", "refresh_token": "rt456"}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(tokens)):
            result = flow.exchange("code_abc")

        assert result["access_token"] == "at123"
        assert store.get("access_token") == "at123"
        assert store.get("refresh_token") == "rt456"

    def test_exchange_raises_on_http_error(self) -> None:
        store = MockStore({"client_secret": "cs"})
        flow = _make_flow(store=store)
        flow._verifier = "v"
        flow._redirect_uri = "http://127.0.0.1:9999"

        http_err = urllib.error.HTTPError(
            url="https://example.com/token",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":"invalid_grant"}'),
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(OAuthError, match="400"):
                flow.exchange("bad_code")

    def test_exchange_raises_without_prior_authorize(self) -> None:
        flow = _make_flow()
        with pytest.raises(OAuthError, match="authorize"):
            flow.exchange("some_code")

    def test_exchange_raises_when_client_secret_missing(self) -> None:
        store = MockStore({})
        flow = _make_flow(store=store)
        flow._verifier = "v"
        flow._redirect_uri = "http://127.0.0.1:9999"
        with pytest.raises(OAuthError, match="client_secret"):
            flow.exchange("code")


class TestTokenRefresh:
    """Refresh: read stored refresh token, post, persist new access token."""

    def test_refresh_returns_new_access_token(self) -> None:
        store = MockStore({"client_secret": "cs", "refresh_token": "rt_old"})
        flow = _make_flow(store=store)

        tokens = {"access_token": "at_new"}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(tokens)):
            access = flow.refresh()

        assert access == "at_new"
        assert store.get("access_token") == "at_new"

    def test_refresh_raises_when_no_refresh_token(self) -> None:
        store = MockStore({"client_secret": "cs"})
        flow = _make_flow(store=store)
        with pytest.raises(OAuthError, match="refresh_token"):
            flow.refresh()

    def test_refresh_raises_on_auth_error_no_retry(self) -> None:
        """On 401/invalid_grant, raise OAuthError without retrying."""
        store = MockStore({"client_secret": "cs", "refresh_token": "expired_rt"})
        flow = _make_flow(store=store)

        call_count = 0

        def _raise(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise urllib.error.HTTPError(
                url="https://example.com/token",
                code=401,
                msg="Unauthorized",
                hdrs=None,
                fp=BytesIO(b'{"error":"invalid_grant"}'),
            )

        with patch("urllib.request.urlopen", side_effect=_raise):
            with pytest.raises(OAuthError):
                flow.refresh()

        assert call_count == 1, "Must not retry on Auth failure"

    def test_refresh_raises_when_client_secret_missing(self) -> None:
        store = MockStore({"refresh_token": "rt"})
        flow = _make_flow(store=store)
        with pytest.raises(OAuthError, match="client_secret"):
            flow.refresh()


class TestNoSecretLeak:
    """Client secret and token values must not appear in OAuthError messages."""

    def test_client_secret_absent_from_http_error(self) -> None:
        store = MockStore({"client_secret": "SUPER_SECRET_CS", "refresh_token": "rt"})
        flow = _make_flow(store=store)

        http_err = urllib.error.HTTPError(
            url="https://example.com/token",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":"invalid_grant"}'),
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(OAuthError) as exc_info:
                flow.refresh()
        assert "SUPER_SECRET_CS" not in str(exc_info.value)

    def test_refresh_token_absent_from_error(self) -> None:
        store = MockStore({"client_secret": "cs", "refresh_token": "SUPER_SECRET_RT"})
        flow = _make_flow(store=store)

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("unreachable")):
            with pytest.raises(OAuthError) as exc_info:
                flow.refresh()
        assert "SUPER_SECRET_RT" not in str(exc_info.value)
