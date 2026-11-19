"""CI discovery output must remain data, never shell syntax."""

from __future__ import annotations

import json

from tools import ci_discover


def test_lint_paths_json_round_trips_shell_metacharacters(tmp_path, capsys) -> None:
    member = tmp_path / "unsafe $(touch injected)-kit"
    member.mkdir()
    (member / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")

    assert ci_discover._cmd_lint_paths_json(tmp_path) == 0

    assert json.loads(capsys.readouterr().out) == [member.name]
