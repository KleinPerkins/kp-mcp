"""Review-round structural integrity checks for generated google-kit surfaces."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import google_kit  # noqa: F401 - triggers service registration
from kp_mcp_bootstrap.docgen import mcp_tool_name


ROOT = Path(__file__).parent.parent
IGNORED_DRIFT_FILES = {"drive.upload.md", "drive.upload.json"}


def _ops() -> set[str]:
    from google_kit.registry import all_specs

    return {spec.name for spec in all_specs()}


def _covers(grants: set[str], required: str) -> bool:
    if required in grants:
        return True
    if required.endswith(".readonly") and required.removesuffix(".readonly") in grants:
        return True
    return False


def test_registry_ops_have_all_generated_surfaces() -> None:
    from google_kit.mcp import _build_tool_map
    from google_kit.registry import all_specs

    ops = _ops()
    cards = {p.stem for p in (ROOT / "docs" / "cards").glob("*.md")}
    schemas = {
        p.stem
        for p in (ROOT / "docs" / "schemas").glob("*.json")
        if p.name != "_manifest.json"
    }
    manifest = json.loads((ROOT / "docs" / "schemas" / "_manifest.json").read_text())["ops"]
    index = (ROOT / "docs" / "INDEX.md").read_text()
    intents = (ROOT / "docs" / "INTENTS.md").read_text()
    index_ops = set(re.findall(r"\| `([^`]+)` \| [^|]+ \| \[card\]", index))
    intent_ops = set(re.findall(r"^\| `([^`]+)` \| `google-kit ", intents, flags=re.M))
    tool_names = set(_build_tool_map(list(all_specs())))

    assert cards == ops
    assert schemas == ops
    assert set(manifest) == ops
    assert index_ops == ops
    assert intent_ops == ops
    assert tool_names == {mcp_tool_name(op) for op in ops}


def test_auth_mapping_and_declared_scope_satisfiability() -> None:
    from google_kit.core.auth import GOOGLE_KIT_SCOPES, _SERVICE_API_MAP
    from google_kit.core.scopes import SCOPE_MODES
    from google_kit.registry import all_specs

    composite_prefixes = {"recipes"}
    prefixes = {spec.name.split(".", 1)[0] for spec in all_specs()}
    assert prefixes - composite_prefixes <= set(_SERVICE_API_MAP)

    declared_grants: set[str] = set()
    for scopes in SCOPE_MODES.values():
        declared_grants.update(scopes)
    declared_grants.update(GOOGLE_KIT_SCOPES)

    unsatisfied = [
        (spec.name, scope)
        for spec in all_specs()
        for scope in spec.scopes
        if not _covers(declared_grants, scope)
    ]
    assert unsatisfied == []


def _assert_no_file_drift(committed_dir: Path, generated_dir: Path, names: Iterable[str]) -> None:
    drift: list[str] = []
    for name in sorted(names):
        if name in IGNORED_DRIFT_FILES:
            continue
        committed = committed_dir / name
        generated = generated_dir / name
        if not committed.exists() or not generated.exists():
            drift.append(name)
            continue
        if committed.read_text(encoding="utf-8") != generated.read_text(encoding="utf-8"):
            drift.append(name)
    assert drift == []


def test_generators_are_deterministic_without_committed_drift(tmp_path: Path) -> None:
    from google_kit import aliases_gen, docgen_gen, schema_gen

    generated_cards = tmp_path / "cards"
    generated_index = tmp_path / "INDEX.md"
    generated_schemas = tmp_path / "schemas"
    generated_intents = tmp_path / "INTENTS.md"

    docgen_gen.generate(cards_dir=generated_cards, index_path=generated_index)
    schema_gen.generate(schemas_dir=generated_schemas)
    aliases_gen.generate(manifest_path=generated_intents)

    card_names = {p.name for p in (ROOT / "docs" / "cards").glob("*.md")}
    schema_names = {p.name for p in (ROOT / "docs" / "schemas").glob("*.json")}

    _assert_no_file_drift(ROOT / "docs" / "cards", generated_cards, card_names)
    _assert_no_file_drift(ROOT / "docs" / "schemas", generated_schemas, schema_names)
    assert (ROOT / "docs" / "INDEX.md").read_text(
        encoding="utf-8",
    ) == generated_index.read_text(encoding="utf-8")
    assert (ROOT / "docs" / "INTENTS.md").read_text(
        encoding="utf-8",
    ) == generated_intents.read_text(encoding="utf-8")
