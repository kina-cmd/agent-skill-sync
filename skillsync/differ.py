"""Differ: compare scanned source skills against the target root.

Matching a source skill to its target slot:

1. Qualified ``plugin:base`` prefers target dir ``plugin-base`` (the WorkBuddy
   convention for the superpowers family), then falls back to ``base``.
2. Bare ``base`` prefers target dir ``base``, then tries known prefixed
   variants (``superpowers-base`` …) — qoder-cn stores superpowers skills
   without the prefix, so a bare source name can legitimately own a prefixed
   target slot.

States: **missing** (no target slot), **identical** (same content modulo line
endings), **drifted** (target slot exists but content differs).
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .model import Skill

DEFAULT_PREFIXES = ("superpowers-",)


def build_target_index(config: Config) -> dict[str, Path]:
    """Map raw target directory name → SKILL.md path."""
    index: dict[str, Path] = {}
    target = config.target
    if target is None or not target.path.is_dir():
        return index
    for match in sorted(target.path.glob(target.glob)):
        if match.is_file():
            index[match.parent.name] = match
    return index


def match_target(
    skill_name: str,
    target_index: dict[str, Path],
    prefixes: tuple[str, ...] = DEFAULT_PREFIXES,
) -> Path | None:
    """Find the target SKILL.md a source skill name maps onto (or None)."""
    plugin: str | None = None
    base = skill_name
    if ":" in skill_name:
        plugin, base = skill_name.split(":", 1)
    # Qualified names prefer their prefixed slot to avoid hijacking a
    # same-basename skill from a different plugin.
    if plugin:
        prefixed = f"{plugin}-{base}"
        if prefixed in target_index:
            return target_index[prefixed]
    if base in target_index:
        return target_index[base]
    for prefix in prefixes:
        if base.startswith(prefix):
            continue
        variant = prefix + base
        if variant in target_index:
            return target_index[variant]
    return None


def _norm(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def diff(skill: Skill, target_index: dict[str, Path]) -> None:
    candidate = match_target(skill.name, target_index)
    if candidate is None:
        skill.synced_to = None
        skill.in_sync = None
        return
    skill.synced_to = candidate
    try:
        same = _norm(candidate.read_bytes()) == _norm(skill.path.read_bytes())
    except OSError:
        same = False
    skill.in_sync = same


def diff_all(
    skills,
    config: Config,
    prefixes: tuple[str, ...] = DEFAULT_PREFIXES,
) -> dict[str, Path]:
    target_index = build_target_index(config)
    for skill in skills:
        diff(skill, target_index)
    return target_index


def sync_state(skill: Skill) -> str:
    """Human-readable sync state for one skill."""
    if skill.synced_to is None:
        return "missing"
    return "identical" if skill.in_sync else "drifted"
