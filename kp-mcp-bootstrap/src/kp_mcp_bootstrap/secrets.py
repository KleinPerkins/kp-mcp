"""SecretStore protocol and macOS Keychain implementation.

No plaintext fallback (R15/B5): authenticated operations fail closed on non-macOS.
Secret values are never echoed in logs or exception messages.
"""

import subprocess
import json
import os
from pathlib import Path
import sys
from typing import Protocol, runtime_checkable

from kp_mcp_bootstrap.errors import SecretStoreError


@runtime_checkable
class SecretStore(Protocol):
    """Read/write interface for opaque secret values."""

    def get(self, key: str) -> str:
        """Retrieve a secret by key. Raises KeyError if absent."""
        ...

    def set(self, key: str, value: str) -> None:
        """Store a secret. Overwrites any existing value for key."""
        ...

    def delete(self, key: str) -> None:
        """Delete a secret by key. No-op if absent."""
        ...

    def has(self, key: str) -> bool:
        """Return True if a secret exists for key."""
        ...


_SECURITY = "/usr/bin/security"
_NOT_FOUND_EXIT = 44


def _keychain_write_input(args: list[str]) -> str:
    """Convert only the existing generic-password write shape to bounded stdin."""
    from kp_mcp_bootstrap._keychain_write import encode_payload
    try:
        if not args or args[0] != "add-generic-password":
            raise ValueError("Unsupported Keychain write command.")
        fields = {}; update = False; i = 1
        while i < len(args):
            flag = args[i]
            if flag == "-U" and not update:
                update = True; i += 1; continue
            if flag not in ("-s", "-a", "-w") or flag in fields or i + 1 >= len(args):
                raise ValueError("Invalid Keychain write command.")
            fields[flag] = args[i + 1]; i += 2
        if set(fields) != {"-s", "-a", "-w"}:
            raise ValueError("Invalid Keychain write command.")
        text, _ = encode_payload({"service":fields["-s"], "account":fields["-a"],
                                  "value":fields["-w"], "update":update})
        return text
    except ValueError:
        raise SecretStoreError("Invalid or unsupported Keychain write payload.") from None


def _keychain_access_input(args: list[str]) -> str:
    """Accept only the store's exact get/has/delete command shapes."""
    from kp_mcp_bootstrap._keychain_access import validate_payload
    try:
        if not args or args[0] not in ('find-generic-password','delete-generic-password'):
            raise ValueError('Unsupported access command.')
        fields={};read=False;i=1
        while i<len(args):
            flag=args[i]
            if flag=='-w' and not read and args[0]=='find-generic-password':
                read=True;i+=1;continue
            if flag not in ('-s','-a') or flag in fields or i+1>=len(args):raise ValueError('Invalid access command.')
            fields[flag]=args[i+1];i+=2
        if set(fields)!={'-s','-a'}:raise ValueError('Invalid access command.')
        payload={'operation':'delete' if args[0]=='delete-generic-password' else 'get' if read else 'has',
                 'service':fields['-s'],'account':fields['-a']}
        validate_payload(payload)
        return json.dumps(payload,ensure_ascii=True,separators=(',',':'))
    except (ValueError,TypeError):raise SecretStoreError('Invalid or unsupported Keychain access payload.') from None


def _run_security(args: list[str]) -> subprocess.CompletedProcess:
    """Run the exact native store helper under the same Python identity as writes."""
    try:
        writing = bool(args) and args[0] == "add-generic-password"
        options = {"input": _keychain_write_input(args) if writing else _keychain_access_input(args), "encoding": "utf-8",
                   "env": {key:value for key,value in os.environ.items() if key in (
                       "HOME", "CODEX_HOME", "USER", "LOGNAME", "TMPDIR", "LANG",
                       "LC_CTYPE", "SECURITYSESSIONID", "__CF_USER_TEXT_ENCODING")}}
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(Path(__file__).with_name("_keychain_write.py" if writing else "_keychain_access.py"))],
            capture_output=True,
            text=True,
            timeout=15,
            **options,
        )
        if not writing and (proc.stderr or (proc.returncode==0 and json.loads(options['input'])['operation']!='get' and proc.stdout)):
            raise SecretStoreError('Keychain access helper returned an invalid response.')
        return proc
    except FileNotFoundError:
        raise SecretStoreError(
            "macOS Keychain security helper could not be executed. "
            "Ensure Python and the owner helper are available."
        )
    except subprocess.TimeoutExpired:
        raise SecretStoreError("Keychain operation timed out after 15 seconds.")


class KeychainSecretStore:
    """macOS login-Keychain SecretStore (non-biometric).

    Each secret is stored as a generic password item with:
      service  = "google-kit"
      account  = "{profile}:{key}"

    This allows multiple named secrets per profile under one service namespace.
    Importing this class on non-macOS is allowed; calling its methods raises
    RuntimeError so callers fail closed rather than silently using plaintext.

    All operations use isolated native helpers under the same Python identity.
    Locked-keychain and access-control failures remain OS authorization failures;
    the store does not unlock a keychain, grant trust, change ACLs, or retry.
    Authenticated background use needs separately qualified session ownership.
    """

    SERVICE = "google-kit"

    def __init__(self, profile: str = "default") -> None:
        self._profile = profile

    @property
    def profile(self) -> str:
        """Keychain account namespace this store reads/writes.

        Exposed as part of the store contract so callers (e.g. the client's
        cross-process token-refresh lock) can key per-profile coordination off a
        public attribute rather than the private ``_profile``.
        """
        return self._profile

    def _assert_macos(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError(
                "KeychainSecretStore requires macOS. "
                "Authenticated operations are macOS-only in v1 (R38/B5)."
            )

    def _account(self, key: str) -> str:
        return f"{self._profile}:{key}"

    def get(self, key: str) -> str:
        """Retrieve a secret from the macOS login Keychain.

        Raises KeyError if the key does not exist.
        Raises SecretStoreError on Keychain access failure.
        Secret value is never included in any raised exception.
        """
        self._assert_macos()
        proc = _run_security([
            "find-generic-password",
            "-s", self.SERVICE,
            "-a", self._account(key),
            "-w",
        ])
        if proc.returncode == _NOT_FOUND_EXIT:
            raise KeyError(key)
        if proc.returncode != 0:
            raise SecretStoreError(
                f"Keychain read failed for key '{key}' (exit {proc.returncode})"
            )
        from kp_mcp_bootstrap._keychain_access import parse_result
        try:
            return parse_result(proc.stdout)
        except (ValueError,UnicodeError,TypeError):
            raise SecretStoreError('Keychain read returned an invalid native response.') from None

    def set(self, key: str, value: str) -> None:
        """Store a secret in the macOS login Keychain.

        Overwrites any existing value. Secret value is never included in
        any raised exception or logged.

        Raises SecretStoreError on Keychain access failure.
        """
        self._assert_macos()
        proc = _run_security([
            "add-generic-password",
            "-U",
            "-s", self.SERVICE,
            "-a", self._account(key),
            "-w", value,
        ])
        if proc.returncode != 0 or proc.stderr:
            raise SecretStoreError(
                f"Keychain write failed for key '{key}' (exit {proc.returncode})"
            )

    def delete(self, key: str) -> None:
        """Delete a secret from the macOS login Keychain. No-op if absent.

        Raises SecretStoreError on unexpected Keychain failure.
        """
        self._assert_macos()
        proc = _run_security([
            "delete-generic-password",
            "-s", self.SERVICE,
            "-a", self._account(key),
        ])
        if proc.returncode not in (0, _NOT_FOUND_EXIT):
            raise SecretStoreError(
                f"Keychain delete failed for key '{key}' (exit {proc.returncode})"
            )

    def validate_create(self, key: str, value: str) -> None:
        """Validate the transport bound before any item in a new profile is written."""
        _keychain_write_input(["add-generic-password", "-s", self.SERVICE,
                             "-a", self._account(key), "-w", value])

    def create(self, key: str, value: str) -> None:
        """Create one absent item; native duplicate refusal preserves existing values.

        There is deliberately no update flag, pre-delete, retry or rollback.
        A transport error can have an unknown outcome and must remain held.
        """
        self._assert_macos()
        proc = _run_security(["add-generic-password", "-s", self.SERVICE,
                              "-a", self._account(key), "-w", value])
        if proc.returncode != 0 or proc.stderr:
            raise SecretStoreError("Keychain create was refused or its outcome is unknown.")

    def has(self, key: str) -> bool:
        """Return True if a secret exists for key in the macOS login Keychain.

        Raises SecretStoreError on unexpected Keychain failure.
        """
        self._assert_macos()
        proc = _run_security([
            "find-generic-password",
            "-s", self.SERVICE,
            "-a", self._account(key),
        ])
        if proc.returncode == _NOT_FOUND_EXIT:
            return False
        if proc.returncode != 0:
            raise SecretStoreError(
                f"Keychain lookup failed for key '{key}' (exit {proc.returncode})"
            )
        return True
