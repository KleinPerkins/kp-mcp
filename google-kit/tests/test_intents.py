"""E6 intent resolver + help surfaces + manifest determinism.

Covers core/manifest.resolve_intent ranking and determinism, the CLI
`help <intent>` command, the MCP `help` meta-tool, and aliases_gen determinism
(docs/INTENTS.md never drifts from the registry).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from dataclasses import fields
from pathlib import Path

import pytest

import google_kit  # noqa: F401 — register all
from google_kit.core.manifest import (
    _CURATED_ALIASES,
    IntentMatch,
    curated_aliases,
    op_triggers,
    resolve_intent,
)


class TestResolveIntent:
    @pytest.mark.parametrize(
        "query,expected_top",
        [
            ("send an email", "gmail.send"),
            ("create a spreadsheet", "sheets.create"),
            ("find a file", "drive.search"),
            ("schedule a meeting", "calendar.create"),
            ("who changed a file", "drive_activity.query"),
            ("add a todo", "tasks.create"),
            ("share a file", "drive.permissions"),
            ("make a presentation", "slides.create"),
            ("find a coworker", "people.search_directory"),
            ("check my inbox", "gmail.list"),
        ],
    )
    def test_curated_intents_rank_top(self, query: str, expected_top: str) -> None:
        matches = resolve_intent(query, limit=5)
        assert matches, f"no match for {query!r}"
        assert matches[0].op == expected_top, (
            f"{query!r} → {matches[0].op} (expected {expected_top}); top5="
            f"{[(m.op, m.score) for m in matches]}"
        )

    def test_exact_op_name_resolves_to_itself(self) -> None:
        assert resolve_intent("drive.fetch")[0].op == "drive.fetch"
        assert resolve_intent("drive fetch")[0].op == "drive.fetch"

    def test_deterministic(self) -> None:
        a = resolve_intent("share a document with someone", limit=5)
        b = resolve_intent("share a document with someone", limit=5)
        assert [(m.op, m.score, m.matched) for m in a] == [(m.op, m.score, m.matched) for m in b]

    def test_limit_respected(self) -> None:
        assert len(resolve_intent("file", limit=3)) <= 3

    def test_no_match_returns_empty(self) -> None:
        assert resolve_intent("zzzqqq nonsense xyzzy") == []

    def test_scores_sorted_descending(self) -> None:
        ms = resolve_intent("create a file in drive", limit=10)
        scores = [m.score for m in ms]
        assert scores == sorted(scores, reverse=True)

    def test_match_is_frozen_dataclass(self) -> None:
        m = resolve_intent("send an email")[0]
        assert isinstance(m, IntentMatch)
        assert [field.name for field in fields(IntentMatch)] == [
            "op",
            "score",
            "matched",
        ]
        with pytest.raises(Exception):
            m.op = "x"  # type: ignore[misc]


class TestTriggers:
    def test_curated_aliases_lookup(self) -> None:
        assert "send an email" in curated_aliases("gmail.send")
        assert curated_aliases("nonexistent.op") == ()

    def test_op_triggers_include_name_and_service_synonyms(self) -> None:
        t = op_triggers_for("gmail.send")
        assert "gmail" in t and "send" in t  # name tokens
        assert "email" in t and "mail" in t  # service synonyms

    def test_every_curated_op_exists_in_registry(self) -> None:
        names = {s.name for s in google_kit.registry.all_specs()}
        missing = set(_CURATED_ALIASES) - names
        assert missing == set(), f"curated aliases reference unknown ops: {missing}"


def op_triggers_for(name: str) -> set[str]:
    from google_kit.registry import get

    return op_triggers(get(name))


class TestCliHelp:
    def test_help_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        from google_kit.cli import main

        with pytest.raises(SystemExit) as ei:
            main(["help", "send", "an", "email"])
        assert ei.value.code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["intent"] == "send an email"
        assert out["matches"][0]["op"] == "gmail.send"
        assert out["matches"][0]["cli"] == "google-kit gmail send"
        assert out["matches"][0]["summary"]

    def test_help_text_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        from google_kit.cli import main

        with pytest.raises(SystemExit) as ei:
            main(["--format", "text", "help", "schedule", "a", "meeting"])
        assert ei.value.code == 0
        out = capsys.readouterr().out
        assert "google-kit calendar create" in out

    def test_help_empty_intent_errors(self) -> None:
        from google_kit.cli import main

        with pytest.raises(SystemExit) as ei:
            main(["help"])
        assert ei.value.code == 1

    def test_help_no_match_errors(self) -> None:
        from google_kit.cli import main

        with pytest.raises(SystemExit) as ei:
            main(["help", "zzzqqq", "xyzzy"])
        assert ei.value.code == 1


class TestMcpHelpTool:
    def _list_tools(self) -> list:
        import asyncio

        from mcp.types import ListToolsRequest

        from google_kit.mcp import build_mcp_server

        server = build_mcp_server()
        handler = server.request_handlers[ListToolsRequest]

        async def _run():
            return await handler(ListToolsRequest(method="tools/list", params=None))

        result = asyncio.run(_run())
        return getattr(result, "root", result).tools

    def test_help_tool_listed(self) -> None:
        names = {t.name for t in self._list_tools()}
        assert "help" in names

    def test_help_tool_schema_requires_intent(self) -> None:
        tool = next(t for t in self._list_tools() if t.name == "help")
        assert tool.inputSchema["required"] == ["intent"]

    def test_help_tool_call_resolves(self) -> None:
        import asyncio

        from mcp.types import CallToolRequest

        from google_kit.mcp import build_mcp_server

        server = build_mcp_server()
        handler = server.request_handlers[CallToolRequest]

        async def _run():
            req = CallToolRequest(
                method="tools/call",
                params={"name": "help", "arguments": {"intent": "send an email", "limit": 3}},
            )
            return await handler(req)

        result = asyncio.run(_run())
        root = getattr(result, "root", result)
        payload = json.loads(root.content[0].text)
        assert payload["matches"][0]["op"] == "gmail.send"
        assert len(payload["matches"]) <= 3


class TestManifestDeterminism:
    def test_aliases_gen_deterministic(self, tmp_path: Path) -> None:
        from google_kit.aliases_gen import generate

        p1 = tmp_path / "a.md"
        p2 = tmp_path / "b.md"
        generate(manifest_path=p1)
        generate(manifest_path=p2)
        assert p1.read_text() == p2.read_text()

    def test_committed_manifest_matches_fresh_generation(self, tmp_path: Path) -> None:
        from google_kit.aliases_gen import _manifest_path, generate

        committed = _manifest_path()
        assert committed.exists(), "docs/INTENTS.md missing — run aliases_gen"
        fresh = tmp_path / "fresh.md"
        generate(manifest_path=fresh)
        assert fresh.read_text() == committed.read_text(), (
            "docs/INTENTS.md is stale — run `uv run python -m google_kit.aliases_gen`"
        )


class TestSharedEngineCompatibility:
    def test_exhaustive_e6_baseline_is_unchanged(self) -> None:
        from google_kit.cli import cmd_help
        from google_kit.core.manifest import _SERVICE_TRIGGERS
        from google_kit.mcp import _resolve_help
        from google_kit.registry import all_specs

        baseline_path = (
            Path(__file__).parents[1]
            / "fixtures"
            / "golden"
            / "intents"
            / "e6_baseline.json"
        )
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        assert (
            baseline["baseline_commit"]
            == "ae4c7c9346adcb1e1f549840a59d60e3814d9420"
        )
        cases: list[tuple[str, str, str]] = []
        for spec in sorted(all_specs(), key=lambda item: item.name):
            cases.append(("op", spec.name, spec.name))
            cases.append(("cli", spec.name, spec.name.replace(".", " ")))
            for value in _CURATED_ALIASES.get(spec.name, ()):
                cases.append(("curated", spec.name, value))
            for value in spec.aliases:
                cases.append(("alias", spec.name, str(value)))
            for value in spec.keywords:
                cases.append(("keyword", spec.name, str(value)))
        for service, values in sorted(_SERVICE_TRIGGERS.items()):
            for value in values:
                cases.append(("service", service, value))

        resolver_rows = []
        cli_rows = []
        mcp_rows = []
        for kind, owner, query in cases:
            resolver_rows.append(
                {
                    "kind": kind,
                    "owner": owner,
                    "query": query,
                    "matches": [
                        [match.op, match.score, list(match.matched)]
                        for match in resolve_intent(query, limit=999)
                    ],
                }
            )
            stdout = io.StringIO()
            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                return_code = cmd_help(query, limit=5, fmt="json")
            cli_rows.append([kind, owner, query, return_code, stdout.getvalue()])
            mcp_rows.append(
                [kind, owner, query, _resolve_help({"intent": query, "limit": 5})]
            )

        kind_counts = {
            kind: sum(1 for row in cases if row[0] == kind)
            for kind in sorted({row[0] for row in cases})
        }
        assert len(cases) == baseline["case_count"]
        assert kind_counts == baseline["kind_counts"]
        assert _digest(resolver_rows) == baseline["resolver_sha256"]
        assert _digest(cli_rows) == baseline["cli_json_sha256"]
        assert _digest(mcp_rows) == baseline["mcp_json_sha256"]
        docs_root = Path(__file__).parents[1] / "docs"
        docs_rows = [
            [
                path.relative_to(docs_root).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            ]
            for path in sorted(docs_root.rglob("*"))
            if path.is_file()
        ]
        delta = json.loads((baseline_path.parent / "registrar_0_3_doc_delta.json").read_text())
        assert delta["schema"] == "kp-mcp/doc-compatibility-delta/v1"
        assert delta["baseline_commit"] == baseline["baseline_commit"]
        assert delta["path"] == "QUICKSTART.md"
        native_delta = json.loads((baseline_path.parent / "native_doc_style_doc_delta.json").read_text())
        assert native_delta["schema"] == "kp-mcp/native-doc-style-compatibility-delta/v1"
        assert native_delta["baseline_commit"] == baseline["baseline_commit"]
        assert native_delta["accepted_source_commit"] == "10fd36075c9c50c18460eee1cf08a67f6fcb67f2"
        assert native_delta["accepted_source_parent"] == "140959003cea1634811f691a742081419804133a"
        assert native_delta["source_pull_request"] == 98
        native_files = {row["path"]: row for row in native_delta["files"]}
        assert len(native_delta["files"]) == 2
        assert set(native_files) == {"INDEX.md", "QUICKSTART.md"}
        # Keep the historical E6 fixture immutable. Only the explicit registrar
        # Quickstart delta and the exact accepted native-style doc successor are
        # normalized in reverse acceptance order. Every other byte stays exact.
        normalized_rows = []
        for name, digest in docs_rows:
            if name in native_files:
                assert digest == native_files[name]["after_sha256"]
                digest = native_files[name]["before_sha256"]
            if name == delta["path"]:
                assert digest == delta["after_sha256"]
                digest = delta["before_sha256"]
            normalized_rows.append([name, digest])
        assert len(normalized_rows) == baseline["docs_file_count"]
        assert _digest(normalized_rows) == baseline["docs_tree_sha256"]
        assert len(resolve_intent("file", limit=-1)) == baseline["legacy_limit_cases"][
            "negative_one_count"
        ]
        assert len(resolve_intent("file", limit=999)) == baseline[
            "legacy_limit_cases"
        ]["large_count"]


def _digest(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(raw).hexdigest()
