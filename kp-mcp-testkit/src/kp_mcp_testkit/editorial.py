"""Editorial lint enforcing R29 discipline.

Rules enforced:
  A  No commented-out code blocks in .py files (heuristic: ≥2 consecutive
     comment lines whose stripped bodies are valid Python per ast.parse).
  B  No duplicate headings within a .md file.
  C  No stale-redirect phrases in any file:
       'see updated section', 'deprecated below', 'see above section',
       and the word 'superseded' appearing in a heading line.
  D  Per-file line-count budget (default 2000, configurable via --budget).

CLI: python -m kp_mcp_testkit.editorial <path...> [--budget N]
Exit: 0 if clean, 1 if any violation found.
"""

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Violation:
    """A single editorial lint violation."""

    path: Path
    rule: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


_STALE_PHRASES: list[tuple[str, re.Pattern[str]]] = [
    ("see updated section", re.compile(r"see\s+updated\s+section", re.IGNORECASE)),
    ("deprecated below", re.compile(r"deprecated\s+below", re.IGNORECASE)),
    ("see above section", re.compile(r"see\s+above\s+section", re.IGNORECASE)),
]

_SUPERSEDED_IN_HEADING = re.compile(r"superseded", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s")


def _parsed_comment_run_looks_like_code(tree: ast.Module) -> bool:
    """Filter out prose labels that Python parses as bare-name expressions."""
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Name, ast.Constant)):
            continue
        return True
    return False


def _is_code_fence_delimiter(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def _check_commented_out_code(path: Path, lines: list[str]) -> list[Violation]:
    """Rule A: flag runs of ≥2 consecutive comment lines parseable as Python code."""
    violations: list[Violation] = []
    run: list[tuple[int, str]] = []

    def _flush_run() -> None:
        if len(run) < 2:
            run.clear()
            return
        body = "\n".join(body for _, body in run)
        try:
            tree = ast.parse(body)
            if _parsed_comment_run_looks_like_code(tree):
                start_line = run[0][0]
                violations.append(
                    Violation(
                        path=path,
                        rule="A",
                        line=start_line,
                        message=(
                            f"{len(run)}-line commented-out code block "
                            f"(lines {run[0][0]}–{run[-1][0]}). "
                            "Remove by subtraction; use NotImplementedError for deferred behavior."
                        ),
                    )
                )
        except SyntaxError:
            pass
        run.clear()

    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.lstrip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            body = stripped[1:].strip()
            if body:
                run.append((lineno, body))
                continue
        _flush_run()

    _flush_run()
    return violations


def _heading_depth(raw: str) -> int:
    """Return the depth (1-6) of a heading line, or 0 if not a heading."""
    m = re.match(r"^(#{1,6})\s", raw)
    return len(m.group(1)) if m else 0


def _check_duplicate_headings(path: Path, lines: list[str]) -> list[Violation]:
    """Rule B: flag duplicate heading text within the same parent section.

    Headings of depth D reset the duplicate-detection context for all
    headings of depth > D, so the same H3 name used in different H2 sections
    is not flagged — only a genuine repeat within the same section.
    """
    violations: list[Violation] = []
    in_code_block = False

    seen_at_depth: dict[int, dict[str, int]] = {}

    for lineno, raw in enumerate(lines, start=1):
        if _is_code_fence_delimiter(raw):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        depth = _heading_depth(raw)
        if depth == 0:
            continue

        for d in list(seen_at_depth.keys()):
            if d > depth:
                del seen_at_depth[d]

        text = raw.lstrip("#").strip().lower()
        bucket = seen_at_depth.setdefault(depth, {})

        if text in bucket:
            violations.append(
                Violation(
                    path=path,
                    rule="B",
                    line=lineno,
                    message=(
                        f"Duplicate heading {raw.strip()!r} within the same section "
                        f"(first occurrence at line {bucket[text]})."
                    ),
                )
            )
        else:
            bucket[text] = lineno

    return violations


_QUOTED_PHRASE_RE = re.compile(r'["`\']([^"`\']*)["`\']')


def _strip_quoted_spans(line: str) -> str:
    """Remove text inside backtick code spans, double-quoted, or single-quoted strings.

    Used to avoid flagging phrases that appear as quoted examples or string
    literals rather than live stale-redirect text.
    """
    return _QUOTED_PHRASE_RE.sub("", line)


def _check_stale_phrases(path: Path, lines: list[str]) -> list[Violation]:
    """Rule C: flag stale-redirect phrases and superseded headings.

    For .md files: skip phrases that appear inside quoted spans (backtick,
    double-quote, single-quote) to avoid false positives on meta-references.

    For .py files: only inspect single-line comment content (lines starting
    with #), not string literals or docstrings.
    """
    violations: list[Violation] = []
    in_code_block = False
    is_py = path.suffix.lower() == ".py"

    for lineno, raw in enumerate(lines, start=1):
        if _is_code_fence_delimiter(raw):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        stripped = raw.lstrip()

        if is_py:
            if not (stripped.startswith("#") and not stripped.startswith("#!")):
                continue
            scan_line = stripped[1:].strip()
        else:
            scan_line = _strip_quoted_spans(raw)

        for label, pattern in _STALE_PHRASES:
            if pattern.search(scan_line):
                violations.append(
                    Violation(
                        path=path,
                        rule="C",
                        line=lineno,
                        message=f"Stale-redirect phrase {label!r} found.",
                    )
                )

        if _HEADING_RE.match(raw) and _SUPERSEDED_IN_HEADING.search(raw):
            violations.append(
                Violation(
                    path=path,
                    rule="C",
                    line=lineno,
                    message=f"Heading contains 'superseded': {raw.strip()!r}.",
                )
            )

    return violations


def _check_line_budget(path: Path, lines: list[str], budget: int) -> list[Violation]:
    """Rule D: flag files exceeding the line-count budget."""
    count = len(lines)
    if count > budget:
        return [
            Violation(
                path=path,
                rule="D",
                line=count,
                message=f"File has {count} lines; budget is {budget}.",
            )
        ]
    return []


def lint_file(path: Path, budget: int = 2000) -> list[Violation]:
    """Run all applicable rules on a single file.

    Args:
        path: File to lint (.py or .md; others are skipped silently).
        budget: Maximum allowed line count (rule D).

    Returns:
        List of Violation objects; empty if clean.
    """
    suffix = path.suffix.lower()
    if suffix not in (".py", ".md"):
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    lines = text.splitlines()
    violations: list[Violation] = []

    if suffix == ".py":
        violations += _check_commented_out_code(path, lines)
        violations += _check_stale_phrases(path, lines)
        violations += _check_line_budget(path, lines, budget)

    if suffix == ".md":
        violations += _check_duplicate_headings(path, lines)
        violations += _check_stale_phrases(path, lines)
        violations += _check_line_budget(path, lines, budget)

    return violations


def lint_paths(paths: list[Path], budget: int = 2000) -> list[Violation]:
    """Recursively lint all .py and .md files under the given paths.

    Args:
        paths: Files or directories to scan.
        budget: Per-file line-count budget.

    Returns:
        All violations found, sorted by (path, line).
    """
    all_violations: list[Violation] = []

    for root in paths:
        if root.is_file():
            all_violations += lint_file(root, budget=budget)
        elif root.is_dir():
            for file in sorted(root.rglob("*")):
                if file.is_file():
                    all_violations += lint_file(file, budget=budget)

    all_violations.sort(key=lambda v: (str(v.path), v.line))
    return all_violations


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Usage: python -m kp_mcp_testkit.editorial <path...> [--budget N]

    Returns:
        0 if no violations; 1 otherwise.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m kp_mcp_testkit.editorial",
        description="Editorial lint: R29 discipline checks for .py and .md files.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="Files or directories to lint.",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=2000,
        metavar="N",
        help="Per-file line-count budget (default: 2000).",
    )

    args = parser.parse_args(argv)
    resolved = [Path(p) for p in args.paths]
    violations = lint_paths(resolved, budget=args.budget)

    for v in violations:
        print(v, file=sys.stderr)

    if violations:
        print(
            f"\neditorial: {len(violations)} violation(s) found.",
            file=sys.stderr,
        )
        return 1

    print("editorial: clean.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
