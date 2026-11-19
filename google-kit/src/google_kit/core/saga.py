"""LIFO saga executor for multi-API composition recipes (architecture brief §4 + §6).

Google Workspace exposes no cross-API transaction: a recipe that creates a Doc
and then shares it issues two independent API calls, and the second can fail
after the first has already mutated state. ``run_saga`` sequences a list of
:class:`SagaStep` forward actions in order; on the first failure it invokes the
recorded compensations of the already-completed steps in **LIFO** order (the
last step to complete is the first to be undone), best-effort, and then raises
:class:`SagaError` carrying the original cause plus the compensation outcome.

The executor is pure and service-injectable: a step's ``forward`` and
``compensate`` are plain zero-/one-argument callables, so recipes inject their
already-bound API calls and tests inject ordering-recorder lambdas — no network,
no global state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

ForwardFn = Callable[[], Any]
CompensateFn = Callable[[Any], Any]


@dataclass
class SagaStep:
    """One step in a saga.

    Attributes:
        name:       Stable identifier used in meta/warnings (e.g. ``"create_doc"``).
        forward:    Zero-arg callable performing the step; its return value is
                    passed to ``compensate`` if a later step fails.
        compensate: Optional one-arg callable that undoes ``forward`` given its
                    result. ``None`` for read-only or terminal steps that need no
                    rollback.
    """

    name: str
    forward: ForwardFn
    compensate: CompensateFn | None = None


@dataclass
class SagaOutcome:
    """Result of a fully-successful saga run."""

    results: list[Any]
    compensated: bool = False
    failed_step: str | None = None
    compensated_steps: list[str] | None = None
    compensation_errors: list[str] | None = None


class SagaError(RuntimeError):
    """Raised when a saga step fails, after LIFO compensation has run.

    Attributes:
        failed_step:          Name of the step whose ``forward`` raised.
        original:             The exception raised by the failed step.
        compensated_steps:    Names of steps successfully compensated, in the
                              LIFO order they were undone.
        compensation_errors:  ``"<step>: <error>"`` for any compensation that
                              itself failed (best-effort; never masks ``original``).
    """

    def __init__(
        self,
        *,
        failed_step: str,
        original: BaseException,
        compensated_steps: list[str],
        compensation_errors: list[str],
    ) -> None:
        self.failed_step = failed_step
        self.original = original
        self.compensated_steps = compensated_steps
        self.compensation_errors = compensation_errors
        if compensated_steps:
            comp = f"compensated {compensated_steps} (LIFO)"
        else:
            comp = "no completed steps to compensate"
        msg = f"saga failed at step {failed_step!r}: {original}; {comp}"
        if compensation_errors:
            msg += f"; compensation errors: {compensation_errors}"
        super().__init__(msg)


def run_saga(steps: list[SagaStep]) -> SagaOutcome:
    """Run ``steps`` forward in order; on failure compensate completed steps LIFO.

    Returns a :class:`SagaOutcome` with every forward result when all steps
    succeed. On the first failing step, compensations for the steps that already
    completed run in reverse (LIFO) order, best-effort, and a :class:`SagaError`
    is raised carrying the original cause and which steps were rolled back.

    Compensation failures are collected (not raised) so a single bad compensator
    cannot prevent the remaining ones from running or mask the original error.
    """
    completed: list[tuple[SagaStep, Any]] = []
    for step in steps:
        try:
            result = step.forward()
        except Exception as exc:  # noqa: BLE001 — saga boundary: compensate then re-raise
            compensated_steps, compensation_errors = _compensate(completed)
            raise SagaError(
                failed_step=step.name,
                original=exc,
                compensated_steps=compensated_steps,
                compensation_errors=compensation_errors,
            ) from exc
        completed.append((step, result))
    return SagaOutcome(results=[r for _, r in completed])


def _compensate(completed: list[tuple[SagaStep, Any]]) -> tuple[list[str], list[str]]:
    """Run compensations for ``completed`` steps in LIFO order, best-effort."""
    compensated_steps: list[str] = []
    compensation_errors: list[str] = []
    for step, result in reversed(completed):
        if step.compensate is None:
            continue
        try:
            step.compensate(result)
            compensated_steps.append(step.name)
        except Exception as cexc:  # noqa: BLE001 — best-effort rollback
            compensation_errors.append(f"{step.name}: {cexc}")
    return compensated_steps, compensation_errors
