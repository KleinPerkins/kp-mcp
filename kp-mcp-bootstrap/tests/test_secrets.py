"""Tests for KeychainSecretStore.

All tests mock subprocess.run — no live Keychain interaction.
Real-Keychain tests are skipped (require interactive macOS session).
"""

import subprocess
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from kp_mcp_bootstrap.errors import SecretStoreError
from kp_mcp_bootstrap.secrets import KeychainSecretStore, _SECURITY, _NOT_FOUND_EXIT


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


_macos_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="KeychainSecretStore is macOS-only (R38/B5); these tests invoke methods that fail-closed on non-Darwin.",
)


@_macos_only
class TestCommandConstruction:
    """Verify isolated native helpers receive the complete exact request."""

    def test_get_command(self) -> None:
        store = KeychainSecretStore(profile="myprofile")
        with patch("subprocess.run", return_value=_completed(0, json.dumps({'value':'secret'}))) as mock_run:
            assert store.get("refresh_token") == 'secret'
        args = mock_run.call_args[0][0]
        assert args[0] == sys.executable and args[1:4] == ['-I','-S','-B']
        assert args[-1].endswith('/_keychain_access.py')
        assert json.loads(mock_run.call_args.kwargs['input']) == {
            'operation':'get','service':'google-kit','account':'myprofile:refresh_token'}
        assert 'myprofile:refresh_token' not in repr(args)

    def test_set_command_uses_update_flag(self) -> None:
        store = KeychainSecretStore(profile="myprofile")
        with patch("subprocess.run", return_value=_completed(0)) as mock_run:
            store.set("access_token", "tok123")
        args = mock_run.call_args[0][0]
        import json
        payload = json.loads(mock_run.call_args.kwargs["input"])
        assert payload["update"] is True
        assert payload["service"] == "google-kit"
        assert payload["account"] == "myprofile:access_token"
        assert payload["value"] == "tok123"
        assert "tok123" not in repr(args)
        assert args[1:4] == ["-I", "-S", "-B"]

    def test_delete_command(self) -> None:
        store = KeychainSecretStore(profile="myprofile")
        with patch("subprocess.run", return_value=_completed(0)) as mock_run:
            store.delete("client_secret")
        args = mock_run.call_args[0][0]
        assert args[0] == sys.executable and args[1:4] == ['-I','-S','-B']
        assert args[-1].endswith('/_keychain_access.py')
        assert json.loads(mock_run.call_args.kwargs['input']) == {
            'operation':'delete','service':'google-kit','account':'myprofile:client_secret'}

    def test_has_command(self) -> None:
        store = KeychainSecretStore(profile="default")
        with patch("subprocess.run", return_value=_completed(0)) as mock_run:
            store.has("some_key")
        args = mock_run.call_args[0][0]
        assert args[0] == sys.executable and args[1:4] == ['-I','-S','-B']
        assert args[-1].endswith('/_keychain_access.py')
        assert json.loads(mock_run.call_args.kwargs['input']) == {
            'operation':'has','service':'google-kit','account':'default:some_key'}


@_macos_only
class TestGetBehavior:
    def test_get_returns_stripped_value(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(0, json.dumps({'value':'mytoken'}))):
            assert store.get("k") == "mytoken"

    def test_get_raises_key_error_when_not_found(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(_NOT_FOUND_EXIT)):
            with pytest.raises(KeyError):
                store.get("missing_key")

    def test_get_raises_secret_store_error_on_other_failure(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(36)):
            with pytest.raises(SecretStoreError):
                store.get("k")


@_macos_only
class TestSetBehavior:
    def test_set_succeeds(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(0)):
            store.set("k", "v")

    def test_set_raises_on_failure(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(1)):
            with pytest.raises(SecretStoreError):
                store.set("k", "v")


@_macos_only
class TestDeleteBehavior:
    def test_delete_is_noop_when_not_found(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(_NOT_FOUND_EXIT)):
            store.delete("missing")

    def test_delete_raises_on_unexpected_error(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(1)):
            with pytest.raises(SecretStoreError):
                store.delete("k")


@_macos_only
class TestHasBehavior:
    def test_has_true_when_found(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(0)):
            assert store.has("k") is True

    def test_has_false_when_not_found(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(_NOT_FOUND_EXIT)):
            assert store.has("k") is False


class TestFailLoud:
    """Verified: non-macOS fails closed; security CLI absence fails closed."""

    def test_fails_on_non_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        store = KeychainSecretStore()
        with pytest.raises(RuntimeError, match="macOS"):
            store.get("k")

    def test_fails_on_non_macos_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        store = KeychainSecretStore()
        with pytest.raises(RuntimeError, match="macOS"):
            store.set("k", "v")

    def test_fails_when_security_cli_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch("subprocess.run", side_effect=FileNotFoundError("security not found")):
            store = KeychainSecretStore()
            with pytest.raises(SecretStoreError, match="security"):
                store.get("k")


@_macos_only
class TestNoPlaintext:
    """Verified: secret values never appear in raised exception text."""

    def test_secret_value_absent_from_get_error(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(36, stdout="SUPER_SECRET_VALUE")):
            with pytest.raises(SecretStoreError) as exc_info:
                store.get("k")
        assert "SUPER_SECRET_VALUE" not in str(exc_info.value)

    def test_secret_value_absent_from_set_error(self) -> None:
        store = KeychainSecretStore()
        with patch("subprocess.run", return_value=_completed(1, stderr="some error")):
            with pytest.raises(SecretStoreError) as exc_info:
                store.set("k", "SUPER_SECRET_VALUE")
        assert "SUPER_SECRET_VALUE" not in str(exc_info.value)

    def test_secret_never_written_to_file(self, tmp_path) -> None:
        """No file I/O during secret storage — only subprocess calls."""
        store = KeychainSecretStore()
        file_writes = []
        original_open = open

        def _mock_open(path, mode="r", *args, **kwargs):
            if "w" in mode or "a" in mode:
                file_writes.append(str(path))
            return original_open(path, mode, *args, **kwargs)

        with patch("subprocess.run", return_value=_completed(0)):
            with patch("builtins.open", side_effect=_mock_open):
                store.set("refresh_token", "SUPER_SECRET")

        assert not file_writes, f"Unexpected file writes: {file_writes}"


@pytest.mark.skip(reason="requires interactive macOS Keychain session")
class TestLiveKeychain:
    def test_round_trip(self) -> None:
        store = KeychainSecretStore(profile="test-p3-secure-auth")
        store.set("test_key", "test_value")
        assert store.get("test_key") == "test_value"
        assert store.has("test_key") is True
        store.delete("test_key")
        with pytest.raises(KeyError):
            store.get("test_key")
