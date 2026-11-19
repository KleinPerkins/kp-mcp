"""Registrar-v1 public contracts and explicit fixture happy path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kp_mcp_bootstrap.registrars import (
    ClaudeRegistrar,
    CodexRegistrar,
    CursorRegistrar,
    Outcome,
    ReasonCode,
    RegistrarError,
    RegistrationDefinition,
    ServerEntry,
    SourceIdentity,
    StdioTransport,
    fixture_approval,
    fixture_context,
)
from kp_mcp_bootstrap.registrars.contracts import (
    iter_mapping_leaves,
    validate_pointer_set,
)


IDENTITY = SourceIdentity(
    source_owner="KleinPerkins/kp-mcp",
    connection_id="kp-mcp:fixture-kit",
    source_revision="a" * 40,
    native_name="fixture-kit",
)


def definition() -> RegistrationDefinition:
    return RegistrationDefinition.stdio(
        IDENTITY,
        command="/opt/fixtures/fixture-kit",
        args=(),
        env={"FIXTURE_CONFIG_DIR": "/tmp/fixture-config"},
    )


def test_legacy_server_entry_keeps_020_empty_args_behavior() -> None:
    assert ServerEntry("/opt/fixture", args=[]).args == ["mcp"]
    assert StdioTransport("/opt/fixture", args=[]).args == ()


def test_definition_requires_complete_canonical_pointer_set() -> None:
    transport = StdioTransport("/opt/fixture", env={"A_B_C": "value"})
    expected = {
        "/transport/kind",
        "/transport/command",
        "/transport/args",
        "/transport/env/A_B_C",
    }
    valid = RegistrationDefinition(
        connection_id=IDENTITY.connection_id,
        source_owner=IDENTITY.source_owner,
        source_revision=IDENTITY.source_revision,
        native_name=IDENTITY.native_name,
        transport=transport,
        owned_paths=tuple(expected),
    )
    assert set(valid.owned_paths) == expected
    with pytest.raises(ValueError):
        RegistrationDefinition(
            connection_id=IDENTITY.connection_id,
            source_owner=IDENTITY.source_owner,
            source_revision=IDENTITY.source_revision,
            native_name=IDENTITY.native_name,
            transport=transport,
            owned_paths=("/transport", "/transport/command"),
        )


def test_definition_rejects_unknown_transport_union_member() -> None:
    with pytest.raises(RegistrarError) as caught:
        RegistrationDefinition(
            connection_id=IDENTITY.connection_id,
            source_owner=IDENTITY.source_owner,
            source_revision=IDENTITY.source_revision,
            native_name=IDENTITY.native_name,
            transport=object(),  # type: ignore[arg-type]
            owned_paths=("/transport/kind",),
        )
    assert caught.value.code is ReasonCode.UNSUPPORTED_TRANSPORT


@pytest.mark.parametrize(
    "pointers",
    [
        ("transport/command",),
        ("/",),
        ("/transport/~2bad",),
        ("/transport/command", "/transport/command"),
        ("/transport", "/transport/command"),
    ],
)
def test_pointer_contract_rejects_partial_or_ambiguous_ownership(
    pointers: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        validate_pointer_set(pointers)


def test_pointer_contract_escapes_slash_tilde_and_preserves_dotted_key() -> None:
    leaves = dict(
        iter_mapping_leaves(
            {"slash/key": {"tilde~key": "value", "dot.key": "other"}}
        )
    )
    assert leaves == {
        "/slash~1key/dot.key": "other",
        "/slash~1key/tilde~0key": "value",
    }
    assert validate_pointer_set(tuple(leaves)) == tuple(sorted(leaves))


@pytest.mark.parametrize("missing_or_extra", ["missing", "extra"])
def test_definition_refuses_incomplete_or_extra_pointer_set(
    missing_or_extra: str,
) -> None:
    transport = StdioTransport("/opt/fixture", env={"A_B_C": "value"})
    pointers = [
        "/transport/kind",
        "/transport/command",
        "/transport/args",
        "/transport/env/A_B_C",
    ]
    if missing_or_extra == "missing":
        pointers.pop()
    else:
        pointers.append("/transport/unknown")
    with pytest.raises(ValueError):
        RegistrationDefinition(
            connection_id=IDENTITY.connection_id,
            source_owner=IDENTITY.source_owner,
            source_revision=IDENTITY.source_revision,
            native_name=IDENTITY.native_name,
            transport=transport,
            owned_paths=tuple(pointers),
        )


@pytest.mark.parametrize(
    "registrar",
    [CursorRegistrar(), CodexRegistrar(), ClaudeRegistrar()],
)
def test_fixture_preview_prepare_approval_apply_is_explicit(
    registrar, tmp_path: Path
) -> None:
    desired = definition()
    with fixture_context(registrar, desired, fixture_root=tmp_path) as fixture:
        before = set(fixture.root.iterdir())
        preview = registrar.preview(
            fixture.config_path, desired, context=fixture.context
        )
        assert preview.ready and preview.config_changed
        assert not fixture.config_path.exists()
        assert set(fixture.root.iterdir()) == before
        prepared = registrar.prepare(preview)
        assert not fixture.config_path.exists()
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.outcome is Outcome.APPLIED
        assert result.config_changed
        inspection = registrar.inspect_registration(
            fixture.config_path, context=fixture.context
        )
        assert inspection.present and inspection.owned_projection_match
        public = json.dumps(inspection.to_dict())
        assert "/opt/fixtures/fixture-kit" not in public
        assert "unknown" in public
        repeated = registrar.preview(
            fixture.config_path, desired, context=fixture.context
        )
        assert not repeated.config_changed
        assert not repeated.state_changed


def test_missing_context_refuses_before_path_read_or_write(tmp_path: Path) -> None:
    target = tmp_path / "mcp.json"
    with pytest.raises(RegistrarError) as caught:
        CursorRegistrar().register(
            target,
            ServerEntry("/opt/fixtures/fixture-kit"),
        )
    assert caught.value.code is ReasonCode.CONTEXT_REQUIRED
    assert not target.exists()
