"""Differ: compare scanned source skills against the target root.

For each source skill we look for a same-named skill in the target and decide:

* **missing** — not present in the target at all.
* **identical** — present and byte-for-byte the same.
* **drifted** — present but content differs (someone edited one side).

The target may use a prefix to avoid name clashes (e.g. ``superpowers-``);
we strip a configured set of prefixes when matching names.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .model import Skill

DEFAULT_PREFIXES = ("superpowers-",)


def _target_index(config: Config, prefixes: tuple[str, ...]) -> dict[str, Path]:
    """Map normalized skill name → SKILL.md path in the target root."""
    index: dict[str, Path] = {}
    target = config.target
    if target is None or not target.path.is_dir():
        return index
    for match in sorted(target.path.glob(target.glob)):
        if not match.is_file():
            continue
        name = match.parent.name
        for prefix in prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        index[name] = match
    return index


def diff(skill: Skill, target_index: dict[str, Path]) -> None:
    base = skill.name
    if ":" in base:
        base = base.split(":", 1)[1]
    candidate = target_index.get(base)
    if candidate is None:
        skill.synced_to = None
        skill.in_sync = None
        return
    skill.synced_to = candidate
    try:
        same = candidate.read_bytes() == skill.path.read_bytes()
    except OSError:
        same = False
    skill.in_sync = same


def diff_all(skills, config: Config, prefixes: tuple[str, ...] = DEFAULT_PREFIXES) -> dict[str, Path]:
    target_index = _target_index(config, prefixes)
    for skill in skills:
        diff(skill, target_index)
    return target_index


def sync_state(skill: Skill) -> str:
    """Human-readable sync state for one skill."""
    if skill.synced_to is None:
        return "missing"
    return "identical" if skill.in_sync else "drifted"
