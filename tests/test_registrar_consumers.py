"""Offline integration contracts for every kit and the generated scaffold."""
from __future__ import annotations

import importlib
import json
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import pytest

from kp_mcp_bootstrap.registrars import (
    Outcome, ReasonCode, RegistrarError, fixture_approval, fixture_context,
)
from tools.new_kit import _derive, _render


@pytest.fixture(params=["google_kit", "snow_kit", "widget_kit", "scaffold"])
def kit(request, tmp_path, monkeypatch):
    name = request.param
    if name == "scaffold":
        destination = tmp_path / "generated" / "sample-kit"
        _render(Path(__file__).parents[1] / "template", destination, _derive("sample"))
        monkeypatch.syspath_prepend(str(destination / "src"))
        name = "sample_kit"
    return importlib.import_module(f"{name}.bootstrap")


def inputs(kit, tmp_path):
    kwargs = {"binary_path": f"/opt/fixtures/{kit.SERVER_NAME}"}
    if kit.SERVER_NAME == "snow-kit":
        kwargs["config_path"] = tmp_path / "profile.env"
    return kwargs


def fixtures(stack, kit, tmp_path, kwargs):
    definition = kit.registration_definition("a" * 40, **kwargs)
    adapters = kit.registrars()
    targets = {
        host: stack.enter_context(fixture_context(registrar, definition, fixture_root=tmp_path))
        for host, registrar in adapters.items()
    }
    return definition, adapters, targets


def prepared_batch(definition, adapters, targets):
    operations, approvals = {}, {}
    for host, registrar in adapters.items():
        target = targets[host]
        operation = registrar.prepare(registrar.preview(target.config_path, definition, context=target.context))
        operations[host] = operation
        approvals[host] = fixture_approval(operation)
    return operations, approvals


def test_missing_authority_cannot_write_even_to_a_temp_path(kit, tmp_path):
    paths = {f"{host}_path": tmp_path / host / "config" for host in ("cursor", "codex", "claude")}
    before = set(tmp_path.rglob("*"))
    with pytest.raises(RegistrarError) as caught:
        kit.register_all(**paths, **inputs(kit, tmp_path))
    assert caught.value.code is ReasonCode.CONTEXT_REQUIRED
    assert set(tmp_path.rglob("*")) == before


def test_kit_identity_and_exact_prepared_batch(kit, tmp_path):
    kwargs = inputs(kit, tmp_path)
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        paths = {f"{host}_path": target.config_path for host, target in targets.items()}
        contexts = {host: target.context for host, target in targets.items()}
        preview = kit.register_all(**paths, **kwargs, contexts=contexts, dry_run=True)
        assert set(preview.values()) == {"would-change"}
        assert all(not target.config_path.exists() for target in targets.values())
        operations, approvals = prepared_batch(definition, adapters, targets)
        results = kit.register_all(**paths, **kwargs, contexts=contexts, prepared=operations, approvals=approvals)
        assert set(results) == set(targets)
        assert all(result.outcome is Outcome.APPLIED and result.config_changed for result in results.values())
        for host, registrar in adapters.items():
            inspection = registrar.inspect_registration(targets[host].config_path, context=contexts[host])
            assert inspection.present and inspection.owned_projection_match
            public = json.dumps(inspection.to_dict())
            assert kwargs["binary_path"] not in public
            assert "unknown" in public
        assert set(kit.register_all(**paths, **kwargs, contexts=contexts, dry_run=True).values()) == {"already-up-to-date"}


def test_last_target_bad_approval_prevents_first_target_write(kit, tmp_path):
    kwargs = inputs(kit, tmp_path)
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        operations, approvals = prepared_batch(definition, adapters, targets)
        approvals["claude"] = replace(approvals["claude"], action_digest="0" * 64)
        with pytest.raises(RegistrarError):
            kit.register_all(
                **{f"{host}_path": target.config_path for host, target in targets.items()},
                **kwargs, contexts={host: target.context for host, target in targets.items()},
                prepared=operations, approvals=approvals,
            )
        assert all(not target.config_path.exists() for target in targets.values())


def test_caller_definition_change_cannot_apply_old_prepared_bytes(kit, tmp_path):
    kwargs = inputs(kit, tmp_path)
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        operations, approvals = prepared_batch(definition, adapters, targets)
        kwargs["binary_path"] = "/opt/fixtures/different"
        with pytest.raises(RegistrarError):
            kit.register_all(
                **{f"{host}_path": target.config_path for host, target in targets.items()},
                **kwargs, contexts={host: target.context for host, target in targets.items()},
                prepared=operations, approvals=approvals,
            )
        assert all(not target.config_path.exists() for target in targets.values())


def test_snow_policy_override_is_preserved_and_conflicted(tmp_path):
    from snow_kit import bootstrap as kit
    kwargs = inputs(kit, tmp_path)
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        operations, approvals = prepared_batch(definition, adapters, targets)
        kit.register_all(
            **{f"{host}_path": target.config_path for host, target in targets.items()}, **kwargs,
            contexts={host: target.context for host, target in targets.items()},
            prepared=operations, approvals=approvals,
        )
        target = targets["cursor"]
        data = json.loads(target.config_path.read_text())
        data["mcpServers"]["snow-kit"]["env"]["SNOW_KIT_ENABLE_WRITE"] = "1"
        target.config_path.write_text(json.dumps(data))
        before = target.config_path.read_bytes()
        inspection = adapters["cursor"].inspect_registration(target.config_path, context=target.context)
        assert ReasonCode.POLICY_CONFLICT in inspection.reason_codes
        assert target.config_path.read_bytes() == before


@pytest.mark.parametrize("module", ["google_kit", "snow_kit"])
def test_unregister_uses_its_own_prepared_action(module, tmp_path):
    kit = importlib.import_module(f"{module}.bootstrap")
    kwargs = inputs(kit, tmp_path)
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        operations, approvals = prepared_batch(definition, adapters, targets)
        paths = {f"{host}_path": target.config_path for host, target in targets.items()}
        contexts = {host: target.context for host, target in targets.items()}
        # A registration approval cannot be used as withdrawal approval.
        with pytest.raises(RegistrarError):
            kit.unregister_all(**paths, **kwargs, contexts=contexts, prepared=operations, approvals=approvals)
        assert all(not target.config_path.exists() for target in targets.values())
        kit.register_all(**paths, **kwargs, contexts=contexts, prepared=operations, approvals=approvals)
        removal, removal_approvals = {}, {}
        for host, registrar in adapters.items():
            removal[host] = registrar.prepare(registrar.preview_unregister(paths[f"{host}_path"], context=contexts[host]))
            removal_approvals[host] = fixture_approval(removal[host])
        results = kit.unregister_all(**paths, **kwargs, contexts=contexts, prepared=removal, approvals=removal_approvals)
        assert all(result.outcome is Outcome.APPLIED and result.config_changed for result in results.values())
        assert all(not adapters[host].inspect_registration(target.config_path, context=contexts[host]).present
                   for host, target in targets.items())


def test_google_bootstrap_applies_explicit_definition_without_profile_repair(tmp_path, monkeypatch):
    from google_kit import bootstrap as kit
    kwargs = {"binary_path": "/opt/fixtures/google-kit",
              "env": {"GOOGLE_KIT_CONFIG_DIR": str(tmp_path / "profile")}}
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        operations, approvals = prepared_batch(definition, adapters, targets)
        monkeypatch.setattr(kit, "default_platform_paths", lambda: {
            host: target.config_path for host, target in targets.items()
        })
        def forbidden(**kwargs):
            pytest.fail("registration must not invoke style-profile repair")
        monkeypatch.setattr("google_kit.core.profiles.doctor_profiles", forbidden)
        result = kit.bootstrap(**kwargs, contexts={host: target.context for host, target in targets.items()},
                               prepared=operations, approvals=approvals)
        assert all(item.outcome is Outcome.APPLIED for item in result.values())
        assert not (tmp_path / "profile").exists()


def test_snow_setup_validates_entire_batch_before_profile_write(tmp_path, monkeypatch):
    from snow_kit import bootstrap as kit
    for key in kit.profile_keys():
        monkeypatch.delenv(key, raising=False)
    kwargs = inputs(kit, tmp_path)
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        operations, approvals = prepared_batch(definition, adapters, targets)
        monkeypatch.setattr(kit, "default_platform_paths", lambda: {
            host: target.config_path for host, target in targets.items()
        })
        invalid = dict(approvals)
        invalid["claude"] = replace(invalid["claude"], action_digest="0" * 64)
        with pytest.raises(RegistrarError):
            kit.setup(**kwargs, profile_values={"SNOW_KIT_ACCOUNT": "fixture", "SNOW_KIT_USER": "fixture"},
                      contexts={host: target.context for host, target in targets.items()},
                      prepared=operations, approvals=invalid)
        assert not kwargs["config_path"].exists()
        assert all(not target.config_path.exists() for target in targets.values())
        result = kit.setup(**kwargs, profile_values={"SNOW_KIT_ACCOUNT": "fixture", "SNOW_KIT_USER": "fixture"},
                           contexts={host: target.context for host, target in targets.items()},
                           prepared=operations, approvals=approvals)
        assert result["state"] == "needs_sign_in"
        assert kwargs["config_path"].stat().st_mode & 0o777 == 0o600
        assert all(item.outcome is Outcome.APPLIED for item in result["registrations"].values())


@pytest.mark.parametrize("module", ["google_kit", "snow_kit"])
def test_unregister_dry_run_rejects_preserved_policy(module, tmp_path):
    kit = importlib.import_module(f"{module}.bootstrap")
    kwargs = inputs(kit, tmp_path)
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        operations, approvals = prepared_batch(definition, adapters, targets)
        paths = {f"{host}_path": target.config_path for host, target in targets.items()}
        contexts = {host: target.context for host, target in targets.items()}
        kit.register_all(**paths, **kwargs, contexts=contexts, prepared=operations, approvals=approvals)
        cursor = targets["cursor"].config_path
        data = json.loads(cursor.read_text())
        data["mcpServers"][kit.SERVER_NAME]["disabled"] = True
        cursor.write_text(json.dumps(data))
        before = cursor.read_bytes()
        with pytest.raises(RegistrarError) as caught:
            kit.unregister_all(**paths, **kwargs, contexts=contexts, dry_run=True)
        assert caught.value.code is ReasonCode.REMOVAL_CONFLICT
        assert cursor.read_bytes() == before


def test_all_changed_packages_record_exact_wheel_versions_and_dependencies(tmp_path):
    import subprocess
    import tarfile
    import zipfile
    from email.parser import Parser

    workspace = Path(__file__).parents[1]
    dist = tmp_path / "dist"
    subprocess.run(["uv", "build", "--offline", "--all-packages", "--out-dir", str(dist)],
                   cwd=workspace, check=True, capture_output=True, text=True)
    versions = {"kp_mcp_bootstrap": "0.4.0", "google_kit": "0.3.0",
                "snow_kit": "0.4.0", "widget_kit": "0.3.0"}
    for package, version in versions.items():
        with zipfile.ZipFile(dist / f"{package}-{version}-py3-none-any.whl") as archive:
            metadata = Parser().parsestr(archive.read(f"{package}-{version}.dist-info/METADATA").decode())
            assert metadata["Version"] == version
            expected = "tomlkit==0.15.2" if package == "kp_mcp_bootstrap" else "kp-mcp-bootstrap==0.4.0"
            assert expected in metadata.get_all("Requires-Dist", [])
            assert f'__version__ = "{version}"' in archive.read(f"{package}/__init__.py").decode()
        with tarfile.open(dist / f"{package}-{version}.tar.gz") as archive:
            names = archive.getnames()
            assert any(name.endswith(f"/src/{package}/__init__.py") for name in names)
            if package == "kp_mcp_bootstrap":
                assert any(name.endswith("/registrars/consumers.py") for name in names)


@pytest.mark.parametrize("module,key", [
    ("google_kit", "GOOGLE_KIT_PROFILE"),
    ("google_kit", "GOOGLE_KIT_ENABLE_WRITES"),
    ("google_kit", "ACCESS_TOKEN"),
    ("widget_kit", "WIDGET_KIT_PROFILE"),
    ("widget_kit", "ACCESS_TOKEN"),
    ("snow_kit", "SNOW_KIT_ENABLE_WRITE"),
])
def test_kit_definitions_do_not_claim_auth_account_or_enablement(module, key):
    kit = importlib.import_module(f"{module}.bootstrap")
    with pytest.raises(RegistrarError) as caught:
        kit.registration_definition("a" * 40, "/opt/fixture/kit", env={key: "sensitive-fixture-value"})
    assert caught.value.code is ReasonCode.UNSUPPORTED_FIELD
    assert "sensitive-fixture-value" not in str(caught.value)


def test_rendered_scaffold_runs_its_offline_tests(tmp_path):
    import os
    import subprocess
    import sys

    destination = tmp_path / "generated-kit"
    _render(Path(__file__).parents[1] / "template", destination, _derive("generated"))
    env = dict(os.environ)
    env.pop("GOOGLE_KIT_SANDBOX", None)
    env["PYTHONPATH"] = str(destination / "src")
    subprocess.run([sys.executable, "-m", "pytest", "-q", str(destination / "tests")],
                   cwd=tmp_path, env=env, check=True, capture_output=True, text=True)


@pytest.mark.parametrize("verb,profile_writer", [("setup", "write_profile"), ("repair", "repair_profile")])
def test_snow_reports_profile_outcome_when_registration_recheck_refuses(tmp_path, monkeypatch, verb, profile_writer):
    from snow_kit import bootstrap as kit
    for key in kit.profile_keys():
        monkeypatch.delenv(key, raising=False)
    kwargs = inputs(kit, tmp_path)
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        operations, approvals = prepared_batch(definition, adapters, targets)
        monkeypatch.setattr(kit, "default_platform_paths", lambda: {
            host: target.config_path for host, target in targets.items()
        })
        original_writer = getattr(kit, profile_writer)
        changed = b'{"host_setting": true}\n'
        def write_then_change_target(*args, **options):
            outcome = original_writer(*args, **options)
            targets["cursor"].config_path.write_bytes(changed)
            return outcome
        monkeypatch.setattr(kit, profile_writer, write_then_change_target)
        extra = {"profile_values": {"SNOW_KIT_ACCOUNT": "fixture", "SNOW_KIT_USER": "fixture"}} if verb == "setup" else {}
        result = getattr(kit, verb)(
            **kwargs, **extra, contexts={host: target.context for host, target in targets.items()},
            prepared=operations, approvals=approvals,
        )
        assert result["state"] == "registration_incomplete"
        assert result["profile"]["state"] == "ready"
        assert result["reason_codes"]
        assert result["registrations"] == {}
        assert kwargs["config_path"].exists()
        assert targets["cursor"].config_path.read_bytes() == changed
        assert all(not targets[host].config_path.exists() for host in ("codex", "claude"))


def test_each_cli_reports_failed_registration_as_structured_nonzero(kit, tmp_path, monkeypatch, capsys):
    kwargs = inputs(kit, tmp_path)
    with ExitStack() as stack:
        definition, adapters, targets = fixtures(stack, kit, tmp_path, kwargs)
        operations, approvals = prepared_batch(definition, adapters, targets)
        success = adapters["cursor"].apply(operations["cursor"], approvals["cursor"])
        failed = replace(success, outcome=Outcome.FAILED, config_changed=False, state_changed=False,
                         reason_codes=(ReasonCode.PREIMAGE_CHANGED,))
        results = {"cursor": success, "codex": failed, "claude": failed}
        monkeypatch.setattr(kit, "bootstrap", lambda **_kwargs: results)
        cli = importlib.import_module(kit.__package__ + ".cli")
        code = cli.cmd_bootstrap() if kit.SERVER_NAME == "google-kit" else cli.main(["bootstrap"])
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        native = payload["platforms"] if kit.SERVER_NAME == "google-kit" else payload
        assert native["cursor"]["outcome"] == "applied"
        assert native["codex"]["outcome"] == "failed"
        assert native["codex"]["reason_codes"] == ["preimage_changed"]


@pytest.mark.parametrize("verb", ["setup", "repair"])
def test_snow_cli_partial_profile_outcome_is_nonzero(verb, monkeypatch, capsys):
    from snow_kit import bootstrap as kit
    from snow_kit.cli import main
    monkeypatch.setattr(kit, verb, lambda **_kwargs: {
        "state": "registration_incomplete", "profile": {"state": "ready"},
        "registrations": {}, "reason_codes": ["preimage_changed"],
    })
    assert main([verb]) == 1
    assert json.loads(capsys.readouterr().out)["profile"]["state"] == "ready"
