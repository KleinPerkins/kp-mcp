"""Adversarial regression tests for workspace tools and scaffold template."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from tools import catalog_gen, new_kit
from tools.caller_matrix import scan as caller_scan


def test_break_new_kit_rejects_numeric_domain(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="valid Python package"):
        new_kit.main(["--domain", "123", "--dest", str(tmp_path)])

    assert not (tmp_path / "123-kit").exists()


def test_break_new_kit_scaffold_is_importable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert new_kit.main(["--domain", "sample", "--dest", str(tmp_path)]) == 0
    src = tmp_path / "sample-kit" / "src"
    monkeypatch.syspath_prepend(str(src))

    pkg = importlib.import_module("sample_kit")
    registry = importlib.import_module("sample_kit.registry")

    assert pkg.__version__ == "0.1.0"
    specs = registry.all_specs()
    assert [spec.name for spec in specs] == ["items.list", "items.create"]
    assert all(spec.input_model is not None and spec.output_model is not None for spec in specs)


def test_break_catalog_generate_zero_kits_creates_docs_dir(tmp_path: Path) -> None:
    catalog_gen.generate(root=tmp_path)

    catalog = tmp_path / "docs" / "CATALOG.md"
    assert catalog.is_file()
    assert "Kit Catalog" in catalog.read_text(encoding="utf-8")


def test_break_catalog_missing_registry_has_clear_error(tmp_path: Path) -> None:
    kit = tmp_path / "broken-kit"
    pkg = kit / "src" / "broken_kit"
    pkg.mkdir(parents=True)
    (kit / "pyproject.toml").write_text(
        "[project]\nname = 'broken-kit'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match="broken-kit.*registry"):
        catalog_gen.generate(root=tmp_path)


def test_break_caller_matrix_canonicalizes_md_to_gdoc() -> None:
    assert caller_scan._canonical("md_to_gdoc") == "md_to_gdoc"
    assert caller_scan._canonical("md-to-gdoc") == "md_to_gdoc"
