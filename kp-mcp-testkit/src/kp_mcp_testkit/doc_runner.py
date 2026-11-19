"""Subagent doc-comprehension runner harness.

Phase 7 empirical doc-validation loop (R28, B13).

Design: DocRunner is a pure harness. It does NOT spawn live agents itself.
The orchestrator injects a ``run_agent`` callable at construction time, which
is what actually invokes a read-only subagent given a task. This allows the
harness to be unit-tested with a fake runner (no network, no LLM calls).

Injected seam signature::

    run_agent(task_id: str, context_paths: list[str], task: str) -> DocRunnerResult

When ``run_agent`` is not injected (``None``), every call raises
``RuntimeError("inject an agent runner (orchestrator provides the live one)")``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class DocRunnerResult:
    """Outcome of one subagent doc-comprehension task."""

    task_id: str
    success: bool
    clarifying_questions: int = 0
    doc_induced_errors: int = 0
    tokens_to_completion: int = 0
    friction_log: list[str] = field(default_factory=list)


@dataclass
class SuiteResult:
    """Aggregate outcome of a full doc-suite run."""

    iteration: int
    results: list[DocRunnerResult]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    @property
    def total_clarifying_questions(self) -> int:
        return sum(r.clarifying_questions for r in self.results)

    @property
    def friction_log(self) -> list[str]:
        """All friction points across every task, tagged with task_id."""
        out: list[str] = []
        for r in self.results:
            for entry in r.friction_log:
                out.append(f"[{r.task_id}] {entry}")
        return out

    def failed_ids(self) -> list[str]:
        return [r.task_id for r in self.results if not r.success]


class DocRunner:
    """Runs the doc-comprehension task suite against an injected agent runner.

    The runner itself is a harness — it never spawns live agents.  The
    orchestrator provides a ``run_agent`` callable that wraps whatever agent
    framework is in use for P7 empirical validation (R28).

    Args:
        run_agent: Callable with signature
            ``(task_id, context_paths, task) -> DocRunnerResult``.
            Pass ``None`` (default) to get an explicit error on first use,
            which acts as a reminder to inject the live runner.
    """

    def __init__(
        self,
        run_agent: Callable[[str, list[str], str], DocRunnerResult] | None = None,
    ) -> None:
        self._run_agent = run_agent

    @staticmethod
    def _validate_suite_entry(entry: dict[str, Any], index: int) -> tuple[str, list[str], str]:
        required = ("task_id", "context_paths", "task")
        missing = [key for key in required if key not in entry]
        if missing:
            raise ValueError(f"suite[{index}] missing required field(s): {', '.join(missing)}")

        task_id = entry["task_id"]
        context_paths = entry["context_paths"]
        task = entry["task"]
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"suite[{index}].task_id must be a non-empty string")
        if (
            not isinstance(context_paths, list)
            or not all(isinstance(path, str) for path in context_paths)
        ):
            raise ValueError(f"suite[{index}].context_paths must be a list of strings")
        if not isinstance(task, str) or not task:
            raise ValueError(f"suite[{index}].task must be a non-empty string")
        return task_id, context_paths, task

    def run_task(self, task_id: str, context_paths: list[str], task: str) -> DocRunnerResult:
        """Run a single doc-comprehension task via the injected runner.

        Args:
            task_id: Unique identifier for the task in the suite.
            context_paths: Doc paths the subagent is given as its only context
                (e.g. ``["google-kit/docs/INDEX.md"]``).
            task: Natural-language task description.

        Returns:
            DocRunnerResult capturing success, friction points, and metrics.

        Raises:
            RuntimeError: If no ``run_agent`` was injected at construction.
        """
        if self._run_agent is None:
            raise RuntimeError(
                "inject an agent runner (orchestrator provides the live one)"
            )
        return self._run_agent(task_id, context_paths, task)

    def run_suite(
        self,
        suite: list[dict[str, Any]],
        max_iterations: int = 25,
    ) -> SuiteResult:
        """Run the full task suite up to max_iterations, tracking results.

        Each suite entry must have keys: ``task_id``, ``context_paths``, ``task``.

        The method runs all tasks in a single iteration and returns the
        SuiteResult from that iteration.  The orchestrator decides whether to
        apply doc fixes and re-run based on the result (B13: 100% success or
        25-iteration cap); DocRunner records but does not mutate docs itself.

        Args:
            suite: List of task dicts with keys: task_id, context_paths, task.
            max_iterations: Hard cap per R28/B13.  Iteration counter is
                passed to the caller in SuiteResult so the orchestrator can
                enforce the cap across multiple ``run_suite`` calls.

        Returns:
            SuiteResult for the run, with per-task DocRunnerResults.

        Raises:
            RuntimeError: If no ``run_agent`` was injected at construction.
            ValueError: If ``max_iterations`` < 1 or a suite entry is malformed.
        """
        if self._run_agent is None:
            raise RuntimeError(
                "inject an agent runner (orchestrator provides the live one)"
            )
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")

        results: list[DocRunnerResult] = []
        for index, entry in enumerate(suite):
            task_id, context_paths, task = self._validate_suite_entry(entry, index)
            result = self.run_task(task_id, context_paths, task)
            results.append(result)

        return SuiteResult(iteration=1, results=results)

    def run_suite_until_pass(
        self,
        suite: list[dict[str, Any]],
        *,
        max_iterations: int = 25,
    ) -> list[SuiteResult]:
        """Run suite repeatedly until all tasks pass or max_iterations is reached.

        Between iterations the orchestrator should apply doc fixes; this method
        drives the loop mechanically, delegating doc edits to the caller via the
        returned history.

        Returns:
            List of SuiteResult, one per iteration.  The last entry is the
            final state.  If all tasks pass before the cap, the list is shorter
            than max_iterations.
        """
        if self._run_agent is None:
            raise RuntimeError(
                "inject an agent runner (orchestrator provides the live one)"
            )
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")
        history: list[SuiteResult] = []
        for i in range(1, max_iterations + 1):
            sr = self.run_suite(suite, max_iterations=max_iterations)
            sr.iteration = i
            history.append(sr)
            if sr.all_passed:
                break
        return history
