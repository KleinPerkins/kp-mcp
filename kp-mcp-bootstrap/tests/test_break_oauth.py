"""Adversarial tests for LoopbackPKCEFlow.

Covers the two seeded findings:
  (a) single handle_request() drops the real redirect when a stray request
      (favicon / wrong state) arrives first — listener must loop.
  (b) port TOCTOU from bind-0 → close → rebind — listener must bind once.

Plus probes for secret-leakage in token-endpoint error paths.
No live network: real loopback sockets are localhost-only; token endpoint mocked.
"""

import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from kp_mcp_bootstrap.errors import OAuthError
from kp_mcp_bootstrap.oauth import (
    LoopbackPKCEFlow,
    _make_loopback_handler,
    _serve_until_done,
)


class MockStore:
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


def _make_flow(store: MockStore | None = None, headless: bool = False, timeout: int = 8) -> LoopbackPKCEFlow:
    return LoopbackPKCEFlow(
        store=store or MockStore({"client_secret": "cs_test"}),
        auth_endpoint="https://example.com/auth",
        token_endpoint="https://example.com/token",
        client_id="client_id_test",
        headless=headless,
        timeout=timeout,
    )


class _FakeListener:
    """Stand-in for HTTPServer.handle_request that scripts a request sequence."""

    def __init__(self, scripted) -> None:
        self.timeout = None
        self._scripted = list(scripted)
        self.calls = 0

    def handle_request(self) -> None:
        self.calls += 1
        if self._scripted:
            action = self._scripted.pop(0)
            action()


class TestServeLoopRobustness:
    """Finding (a): the serve loop must ignore stray requests until done."""

    def test_loop_ignores_stray_request_then_completes(self) -> None:
        done = threading.Event()
        # First request is a stray (no done); second sets done (real redirect).
        listener = _FakeListener([lambda: None, lambda: done.set()])
        _serve_until_done(listener, done)
        assert listener.calls == 2, "must keep serving past the ignored stray request"
        assert done.is_set()

    def test_loop_exits_on_socket_close(self) -> None:
        done = threading.Event()

        def _boom() -> None:
            raise OSError("socket closed")

        listener = _FakeListener([_boom])
        _serve_until_done(listener, done)  # must not raise / hang
        assert not done.is_set()

    def test_loop_sets_socket_timeout(self) -> None:
        done = threading.Event()
        done.set()
        listener = _FakeListener([])
        _serve_until_done(listener, done)
        assert listener.timeout is not None, "must set a socket timeout so done is observable"


class TestSingleBindNoTOCTOU:
    """Finding (b): authorize must instantiate exactly one HTTPServer (no rebind)."""

    def test_authorize_binds_listener_once(self) -> None:
        flow = _make_flow(headless=True, timeout=2)
        instances: list[MagicMock] = []

        def fake_httpserver(addr, handler):
            srv = MagicMock()
            srv.server_address = ("127.0.0.1", 54321)
            instances.append(srv)
            return srv

        with patch("kp_mcp_bootstrap.oauth.HTTPServer", side_effect=fake_httpserver):
            with patch("kp_mcp_bootstrap.oauth.threading.Thread") as thr:
                thr.return_value.start = lambda: None
                with patch("kp_mcp_bootstrap.oauth.threading.Event") as ev_cls:
                    ev = MagicMock()
                    ev.wait.return_value = True
                    ev_cls.return_value = ev
                    with pytest.raises(OAuthError):  # no code captured -> raises
                        flow.authorize(["openid"])

        assert len(instances) == 1, "must not bind-then-rebind (TOCTOU race)"
        instances[0].server_close.assert_called()


class TestStrayRedirectIntegration:
    """End-to-end: a favicon GET before the real redirect must not hang the flow."""

    def test_favicon_then_real_redirect_returns_code(self) -> None:
        flow = _make_flow(headless=False, timeout=10)

        def fake_open(auth_url: str) -> None:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
            redirect_uri = qs["redirect_uri"][0]
            state = qs["state"][0]

            def _drive() -> None:
                # Stray request first (no state) — must be ignored, not consumed.
                _get(redirect_uri + "/favicon.ico")
                _get(f"{redirect_uri}/?code=THE_CODE&state={urllib.parse.quote(state)}")

            threading.Thread(target=_drive, daemon=True).start()

        with patch("kp_mcp_bootstrap.oauth.webbrowser.open", side_effect=fake_open):
            code = flow.authorize(["openid"])

        assert code == "THE_CODE"

    def test_wrong_state_then_real_redirect_returns_code(self) -> None:
        flow = _make_flow(headless=False, timeout=10)

        def fake_open(auth_url: str) -> None:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
            redirect_uri = qs["redirect_uri"][0]
            state = qs["state"][0]

            def _drive() -> None:
                _get(f"{redirect_uri}/?code=EVIL&state=not-the-real-state")
                _get(f"{redirect_uri}/?code=GOOD&state={urllib.parse.quote(state)}")

            threading.Thread(target=_drive, daemon=True).start()

        with patch("kp_mcp_bootstrap.oauth.webbrowser.open", side_effect=fake_open):
            code = flow.authorize(["openid"])

        assert code == "GOOD"


def _get(url: str) -> None:
    """Best-effort loopback GET with a brief retry (listener may not be up yet)."""
    for _ in range(50):
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except urllib.error.URLError:
            time.sleep(0.05)
        except Exception:
            return


class TestTokenErrorNoSecretLeak:
    """client_secret must never appear in token-endpoint error messages."""

    def test_non_json_response_does_not_leak_secret(self) -> None:
        store = MockStore({"client_secret": "TOP_SECRET_CS", "refresh_token": "rt"})
        flow = _make_flow(store=store)
        resp = MagicMock()
        resp.read.return_value = b"<html>garbage TOP_SECRET_CS</html>"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            with pytest.raises(OAuthError) as exc:
                flow.refresh()
        # Error message itself must not interpolate the secret.
        assert "TOP_SECRET_CS" not in str(exc.value)

    def test_missing_access_token_does_not_leak_secret(self) -> None:
        import json

        store = MockStore({"client_secret": "TOP_SECRET_CS", "refresh_token": "rt"})
        flow = _make_flow(store=store)
        resp = MagicMock()
        resp.read.return_value = json.dumps({"error": "invalid_grant"}).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            with pytest.raises(OAuthError) as exc:
                flow.refresh()
        assert "TOP_SECRET_CS" not in str(exc.value)


class TestHandlerStrayDoesNotSetDone:
    """Documents that the handler leaves done unset for stray/wrong-state hits."""

    def _handler(self, path: str, state: str):
        result: dict = {}
        done = threading.Event()
        cls = _make_loopback_handler(result, done, state)
        h = cls.__new__(cls)
        h.path = path
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        h.wfile = MagicMock()
        h.do_GET()
        return result, done

    def test_favicon_leaves_done_unset(self) -> None:
        result, done = self._handler("/favicon.ico", "st")
        assert not done.is_set()
        assert "code" not in result
