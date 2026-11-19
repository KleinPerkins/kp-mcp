"""Unit tests for the DocRunner harness.

All tests use a fake ``run_agent`` callable — no live agents, no network.
Covers: injected-seam enforcement, suite bookkeeping, max_iterations cap,
pass/fail aggregation, friction_log collation, SuiteResult properties.
"""
from __future__ import annotations

import pytest

from kp_mcp_testkit.doc_runner import DocRunner, DocRunnerResult, SuiteResult


# ---------------------------------------------------------------------------
# Fake agent runner
# ---------------------------------------------------------------------------

def _always_pass(task_id: str, context_paths: list[str], task: str) -> DocRunnerResult:
    return DocRunnerResult(task_id=task_id, success=True, tokens_to_completion=100)


def _always_fail(task_id: str, context_paths: list[str], task: str) -> DocRunnerResult:
    return DocRunnerResult(
        task_id=task_id,
        success=False,
        clarifying_questions=2,
        doc_induced_errors=1,
        friction_log=["ambiguous install step"],
    )


def _selective_fail(fail_ids: set[str]):
    """Return a runner that fails for specific task_ids."""
    def _run(task_id: str, context_paths: list[str], task: str) -> DocRunnerResult:
        if task_id in fail_ids:
            return DocRunnerResult(
                task_id=task_id, success=False, friction_log=[f"{task_id}: unclear"]
            )
        return DocRunnerResult(task_id=task_id, success=True)
    return _run


_MINIMAL_SUITE = [
    {"task_id": "t1", "context_paths": ["docs/INDEX.md"], "task": "Install google-kit"},
    {"task_id": "t2", "context_paths": ["docs/INDEX.md"], "task": "Run auth login"},
    {"task_id": "t3", "context_paths": ["docs/INDEX.md"], "task": "Fetch a Drive file"},
]


# ---------------------------------------------------------------------------
# Injected-seam enforcement
# ---------------------------------------------------------------------------

class TestNoRunnerRaises:
    def test_run_task_raises_without_runner(self):
        dr = DocRunner()
        with pytest.raises(RuntimeError, match="inject an agent runner"):
            dr.run_task("t1", ["docs/INDEX.md"], "do something")

    def test_run_suite_raises_without_runner(self):
        dr = DocRunner()
        with pytest.raises(RuntimeError, match="inject an agent runner"):
            dr.run_suite(_MINIMAL_SUITE)

    def test_run_suite_until_pass_raises_without_runner(self):
        dr = DocRunner()
        with pytest.raises(RuntimeError, match="inject an agent runner"):
            dr.run_suite_until_pass(_MINIMAL_SUITE)

    def test_error_message_exact(self):
        dr = DocRunner()
        with pytest.raises(RuntimeError) as exc:
            dr.run_task("t1", [], "task")
        assert "inject an agent runner" in str(exc.value)
        assert "orchestrator" in str(exc.value)


# ---------------------------------------------------------------------------
# run_task
# ---------------------------------------------------------------------------

class TestRunTask:
    def test_returns_result_with_correct_task_id(self):
        dr = DocRunner(run_agent=_always_pass)
        result = dr.run_task("install-bootstrap", ["docs/INDEX.md"], "Install google-kit")
        assert result.task_id == "install-bootstrap"
        assert result.success is True

    def test_passes_context_paths_to_runner(self):
        received: list = []

        def _capture(task_id, context_paths, task):
            received.append(context_paths)
            return DocRunnerResult(task_id=task_id, success=True)

        dr = DocRunner(run_agent=_capture)
        dr.run_task("t1", ["google-kit/docs/INDEX.md", "google-kit/docs/QUICKSTART.md"], "task")
        assert received[0] == ["google-kit/docs/INDEX.md", "google-kit/docs/QUICKSTART.md"]

    def test_failing_result_preserved(self):
        dr = DocRunner(run_agent=_always_fail)
        result = dr.run_task("t1", ["docs/INDEX.md"], "bad task")
        assert result.success is False
        assert result.clarifying_questions == 2
        assert result.doc_induced_errors == 1
        assert "ambiguous install step" in result.friction_log


# ---------------------------------------------------------------------------
# run_suite — bookkeeping
# ---------------------------------------------------------------------------

class TestRunSuiteBookkeeping:
    def test_all_tasks_run(self):
        dr = DocRunner(run_agent=_always_pass)
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert sr.total == 3
        ids = {r.task_id for r in sr.results}
        assert ids == {"t1", "t2", "t3"}

    def test_suite_order_preserved(self):
        dr = DocRunner(run_agent=_always_pass)
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert [r.task_id for r in sr.results] == ["t1", "t2", "t3"]

    def test_empty_suite(self):
        dr = DocRunner(run_agent=_always_pass)
        sr = dr.run_suite([])
        assert sr.total == 0
        assert sr.all_passed

    def test_iteration_number_set(self):
        dr = DocRunner(run_agent=_always_pass)
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert sr.iteration == 1


# ---------------------------------------------------------------------------
# run_suite — pass/fail aggregation
# ---------------------------------------------------------------------------

class TestRunSuiteAggregation:
    def test_all_pass(self):
        dr = DocRunner(run_agent=_always_pass)
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert sr.all_passed
        assert sr.passed == 3
        assert sr.failed == 0

    def test_all_fail(self):
        dr = DocRunner(run_agent=_always_fail)
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert not sr.all_passed
        assert sr.failed == 3
        assert sr.passed == 0

    def test_partial_fail(self):
        dr = DocRunner(run_agent=_selective_fail({"t1", "t3"}))
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert sr.passed == 1
        assert sr.failed == 2
        assert set(sr.failed_ids()) == {"t1", "t3"}

    def test_total_clarifying_questions(self):
        def _runner(task_id, ctx, task):
            return DocRunnerResult(task_id=task_id, success=True, clarifying_questions=3)

        dr = DocRunner(run_agent=_runner)
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert sr.total_clarifying_questions == 9


# ---------------------------------------------------------------------------
# run_suite — friction_log collation
# ---------------------------------------------------------------------------

class TestFrictionLogCollation:
    def test_friction_tagged_with_task_id(self):
        dr = DocRunner(run_agent=_always_fail)
        sr = dr.run_suite([{"task_id": "install-bootstrap", "context_paths": [], "task": "t"}])
        assert any("install-bootstrap" in entry for entry in sr.friction_log)

    def test_friction_from_multiple_tasks_merged(self):
        def _runner(task_id, ctx, task):
            return DocRunnerResult(
                task_id=task_id, success=False, friction_log=[f"gap in {task_id}"]
            )

        dr = DocRunner(run_agent=_runner)
        sr = dr.run_suite(_MINIMAL_SUITE)
        log = sr.friction_log
        assert len(log) == 3
        for entry in log:
            assert "gap in" in entry

    def test_no_friction_when_all_pass(self):
        dr = DocRunner(run_agent=_always_pass)
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert sr.friction_log == []


# ---------------------------------------------------------------------------
# run_suite_until_pass — max_iterations cap
# ---------------------------------------------------------------------------

class TestMaxIterationsCap:
    def test_cap_honored_when_always_fail(self):
        dr = DocRunner(run_agent=_always_fail)
        history = dr.run_suite_until_pass(_MINIMAL_SUITE, max_iterations=3)
        assert len(history) == 3
        assert all(not sr.all_passed for sr in history)

    def test_stops_early_when_all_pass(self):
        dr = DocRunner(run_agent=_always_pass)
        history = dr.run_suite_until_pass(_MINIMAL_SUITE, max_iterations=25)
        assert len(history) == 1
        assert history[0].all_passed

    def test_iteration_numbers_sequential(self):
        call_count = 0

        def _fail_then_pass(task_id, ctx, task):
            nonlocal call_count
            call_count += 1
            success = call_count > len(_MINIMAL_SUITE)
            return DocRunnerResult(task_id=task_id, success=success)

        dr = DocRunner(run_agent=_fail_then_pass)
        history = dr.run_suite_until_pass(_MINIMAL_SUITE, max_iterations=5)
        for i, sr in enumerate(history, start=1):
            assert sr.iteration == i

    def test_invalid_max_iterations_raises(self):
        dr = DocRunner(run_agent=_always_pass)
        with pytest.raises(ValueError, match="max_iterations"):
            dr.run_suite(_MINIMAL_SUITE, max_iterations=0)

    def test_b13_cap_default_is_25(self):
        import inspect
        sig = inspect.signature(DocRunner.run_suite)
        assert sig.parameters["max_iterations"].default == 25


# ---------------------------------------------------------------------------
# SuiteResult properties
# ---------------------------------------------------------------------------

class TestSuiteResultProperties:
    def test_failed_ids_empty_when_all_pass(self):
        dr = DocRunner(run_agent=_always_pass)
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert sr.failed_ids() == []

    def test_failed_ids_correct(self):
        dr = DocRunner(run_agent=_selective_fail({"t2"}))
        sr = dr.run_suite(_MINIMAL_SUITE)
        assert sr.failed_ids() == ["t2"]
