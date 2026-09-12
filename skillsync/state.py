"""Snapshot state: detect upstream changes between runs.

Each ``check`` / ``index`` run records a snapshot of every scanned skill
(content hash + category + sync state). The next run compares against it and
reports what moved upstream: new skills, removed skills, content changes,
category re-classifications and new drift against the target.

This is the "come back and maintain me" hook: the tool tells you, in one
screen, exactly what changed since you last looked.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

from .differ import sync_state
from .model import ScanResult, Skill

KINDS = ("new", "removed", "content", "category", "sync")


@dataclass
class Change:
    kind: str     # one of KINDS
    key: str      # "<source>:<name>"
    detail: str = ""


def _key(skill: Skill) -> str:
    return f"{skill.source}:{skill.name}"


def snapshot_from(result: ScanResult) -> dict:
    return {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "skills": {
            _key(s): {
                "hash": s.body_hash,
                "category": s.category,
                "sync": sync_state(s),
            }
            for s in result.skills
        },
    }


def load_snapshot(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
        return None
    return data


def save_snapshot(path: Path, snap: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")


def compare(old: dict | None, result: ScanResult) -> list[Change]:
    """Diff the previous snapshot against the current scan.

    An absent baseline (first run) yields no changes — there is nothing to
    compare against yet.
    """
    changes: list[Change] = []
    current = snapshot_from(result)["skills"]
    if old is None:
        return changes
    prev = old.get("skills", {})
    for key, cur in sorted(current.items()):
        if key not in prev:
            changes.append(Change("new", key, f"category {cur['category']}"))
            continue
        p = prev[key]
        if p.get("hash") != cur["hash"]:
            changes.append(Change("content", key, "upstream content changed"))
        if p.get("category") != cur["category"]:
            changes.append(
                Change("category", key, f"{p.get('category')} -> {cur['category']}")
            )
        if p.get("sync") != cur["sync"]:
            changes.append(Change("sync", key, f"{p.get('sync')} -> {cur['sync']}"))
    for key in sorted(set(prev) - set(current)):
        changes.append(Change("removed", key, "no longer present in any source root"))
    return changes


def format_report(changes: list[Change], old: dict | None) -> str:
    if old is None:
        return "first run: baseline recorded; future runs report upstream changes"
    if not changes:
        return "no upstream changes since last run"
    lines = [f"{len(changes)} change(s) since {old.get('generated_at', 'last run')}:"]
    for c in changes:
        lines.append(f"  [{c.kind:8}] {c.key}  {c.detail}")
    return "\n".join(lines)
