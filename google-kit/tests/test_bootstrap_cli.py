"""Tests for the google-kit ``bootstrap`` CLI subcommand.

CRITICAL: every test redirects ``google_kit.bootstrap.default_platform_paths``
to ``tmp_path`` via monkeypatch (the ``fake_paths`` fixture), so NO test ever
reads or writes the operator's real ``~/.cursor/mcp.json``,
``~/.codex/config.toml``, or ``~/.claude.json``.

Parity: bootstrap-CLI DONE; live-platform DEFERRED(P6)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import google_kit.bootstrap as gk_bootstrap
from google_kit.cli import _build_parser, cmd_bootstrap, main


@pytest.fixture
def fake_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect ALL platform paths into tmp_path — never touch real configs.

    Patches the module-level name so both the direct call in ``cmd_bootstrap``
    (for ``--remove``) and the internal call inside ``bootstrap()`` (for
    register / dry-run) resolve to these temp paths.
    """
    paths = {
        "cursor": tmp_path / "mcp.json",
        "codex": tmp_path / "config.toml",
        "claude": tmp_path / ".claude.json",
    }
    monkeypatch.setattr(gk_bootstrap, "default_platform_paths", lambda: paths)
    return paths


# ---------------------------------------------------------------------------
# Parser structure
# ---------------------------------------------------------------------------


class TestBootstrapParser:
    def test_bootstrap_is_a_valid_service_choice(self) -> None:
        # Regression for the documented-but-missing command: parsing 'bootstrap'
        # must NOT raise 'invalid choice'.
        parser = _build_parser()
        ns = parser.parse_args(["bootstrap", "--dry-run"])
        assert ns.service == "bootstrap"
        assert ns.dry_run is True
        assert ns.remove is False

    def test_remove_and_unregister_are_aliases(self) -> None:
        parser = _build_parser()
        assert parser.parse_args(["bootstrap", "--remove"]).remove is True
        assert parser.parse_args(["bootstrap", "--unregister"]).remove is True

    def test_bootstrap_help_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["bootstrap", "--help"])
        assert exc.value.code == 0


@pytest.mark.parametrize("options", [{}, {"dry_run": True}, {"remove": True}, {"remove": True, "dry_run": True}])
def test_cli_refuses_without_authority_and_never_writes(fake_paths, capsys, options):
    assert cmd_bootstrap(**options) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["reason_codes"] == ["context_required"]
    assert all(not path.exists() for path in fake_paths.values())


@pytest.mark.parametrize("argv", [["bootstrap"], ["bootstrap", "--dry-run"], ["bootstrap", "--unregister"]])
def test_main_reports_bounded_nonzero_refusal(fake_paths, capsys, argv):
    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == 1
    output = capsys.readouterr()
    assert json.loads(output.err)["reason_codes"] == ["context_required"]
    assert all(str(path) not in output.err for path in fake_paths.values())
    assert all(not path.exists() for path in fake_paths.values())


def test_cli_keeps_all_bounded_conflict_reasons(fake_paths, monkeypatch, capsys):
    from kp_mcp_bootstrap.registrars import ReasonCode, RegistrarError

    def conflict(**kwargs):
        raise RegistrarError(ReasonCode.OWNED_FIELD_DRIFT,
                             reason_codes=(ReasonCode.OWNED_FIELD_DRIFT, ReasonCode.POLICY_CONFLICT))
    monkeypatch.setattr(gk_bootstrap, "bootstrap", conflict)
    assert cmd_bootstrap(dry_run=True) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["reason_codes"] == ["owned_field_drift", "policy_conflict"]
    assert "native writer exclusion" in payload["next_action"]
    assert all(not path.exists() for path in fake_paths.values())
