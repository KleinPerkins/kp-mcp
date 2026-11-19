"""Scaffold a new <domain>-kit from template/ into the workspace.

Usage::

    uv run python tools/new_kit.py --domain widget [--dest <workspace-root>]

Derives, from ``--domain``:
    kit name     = <domain>-kit     (pyproject name, CLI binary, MCP server name)
    package      = <domain>_kit     (Python package; non-alnum chars collapse to _)
    domain title = <Domain>         (Title Case, for descriptions)

Renders every ``template/**/*.tmpl`` file (tokens substituted in BOTH path and
content, ``.tmpl`` suffix stripped) into ``<dest>/<domain>-kit/``. The workspace
auto-discovers the new member (members glob ``*-kit``), so ``uv sync`` and the
parametrized CI pick it up with no further edits.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SUFFIX = ".tmpl"


def _derive(domain: str) -> dict[str, str]:
    """Map a raw domain to the substitution tokens."""
    slug = re.sub(r"[^a-z0-9]+", "-", domain.strip().lower()).strip("-")
    if not slug:
        raise SystemExit("error: --domain must contain at least one alphanumeric character")
    package = f"{slug.replace('-', '_')}_kit"
    if not package.isidentifier():
        raise SystemExit(
            "error: --domain must derive to a valid Python package name "
            "(start with a letter or underscore)"
        )
    return {
        "__KIT_NAME__": f"{slug}-kit",
        "__PKG__": package,
        "__DOMAIN_TITLE__": slug.replace("-", " ").title(),
        "__DOMAIN__": slug,
    }


def _apply_tokens(text: str, tokens: dict[str, str]) -> str:
    for key, value in tokens.items():
        text = text.replace(key, value)
    return text


def _render(template_root: Path, dest_kit: Path, tokens: dict[str, str]) -> list[Path]:
    """Render every *.tmpl under template_root into dest_kit. Returns written paths."""
    written: list[Path] = []
    for src in sorted(template_root.rglob(f"*{_SUFFIX}")):
        rel = _apply_tokens(str(src.relative_to(template_root)), tokens)[: -len(_SUFFIX)]
        out = dest_kit / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_apply_tokens(src.read_text(encoding="utf-8"), tokens), encoding="utf-8")
        written.append(out)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="new_kit.py", description="Scaffold a new <domain>-kit from template/."
    )
    parser.add_argument("--domain", required=True, help="Domain name, e.g. 'slack' or 'widget'.")
    parser.add_argument("--dest", default=None, help="Workspace root (default: repo root).")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    dest_root = Path(args.dest).resolve() if args.dest else root
    template_root = root / "template"
    tokens = _derive(args.domain)
    dest_kit = dest_root / tokens["__KIT_NAME__"]
    if dest_kit.exists():
        raise SystemExit(f"error: {dest_kit} already exists — choose another domain or remove it")

    written = _render(template_root, dest_kit, tokens)
    kit, pkg = tokens["__KIT_NAME__"], tokens["__PKG__"]
    print(f"Scaffolded {kit} ({len(written)} files) at {dest_kit}", file=sys.stderr)
    print(
        "Next: uv sync && "
        f"uv run pytest {kit}/ && "
        f"uv run python -m {pkg}.schema_gen && uv run python -m {pkg}.docgen_gen && "
        "uv run python tools/catalog_gen.py",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
