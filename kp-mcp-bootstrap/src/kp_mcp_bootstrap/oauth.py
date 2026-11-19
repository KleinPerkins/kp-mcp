"""PKCE loopback OAuth 2.0 flow — generic, provider-agnostic.

Provider endpoints (auth_endpoint, token_endpoint), client_id, and scopes are
injected parameters; this engine makes no Google-specific assumptions. google-kit
passes Google's values in Phase 4.

Security properties:
- PKCE S256: verifier is 32 random bytes base64url-encoded; challenge is
  SHA-256(verifier) base64url-encoded (RFC 7636 §4.2).
- Client secret is read from SecretStore; never echoed in logs or exceptions.
- Tokens are persisted through SecretStore only; never written to files.
- Never retries on Auth failure (RFC 6749 §5.2 error=invalid_grant).

launchd / locked-keychain note: if a launchd job runs this flow before the
user has unlocked the login keychain, token storage will fail. Run in a
LoginAgent (LaunchAgents, SessionCreate=true) or unlock the keychain first.
"""

import base64
import hashlib
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Protocol

from kp_mcp_bootstrap.errors import OAuthError
from kp_mcp_bootstrap.secrets import SecretStore

_KEY_REFRESH = "refresh_token"
_KEY_ACCESS = "access_token"
_KEY_CLIENT_SECRET = "client_secret"


def _generate_pkce() -> tuple[str, str]:
    """Return (verifier, challenge) as base64url strings (no padding)."""
    raw = secrets.token_bytes(32)
    verifier = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _make_loopback_handler(
    result: dict,
    done: threading.Event,
    expected_state: str,
):
    """Return an HTTPRequestHandler class that captures the OAuth redirect."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            received_state = qs.get("state", [None])[0]
            if received_state != expected_state:
                self._respond(400, b"State mismatch. Authorization rejected.")
                return
            error = qs.get("error", [None])[0]
            if error:
                result["error"] = error
                result["error_description"] = qs.get("error_description", [error])[0]
            else:
                result["code"] = qs.get("code", [None])[0]
            self._respond(200, b"Authorization complete. You may close this window.")
            done.set()

        def _respond(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            pass

    return _Handler


def _serve_until_done(listener: HTTPServer, done: threading.Event) -> None:
    """Service loopback requests until the real redirect arrives.

    A single ``handle_request()`` is unsafe: a stray request (e.g. the browser
    fetching ``/favicon.ico``, or any request lacking the correct ``state``) is
    answered with a 400 by the handler but does NOT set ``done`` — so a single
    blocking ``handle_request()`` would consume that stray request and the real
    redirect would be missed, hanging the flow until timeout.

    Instead we loop, ignoring unrelated requests, until the handler signals the
    real code/error by setting ``done``. ``listener.timeout`` makes each
    ``handle_request()`` return periodically so the loop can observe ``done``
    being set (and so it can exit promptly when the server socket is closed on
    timeout from the main thread).
    """
    listener.timeout = 0.5
    while not done.is_set():
        try:
            listener.handle_request()
        except OSError:
            # Socket was closed (e.g. server_close on main-thread timeout).
            break


class PKCEFlow(Protocol):
    """Interface for PKCE loopback OAuth authorization."""

    def authorize(self, scopes: list[str]) -> str:
        """Run the PKCE loopback flow and return the authorization code."""
        ...

    def exchange(self, code: str) -> dict[str, str]:
        """Exchange an authorization code for access + refresh tokens.

        Stores tokens in the SecretStore. Returns a dict with at least
        'access_token' and 'refresh_token'.
        """
        ...

    def refresh(self) -> str:
        """Refresh the access token using the stored refresh token.

        Returns the new access token. Never retries on Auth failure.
        """
        ...


class LoopbackPKCEFlow:
    """Concrete PKCE loopback OAuth 2.0 flow (S256, generic provider).

    Args:
        store:          SecretStore instance holding client_secret and tokens.
        auth_endpoint:  Provider authorization endpoint URL.
        token_endpoint: Provider token endpoint URL.
        client_id:      OAuth 2.0 client ID.
        headless:       If True, print auth URL to stderr instead of opening
                        a browser, then read the redirect URL from stdin.
        timeout:        Seconds to wait for the browser redirect (default 120).
    """

    def __init__(
        self,
        store: SecretStore,
        auth_endpoint: str,
        token_endpoint: str,
        client_id: str,
        headless: bool = False,
        timeout: int = 120,
        authorization_params: dict[str, str] | None = None,
    ) -> None:
        self._store = store
        self._auth_endpoint = auth_endpoint
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._headless = headless
        self._timeout = timeout
        # Provider hints cannot replace any security-critical PKCE/flow field.
        extras = dict(authorization_params or {})
        allowed = {"login_hint", "prompt", "include_granted_scopes"}
        if any(not isinstance(k, str) or not isinstance(v, str) or k not in allowed
               for k, v in extras.items()):
            raise OAuthError("Invalid provider authorization parameters.")
        self._authorization_params = extras
        self._verifier: str | None = None
        self._redirect_uri: str | None = None

    def authorize(self, scopes: list[str]) -> str:
        """Run PKCE loopback flow; return authorization code.

        Opens (or prints) the auth URL, waits for the provider to redirect to
        the loopback listener, and returns the code for exchange().

        Raises OAuthError on timeout, state mismatch, or provider error.
        """
        verifier, challenge = _generate_pkce()
        state = secrets.token_urlsafe(16)
        self._verifier = verifier

        result: dict = {}
        done = threading.Event()
        handler_cls = _make_loopback_handler(result, done, state)

        # Bind the real listener directly on an ephemeral port (port 0). Reading
        # the OS-assigned port from this already-bound socket avoids the TOCTOU
        # race of the old "bind 0 → close → rebind same port" pattern, where
        # another process could steal the port in the window between close and
        # rebind.
        listener = HTTPServer(("127.0.0.1", 0), handler_cls)
        original_get_request = listener.get_request
        def bounded_get_request():
            connection, address = original_get_request()
            try:
                connection.settimeout(1)
            except BaseException:
                connection.close()
                raise
            return connection, address
        listener.get_request = bounded_get_request
        port = listener.server_address[1]

        redirect_uri = f"http://127.0.0.1:{port}"
        self._redirect_uri = redirect_uri

        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
        }
        params.update(self._authorization_params)
        auth_url = self._auth_endpoint + "?" + urllib.parse.urlencode(params)

        # Start serving before opening the browser: the listener socket is bound
        # at construction, but starting the accept loop first guarantees we never
        # drop a redirect that races ahead of the browser handoff.
        thread = threading.Thread(target=_serve_until_done, args=(listener, done), daemon=True)
        started = False
        try:
            thread.start(); started = True
            if self._headless:
                print(f"\nOpen this URL in your browser to authorize:\n\n  {auth_url}\n", file=sys.stderr, flush=True)
                print("Waiting for redirect...", file=sys.stderr, flush=True)
            else:
                webbrowser.open(auth_url)
            if not done.wait(timeout=self._timeout):
                raise OAuthError(
                    f"Authorization timed out after {self._timeout}s waiting for loopback redirect."
                )
            if "error" in result:
                desc = result.get("error_description", result["error"])
                raise OAuthError(f"Authorization failed: {result['error']} — {desc}")
            code = result.get("code")
            if not code:
                raise OAuthError("Authorization redirect did not contain a code.")
            return code
        finally:
            done.set()
            listener.server_close()
            if started:
                thread.join(timeout=2)
                if thread.is_alive():
                    raise OAuthError("OAuth loopback listener did not terminate.")

    def exchange(self, code: str) -> dict[str, str]:
        """Exchange authorization code for tokens; persist via SecretStore.

        Raises OAuthError on HTTP or provider error.
        Client secret is read from SecretStore and never echoed.
        """
        if self._verifier is None or self._redirect_uri is None:
            raise OAuthError("exchange() called before authorize(); no PKCE verifier available.")

        try:
            client_secret = self._store.get(_KEY_CLIENT_SECRET)
        except KeyError:
            raise OAuthError(
                "client_secret not found in SecretStore. Store it before running OAuth."
            )

        body = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "client_secret": client_secret,
            "code_verifier": self._verifier,
        }).encode()

        tokens = self._post_token(body)
        self._store.set(_KEY_ACCESS, tokens["access_token"])
        if "refresh_token" in tokens:
            self._store.set(_KEY_REFRESH, tokens["refresh_token"])
        return tokens

    def refresh(self) -> str:
        """Refresh the access token using the stored refresh token.

        Returns the new access token.
        Never retries on Auth failure.

        Raises OAuthError on provider error or missing refresh token.
        Client secret is read from SecretStore and never echoed.
        """
        try:
            refresh_token = self._store.get(_KEY_REFRESH)
        except KeyError:
            raise OAuthError(
                "refresh_token not found in SecretStore. Run the full OAuth flow first."
            )

        try:
            client_secret = self._store.get(_KEY_CLIENT_SECRET)
        except KeyError:
            raise OAuthError(
                "client_secret not found in SecretStore. Store it before running OAuth."
            )

        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "client_secret": client_secret,
        }).encode()

        tokens = self._post_token(body)
        access_token = tokens["access_token"]
        self._store.set(_KEY_ACCESS, access_token)
        if "refresh_token" in tokens:
            self._store.set(_KEY_REFRESH, tokens["refresh_token"])
        return access_token

    def _post_token(self, body: bytes) -> dict[str, str]:
        """POST to token endpoint; parse JSON response.

        Raises OAuthError on HTTP error or missing access_token.
        Never echoes secrets in the error message.
        """
        req = urllib.request.Request(
            self._token_endpoint,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode(errors="replace")
            try:
                err_json = json.loads(error_body)
                error_code = err_json.get("error", "unknown")
            except Exception:
                error_code = "unknown"
            raise OAuthError(
                f"Token endpoint returned HTTP {exc.code}: error={error_code}"
            ) from None
        except urllib.error.URLError as exc:
            raise OAuthError(f"Token endpoint unreachable: {exc.reason}") from None

        try:
            data: dict = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OAuthError(f"Token endpoint returned non-JSON response: {exc}") from None

        if "access_token" not in data:
            error = data.get("error", "unknown")
            raise OAuthError(f"Token response missing access_token: error={error}")

        return data
