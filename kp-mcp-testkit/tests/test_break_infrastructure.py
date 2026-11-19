"""Adversarial regression tests for kp_mcp_testkit infrastructure."""

from __future__ import annotations

import re

import pytest

from kp_mcp_testkit import faults as faults_mod
from kp_mcp_testkit.doc_runner import DocRunner, DocRunnerResult
from kp_mcp_testkit.editorial import lint_file
from kp_mcp_testkit.faults import inject_fault, inject_fault_fn
from kp_mcp_testkit.parity import compare
from kp_mcp_testkit.sandbox import sandbox_profile


def test_break_editorial_does_not_flag_bare_comment_labels(tmp_path) -> None:
    path = tmp_path / "labels.py"
    path.write_text("# TODO\n# FIXME\nvalue = 1\n", encoding="utf-8")

    assert [v for v in lint_file(path) if v.rule == "A"] == []


def test_break_mutation_request_preserves_list_order() -> None:
    expected = {"requests": [{"insertText": {"text": "a"}}, {"insertText": {"text": "b"}}]}
    actual = {"requests": [{"insertText": {"text": "b"}}, {"insertText": {"text": "a"}}]}

    result = compare("mutation-request", expected, actual)

    assert result.match is False
    assert result.diff


def test_break_inject_fault_passes_through_and_restores(monkeypatch) -> None:
    calls: list[int] = []

    def original(value: int) -> int:
        calls.append(value)
        return value + 1

    monkeypatch.setattr(faults_mod, "_break_dummy", original, raising=False)

    with inject_fault("kp_mcp_testkit.faults._break_dummy", TimeoutError, "boom", after_calls=1):
        assert faults_mod._break_dummy(1) == 2
        with pytest.raises(TimeoutError, match="boom"):
            faults_mod._break_dummy(2)

    assert faults_mod._break_dummy(3) == 4
    assert calls == [1, 3]


def test_break_inject_fault_rejects_negative_after_calls() -> None:
    with pytest.raises(ValueError, match="after_calls"):
        with inject_fault_fn(lambda: None, RuntimeError, after_calls=-1):
            pass


def test_break_doc_runner_malformed_suite_raises_value_error() -> None:
    runner = DocRunner(
        run_agent=lambda task_id, context_paths, task: DocRunnerResult(
            task_id=task_id,
            success=True,
        )
    )

    with pytest.raises(ValueError, match=re.escape("suite[0]")):
        runner.run_suite([{"task_id": "missing-context", "task": "Do it"}])


def test_break_doc_runner_until_pass_rejects_invalid_max_iterations() -> None:
    runner = DocRunner(
        run_agent=lambda task_id, context_paths, task: DocRunnerResult(
            task_id=task_id,
            success=True,
        )
    )

    with pytest.raises(ValueError, match="max_iterations"):
        runner.run_suite_until_pass([], max_iterations=0)


def test_break_sandbox_blank_profile_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_KIT_SANDBOX_PROFILE", "   ")

    assert sandbox_profile() == "sandbox"
