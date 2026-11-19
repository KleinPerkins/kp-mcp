"""Tests for editorial.py lint rules A–D."""

from pathlib import Path

import pytest

from kp_mcp_testkit.editorial import lint_file, lint_paths


def write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestRuleA_CommentedOutCode:
    def test_clean_py_no_violations(self, tmp_path: Path) -> None:
        p = write(tmp_path, "clean.py", "x = 1\n# a normal comment\ny = 2\n")
        assert lint_file(p) == []

    def test_two_consecutive_parseable_comments_flagged(self, tmp_path: Path) -> None:
        content = "# x = 1\n# y = 2\n"
        p = write(tmp_path, "bad.py", content)
        violations = lint_file(p)
        assert any(v.rule == "A" for v in violations)

    def test_single_comment_line_not_flagged(self, tmp_path: Path) -> None:
        p = write(tmp_path, "ok.py", "# x = 1\ndef foo(): pass\n")
        violations = [v for v in lint_file(p) if v.rule == "A"]
        assert violations == []

    def test_three_consecutive_parseable_comments_flagged(self, tmp_path: Path) -> None:
        content = "# a = 1\n# b = 2\n# c = 3\n"
        p = write(tmp_path, "block.py", content)
        violations = lint_file(p)
        assert any(v.rule == "A" for v in violations)

    def test_non_parseable_comment_run_not_flagged(self, tmp_path: Path) -> None:
        content = "# This is a description\n# of the algorithm below\n"
        p = write(tmp_path, "prose.py", content)
        violations = [v for v in lint_file(p) if v.rule == "A"]
        assert violations == []

    def test_shebang_not_flagged(self, tmp_path: Path) -> None:
        content = "#!/usr/bin/env python3\n# normal comment\nx = 1\n"
        p = write(tmp_path, "shebang.py", content)
        violations = [v for v in lint_file(p) if v.rule == "A"]
        assert violations == []


class TestRuleB_DuplicateHeadings:
    def test_clean_md_no_violations(self, tmp_path: Path) -> None:
        p = write(tmp_path, "clean.md", "# Title\n## Section A\n## Section B\n")
        assert lint_file(p) == []

    def test_duplicate_heading_flagged(self, tmp_path: Path) -> None:
        content = "# Title\n## Section\nsome text\n## Section\nmore text\n"
        p = write(tmp_path, "dup.md", content)
        violations = [v for v in lint_file(p) if v.rule == "B"]
        assert len(violations) == 1

    def test_headings_in_code_block_ignored(self, tmp_path: Path) -> None:
        content = "# Real\n```\n# Fake heading inside code\n# Fake heading inside code\n```\n"
        p = write(tmp_path, "code.md", content)
        violations = [v for v in lint_file(p) if v.rule == "B"]
        assert violations == []

    def test_case_insensitive_duplicate_flagged(self, tmp_path: Path) -> None:
        content = "# My Section\n## content\n# my section\n"
        p = write(tmp_path, "case.md", content)
        violations = [v for v in lint_file(p) if v.rule == "B"]
        assert len(violations) == 1


class TestRuleC_StalePhrases:
    def test_see_updated_section_flagged_md(self, tmp_path: Path) -> None:
        p = write(tmp_path, "stale.md", "See updated section for details.\n")
        violations = [v for v in lint_file(p) if v.rule == "C"]
        assert len(violations) >= 1

    def test_deprecated_below_flagged_md(self, tmp_path: Path) -> None:
        p = write(tmp_path, "dep.md", "This API is deprecated below.\n")
        violations = [v for v in lint_file(p) if v.rule == "C"]
        assert len(violations) >= 1

    def test_see_above_section_flagged_md(self, tmp_path: Path) -> None:
        p = write(tmp_path, "above.md", "See above section for context.\n")
        violations = [v for v in lint_file(p) if v.rule == "C"]
        assert len(violations) >= 1

    def test_superseded_in_heading_flagged_md(self, tmp_path: Path) -> None:
        p = write(tmp_path, "sup.md", "## Old Section (superseded)\nsome content\n")
        violations = [v for v in lint_file(p) if v.rule == "C"]
        assert len(violations) >= 1

    def test_superseded_in_table_not_flagged(self, tmp_path: Path) -> None:
        p = write(tmp_path, "table.md", "| op | note |\n| gdoc-fetch | migration note |\n")
        violations = [v for v in lint_file(p) if v.rule == "C"]
        assert violations == []

    def test_clean_file_no_stale(self, tmp_path: Path) -> None:
        p = write(tmp_path, "clean.md", "# Title\nContent here.\n")
        violations = [v for v in lint_file(p) if v.rule == "C"]
        assert violations == []


class TestRuleD_LineBudget:
    def test_under_budget_ok(self, tmp_path: Path) -> None:
        p = write(tmp_path, "small.py", "x = 1\n" * 10)
        violations = lint_file(p, budget=20)
        assert all(v.rule != "D" for v in violations)

    def test_over_budget_flagged(self, tmp_path: Path) -> None:
        p = write(tmp_path, "big.py", "x = 1\n" * 101)
        violations = lint_file(p, budget=100)
        assert any(v.rule == "D" for v in violations)


class TestSkipsNonTargetFiles:
    def test_json_file_skipped(self, tmp_path: Path) -> None:
        p = write(tmp_path, "data.json", '{"key": "value"}')
        assert lint_file(p) == []

    def test_txt_file_skipped(self, tmp_path: Path) -> None:
        p = write(tmp_path, "notes.txt", "See updated section\n")
        assert lint_file(p) == []


class TestLintPaths:
    def test_recursive_scan(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        write(sub, "dup.md", "# H\n## H\n# H\n")
        violations = lint_paths([tmp_path])
        assert any(v.rule == "B" for v in violations)

    def test_clean_dir_no_violations(self, tmp_path: Path) -> None:
        write(tmp_path, "ok.py", "def foo():\n    pass\n")
        write(tmp_path, "ok.md", "# Title\nContent.\n")
        violations = lint_paths([tmp_path])
        assert violations == []
