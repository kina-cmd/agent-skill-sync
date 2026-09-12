"""Core data models: what a "skill" is, and what a scan produces."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Classification taxonomy (mirrors a common migration workflow):
#   A — copied/runnable as-is in the target toolchain
#   B — skill is portable but needs external dependencies (CLI/MCP/venv)
#   C — methodology is reusable but the skill must be rewritten for the target
#   D — bound to the source platform's private runtime; do not migrate
CATEGORIES = ("A", "B", "C", "D")


@dataclass
class Skill:
    """One discovered SKILL.md and its metadata."""

    name: str                       # skill directory name (or qualified name)
    path: Path                      # absolute path to SKILL.md
    source: str                     # label of the root it was found under
    root: Path                      # absolute path of the scan root
    frontmatter: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    parse_warnings: list[str] = field(default_factory=list)
    # Derived by the classifier:
    category: str = "?"             # A / B / C / D / "?"
    category_reason: str = ""
    missing_deps: list[str] = field(default_factory=list)
    # Derived by the differ:
    synced_to: str | None = None    # absolute path in the target, if present
    in_sync: bool | None = None     # content identical? (None = not synced)

    @property
    def qualified_name(self) -> str:
        return f"{self.source}:{self.name}"

    @property
    def body_hash(self) -> str:
        """Stable hash of the file content, for drift detection."""
        import hashlib

        try:
            data = self.path.read_bytes()
        except OSError:
            return ""
        return hashlib.sha256(data).hexdigest()[:16]


@dataclass
class ScanResult:
    """Everything one run of the scanner knows."""

    skills: list[Skill] = field(default_factory=list)
    roots_scanned: list[tuple[str, Path]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Raw (pre-dedupe) skill count per source label, for honest reporting.
    raw_counts: dict[str, int] = field(default_factory=dict)
    # Populated by resolve(): base_name -> [source labels] for names that were
    # identical across multiple roots and collapsed to a single entry.
    duplicates: list[tuple[str, list[str]]] = field(default_factory=list)
    # (target_name, winner_source, [loser sources]) for stale copies superseded
    # by a higher-priority canonical version.
    shadowed: list[tuple[str, str, list[str]]] = field(default_factory=list)
    resolved: bool = False

    def by_name(self) -> dict[str, list[Skill]]:
        out: dict[str, list[Skill]] = {}
        for skill in self.skills:
            out.setdefault(skill.name, []).append(skill)
        return out

    def by_category(self) -> dict[str, list[Skill]]:
        out: dict[str, list[Skill]] = {c: [] for c in CATEGORIES}
        out["?"] = []
        for skill in self.skills:
            out.setdefault(skill.category, []).append(skill)
        return out
