"""OS and platform-tool config detection. Stdlib-only; no side effects."""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DetectResult:
    """Snapshot of the host environment relevant to kp-mcp bootstrap."""

    is_macos: bool
    home: Path
    cursor_config: Optional[Path] = field(default=None)
    codex_config: Optional[Path] = field(default=None)
    claude_config: Optional[Path] = field(default=None)

    @property
    def platform_configs(self) -> dict[str, Optional[Path]]:
        """Return a mapping of platform name → config path (None if not present)."""
        return {
            "cursor": self.cursor_config,
            "codex": self.codex_config,
            "claude": self.claude_config,
        }


def detect(home: Optional[Path] = None) -> DetectResult:
    """Detect OS type and presence of platform tool config files.

    Args:
        home: Override HOME for testing; defaults to Path.home().

    Returns:
        DetectResult with is_macos flag and resolved config paths for any
        Cursor / Codex / Claude config files that currently exist on disk.
    """
    if home is None:
        home = Path.home()

    is_macos: bool = sys.platform == "darwin"

    def _present(path: Path) -> Optional[Path]:
        return path if path.exists() else None

    return DetectResult(
        is_macos=is_macos,
        home=home,
        cursor_config=_present(home / ".cursor" / "mcp.json"),
        codex_config=_present(home / ".codex" / "config.toml"),
        claude_config=_present(home / ".claude.json"),
    )
