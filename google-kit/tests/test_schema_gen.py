"""Tests for google-kit MCP schema generator.

Parity: schema-generation DONE; reproducibility DONE; sandbox DEFERRED(P6)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import google_kit  # noqa: F401 — triggers registration
from google_kit.registry import all_specs
from google_kit.schema_gen import generate
from kp_mcp_bootstrap.docgen import mcp_tool_name


class TestSchemaGeneration:
    def test_generates_one_file_per_op(self, tmp_path: Path) -> None:
        generate(schemas_dir=tmp_path)
        specs = list(all_specs())
        for spec in specs:
            assert (tmp_path / f"{spec.name}.json").exists(), f"Missing schema for {spec.name}"

    def test_generates_manifest(self, tmp_path: Path) -> None:
        generate(schemas_dir=tmp_path)
        manifest_path = tmp_path / "_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert "ops" in manifest
        assert len(manifest["ops"]) == len(list(all_specs()))

    def test_schema_files_valid_json(self, tmp_path: Path) -> None:
        generate(schemas_dir=tmp_path)
        for spec in all_specs():
            raw = (tmp_path / f"{spec.name}.json").read_text()
            obj = json.loads(raw)
            # File is keyed by the dotted op name; the embedded `name` is the
            # sanitized (MCP-valid) tool name.
            assert obj["name"] == mcp_tool_name(spec.name)
            assert "inputSchema" in obj
            assert "description" in obj

    def test_reproducible_no_diff(self, tmp_path: Path) -> None:
        """Re-running generate on the same dir produces identical files."""
        out = tmp_path / "schemas"
        out.mkdir()
        generate(schemas_dir=out)
        first_pass = {f.name: f.read_text() for f in out.iterdir()}
        generate(schemas_dir=out)
        second_pass = {f.name: f.read_text() for f in out.iterdir()}
        assert first_pass == second_pass, "Schema generation is not reproducible"

    def test_all_41_ops_in_manifest(self, tmp_path: Path) -> None:
        generate(schemas_dir=tmp_path)
        manifest = json.loads((tmp_path / "_manifest.json").read_text())
        op_names = set(s.name for s in all_specs())
        manifest_names = set(manifest["ops"].keys())
        assert op_names == manifest_names

    def test_input_schema_is_object(self, tmp_path: Path) -> None:
        generate(schemas_dir=tmp_path)
        for spec in all_specs():
            obj = json.loads((tmp_path / f"{spec.name}.json").read_text())
            input_schema = obj["inputSchema"]
            assert isinstance(input_schema, dict)


class TestCommittedSchemas:
    """Verify that committed schemas in docs/schemas/ are up-to-date."""

    def test_committed_schemas_match_generated(self, tmp_path: Path) -> None:
        from pathlib import Path as P

        committed = P(__file__).parent.parent / "docs" / "schemas"
        if not committed.exists():
            pytest.skip("docs/schemas/ not yet committed — run schema_gen first")

        generate(schemas_dir=tmp_path)
        for spec in all_specs():
            fname = f"{spec.name}.json"
            committed_file = committed / fname
            generated_file = tmp_path / fname
            assert committed_file.exists(), f"Committed schema missing: {fname}"
            assert committed_file.read_text() == generated_file.read_text(), (
                f"Committed schema out of sync with generator: {fname}\n"
                f"Re-run: uv run python -m google_kit.schema_gen"
            )
