"""Cross-source resolution: one logical skill may exist in several roots.

After scanning, many skill *names* appear in multiple source roots (Codex,
Qoder-CN...). ``resolve()`` collapses them into a single authoritative skill:

* **identical** — every copy has the same content (ignoring line endings).
  Keep one representative, record the rest as ``duplicates``.
* **shadowed** — copies differ. The highest-priority source (per
  ``source_priority``) is the *canonical* version and is kept; lower-priority
  copies are recorded as ``shadowed`` (stale duplicates superseded by the
  canonical one). They are dropped from the main list so they cannot create
  false drift signals or be synced back over the newer version.

Grouping uses the **expected target directory name**, not the bare skill name,
so that distinct skills that merely share a base name — e.g.
``agent-skills:test-driven-development`` (target ``test-driven-development``)
and ``superpowers:test-driven-development`` (target
``superpowers-test-driven-development``) — are never merged.
"""

from __future__ import annotations

from .differ import DEFAULT_PREFIXES
from .model import Skill

DEFAULT_PRIORITY = (
    "codex-marketplace",
    "codex",
    "qoder-cn",
    "qoder",
    "claude",
    "copilot",
    "gemini",
    "cursor",
    "opencode",
)


def _norm(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _content(skill: Skill) -> bytes:
    try:
        return _norm(skill.path.read_bytes())
    except OSError:
        return b""


def expected_target_name(skill_name: str) -> str:
    """Map a (possibly qualified) source skill name to its target dir name.

    ``superpowers:X`` → ``superpowers-X`` (the WorkBuddy convention that keeps
    the superpowers family from clashing with same-named skills); any other
    qualified ``plugin:X`` and every bare ``X`` → ``X``.
    """
    if ":" not in skill_name:
        return skill_name
    plugin, skill_part = skill_name.split(":", 1)
    if f"{plugin}-" in DEFAULT_PREFIXES:
        return f"{plugin}-{skill_part}"
    return skill_part


def _rank(source: str, priority: tuple[str, ...]) -> int:
    try:
        return priority.index(source)
    except ValueError:
        return len(priority)


def _group_key(skill: Skill) -> str:
    """Group skills by the target slot they map onto.

    Prefer the slot the differ actually matched (``synced_to``), so a bare
    qoder-cn copy that owns a prefixed target dir (e.g. bare
    ``finishing-a-development-branch`` → ``superpowers-finishing-a-development-branch``)
    groups together with its qualified codex counterpart. Fall back to the
    expected target name for skills with no target slot yet.
    """
    if skill.synced_to is not None:
        return f"@{skill.synced_to.parent}"
    return expected_target_name(skill.name)


def resolve(
    skills: list[Skill],
    *,
    source_priority: tuple[str, ...] = DEFAULT_PRIORITY,
) -> tuple[list[Skill], list[tuple[str, list[str]]], list[tuple[str, str, list[str]]]]:
    """Deduplicate skills across sources.

    Returns ``(resolved, duplicates, shadowed)``:

    * ``resolved``   — the canonical skill list (one entry per target slot).
    * ``duplicates`` — ``(target_name, [source labels])`` collapsed as identical.
    * ``shadowed``   — ``(target_name, winner_source, [loser sources])`` where a
      lower-priority stale copy was superseded by a newer canonical version.
    """
    groups: dict[str, list[Skill]] = {}
    for skill in skills:
        groups.setdefault(_group_key(skill), []).append(skill)

    resolved: list[Skill] = []
    duplicates: list[tuple[str, list[str]]] = []
    shadowed: list[tuple[str, str, list[str]]] = []

    for target_name, group in groups.items():
        group.sort(key=lambda s: (_rank(s.source, source_priority), str(s.path)))
        if len(group) == 1:
            resolved.append(group[0])
            continue
        contents = [_content(s) for s in group]
        if len(set(contents)) == 1:
            resolved.append(group[0])
            duplicates.append((target_name, [s.source for s in group]))
        else:
            winner = group[0]
            resolved.append(winner)
            losers = group[1:]
            shadowed.append((target_name, winner.source, [s.source for s in losers]))

    resolved.sort(key=lambda s: (s.source, expected_target_name(s.name)))
    return resolved, duplicates, shadowed
