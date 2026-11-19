from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from google_kit.registry import OpSpec, register


class _In(BaseModel):
    value: str


class _Out(BaseModel):
    value: str


def _fn(inp: _In) -> _Out:
    return _Out(value=inp.value)


def _spec_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "drive.valid",
        "fn": _fn,
        "input_model": _In,
        "output_model": _Out,
        "posture": "read",
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
    }
    base.update(overrides)
    return base


def test_opspec_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        OpSpec(**_spec_kwargs(name=""))


def test_opspec_rejects_unknown_posture() -> None:
    with pytest.raises(ValueError, match="posture"):
        OpSpec(**_spec_kwargs(posture="root"))


def test_opspec_rejects_empty_scopes() -> None:
    with pytest.raises(ValueError, match="scope"):
        register(OpSpec(**_spec_kwargs(scopes=[])))


def test_opspec_rejects_non_model_input() -> None:
    with pytest.raises(TypeError, match="input_model"):
        OpSpec(**_spec_kwargs(input_model=dict))
