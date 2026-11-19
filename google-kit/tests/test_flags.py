"""Tests for the ADR F5 off-by-default flag gate (google_kit.core.flags)."""
from __future__ import annotations

import pytest

from google_kit.core.flags import FlagDisabledError, ensure_enabled, is_flag_enabled


class _Spec:
    """Minimal duck-typed stand-in for an OpSpec (name + flag)."""

    def __init__(self, name: str, flag: str | None) -> None:
        self.name = name
        self.flag = flag


class TestIsFlagEnabled:
    def test_none_is_enabled(self) -> None:
        assert is_flag_enabled(None) is True

    def test_empty_is_enabled(self) -> None:
        assert is_flag_enabled("") is True

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", " On "])
    def test_truthy_values(self, val: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GK_TEST_FLAG", val)
        assert is_flag_enabled("GK_TEST_FLAG") is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "maybe"])
    def test_falsy_values(self, val: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GK_TEST_FLAG", val)
        assert is_flag_enabled("GK_TEST_FLAG") is False

    def test_unset_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GK_TEST_FLAG", raising=False)
        assert is_flag_enabled("GK_TEST_FLAG") is False


class TestEnsureEnabled:
    def test_ungated_passes(self) -> None:
        ensure_enabled(_Spec("svc.read", None))

    def test_gated_unset_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GK_TEST_FLAG", raising=False)
        with pytest.raises(FlagDisabledError, match="not authorized"):
            ensure_enabled(_Spec("svc.write", "GK_TEST_FLAG"))

    def test_gated_set_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GK_TEST_FLAG", "1")
        ensure_enabled(_Spec("svc.write", "GK_TEST_FLAG"))

    def test_error_message_names_op_and_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GK_TEST_FLAG", raising=False)
        with pytest.raises(FlagDisabledError) as exc:
            ensure_enabled(_Spec("gmail.send", "GK_TEST_FLAG"))
        assert "gmail.send" in str(exc.value)
        assert "GK_TEST_FLAG" in str(exc.value)
