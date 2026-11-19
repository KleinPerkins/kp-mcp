"""Lossless native JSON numbers remain private across registration updates."""
import json
from dataclasses import replace

import pytest

from kp_mcp_bootstrap.registrars import (
    ClaudeRegistrar, CursorRegistrar, Outcome, ReasonCode, RegistrarError,
    RegistrationDefinition, SourceIdentity, fixture_approval, fixture_context,
)


@pytest.mark.parametrize("adapter", [CursorRegistrar, ClaudeRegistrar])
def test_native_numbers_keep_exact_lexemes_in_siblings_and_preserved_fields(adapter, tmp_path):
    registrar = adapter()
    definition = RegistrationDefinition.stdio(
        SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:decimal", "a" * 40, "decimal.fixture"),
        command="/opt/fixture/decimal", args=(),
    )
    raw = b'{"preferences":{"numbers":[1.00,-0.000,1e+003,1E-10000,123456789012345678901234567890.12345678901234567890,-0],"text":"1.00","enabled":true,"empty":null},"mcpServers":{}}'
    def exact(data):
        return json.loads(data, parse_int=lambda token: token, parse_float=lambda token: token)
    expected = exact(raw)["preferences"]
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_bytes(raw)
        preview = registrar.preview(fixture.config_path, definition, context=fixture.context)
        assert "1E-10000" not in json.dumps(preview.to_dict())
        prepared = registrar.prepare(preview)
        assert registrar.apply(prepared, fixture_approval(prepared)).outcome is Outcome.APPLIED
        assert exact(fixture.config_path.read_bytes())["preferences"] == expected
        # Preserve a host-owned decimal inside the selected entry while updating
        # an independently owned source leaf.
        old = '"command": "/opt/fixture/decimal"'
        text = fixture.config_path.read_text()
        assert text.count(old) == 1
        fixture.config_path.write_text(text.replace(old, '"budget": 1.00, ' + old))
        updated = RegistrationDefinition.stdio(
            SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:decimal", "b" * 40, "decimal.fixture"),
            command="/opt/fixture/updated", args=(),
        )
        context = replace(fixture.context, source_revision=updated.source_revision, definition_digest=updated.digest)
        prepared = registrar.prepare(registrar.preview(fixture.config_path, updated, context=context))
        assert registrar.apply(prepared, fixture_approval(prepared)).outcome is Outcome.APPLIED
        result = exact(fixture.config_path.read_bytes())
        assert result["preferences"] == expected
        assert result["mcpServers"]["decimal.fixture"]["budget"] == "1.00"


@pytest.mark.parametrize("adapter", [CursorRegistrar, ClaudeRegistrar])
@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":01}'])
def test_native_json_rejects_duplicate_or_invalid_numbers_without_writes(adapter, raw, tmp_path):
    registrar = adapter()
    definition = RegistrationDefinition.stdio(
        SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:invalid-json", "a" * 40, "fixture"),
        command="/opt/fixture/json", args=(),
    )
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_bytes(raw)
        with pytest.raises(RegistrarError) as caught:
            registrar.preview(fixture.config_path, definition, context=fixture.context)
        assert caught.value.code is ReasonCode.MALFORMED_CONFIG
        assert fixture.config_path.read_bytes() == raw
        assert not list(fixture.state_directory.iterdir())


def test_native_numeric_tokens_cannot_enter_canonical_records():
    from kp_mcp_bootstrap.registrars.contracts import canonical_json_bytes, digest_value
    from kp_mcp_bootstrap.registrars.native_json import loads, native_number_digest

    native = loads(b'{"setting":1.00}')
    with pytest.raises(TypeError):
        canonical_json_bytes(native)
    assert native_number_digest(native) is not None
    assert native_number_digest(loads(b'1.00')) != digest_value("1.00")
    assert native_number_digest({"setting": "1.00"}) is None


def test_native_json_escaping_cannot_turn_strings_into_numeric_or_object_tokens():
    from kp_mcp_bootstrap.registrars.native_json import dumps, loads

    raw = b'{"text":"1.00, \\"forged\\": true", "surrogate":"\\ud800", "nested":[{"x":1e+003}]}'
    decoded = json.loads(dumps(loads(raw)), parse_float=lambda token: token)
    expected = json.loads(raw, parse_float=lambda token: token)
    assert decoded == expected
    assert "forged" not in decoded


@pytest.mark.parametrize("adapter", [CursorRegistrar, ClaudeRegistrar])
def test_numeric_host_edit_is_distinct_from_an_owned_string(adapter, tmp_path):
    registrar = adapter()
    definition = RegistrationDefinition.stdio(
        SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:numeric-drift", "a" * 40, "fixture"),
        command="/opt/fixture/numeric-drift", args=(), env={"COUNT": "1.00"},
    )
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        operation = registrar.prepare(registrar.preview(fixture.config_path, definition, context=fixture.context))
        assert registrar.apply(operation, fixture_approval(operation)).outcome is Outcome.APPLIED
        text = fixture.config_path.read_text()
        assert '"COUNT": "1.00"' in text
        fixture.config_path.write_text(text.replace('"COUNT": "1.00"', '"COUNT": 1.00'))
        before = {p.relative_to(fixture.root): p.read_bytes() for p in fixture.root.rglob("*") if p.is_file()}
        preview = registrar.preview(fixture.config_path, definition, context=fixture.context)
        assert ReasonCode.OWNED_FIELD_DRIFT in preview.conflicts
        inspection = registrar.inspect_registration(fixture.config_path, context=fixture.context)
        assert inspection.owned_projection_match is False
        assert ReasonCode.OWNED_FIELD_DRIFT in inspection.reason_codes
        assert "1.00" not in json.dumps([preview.to_dict(), inspection.to_dict()])
        assert {p.relative_to(fixture.root): p.read_bytes() for p in fixture.root.rglob("*") if p.is_file()} == before
