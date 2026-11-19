"""Unit tests for the LIFO saga executor (core/saga.py).

The executor is pure: forward/compensate are plain callables, so these tests
inject recorder lambdas and assert ordering, LIFO rollback, best-effort
compensation, and original-cause preservation — no network, no services.
"""
from __future__ import annotations

import pytest

from google_kit.core.saga import SagaError, SagaStep, run_saga


def test_all_steps_succeed_returns_results_in_order() -> None:
    outcome = run_saga([
        SagaStep("a", lambda: "ra"),
        SagaStep("b", lambda: "rb"),
        SagaStep("c", lambda: "rc"),
    ])
    assert outcome.results == ["ra", "rb", "rc"]
    assert outcome.compensated is False
    assert outcome.failed_step is None


def test_empty_saga_is_a_noop() -> None:
    outcome = run_saga([])
    assert outcome.results == []
    assert outcome.compensated is False


def test_failure_compensates_completed_steps_lifo() -> None:
    order: list[str] = []

    def fwd(name: str):
        def _f() -> str:
            order.append(f"fwd:{name}")
            return f"id-{name}"
        return _f

    def comp(name: str):
        def _c(result: str) -> None:
            order.append(f"comp:{name}({result})")
        return _c

    def boom() -> str:
        order.append("fwd:c-raises")
        raise RuntimeError("step c failed")

    with pytest.raises(SagaError) as ei:
        run_saga([
            SagaStep("a", fwd("a"), comp("a")),
            SagaStep("b", fwd("b"), comp("b")),
            SagaStep("c", boom, comp("c")),
        ])

    # Forward ran a, b, then c raised; compensation is LIFO over COMPLETED steps
    # (a, b) only — c never completed so it is not compensated.
    assert order == [
        "fwd:a",
        "fwd:b",
        "fwd:c-raises",
        "comp:b(id-b)",
        "comp:a(id-a)",
    ]
    err = ei.value
    assert err.failed_step == "c"
    assert err.compensated_steps == ["b", "a"]
    assert err.compensation_errors == []
    assert isinstance(err.original, RuntimeError)
    assert "step c failed" in str(err.original)


def test_steps_without_compensator_are_skipped_during_rollback() -> None:
    order: list[str] = []

    def rec(label: str, *, raises: bool = False):
        def _f():
            order.append(label)
            if raises:
                raise ValueError("fail")
            return label
        return _f

    with pytest.raises(SagaError) as ei:
        run_saga([
            SagaStep("read", rec("fwd:read")),  # no compensator (read-only)
            SagaStep("write", rec("fwd:write"), lambda r: order.append("comp:write")),
            SagaStep("publish", rec("fwd:publish", raises=True), lambda r: order.append("comp:publish")),
        ])

    assert order == ["fwd:read", "fwd:write", "fwd:publish", "comp:write"]
    assert ei.value.compensated_steps == ["write"]


def test_compensation_errors_are_collected_not_raised() -> None:
    def bad_comp(_r):
        raise RuntimeError("compensation blew up")

    with pytest.raises(SagaError) as ei:
        run_saga([
            SagaStep("a", lambda: "ra", bad_comp),
            SagaStep("b", lambda: (_ for _ in ()).throw(KeyError("b failed"))),
        ])

    err = ei.value
    assert err.failed_step == "b"
    # 'a' had a compensator that itself failed → recorded, not in compensated_steps
    assert err.compensated_steps == []
    assert len(err.compensation_errors) == 1
    assert "a: compensation blew up" in err.compensation_errors[0]
    # original cause preserved despite the compensation error
    assert isinstance(err.original, KeyError)


def test_first_step_failure_has_nothing_to_compensate() -> None:
    with pytest.raises(SagaError) as ei:
        run_saga([
            SagaStep("a", lambda: (_ for _ in ()).throw(RuntimeError("immediate"))),
            SagaStep("b", lambda: "rb", lambda r: None),
        ])
    err = ei.value
    assert err.failed_step == "a"
    assert err.compensated_steps == []
    assert "no completed steps to compensate" in str(err)
