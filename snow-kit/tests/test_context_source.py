"""Synthetic commit-pinned context source and safety tests."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from snow_kit.context.enforcement import query_context_warnings
from snow_kit.context.source import (
    _MAX_FILE_BYTES,
    GitHeadContextSource,
    _path_allowed,
)
from snow_kit.core.config import (
    CONFIG_PATH_ENV,
    CONTEXT_ALLOW_PATHS_KEY,
    SnowKitConfig,
    write_profile,
)
from snow_kit.core.errors import Unavailable, Validation
from snow_kit.mcp.resources import source_status
from snow_kit.services.context.core import context_get, context_search
from snow_kit.services.context.models import ContextGetInput, ContextSearchInput
from snow_kit.services.query.models import ContextReference


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def context_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "analytics"
    repo.mkdir()
    _git(repo, "init")
    (repo / "business-context" / "governance").mkdir(parents=True)
    (repo / "business-context" / "README.md").write_text(
        "# Governed business context\n",
        encoding="utf-8",
    )
    (repo / "business-context" / "governance" / "governance.md").write_text(
        "# Governance\n",
        encoding="utf-8",
    )
    (repo / "business-context" / "shop.md").write_text(
        """# Example Shop Returns

## Metadata & Ownership
Owner: owner@example.invalid

## Objective & Intended Use
Use the canonical return rate.

## Core Principles & Guidance
Exclude test orders.

## Data Sources & Joins
Use EXAMPLE_DB.SHOP.RETURNS. Never read /Users/private/source.

## Key Fields & Derived Metrics
Decline rate is returns divided by completed orders.
""",
        encoding="utf-8",
    )
    (repo / "sandbox").mkdir()
    (repo / "sandbox" / "secret.md").write_text(
        "# Secret return override\n",
        encoding="utf-8",
    )
    _commit(repo, "initial context")
    return repo


def test_search_reads_only_allowed_committed_blobs(context_repo: Path) -> None:
    source = GitHeadContextSource(
        context_repo,
        ("business-context/**/*.md", "sandbox/**/*.md"),
    )
    (context_repo / "business-context" / "shop.md").write_text(
        "# Dirty replacement that must not be read\n",
        encoding="utf-8",
    )
    (context_repo / "business-context" / "untracked.md").write_text(
        "# Untracked return data\n",
        encoding="utf-8",
    )

    result = source.search("return", limit=10)

    assert result["count"] == 1
    match = result["results"][0]
    assert match["title"] == "Example Shop Returns"
    assert match["metadata_complete"] is True
    assert "owner@example.invalid" not in match["snippet"]
    assert "[redacted-email]" in source.get(
        match["document_id"],
        result["revision"],
    )["content"]
    assert "[local-path]" in source.get(
        match["document_id"],
        result["revision"],
    )["content"]
    assert all("sandbox" not in item["provenance"]["relative_path"] for item in result["results"])
    assert any("only committed blobs" in warning for warning in result["warnings"])


def test_get_uses_the_exact_search_revision_after_head_moves(context_repo: Path) -> None:
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))
    result = source.search("return rate")
    match = result["results"][0]
    original_revision = result["revision"]
    path = context_repo / "business-context" / "shop.md"
    path.write_text("# Replacement\n\nNew semantics.\n", encoding="utf-8")
    _commit(context_repo, "replace context")

    document = source.get(match["document_id"], original_revision)

    assert document["provenance"]["revision"] == original_revision
    assert "canonical return rate" in document["content"]
    assert "New semantics" not in document["content"]


def test_search_no_match_has_safe_next_action(context_repo: Path) -> None:
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))

    result = source.search("nonexistenttopic")

    assert result["results"] == []
    assert "do not replace this with broad schema discovery" in result["next_action"]


def test_search_ranking_is_deterministic_for_ties(context_repo: Path) -> None:
    for name in ("zeta.md", "alpha.md"):
        (context_repo / "business-context" / name).write_text(
            "# Equal title\n\nSyntheticTieToken appears once.\n",
            encoding="utf-8",
        )
    _commit(context_repo, "add ranking tie")
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))

    first = source.search("SyntheticTieToken", limit=10)
    second = source.search("SyntheticTieToken", limit=10)

    assert first == second
    assert [
        item["provenance"]["relative_path"] for item in first["results"]
    ] == [
        "business-context/alpha.md",
        "business-context/zeta.md",
    ]


def test_missing_pinned_blob_is_unavailable_not_an_empty_result(
    context_repo: Path,
) -> None:
    blob = _git(
        context_repo,
        "rev-parse",
        "HEAD:business-context/shop.md",
    )
    loose_object = context_repo / ".git" / "objects" / blob[:2] / blob[2:]
    assert loose_object.is_file()
    loose_object.unlink()
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))

    with pytest.raises(Unavailable):
        source.search("return")


def test_oversized_document_is_skipped_with_an_explicit_warning(
    context_repo: Path,
) -> None:
    (context_repo / "business-context" / "oversized.md").write_text(
        "# Oversized\n\n" + ("oversized-token " * (_MAX_FILE_BYTES // 16 + 2)),
        encoding="utf-8",
    )
    _commit(context_repo, "add oversized context")
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))

    result = source.search("oversized-token")

    assert result["results"] == []
    assert any("per-file limit" in warning for warning in result["warnings"])


def test_corpus_limit_fails_as_unavailable(
    context_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("snow_kit.context.source._MAX_CORPUS_BYTES", 1)
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))

    with pytest.raises(Unavailable, match="corpus exceeds"):
        source.search("return")


@pytest.mark.parametrize(
    "path",
    [
        "../private.md",
        "/absolute.md",
        r"business-context\private.md",
        "business-context/data/private.md",
        "business-context/AGENTS.md",
    ],
)
def test_context_paths_fail_closed_before_allow_patterns(path: str) -> None:
    assert _path_allowed(path, ("**/*.md",)) is False


def test_conflict_and_unknown_freshness_are_signaled(context_repo: Path) -> None:
    original_branch = _git(context_repo, "branch", "--show-current")
    _git(context_repo, "checkout", "-b", "conflicting-change")
    card = context_repo / "business-context" / "shop.md"
    card.write_text("# Side change\n\nside conflict\n", encoding="utf-8")
    _commit(context_repo, "side change")
    _git(context_repo, "checkout", original_branch)
    card.write_text("# Main change\n\nmain conflict\n", encoding="utf-8")
    _commit(context_repo, "main change")
    merge = subprocess.run(
        [
            "git",
            "-C",
            str(context_repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "merge",
            "--no-ff",
            "conflicting-change",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert merge.returncode != 0
    assert _git(context_repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    assert "business-context/shop.md" in _git(context_repo, "ls-files", "-u")
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))

    result = source.search("main")
    status = source.status()

    assert any("unresolved Git conflicts" in warning for warning in result["warnings"])
    assert status.state == "freshness_unknown"
    assert any("no fetch was attempted" in warning for warning in status.warnings)


def test_merge_conflict_detected_via_merge_head_when_porcelain_empty(
    context_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_branch = _git(context_repo, "branch", "--show-current")
    _git(context_repo, "checkout", "-b", "conflicting-change")
    card = context_repo / "business-context" / "shop.md"
    card.write_text("# Side change\n\nside conflict\n", encoding="utf-8")
    _commit(context_repo, "side change")
    _git(context_repo, "checkout", original_branch)
    card.write_text("# Main change\n\nmain conflict\n", encoding="utf-8")
    _commit(context_repo, "main change")
    merge = subprocess.run(
        [
            "git",
            "-C",
            str(context_repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "merge",
            "--no-ff",
            "conflicting-change",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert merge.returncode != 0
    assert _git(context_repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    assert "business-context/shop.md" in _git(context_repo, "ls-files", "-u")
    real_git_text = GitHeadContextSource._git_text

    def _git_text_without_conflict_markers(
        self: GitHeadContextSource,
        *args: str,
    ) -> str:
        if args == ("status", "--porcelain=v1", "--untracked-files=normal"):
            return ""
        if args in {
            ("ls-files", "-u", "--full-name"),
            ("diff", "--name-only", "--diff-filter=U"),
        }:
            return ""
        return real_git_text(self, *args)

    monkeypatch.setattr(
        GitHeadContextSource,
        "_git_text",
        _git_text_without_conflict_markers,
    )
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))

    warnings = source._working_tree_warnings()

    assert any("unresolved Git conflicts" in warning for warning in warnings)


def test_get_rejects_unknown_document_id(context_repo: Path) -> None:
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))
    revision = _git(context_repo, "rev-parse", "HEAD")

    with pytest.raises(Validation, match="not found"):
        source.get("0" * 24, revision)


def test_query_context_reference_is_validated_against_pinned_source(
    context_repo: Path,
) -> None:
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))
    result = source.search("return")
    match = result["results"][0]
    config = SnowKitConfig(
        context_repo=context_repo,
        context_allow_paths=("business-context/**/*.md",),
        context_mode="strict",
    )

    warnings = query_context_warnings(
        "SELECT * FROM EXAMPLE_DB.SHOP.RETURNS",
        [
            ContextReference(
                document_id=match["document_id"],
                revision=result["revision"],
            )
        ],
        config=config,
    )

    assert warnings == []
    with pytest.raises(Validation, match="invalid"):
        query_context_warnings(
            "SELECT * FROM EXAMPLE_DB.SHOP.RETURNS",
            [
                ContextReference(
                    document_id="0" * 24,
                    revision=result["revision"],
                )
            ],
            config=config,
        )


def test_dynamic_resource_status_is_redacted(
    context_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "config.env"
    write_profile(
        {
            "SNOW_KIT_CONTEXT_REPO": str(context_repo),
            CONTEXT_ALLOW_PATHS_KEY: '["business-context/**/*.md"]',
        },
        path=profile,
    )
    monkeypatch.setenv(CONFIG_PATH_ENV, str(profile))

    payload = source_status()
    search_output = context_search(ContextSearchInput(query="return"))
    get_output = context_get(
        ContextGetInput(
            document_id=search_output.data.results[0].document_id,
            revision=search_output.data.revision,
            max_chars=500,
        )
    )

    assert payload["source_count"] == 1
    assert payload["sources"][0]["document_count"] == 3
    assert get_output.data.provenance.revision == search_output.data.revision
    assert len(get_output.data.content) <= 500
    assert str(context_repo) not in str(payload)
    assert "example.invalid" not in str(payload)


def test_git_env_redirect_cannot_override_configured_context_repo(
    context_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "-C", str(other), "init"], check=True, capture_output=True)
    (other / "business-context").mkdir()
    (other / "business-context" / "shop.md").write_text(
        "# Wrong repo\n\nwrong return semantics\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(other),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "add",
            ".",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(other),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "other",
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))
    result = source.search("return")

    assert result["count"] == 1
    assert result["results"][0]["title"] == "Example Shop Returns"


def test_validate_references_rejects_malicious_revision_before_git(
    context_repo: Path,
) -> None:
    source = GitHeadContextSource(context_repo, ("business-context/**/*.md",))

    with pytest.raises(Validation, match="revision is invalid"):
        source.validate_references([("0" * 24, "--upload-pack=evil")])
