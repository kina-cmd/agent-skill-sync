"""Configuration: where to scan, and the target to sync into.

Config resolution order (later wins):
1. Built-in defaults — auto-discover common skill roots on this machine.
2. ``skillsync.toml`` in the current working directory.
3. ``skillsync.toml`` under the user's config home.
4. Explicit ``--config`` path passed on the CLI.

The TOML schema is intentionally small::

    [target]
    label = "workbuddy"
    path  = "~/.workbuddy/skills"

    [[sources]]
    label = "codex"
    path  = "~/.codex/skills"
    glob  = "*/SKILL.md"          # optional, default "*/SKILL.md"
    system = false                # optional, mark platform-private roots

    [deps]
    # name -> how to check availability. "shutil" uses shutil.which,
    # "path" checks a filesystem path, "env" checks an env var is set.
    ffmpeg = { kind = "shutil", value = "ffmpeg" }
    codex  = { kind = "shutil", value = "codex" }
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_GLOB = "*/SKILL.md"


@dataclass
class Dep:
    name: str
    kind: str          # "shutil" | "path" | "env"
    value: str
    note: str = ""

    def available(self) -> bool:
        if self.kind == "shutil":
            import shutil

            return shutil.which(self.value) is not None
        if self.kind == "path":
            return Path(os.path.expanduser(self.value)).exists()
        if self.kind == "env":
            return bool(os.environ.get(self.value))
        return False


@dataclass
class SourceRoot:
    label: str
    path: Path
    glob: str = DEFAULT_GLOB
    system: bool = False

    def exists(self) -> bool:
        return self.path.is_dir()


@dataclass
class TargetRoot:
    label: str
    path: Path
    glob: str = DEFAULT_GLOB


@dataclass
class Config:
    sources: list[SourceRoot] = field(default_factory=list)
    target: TargetRoot | None = None
    deps: dict[str, Dep] = field(default_factory=dict)
    # Hints that push a skill toward category C/D regardless of deps.
    platform_private_markers: list[str] = field(
        default_factory=lambda: [
            "image_gen", "view_image", "control-in-app-browser", "computer-use",
            "tool_search", "codex-security", "/plugin", "AGENTS.md", "CLAUDE.md",
            "--tools codex", "present-artifact", "publish-artifact-to-sites",
        ]
    )
    config_path: Path | None = None


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(p)))


def user_config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "skillsync"
    return Path.home() / ".config" / "skillsync"


def default_config() -> Config:
    """Auto-discover the well-known skill roots on this machine."""
    home = Path.home()
    sources: list[SourceRoot] = []

    def add(label: str, path: Path, *, system: bool = False, glob: str = DEFAULT_GLOB) -> None:
        if path.is_dir():
            sources.append(SourceRoot(label=label, path=path, glob=glob, system=system))

    # OpenAI Codex
    add("codex", home / ".codex" / "skills")
    add("codex-system", home / ".codex" / "skills" / ".system", system=True)
    add(
        "codex-marketplace",
        home / ".codex" / "plugins" / "cache",
        glob="**/skills/*/SKILL.md",
    )
    # Claude Code
    add("claude", home / ".claude" / "skills")

    target = TargetRoot(label="workbuddy", path=home / ".workbuddy" / "skills")

    return Config(sources=sources, target=target)


def _load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _merge(cfg: Config, data: dict) -> None:
    if "target" in data and isinstance(data["target"], dict):
        t = data["target"]
        cfg.target = TargetRoot(
            label=t.get("label", cfg.target.label if cfg.target else "target"),
            path=_expand(t["path"]) if "path" in t else (cfg.target.path if cfg.target else Path(".")),
            glob=t.get("glob", DEFAULT_GLOB),
        )
    if "sources" in data and isinstance(data["sources"], list):
        cfg.sources = []
        for s in data["sources"]:
            cfg.sources.append(
                SourceRoot(
                    label=s["label"],
                    path=_expand(s["path"]),
                    glob=s.get("glob", DEFAULT_GLOB),
                    system=bool(s.get("system", False)),
                )
            )
    if "deps" in data and isinstance(data["deps"], dict):
        for name, spec in data["deps"].items():
            if isinstance(spec, str):
                cfg.deps[name] = Dep(name=name, kind="shutil", value=spec)
            elif isinstance(spec, dict):
                cfg.deps[name] = Dep(
                    name=name,
                    kind=spec.get("kind", "shutil"),
                    value=spec.get("value", name),
                    note=spec.get("note", ""),
                )
    if "platform_private_markers" in data and isinstance(data["platform_private_markers"], list):
        cfg.platform_private_markers = list(data["platform_private_markers"])


def load_config(explicit_path: str | None = None) -> Config:
    cfg = default_config()
    for candidate in [
        Path.cwd() / "skillsync.toml",
        user_config_home() / "skillsync.toml",
    ]:
        if candidate.is_file():
            _merge(cfg, _load_toml(candidate))
            cfg.config_path = candidate
    if explicit_path:
        p = _expand(explicit_path)
        _merge(cfg, _load_toml(p))
        cfg.config_path = p
    return cfg
