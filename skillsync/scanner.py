"""Scanner: walk configured roots and produce :class:`Skill` records."""

from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_GLOB, Config, SourceRoot
from .frontmatter import parse_file
from .model import ScanResult, Skill

_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _iter_skill_files(root: SourceRoot) -> list[Path]:
    if not root.path.is_dir():
        return []
    if root.glob == DEFAULT_GLOB:
        # Non-recursive: only direct child directories.
        files = []
        for child in sorted(root.path.iterdir()):
            if child.is_dir() and child.name not in _SKIP_DIRS:
                candidate = child / "SKILL.md"
                if candidate.is_file():
                    files.append(candidate)
        return files
    files = []
    seen: set[Path] = set()
    for match in root.path.glob(root.glob):
        rel_parts = match.relative_to(root.path).parts[:-1]
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        resolved = match.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        files.append(match)
    return sorted(files)


def _qualified_name(root: SourceRoot, path: Path) -> str:
    """Derive a readable skill name.

    For marketplace-style roots (``**/skills/<name>/SKILL.md``) the name is the
    directory. For plugin caches we keep a ``plugin:skill`` qualified name when
    the layout allows it.
    """
    rel = path.relative_to(root.path)
    parts = rel.parts[:-1]  # drop SKILL.md
    if not parts:
        return root.path.name
    name = parts[-1]
    # Heuristic: .../<plugin>/<version>/skills/<name> → plugin:name
    if "skills" in parts:
        idx = parts.index("skills")
        if idx > 0:
            plugin = parts[idx - 2] if idx >= 2 else parts[idx - 1]
            if plugin != "skills":
                return f"{plugin}:{name}"
    return name


def scan(config: Config) -> ScanResult:
    result = ScanResult()
    for root in config.sources:
        result.roots_scanned.append((root.label, root.path))
        if not root.exists():
            result.errors.append(f"source root missing: {root.label} ({root.path})")
            continue
        found = 0
        for skill_file in _iter_skill_files(root):
            try:
                doc = parse_file(skill_file)
            except OSError as exc:
                result.errors.append(f"unreadable: {skill_file}: {exc}")
                continue
            data = doc.data or {}
            name_in_meta = data.get("name")
            skill = Skill(
                name=_qualified_name(root, skill_file),
                path=skill_file,
                source=root.label,
                root=root.path,
                frontmatter=data,
                description=str(data.get("description") or "").strip(),
                parse_warnings=doc.parse_warnings,
            )
            if isinstance(name_in_meta, str) and name_in_meta and ":" not in skill.name:
                # Prefer the declared name when it looks sane.
                skill.name = name_in_meta
            result.skills.append(skill)
            found += 1
        result.raw_counts[root.label] = found
    return result
