"""Tests for faults.py: fault-injection context managers."""

import pytest

from kp_mcp_testkit.faults import inject_fault, inject_fault_fn


def _add(a: int, b: int) -> int:
    return a + b


def test_inject_fault_fn_faults_immediately() -> None:
    with inject_fault_fn(_add, ValueError, "injected") as faulty:
        with pytest.raises(ValueError, match="injected"):
            faulty(1, 2)


def test_inject_fault_fn_after_n_calls() -> None:
    with inject_fault_fn(_add, RuntimeError, "boom", after_calls=2) as faulty:
        assert faulty(1, 2) == 3
        assert faulty(3, 4) == 7
        with pytest.raises(RuntimeError, match="boom"):
            faulty(5, 6)


def test_inject_fault_fn_passes_through_before_fault() -> None:
    results: list[int] = []
    with inject_fault_fn(_add, StopIteration, after_calls=1) as faulty:
        results.append(faulty(10, 20))
        try:
            results.append(faulty(1, 1))
        except StopIteration:
            pass
    assert results == [30]


def test_inject_fault_patches_module_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    import kp_mcp_testkit.faults as faults_mod

    call_log: list[str] = []

    def _mock_side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
        call_log.append("patched")
        raise TimeoutError("timeout injected")

    monkeypatch.setattr(faults_mod, "_add_dummy", lambda: None, raising=False)

    with inject_fault_fn(_add, TimeoutError, "timeout injected") as faulty:
        with pytest.raises(TimeoutError):
            faulty(0, 0)
