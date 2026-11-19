"""Tests for google_kit.core.run_id."""
import contextvars

import pytest

from google_kit.core.run_id import (
    ensure_run_id,
    get_run_id,
    new_run_id,
    reset_run_id,
    set_run_id,
)


def test_new_run_id_format() -> None:
    rid = new_run_id()
    assert len(rid) == 16
    int(rid, 16)


def test_new_run_id_unique() -> None:
    assert new_run_id() != new_run_id()


def test_set_and_get() -> None:
    token = set_run_id("test-id-1234abcd")
    assert get_run_id() == "test-id-1234abcd"
    reset_run_id(token)


def test_get_default_is_empty() -> None:
    ctx = contextvars.copy_context()

    def _check():
        from google_kit.core import run_id as rid_mod
        rid_mod._RUN_ID.set("")
        return rid_mod.get_run_id()

    assert ctx.run(_check) == ""


def test_ensure_run_id_generates_if_absent() -> None:
    ctx = contextvars.copy_context()

    def _check():
        from google_kit.core import run_id as rid_mod
        rid_mod._RUN_ID.set("")
        rid = rid_mod.ensure_run_id()
        assert len(rid) == 16
        assert rid_mod.get_run_id() == rid

    ctx.run(_check)


def test_ensure_run_id_returns_existing() -> None:
    ctx = contextvars.copy_context()

    def _check():
        from google_kit.core import run_id as rid_mod
        rid_mod._RUN_ID.set("existing-id-1")
        rid = rid_mod.ensure_run_id()
        assert rid == "existing-id-1"

    ctx.run(_check)


def test_reset_restores_previous() -> None:
    original = get_run_id()
    token = set_run_id("tmp-id-12345678")
    assert get_run_id() == "tmp-id-12345678"
    reset_run_id(token)
    assert get_run_id() == original
