"""Tests for google_kit.registry."""

import pytest
from pydantic import BaseModel

from google_kit.registry import OpSpec, all_specs, get, register


class FakeIn(BaseModel):
    value: str


class FakeOut(BaseModel):
    result: str


def fake_fn(inp: FakeIn) -> FakeOut:
    return FakeOut(result=inp.value)


def _make_spec(name: str) -> OpSpec:
    return OpSpec(
        name=name,
        fn=fake_fn,
        input_model=FakeIn,
        output_model=FakeOut,
        posture="read",
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Run each test with a clean registry; restore full registry on teardown."""
    import google_kit.registry as reg_mod

    saved = dict(reg_mod._REGISTRY)
    reg_mod._REGISTRY.clear()
    yield
    reg_mod._REGISTRY.clear()
    reg_mod._REGISTRY.update(saved)


def test_register_and_get() -> None:
    spec = _make_spec("drive.test_get")
    register(spec)
    assert get("drive.test_get") is spec


def test_register_duplicate_raises() -> None:
    spec = _make_spec("drive.dup")
    register(spec)
    with pytest.raises(ValueError, match="already registered"):
        register(_make_spec("drive.dup"))


def test_all_specs_returns_list() -> None:
    register(_make_spec("drive.a"))
    register(_make_spec("drive.b"))
    specs = all_specs()
    assert len(specs) == 2
    assert specs[0].name == "drive.a"


def test_get_missing_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get("nonexistent.op")
