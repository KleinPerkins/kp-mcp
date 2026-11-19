#!/usr/bin/env python3
"""
wave6_codemod.py — P8/Wave-6 bulk text reference migrator
Rewrites legacy google_auth invocation patterns → google-kit equivalents
in all doc/config/skill/rule/command text files.

Targets ~1,541 non-functional text references (comments, docs, Markdown, YAML/TOML configs,
shell scripts, skill/rule files). Does NOT touch Python import/call sites (those are Waves 1-5).

Usage:
    python tools/wave6_codemod.py --dry-run --root /path/to/chaos-labs
    python tools/wave6_codemod.py --root /path/to/chaos-labs [--exts ext1,ext2] [--verbose]

Options:
    --root PATH       Root directory to scan (required)
    --dry-run         Preview changes without writing (default: False)
    --exts EXT,...    Comma-separated extra extensions to include
    --exclude DIRS    Comma-separated directory names to skip (default: .git,node_modules,__pycache__,.venv)
    --verbose         Print each change as it is applied
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Rewrite rules: (description, pattern, replacement)
# Applied in ORDER — earlier rules take precedence.
# Each rule is a (label, compiled_re, replacement_str) tuple.
# ---------------------------------------------------------------------------
RAW_RULES: list[tuple[str, str, str]] = [
    # ── Auth CLI ──────────────────────────────────────────────────────────
    (
        "auth-login: python scripts/refresh_google_oauth.py → google-kit auth login",
        r"python\s+(?:scripts/)?refresh_google_oauth\.py(?:\s+--force)?",
        "google-kit auth login",
    ),
    (
        "auth-login-force: refresh_google_oauth.py --force → google-kit auth login --force",
        r"python\s+(?:scripts/)?refresh_google_oauth\.py\s+--force",
        "google-kit auth login --force",
    ),
    (
        "auth-status: google_auth.status → google-kit auth status",
        r"\bgoogle_auth\.status\b",
        "google-kit auth status",
    ),
    (
        "auth-logout: google_auth.logout → google-kit auth logout",
        r"\bgoogle_auth\.logout\b",
        "google-kit auth logout",
    ),
    # ── Gmail ─────────────────────────────────────────────────────────────
    (
        "gmail-list: python scripts/gmail.py list → google-kit gmail list",
        r"python\s+scripts/gmail\.py\s+list",
        "google-kit gmail list",
    ),
    (
        "gmail-get: python scripts/gmail.py get → google-kit gmail get",
        r"python\s+scripts/gmail\.py\s+get",
        "google-kit gmail get",
    ),
    (
        "gmail-search: python scripts/gmail.py search → google-kit gmail search",
        r"python\s+scripts/gmail\.py\s+search",
        "google-kit gmail search",
    ),
    (
        "gmail-labels: python scripts/gmail.py labels → google-kit gmail labels",
        r"python\s+scripts/gmail\.py\s+labels",
        "google-kit gmail labels",
    ),
    (
        "gmail-profile: python scripts/gmail.py profile → google-kit gmail profile",
        r"python\s+scripts/gmail\.py\s+profile",
        "google-kit gmail profile",
    ),
    (
        "gmail-generic: python scripts/gmail.py → google-kit gmail",
        r"python\s+scripts/gmail\.py",
        "google-kit gmail",
    ),
    # ── Calendar ──────────────────────────────────────────────────────────
    (
        "calendar-list: python scripts/gcalendar.py list → google-kit calendar list",
        r"python\s+scripts/gcalendar\.py\s+list",
        "google-kit calendar list",
    ),
    (
        "calendar-freebusy: python scripts/gcalendar.py freebusy → google-kit calendar freebusy",
        r"python\s+scripts/gcalendar\.py\s+freebusy",
        "google-kit calendar freebusy",
    ),
    (
        "calendar-create: python scripts/gcalendar.py create → google-kit calendar create",
        r"python\s+scripts/gcalendar\.py\s+create",
        "google-kit calendar create",
    ),
    (
        "calendar-update: python scripts/gcalendar.py update → google-kit calendar update",
        r"python\s+scripts/gcalendar\.py\s+update",
        "google-kit calendar update",
    ),
    (
        "calendar-delete: python scripts/gcalendar.py delete → google-kit calendar delete",
        r"python\s+scripts/gcalendar\.py\s+delete",
        "google-kit calendar delete",
    ),
    (
        "calendar-generic: python scripts/gcalendar.py → google-kit calendar",
        r"python\s+scripts/gcalendar\.py",
        "google-kit calendar",
    ),
    # ── Drive ─────────────────────────────────────────────────────────────
    (
        "drive-fetch: python scripts/gdrive.py fetch → google-kit drive fetch",
        r"python\s+scripts/gdrive\.py\s+fetch",
        "google-kit drive fetch",
    ),
    (
        "drive-search: python scripts/gdrive.py search → google-kit drive search",
        r"python\s+scripts/gdrive\.py\s+search",
        "google-kit drive search",
    ),
    (
        "drive-upload: python scripts/gdrive.py upload → google-kit drive upload",
        r"python\s+scripts/gdrive\.py\s+upload",
        "google-kit drive upload",
    ),
    (
        "drive-create: python scripts/gdrive.py create → google-kit drive create",
        r"python\s+scripts/gdrive\.py\s+create",
        "google-kit drive create",
    ),
    (
        "drive-generic: python scripts/gdrive.py → google-kit drive",
        r"python\s+scripts/gdrive\.py",
        "google-kit drive",
    ),
    # ── Sheets ────────────────────────────────────────────────────────────
    (
        "sheets-read: python scripts/gsheets.py read → google-kit sheets read",
        r"python\s+scripts/gsheets\.py\s+read",
        "google-kit sheets read",
    ),
    (
        "sheets-write: python scripts/gsheets.py write → google-kit sheets write",
        r"python\s+scripts/gsheets\.py\s+write",
        "google-kit sheets write",
    ),
    (
        "sheets-create: python scripts/gsheets.py create → google-kit sheets create",
        r"python\s+scripts/gsheets\.py\s+create",
        "google-kit sheets create",
    ),
    (
        "sheets-info: python scripts/gsheets.py info → google-kit sheets info",
        r"python\s+scripts/gsheets\.py\s+info",
        "google-kit sheets info",
    ),
    (
        "sheets-add-sheet: python scripts/gsheets.py add-sheet → google-kit sheets add-sheet",
        r"python\s+scripts/gsheets\.py\s+add-sheet",
        "google-kit sheets add-sheet",
    ),
    (
        "sheets-chart: python scripts/gsheets.py chart → google-kit sheets chart",
        r"python\s+scripts/gsheets\.py\s+chart",
        "google-kit sheets chart",
    ),
    (
        "sheets-generic: python scripts/gsheets.py → google-kit sheets",
        r"python\s+scripts/gsheets\.py",
        "google-kit sheets",
    ),
    # ── Tasks ─────────────────────────────────────────────────────────────
    (
        "tasks-list-lists: python scripts/gtasks.py list-lists → google-kit tasks list-lists",
        r"python\s+scripts/gtasks\.py\s+list-lists",
        "google-kit tasks list-lists",
    ),
    (
        "tasks-list: python scripts/gtasks.py list → google-kit tasks list",
        r"python\s+scripts/gtasks\.py\s+list",
        "google-kit tasks list",
    ),
    (
        "tasks-create: python scripts/gtasks.py create → google-kit tasks create",
        r"python\s+scripts/gtasks\.py\s+create",
        "google-kit tasks create",
    ),
    (
        "tasks-complete: python scripts/gtasks.py complete → google-kit tasks complete",
        r"python\s+scripts/gtasks\.py\s+complete",
        "google-kit tasks complete",
    ),
    (
        "tasks-update: python scripts/gtasks.py update → google-kit tasks update",
        r"python\s+scripts/gtasks\.py\s+update",
        "google-kit tasks update",
    ),
    (
        "tasks-delete: python scripts/gtasks.py delete → google-kit tasks delete",
        r"python\s+scripts/gtasks\.py\s+delete",
        "google-kit tasks delete",
    ),
    (
        "tasks-generic: python scripts/gtasks.py → google-kit tasks",
        r"python\s+scripts/gtasks\.py",
        "google-kit tasks",
    ),
    # ── Keep ──────────────────────────────────────────────────────────────
    (
        "keep-list: python scripts/gkeep.py list → google-kit keep list",
        r"python\s+scripts/gkeep\.py\s+list",
        "google-kit keep list",
    ),
    (
        "keep-get: python scripts/gkeep.py get → google-kit keep get",
        r"python\s+scripts/gkeep\.py\s+get",
        "google-kit keep get",
    ),
    (
        "keep-create: python scripts/gkeep.py create → google-kit keep create",
        r"python\s+scripts/gkeep\.py\s+create",
        "google-kit keep create",
    ),
    (
        "keep-delete: python scripts/gkeep.py delete → google-kit keep delete",
        r"python\s+scripts/gkeep\.py\s+delete",
        "google-kit keep delete",
    ),
    (
        "keep-generic: python scripts/gkeep.py → google-kit keep",
        r"python\s+scripts/gkeep\.py",
        "google-kit keep",
    ),
    # ── Slides ────────────────────────────────────────────────────────────
    (
        "slides-generic: python scripts/gslides.py → google-kit slides",
        r"python\s+scripts/gslides\.py",
        "google-kit slides",
    ),
    # ── Forms ─────────────────────────────────────────────────────────────
    (
        "forms-generic: python scripts/gforms.py → google-kit forms",
        r"python\s+scripts/gforms\.py",
        "google-kit forms",
    ),
    # ── Docs / md-to-gdoc ─────────────────────────────────────────────────
    (
        "docs-from-markdown: python scripts/packages/md-to-google-doc/md_to_gdoc.py → google-kit docs from-markdown",
        r"python\s+scripts/packages/md-to-google-doc/md_to_gdoc\.py",
        "google-kit docs from-markdown",
    ),
    # ── staged_review_sheet ───────────────────────────────────────────────
    (
        "staged-review-sheet: python scripts/staged_review_sheet.py → google-kit sheets create",
        r"python\s+scripts/staged_review_sheet\.py",
        "google-kit sheets create",
    ),
    # ── Module reference cleanup ──────────────────────────────────────────
    (
        "google_auth module ref in text: google_auth → google-kit",
        r"(?<!\w)google_auth(?!\w)",
        "google-kit",
    ),
]

# Default file extensions to scan (non-Python text files)
DEFAULT_EXTENSIONS: frozenset[str] = frozenset({
    ".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json",
    ".sh", ".bash", ".zsh", ".fish", ".conf", ".cfg", ".ini",
    ".mdc", ".mdx",  # cursor rule / mdx docs
})

# Also scan Python files, but ONLY for comment/docstring lines
# (Wave 1-5 already handled import/call sites; we avoid double-touching)
PYTHON_EXTENSION = ".py"

DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    "dist", "build", ".eggs",
})


def compile_rules(
    raw: list[tuple[str, str, str]]
) -> list[tuple[str, re.Pattern[str], str]]:
    return [(label, re.compile(pat), repl) for label, pat, repl in raw]


RULES = compile_rules(RAW_RULES)


def _is_python_comment_or_docstring_line(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''")


def apply_rules_to_line(line: str, is_python: bool) -> tuple[str, list[str]]:
    """Return (rewritten_line, [applied_labels])."""
    if is_python and not _is_python_comment_or_docstring_line(line):
        return line, []
    changed_labels: list[str] = []
    for label, pat, repl in RULES:
        new_line, n = pat.subn(repl, line)
        if n:
            changed_labels.append(label)
            line = new_line
    return line, changed_labels


def iter_files(
    root: Path,
    extensions: frozenset[str],
    exclude_dirs: frozenset[str],
) -> Iterator[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in exclude_dirs for part in path.parts):
            continue
        if path.suffix in extensions or path.suffix == PYTHON_EXTENSION:
            yield path


def process_file(
    path: Path,
    dry_run: bool,
    verbose: bool,
) -> tuple[int, int]:
    """Returns (lines_changed, rules_triggered)."""
    is_python = path.suffix == PYTHON_EXTENSION
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        print(f"  SKIP {path}: {exc}", file=sys.stderr)
        return 0, 0

    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    lines_changed = 0
    rules_triggered = 0

    for lineno, line in enumerate(lines, start=1):
        new_line, applied = apply_rules_to_line(line, is_python)
        new_lines.append(new_line)
        if applied:
            lines_changed += 1
            rules_triggered += len(applied)
            if verbose:
                for label in applied:
                    print(f"  {path}:{lineno}: [{label}]")
                    print(f"    - {line.rstrip()}")
                    print(f"    + {new_line.rstrip()}")

    if lines_changed == 0:
        return 0, 0

    new_text = "".join(new_lines)
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return lines_changed, rules_triggered


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wave-6 bulk codemod: legacy google_auth patterns → google-kit"
    )
    parser.add_argument("--root", required=True, help="Root directory to scan")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing"
    )
    parser.add_argument(
        "--exts",
        default="",
        help="Additional comma-separated file extensions (e.g. .ini,.cfg)",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="Comma-separated dir names to exclude (augments defaults)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print each changed line")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"ERROR: --root {root} is not a directory")

    extensions = DEFAULT_EXTENSIONS
    if args.exts:
        extra = {e if e.startswith(".") else f".{e}" for e in args.exts.split(",")}
        extensions = extensions | extra

    exclude_dirs = DEFAULT_EXCLUDE_DIRS
    if args.exclude:
        exclude_dirs = exclude_dirs | frozenset(args.exclude.split(","))

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"wave6_codemod [{mode}] root={root}")
    print(f"  extensions: {sorted(extensions)} + .py (comments only)")
    print(f"  exclude dirs: {sorted(exclude_dirs)}")
    print(f"  rules: {len(RULES)}")
    print()

    total_files = 0
    total_files_changed = 0
    total_lines_changed = 0
    total_rules_triggered = 0

    for path in sorted(iter_files(root, extensions, exclude_dirs)):
        total_files += 1
        lines_changed, rules_triggered = process_file(path, args.dry_run, args.verbose)
        if lines_changed:
            total_files_changed += 1
            total_lines_changed += lines_changed
            total_rules_triggered += rules_triggered
            rel = path.relative_to(root)
            action = "(would change)" if args.dry_run else "(changed)"
            print(f"  {rel}: {lines_changed} line(s) {action}")

    print()
    print(f"{'DRY-RUN ' if args.dry_run else ''}SUMMARY:")
    print(f"  Files scanned:  {total_files}")
    print(f"  Files changed:  {total_files_changed}")
    print(f"  Lines changed:  {total_lines_changed}")
    print(f"  Rules triggered: {total_rules_triggered}")

    if args.dry_run and total_lines_changed == 0:
        print("  0 changes pending — tree is already clean.")
    elif not args.dry_run and total_files_changed == 0:
        print("  Nothing to do.")


if __name__ == "__main__":
    main()
