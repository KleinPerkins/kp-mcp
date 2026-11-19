"""Adversarial tests for KeychainSecretStore.

All subprocess calls are mocked — never touches the real Keychain. Verifies:
  - fail-loud off macOS (no silent plaintext fallback),
  - no shell/arg injection via profile or key names,
  - secret values never appear in raised exceptions,
  - missing key -> KeyError, get/has/delete exit-code handling.
"""

import subprocess
import json
import sys
from unittest.mock import patch

import pytest

from kp_mcp_bootstrap.errors import SecretStoreError
from kp_mcp_bootstrap.secrets import _NOT_FOUND_EXIT, _SECURITY, KeychainSecretStore


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestFailLoudOffMacOS:
    @pytest.mark.parametrize("method,args", [
        ("get", ("k",)),
        ("set", ("k", "v")),
        ("delete", ("k",)),
        ("has", ("k",)),
    ])
    def test_every_method_fails_loud_off_macos(self, method, args, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        store = KeychainSecretStore()
        # Even if subprocess.run is available, it must never be reached off macOS.
        with patch("subprocess.run") as run:
            with pytest.raises(RuntimeError, match="macOS"):
                getattr(store, method)(*args)
        run.assert_not_called()


class TestNoArgInjection:
    """profile/key stay literal stdin data and never become shell syntax."""

    def test_security_invoked_without_shell(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["shell"] = kwargs.get("shell", False)
            return _completed(0, json.dumps({'value':'v'}))

        with patch("subprocess.run", side_effect=fake_run):
            KeychainSecretStore(profile="default").get("refresh_token")
        assert captured["shell"] is False
        assert isinstance(captured["cmd"], list)
        assert captured["cmd"][0] == sys.executable
        assert captured["cmd"][1:4] == ['-I','-S','-B']
        assert captured["cmd"][-1].endswith('/_keychain_access.py')

    def test_injection_chars_in_profile_passed_literally(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured['payload'] = json.loads(kwargs['input'])
            return _completed(0, json.dumps({'value':'v'}))

        evil = "default; rm -rf / && echo"
        with patch("subprocess.run", side_effect=fake_run):
            KeychainSecretStore(profile=evil).get("refresh_token")
        cmd = captured["cmd"]
        account = captured['payload']['account']
        assert account == f"{evil}:refresh_token"
        # The dangerous string stays data and is absent from process arguments.
        assert account not in repr(cmd)

    def test_flaglike_key_not_interpreted_as_option(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured['payload'] = json.loads(kwargs['input'])
            return _completed(0, json.dumps({'value':'v'}))

        with patch("subprocess.run", side_effect=fake_run):
            KeychainSecretStore(profile="p").get("-D")
        cmd = captured["cmd"]
        # The flag-like key remains a literal account value in the JSON request.
        assert captured['payload']['account'] == "p:-D"
        assert 'p:-D' not in repr(cmd)


class TestNoSecretLeak:
    def test_set_failure_does_not_leak_value(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch("subprocess.run", return_value=_completed(1, stderr="boom")):
            store = KeychainSecretStore()
            with pytest.raises(SecretStoreError) as exc:
                store.set("k", "ULTRA_SECRET_VALUE")
        assert "ULTRA_SECRET_VALUE" not in str(exc.value)


class TestExitCodes:
    def test_get_missing_raises_keyerror(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch("subprocess.run", return_value=_completed(_NOT_FOUND_EXIT)):
            with pytest.raises(KeyError):
                KeychainSecretStore().get("missing")

    def test_delete_tolerates_not_found(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch("subprocess.run", return_value=_completed(_NOT_FOUND_EXIT)):
            KeychainSecretStore().delete("missing")  # no raise

    def test_unicode_and_long_value_passed_through(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        captured = {}
        big = "✓" * 5000

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["input"] = kwargs["input"]
            return _completed(0)

        with patch("subprocess.run", side_effect=fake_run):
            KeychainSecretStore().set("k", big)
        import json
        payload = json.loads(captured["input"])
        assert payload["value"] == big
        assert payload["update"] is True
        assert big not in repr(captured["cmd"])
