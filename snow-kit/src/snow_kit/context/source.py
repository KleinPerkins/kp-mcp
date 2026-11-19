"""Secure Git-HEAD analytics context source with deterministic bounded retrieval."""
from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from snow_kit.core.config import SnowKitConfig
from snow_kit.core.errors import (
    Timeout as SnowKitTimeout,
    Unavailable,
    Validation,
)

_SOURCE_ID = "analytics-git-head"
_MAX_FILES = 1_000
_MAX_FILE_BYTES = 256 * 1024
_MAX_CORPUS_BYTES = 5 * 1024 * 1024
_MAX_SEARCH_SECONDS = 2.0
_MAX_SNIPPET_CHARS = 700
_MAX_GET_CHARS = 12_000
_DENIED_SEGMENTS = frozenset(
    {
        ".claude",
        ".cursor",
        ".git",
        "archive",
        "archives",
        "binary",
        "binaries",
        "data",
        "datasets",
        "instruction",
        "instructions",
        "node_modules",
        "prompt",
        "prompts",
        "rule",
        "rules",
        "sandbox",
        "sandboxes",
        "skill",
        "skills",
    }
)
_DENIED_FILENAMES = frozenset(
    {"agents.md", "claude.md", "skill.md", "prompt.md", "instructions.md"}
)
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_HOME_PATH_RE = re.compile(r"(?:/Users|/home)/[^/\s`]+(?:/[^\s`)]*)?")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")
_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_DEFAULT_PATTERN = "business-context/**/*.md"
_GOVERNANCE_MARKERS = (
    "business-context/README.md",
    "business-context/governance/governance.md",
)


@dataclass(frozen=True)
class SourceStatus:
    state: str
    configured: bool
    revision: str | None = None
    document_count: int = 0
    freshness: str = "unknown"
    authority: str = "unverified"
    warnings: tuple[str, ...] = ()
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": _SOURCE_ID,
            "state": self.state,
            "configured": self.configured,
            "revision": self.revision,
            "document_count": self.document_count,
            "freshness": self.freshness,
            "authority": self.authority,
            "warnings": list(self.warnings),
            "message": self.message,
        }


@dataclass(frozen=True)
class _TreeEntry:
    path: str
    object_id: str
    size: int


@dataclass(frozen=True)
class _Document:
    path: str
    document_id: str
    revision: str
    content: str
    title: str
    metadata_complete: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class GitHeadContextSource:
    """Read only explicitly allowed Markdown blobs from one local Git commit."""

    root: Path
    allow_paths: tuple[str, ...]

    def status(self) -> SourceStatus:
        try:
            revision = self._resolve_revision()
            entries, warnings = self._entries(revision)
            if not entries:
                return SourceStatus(
                    state="context_unavailable",
                    configured=True,
                    revision=revision,
                    message="No tracked Markdown documents match the approved context paths.",
                )
            freshness, freshness_warnings = self._freshness(revision)
            authority = (
                "governed"
                if self._has_governance_markers(revision)
                else "operator-approved"
            )
            warnings.extend(freshness_warnings)
            warnings.extend(self._working_tree_warnings())
            return SourceStatus(
                state="ready" if freshness == "current" else "freshness_unknown",
                configured=True,
                revision=revision,
                document_count=len(entries),
                freshness=freshness,
                authority=authority,
                warnings=tuple(_dedupe(warnings)),
                message="Authoritative context is available from a pinned local Git revision.",
            )
        except (PermissionError, OSError):
            return SourceStatus(
                state="access_denied",
                configured=True,
                message="The configured context checkout cannot be read by this operator.",
            )
        except (SnowKitTimeout, Unavailable, Validation):
            return SourceStatus(
                state="context_unavailable",
                configured=True,
                message=(
                    "The configured context source is unavailable. Run `snow-kit repair` "
                    "or update the approved checkout with `snow-kit setup`."
                ),
            )

    def search(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        tokens = _query_tokens(query)
        if not 1 <= limit <= 10:
            raise Validation("context.search limit must be between 1 and 10", op="context.search")
        started = time.monotonic()
        revision = self._resolve_revision()
        documents, source_warnings = self._documents(revision, started=started)
        _freshness, freshness_warnings = self._freshness(revision)
        authority = (
            "governed"
            if self._has_governance_markers(revision)
            else "operator-approved"
        )
        ranked: list[tuple[int, str, _Document]] = []
        for document in documents:
            score = _score(document, tokens)
            if score > 0:
                ranked.append((-score, document.path.casefold(), document))
        ranked.sort(key=lambda item: (item[0], item[1]))
        selected = ranked[:limit]
        results = [
            {
                "document_id": document.document_id,
                "title": document.title,
                "snippet": _snippet(document.content, tokens),
                "score": -score,
                "authority": authority,
                "metadata_complete": document.metadata_complete,
                "provenance": {
                    "source_id": _SOURCE_ID,
                    "revision": revision,
                    "relative_path": _redacted_relative_path(document.path),
                },
                "warnings": list(document.warnings),
            }
            for score, _path, document in selected
        ]
        warnings = [
            *source_warnings,
            *freshness_warnings,
            *self._working_tree_warnings(),
        ]
        next_action = None
        if not results:
            next_action = (
                "No approved context matched. Refine the context query or ask the operator "
                "which governed source applies; do not replace this with broad schema discovery."
            )
        return {
            "query": _redact(query.strip(), root=self.root),
            "revision": revision,
            "results": results,
            "count": len(results),
            "truncated": len(ranked) > limit,
            "next_action": next_action,
            "warnings": _dedupe(warnings),
        }

    def get(
        self,
        document_id: str,
        revision: str,
        *,
        section: str | None = None,
        max_chars: int = 6_000,
    ) -> dict[str, Any]:
        _validate_document_id(document_id, op="context.get")
        _validate_revision(revision, op="context.get")
        if not 200 <= max_chars <= _MAX_GET_CHARS:
            raise Validation(
                f"context.get max_chars must be between 200 and {_MAX_GET_CHARS}",
                op="context.get",
            )
        started = time.monotonic()
        documents, source_warnings = self._documents(revision, started=started)
        _freshness, freshness_warnings = self._freshness(revision)
        document = next(
            (item for item in documents if item.document_id == document_id),
            None,
        )
        if document is None:
            raise Validation(
                "context.get document_id was not found in the approved paths at that revision",
                op="context.get",
            )
        content = document.content
        selected_section = None
        if section:
            content, selected_section = _extract_section(content, section)
        truncated = len(content) > max_chars
        if truncated:
            marker = "\n[truncated]"
            content = content[: max_chars - len(marker)].rstrip() + marker
        return {
            "document_id": document.document_id,
            "title": document.title,
            "section": selected_section,
            "content": content,
            "truncated": truncated,
            "authority": (
                "governed"
                if self._has_governance_markers(revision)
                else "operator-approved"
            ),
            "metadata_complete": document.metadata_complete,
            "provenance": {
                "source_id": _SOURCE_ID,
                "revision": revision,
                "relative_path": _redacted_relative_path(document.path),
            },
            "warnings": _dedupe(
                [*source_warnings, *freshness_warnings, *document.warnings]
            ),
        }

    def validate_references(self, references: Iterable[tuple[str, str]]) -> None:
        by_revision: dict[str, set[str]] = {}
        for document_id, revision in references:
            _validate_document_id(document_id)
            _validate_revision(revision)
            by_revision.setdefault(revision, set()).add(document_id)
        if len(by_revision) > 1:
            raise Validation(
                "All context references for one query must use the same pinned revision.",
                op="query.context_refs",
            )
        for revision, wanted in by_revision.items():
            documents, _warnings = self._documents(revision, started=time.monotonic())
            available = {document.document_id for document in documents}
            missing = wanted - available
            if missing:
                raise Validation(
                    "A context reference is invalid or outside the approved source paths.",
                    op="query.context_refs",
                )

    def _resolve_revision(self) -> str:
        self._validate_root()
        revision = self._git_text("rev-parse", "--verify", "HEAD^{commit}").strip()
        if not re.fullmatch(r"[a-f0-9]{40,64}", revision):
            raise Unavailable("context checkout has no valid HEAD commit", op="context")
        return revision

    def _validate_root(self) -> None:
        try:
            info = self.root.lstat()
        except FileNotFoundError as exc:
            raise Unavailable("configured context checkout is missing", op="context") from exc
        except PermissionError:
            raise
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise Unavailable(
                "configured context checkout must be a regular non-symlink directory",
                op="context",
            )
        inside = self._git_text("rev-parse", "--is-inside-work-tree").strip()
        if inside != "true":
            raise Unavailable("configured context checkout is not a Git worktree", op="context")

    def _entries(self, revision: str) -> tuple[list[_TreeEntry], list[str]]:
        raw = self._git_bytes(
            "ls-tree",
            "-r",
            "-l",
            "-z",
            "--full-tree",
            revision,
        )
        entries: list[_TreeEntry] = []
        warnings: list[str] = []
        total_bytes = 0
        for record in raw.split(b"\x00"):
            if not record:
                continue
            try:
                metadata, raw_path = record.split(b"\t", 1)
                mode, kind, object_id, raw_size = metadata.decode("ascii").split()
                path = raw_path.decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise Unavailable("context Git tree contains an invalid entry", op="context") from exc
            allowed_path = _path_allowed(path, self.allow_paths)
            if kind != "blob" or mode not in {"100644", "100755"}:
                if allowed_path:
                    warnings.append(
                        "One or more approved paths were symlinks or submodules and were denied."
                    )
                continue
            if mode == "100755":
                if allowed_path:
                    warnings.append(
                        "One or more approved Markdown files were executable and were denied."
                    )
                continue
            if not allowed_path:
                continue
            try:
                size = int(raw_size)
            except ValueError as exc:
                raise Unavailable("context Git tree is missing blob sizes", op="context") from exc
            if size > _MAX_FILE_BYTES:
                warnings.append("One or more approved documents exceeded the per-file limit.")
                continue
            total_bytes += size
            if total_bytes > _MAX_CORPUS_BYTES:
                raise Unavailable(
                    "approved context corpus exceeds the bounded source size",
                    op="context",
                )
            entries.append(_TreeEntry(path=path, object_id=object_id, size=size))
            if len(entries) > _MAX_FILES:
                raise Unavailable(
                    "approved context corpus exceeds the bounded file count",
                    op="context",
                )
        return sorted(entries, key=lambda item: item.path.casefold()), warnings

    def _documents(
        self,
        revision: str,
        *,
        started: float,
    ) -> tuple[list[_Document], list[str]]:
        entries, warnings = self._entries(revision)
        if not entries:
            raise Unavailable(
                "no tracked Markdown documents match the approved context paths",
                op="context",
            )
        documents: list[_Document] = []
        blobs = self._git_blobs(entries)
        for entry in entries:
            if time.monotonic() - started > _MAX_SEARCH_SECONDS:
                raise SnowKitTimeout(
                    "context retrieval exceeded its local time limit",
                    op="context",
                )
            raw = blobs[entry.object_id]
            if raw.startswith(_LFS_PREFIX):
                warnings.append("One or more approved documents were Git LFS pointers and were denied.")
                continue
            try:
                original = raw.decode("utf-8")
            except UnicodeDecodeError:
                warnings.append("One or more approved documents were not valid UTF-8 and were denied.")
                continue
            content = _redact(original, root=self.root)
            documents.append(
                _Document(
                    path=entry.path,
                    document_id=_document_id(revision, entry.path),
                    revision=revision,
                    content=content,
                    title=_redact(_title(content, entry.path), root=self.root),
                    metadata_complete=_metadata_complete(original),
                )
            )
        if not documents:
            raise Unavailable(
                "approved context paths contain no readable Markdown documents",
                op="context",
            )
        warnings.extend(self._working_tree_warnings())
        return documents, _dedupe(warnings)

    def _working_tree_warnings(self) -> list[str]:
        try:
            status = self._git_text(
                "status",
                "--porcelain=v1",
                "--untracked-files=normal",
            )
        except Unavailable:
            status = ""
        warnings: list[str] = []
        if status:
            warnings.append(
                "The checkout has local changes; only committed blobs from the pinned revision were read."
            )
        if self._has_unresolved_merge_conflicts(status):
            warnings.append(
                "The checkout has unresolved Git conflicts; committed context may require operator review."
            )
        return warnings

    def _has_unresolved_merge_conflicts(self, status: str = "") -> bool:
        conflict_codes = {"AA", "DD", "AU", "UA", "DU", "UD", "UU"}
        if any(
            len(line) >= 2
            and (line[:2] in conflict_codes or "U" in line[:2])
            for line in status.splitlines()
        ):
            return True
        if self._merge_head_exists():
            return True
        for args in (
            ("ls-files", "-u", "--full-name"),
            ("diff", "--name-only", "--diff-filter=U"),
        ):
            try:
                if self._git_text(*args).strip():
                    return True
            except Unavailable:
                continue
        return False

    def _merge_head_exists(self) -> bool:
        try:
            self._git_bytes("rev-parse", "-q", "--verify", "MERGE_HEAD")
        except Unavailable:
            return False
        return True

    def _git_blobs(self, entries: list[_TreeEntry]) -> dict[str, bytes]:
        if not entries:
            return {}
        env = self._git_env()
        requested = b"".join(
            entry.object_id.encode("ascii") + b"\n"
            for entry in entries
        )
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), "cat-file", "--batch"],
                input=requested,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=2,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SnowKitTimeout(
                "the bounded local Git blob read timed out",
                op="context",
            ) from exc
        except OSError as exc:
            raise Unavailable("local context Git batch read failed", op="context") from exc
        if result.returncode != 0 or len(result.stdout) > _MAX_CORPUS_BYTES + _MAX_FILE_BYTES:
            raise Unavailable(
                "local context Git blobs are unavailable within bounded limits",
                op="context",
            )
        stream = io.BytesIO(result.stdout)
        blobs: dict[str, bytes] = {}
        for entry in entries:
            try:
                header = stream.readline().decode("ascii", errors="strict").strip().split()
            except UnicodeDecodeError as exc:
                raise Unavailable(
                    "context Git batch returned an invalid header",
                    op="context",
                ) from exc
            if len(header) != 3 or header[0] != entry.object_id or header[1] != "blob":
                raise Unavailable("context Git batch returned an invalid blob", op="context")
            try:
                size = int(header[2])
            except ValueError as exc:
                raise Unavailable("context Git batch returned an invalid size", op="context") from exc
            if size != entry.size:
                raise Unavailable("context Git blob size changed unexpectedly", op="context")
            data = stream.read(size)
            if len(data) != size or stream.read(1) != b"\n":
                raise Unavailable("context Git batch output was truncated", op="context")
            blobs[entry.object_id] = data
        if stream.read(1):
            raise Unavailable("context Git batch returned unexpected output", op="context")
        return blobs

    def _freshness(self, revision: str) -> tuple[str, list[str]]:
        try:
            upstream = self._git_text(
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            ).strip()
            upstream_revision = self._git_text("rev-parse", "--verify", upstream).strip()
        except (SnowKitTimeout, Unavailable):
            return "unknown", [
                "Remote freshness is unknown because no local tracking ref is available; no fetch was attempted."
            ]
        if upstream_revision == revision:
            return "current", []
        try:
            counts = self._git_text(
                "rev-list",
                "--left-right",
                "--count",
                f"{revision}...{upstream_revision}",
            ).split()
            ahead, behind = (int(value) for value in counts)
        except (SnowKitTimeout, Unavailable, ValueError):
            return "unknown", [
                "Remote freshness is unknown from local refs; no fetch was attempted."
            ]
        if behind and not ahead:
            return "behind", [
                "The context checkout is behind its already-known tracking ref; update it outside snow-kit."
            ]
        if ahead and not behind:
            return "ahead", [
                "The context checkout is ahead of its already-known tracking ref."
            ]
        return "diverged", [
            "The context checkout has diverged from its already-known tracking ref."
        ]

    def _has_governance_markers(self, revision: str) -> bool:
        try:
            tracked = {
                line
                for line in self._git_text(
                    "ls-tree",
                    "-r",
                    "--name-only",
                    revision,
                    "--",
                    *_GOVERNANCE_MARKERS,
                ).splitlines()
                if line
            }
        except (SnowKitTimeout, Unavailable):
            return False
        return set(_GOVERNANCE_MARKERS).issubset(tracked)

    def _git_text(self, *args: str) -> str:
        try:
            return self._git_bytes(*args).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Unavailable("context Git command returned invalid UTF-8", op="context") from exc

    def _git_bytes(self, *args: str) -> bytes:
        env = self._git_env()
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=2,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SnowKitTimeout(
                "the bounded local Git read timed out",
                op="context",
            ) from exc
        except OSError as exc:
            raise Unavailable("local context Git command failed", op="context") from exc
        if result.returncode != 0:
            raise Unavailable(
                "local context Git data is unavailable; no network fetch was attempted",
                op="context",
            )
        if len(result.stdout) > _MAX_CORPUS_BYTES + _MAX_FILE_BYTES:
            raise Unavailable("local context Git output exceeded its bounded limit", op="context")
        return result.stdout

    @staticmethod
    def _git_env() -> dict[str, str]:
        return _sanitized_git_env()


def build_context_source(config: SnowKitConfig | None = None) -> GitHeadContextSource | None:
    """Build the one configured context source, or return None when unconfigured."""
    resolved = config or SnowKitConfig.from_env()
    if not resolved.context_repo or not resolved.context_allow_paths:
        return None
    return GitHeadContextSource(
        root=resolved.context_repo,
        allow_paths=resolved.context_allow_paths,
    )


def context_source_status(config: SnowKitConfig | None = None) -> SourceStatus:
    """Return redacted source health without exposing local checkout details."""
    try:
        resolved = config or SnowKitConfig.from_env()
        source = build_context_source(resolved)
    except (ValueError, OSError):
        return SourceStatus(
            state="access_denied",
            configured=True,
            message="The local context profile could not be read safely.",
        )
    if source is None:
        partially_configured = bool(
            resolved.context_repo or resolved.context_allow_paths
        )
        return SourceStatus(
            state="context_unavailable",
            configured=partially_configured,
            message=(
                "The authoritative analytics context source is incomplete. "
                "Run `snow-kit setup --context-repo <checkout> --context-path <approved.md>`."
                if partially_configured
                else "No authoritative analytics context source is configured. "
                "Run `snow-kit setup --context-repo <checkout>`."
            ),
        )
    return source.status()


def validate_default_context_governance(root: Path) -> bool:
    """Allow setup's default business-context glob only for a governed checkout."""
    source = GitHeadContextSource(root=root, allow_paths=(_DEFAULT_PATTERN,))
    revision = source._resolve_revision()
    return source._has_governance_markers(revision)


def default_context_pattern() -> str:
    return _DEFAULT_PATTERN


def _sanitized_git_env() -> dict[str, str]:
    """Drop inherited GIT_* variables so local subprocess reads stay repo-local."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_CONFIG_KEY_1": "core.hooksPath",
            "GIT_CONFIG_VALUE_1": os.devnull,
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _validate_document_id(document_id: str, *, op: str = "query.context_refs") -> None:
    if not re.fullmatch(r"[a-f0-9]{24}", document_id):
        raise Validation("context reference document_id is invalid", op=op)


def _validate_revision(revision: str, *, op: str = "query.context_refs") -> None:
    if not re.fullmatch(r"[a-f0-9]{40,64}", revision):
        raise Validation("context reference revision is invalid", op=op)


def _path_allowed(path: str, patterns: tuple[str, ...]) -> bool:
    if not path or path.startswith("/") or "\\" in path:
        return False
    parts = path.split("/")
    lowered = [part.casefold() for part in parts]
    if (
        any(part in {"", ".", ".."} for part in parts)
        or any(part.startswith(".") or part in _DENIED_SEGMENTS for part in lowered)
        or lowered[-1] in _DENIED_FILENAMES
        or not lowered[-1].endswith(".md")
    ):
        return False
    return any(_glob_match(path, pattern) for pattern in patterns)


def _glob_match(path: str, pattern: str) -> bool:
    path_parts = path.split("/")
    pattern_parts = pattern.split("/")

    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        token = pattern_parts[pattern_index]
        if token == "**":
            return match(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and match(path_index + 1, pattern_index)
            )
        if path_index >= len(path_parts):
            return False
        expression = "^" + re.escape(token).replace(r"\*", "[^/]*").replace(r"\?", "[^/]") + "$"
        return bool(re.fullmatch(expression, path_parts[path_index])) and match(
            path_index + 1,
            pattern_index + 1,
        )

    return match(0, 0)


def _query_tokens(query: str) -> tuple[str, ...]:
    stripped = query.strip()
    if not stripped or len(stripped) > 500:
        raise Validation(
            "context.search query must contain 1-500 characters",
            op="context.search",
        )
    tokens = tuple(dict.fromkeys(token.casefold() for token in _TOKEN_RE.findall(stripped)))
    if not tokens or len(tokens) > 20:
        raise Validation(
            "context.search query must contain 1-20 searchable terms",
            op="context.search",
        )
    return tokens


def _score(document: _Document, tokens: tuple[str, ...]) -> int:
    title = document.title.casefold()
    path = document.path.casefold()
    body = document.content.casefold()
    score = 0
    for token in tokens:
        score += 10 * title.count(token)
        score += 4 * path.count(token)
        score += min(body.count(token), 20)
    phrase = " ".join(tokens)
    if len(tokens) > 1 and phrase in body:
        score += 20
    return score


def _snippet(content: str, tokens: tuple[str, ...]) -> str:
    folded = content.casefold()
    positions = [folded.find(token) for token in tokens if folded.find(token) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - _MAX_SNIPPET_CHARS // 3)
    prefix = "… " if start else ""
    available = _MAX_SNIPPET_CHARS - len(prefix)
    end = min(len(content), start + available)
    suffix = " …" if end < len(content) else ""
    if suffix:
        end = max(start, end - len(suffix))
    snippet = re.sub(r"\s+", " ", content[start:end]).strip()
    return f"{prefix}{snippet}{suffix}"


def _extract_section(content: str, requested: str) -> tuple[str, str]:
    requested_key = requested.strip().casefold()
    if not requested_key or len(requested_key) > 200:
        raise Validation("context.get section is invalid", op="context.get")
    headings = list(_HEADING_RE.finditer(content))
    for index, heading in enumerate(headings):
        title = heading.group(2).strip()
        if title.casefold() != requested_key:
            continue
        level = len(heading.group(1))
        end = len(content)
        for following in headings[index + 1 :]:
            if len(following.group(1)) <= level:
                end = following.start()
                break
        return content[heading.start() : end].strip() + "\n", title
    raise Validation(
        "context.get section was not found in the approved document",
        op="context.get",
    )


def _document_id(revision: str, path: str) -> str:
    return hashlib.sha256(f"{revision}\0{path}".encode("utf-8")).hexdigest()[:24]


def _title(content: str, path: str) -> str:
    match = _HEADING_RE.search(content)
    if match:
        return match.group(2).strip()[:200]
    return Path(path).stem.replace("_", " ").replace("-", " ").strip()[:200]


def _metadata_complete(content: str) -> bool:
    folded = content.casefold()
    required = (
        "metadata",
        "objective",
        "core principles",
        "data sources",
        "key fields",
    )
    return all(item in folded for item in required)


def _redact(content: str, *, root: Path) -> str:
    redacted = _EMAIL_RE.sub("[redacted-email]", content)
    redacted = redacted.replace(str(root), "[context-root]")
    return _HOME_PATH_RE.sub("[local-path]", redacted)


def _redacted_relative_path(path: str) -> str:
    return _EMAIL_RE.sub("[redacted-email]", path)


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
