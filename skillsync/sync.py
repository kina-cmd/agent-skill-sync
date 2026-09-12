"""Sync: copy category-A (and optionally B) skills into the target root.

Safety rules, all mandatory:

* Never overwrite by default. ``--force`` is required to replace a drifted
  copy, and the replaced directory is first moved to ``.skillsync-backup/``
  inside the target root (never deleted).
* Skills with large private payloads (``.venv``, ``.env``, node_modules) are
  excluded from the copy — secrets must not travel silently.
* Dry-run (``--dry-run``) prints the exact plan and touches nothing.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .model import Skill

_EXCLUDE_NAMES = {".venv", "venv", "node_modules", "__pycache__", ".env", ".git"}


@dataclass
class SyncPlanItem:
    skill: Skill
    dest: Path
    action: str          # "copy" | "update" | "skip"
    note: str = ""


@dataclass
class SyncReport:
    planned: list[SyncPlanItem] = field(default_factory=list)
    copied: list[SyncPlanItem] = field(default_factory=list)
    updated: list[SyncPlanItem] = field(default_factory=list)
    skipped: list[SyncPlanItem] = field(default_factory=list)
    backed_up: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _copy_tree_filtered(src_dir: Path, dest_dir: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        return {n for n in names if n in _EXCLUDE_NAMES}

    shutil.copytree(src_dir, dest_dir, ignore=ignore, dirs_exist_ok=False)


def plan_sync(
    skills: list[Skill],
    target: Path,
    *,
    categories: tuple[str, ...] = ("A",),
    prefix_collisions: set[str] | None = None,
    force: bool = False,
    name_prefix: str = "",
) -> SyncReport:
    report = SyncReport()
    prefix_collisions = prefix_collisions or set()
    for skill in sorted(skills, key=lambda s: s.name):
        if skill.category not in categories:
            continue
        base = skill.name.split(":", 1)[1] if ":" in skill.name else skill.name
        if base in prefix_collisions:
            base = name_prefix + base
        elif name_prefix:
            base = name_prefix + base
        dest = target / base
        src_dir = skill.path.parent
        if dest.exists():
            same = False
            try:
                src_skill = skill.path.read_bytes()
                dest_skill = dest / "SKILL.md"
                same = dest_skill.is_file() and dest_skill.read_bytes() == src_skill
            except OSError:
                same = False
            if same:
                report.skipped.append(SyncPlanItem(skill, dest, "skip", "identical"))
            elif force:
                report.planned.append(SyncPlanItem(skill, dest, "update", "drifted, --force given"))
            else:
                report.skipped.append(
                    SyncPlanItem(skill, dest, "skip", "exists and differs; use --force to update")
                )
        else:
            report.planned.append(SyncPlanItem(skill, dest, "copy"))
    return report


def execute_sync(
    report: SyncReport,
    target: Path,
    *,
    dry_run: bool = False,
) -> SyncReport:
    if dry_run:
        return report
    backup_root = target / ".skillsync-backup"
    for item in report.planned:
        src_dir = item.skill.path.parent
        try:
            if item.action == "update" and item.dest.exists():
                backup_root.mkdir(parents=True, exist_ok=True)
                backup_dest = backup_root / item.dest.name
                if backup_dest.exists():
                    shutil.rmtree(backup_dest)
                shutil.move(str(item.dest), str(backup_dest))
                report.backed_up.append(backup_dest)
            _copy_tree_filtered(src_dir, item.dest)
            if item.action == "update":
                report.updated.append(item)
            else:
                report.copied.append(item)
        except (OSError, shutil.Error) as exc:
            report.errors.append(f"{item.skill.name}: {exc}")
    return report
