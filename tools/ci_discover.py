"""Workspace discovery for CI parametrization — adding a kit needs no YAML edits.

Subcommands (filesystem-only ones need no `uv sync`; ``regen`` needs the synced
workspace so kit packages import):

  kits          Print a JSON array of kit names (``*-kit`` members) for a matrix.
  lint-paths    Print the space-separated editorial-lint path list.
  lint-paths-json
                Print the same paths as JSON for safe workflow argument transport.
  regen --kit X Re-run every generator a kit ships (schema_gen / docgen_gen /
                aliases_gen, whichever exist). Used twice by the determinism gate.
  regen-catalog Re-run the workspace catalog generator (docs/CATALOG.md + ECOSYSTEM).

The determinism gate runs ``regen`` twice then ``git diff --exit-code <kit>/docs/``;
no generator list is hard-coded in the workflow.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_GENERATOR_MODULES = ("schema_gen", "docgen_gen", "aliases_gen")
_ALWAYS_LINT = ("docs", "CONVENTIONS.md", "README.md", "template", "tools")


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _kit_dirs(root: Path) -> list[Path]:
    return sorted(
        d
        for d in root.iterdir()
        if d.is_dir() and d.name.endswith("-kit") and (d / "pyproject.toml").is_file()
    )


def _member_dirs(root: Path) -> list[Path]:
    """All workspace member dirs: shared engines (``kp-mcp-*``) and kits (``*-kit``)."""
    members = [
        d
        for d in root.iterdir()
        if d.is_dir()
        and (d / "pyproject.toml").is_file()
        and (d.name.startswith("kp-mcp-") or d.name.endswith("-kit"))
    ]
    return sorted(members, key=lambda d: d.name)


def _package_name(kit_dir: Path) -> str:
    src = kit_dir / "src"
    for child in sorted(src.iterdir()):
        if child.is_dir() and (child / "__init__.py").is_file():
            return child.name
    raise RuntimeError(f"No importable package under {src}")


def _cmd_kits(root: Path) -> int:
    print(json.dumps([d.name for d in _kit_dirs(root)]))
    return 0


def _lint_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for member in _member_dirs(root):
        paths.append(member.name)
    for extra in _ALWAYS_LINT:
        if (root / extra).exists():
            paths.append(extra)
    return paths


def _cmd_lint_paths(root: Path) -> int:
    paths = _lint_paths(root)
    print(" ".join(paths))
    return 0


def _cmd_lint_paths_json(root: Path) -> int:
    print(json.dumps(_lint_paths(root)))
    return 0


def _cmd_regen(root: Path, kit_name: str) -> int:
    kit_dir = root / kit_name
    pkg = _package_name(kit_dir)
    importlib.import_module(pkg)
    ran = []
    for gen in _GENERATOR_MODULES:
        module_name = f"{pkg}.{gen}"
        try:
            mod = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            continue
        mod.generate()
        ran.append(gen)
    print(f"{kit_name}: ran {', '.join(ran) or 'no generators'}", file=sys.stderr)
    return 0


def _cmd_regen_catalog(root: Path) -> int:
    sys.path.insert(0, str(root / "tools"))
    import catalog_gen

    catalog_gen.generate(root=root)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = _root()
    if not argv:
        print(
            "usage: ci_discover.py "
            "{kits|lint-paths|lint-paths-json|regen --kit NAME|regen-catalog}",
            file=sys.stderr,
        )
        return 2
    cmd = argv[0]
    if cmd == "kits":
        return _cmd_kits(root)
    if cmd == "lint-paths":
        return _cmd_lint_paths(root)
    if cmd == "lint-paths-json":
        return _cmd_lint_paths_json(root)
    if cmd == "regen-catalog":
        return _cmd_regen_catalog(root)
    if cmd == "regen":
        if len(argv) >= 3 and argv[1] == "--kit":
            return _cmd_regen(root, argv[2])
        print("regen requires: --kit NAME", file=sys.stderr)
        return 2
    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
