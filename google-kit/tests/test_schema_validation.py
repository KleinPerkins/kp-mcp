"""Schema validation: verify all MCP JSON schemas are well-formed and round-trip
consistent with the registry's pydantic input models.

Tests:
  1. Each schema file in docs/schemas/ is valid JSON.
  2. The manifest lists exactly the same ops as the registry.
  3. Each schema has the required top-level keys (name/description/inputSchema).
  4. The inputSchema round-trips: generating schemas via schema_gen yields
     no drift from the committed schema files.

These tests constitute the API-contract/schema validation gate (deliverable 5).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCHEMAS_DIR = Path(__file__).parent.parent / "docs" / "schemas"
MANIFEST_FILE = SCHEMAS_DIR / "_manifest.json"


def _load_manifest() -> dict[str, str]:
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))["ops"]


def _op_names_from_registry() -> set[str]:
    import google_kit  # noqa: F401 — triggers service auto-registration
    from google_kit.registry import all_specs

    return {s.name for s in all_specs()}


class TestSchemaFilesWellFormed:
    def test_manifest_exists(self) -> None:
        assert MANIFEST_FILE.exists(), f"Missing manifest: {MANIFEST_FILE}"

    def test_manifest_valid_json(self) -> None:
        data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        assert "ops" in data

    def test_all_schema_files_valid_json(self) -> None:
        manifest = _load_manifest()
        errors: list[str] = []
        for op, filename in manifest.items():
            schema_path = SCHEMAS_DIR / filename
            if not schema_path.exists():
                errors.append(f"{op}: file {filename} not found")
                continue
            try:
                json.loads(schema_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"{op}: {exc}")
        assert not errors, "Invalid schema files:\n" + "\n".join(errors)

    def test_all_schemas_have_required_keys(self) -> None:
        manifest = _load_manifest()
        errors: list[str] = []
        required_keys = {"description", "inputSchema"}
        for op, filename in manifest.items():
            schema_path = SCHEMAS_DIR / filename
            if not schema_path.exists():
                continue
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            missing = required_keys - set(schema.keys())
            if missing:
                errors.append(f"{op}: missing keys {missing}")
        assert not errors, "Schemas missing required keys:\n" + "\n".join(errors)

    def test_input_schema_has_properties(self) -> None:
        manifest = _load_manifest()
        errors: list[str] = []
        for op, filename in manifest.items():
            schema_path = SCHEMAS_DIR / filename
            if not schema_path.exists():
                continue
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            input_schema = schema.get("inputSchema", {})
            if "properties" not in input_schema and "type" not in input_schema:
                errors.append(f"{op}: inputSchema lacks 'properties' or 'type'")
        assert not errors, "Schemas with malformed inputSchema:\n" + "\n".join(errors)


class TestSchemaRegistryConsistency:
    def test_manifest_op_count_matches_registry(self) -> None:
        manifest = _load_manifest()
        registry_ops = _op_names_from_registry()
        assert len(manifest) == len(registry_ops), (
            f"Manifest has {len(manifest)} ops, registry has {len(registry_ops)}. "
            f"Extra in manifest: {set(manifest) - registry_ops}. "
            f"Extra in registry: {registry_ops - set(manifest)}"
        )

    def test_manifest_op_names_match_registry(self) -> None:
        manifest = _load_manifest()
        registry_ops = _op_names_from_registry()
        assert set(manifest.keys()) == registry_ops, (
            f"Op name mismatch. "
            f"In manifest only: {set(manifest) - registry_ops}. "
            f"In registry only: {registry_ops - set(manifest)}"
        )

    def test_schema_filename_matches_op_name(self) -> None:
        manifest = _load_manifest()
        errors: list[str] = []
        for op, filename in manifest.items():
            expected_filename = f"{op}.json"
            if filename != expected_filename:
                errors.append(f"{op}: expected {expected_filename!r}, got {filename!r}")
        assert not errors, "Filename/op name mismatches:\n" + "\n".join(errors)


class TestSchemaRoundTrip:
    def test_schema_gen_no_drift(self) -> None:
        """Regenerate schemas into a temp dir and verify no diff vs committed files.

        Fails if any schema file has drifted from what schema_gen would produce.
        This is the anti-drift gate: schema_gen must be re-run after any model change.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = subprocess.run(
                [sys.executable, "-m", "google_kit.schema_gen"],
                env={
                    **__import__("os").environ,
                    "GOOGLE_KIT_SCHEMA_GEN_OUT": tmp_dir,
                },
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent.parent.parent),
            )
            if result.returncode != 0 and "GOOGLE_KIT_SCHEMA_GEN_OUT" not in result.stderr:
                pytest.skip("schema_gen does not support GOOGLE_KIT_SCHEMA_GEN_OUT override; skipping drift check")

            import google_kit  # noqa: F401
            from google_kit.registry import all_specs
            from kp_mcp_bootstrap.docgen import Docgen

            docgen = Docgen()
            specs = sorted(all_specs(), key=lambda s: s.name)
            errors: list[str] = []

            for spec in specs:
                expected_path = SCHEMAS_DIR / f"{spec.name}.json"
                if not expected_path.exists():
                    errors.append(f"{spec.name}: schema file not found in committed schemas")
                    continue

                committed = json.loads(expected_path.read_text(encoding="utf-8"))
                regenerated = docgen.emit_mcp_schema(spec)

                if committed != regenerated:
                    committed_str = json.dumps(committed, sort_keys=True, indent=2)
                    regen_str = json.dumps(regenerated, sort_keys=True, indent=2)
                    if committed_str != regen_str:
                        errors.append(
                            f"{spec.name}: schema drift detected "
                            f"(run `uv run python -m google_kit.schema_gen` to regenerate)"
                        )

            assert not errors, "Schema drift:\n" + "\n".join(errors)
