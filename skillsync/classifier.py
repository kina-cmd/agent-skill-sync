"""Classifier: assign each skill an A/B/C/D migration category, automatically.

The taxonomy:

* **A — portable.** Nothing platform-private, every referenced external command
  is present on this machine. Can be copied to the target and used as-is.
* **B — needs dependencies.** Portable in spirit, but references CLIs / MCP
  servers / runtimes that are *missing* here. Runnable once deps are installed.
* **C — rewrite required.** References another agent's config conventions or
  tool-call vocabulary (``AGENTS.md``, ``image_gen``, ``tool_search``…) that has
  no drop-in equivalent. Methodology is reusable, the text is not.
* **D — platform-private.** Bound to the source runtime's internals (Codex
  system skills, in-app browser control, codex-security, plugin management).
  Do not migrate.

Classification is heuristic and intentionally conservative: when a skill
matches both a "private" marker and a missing dependency, the stronger
constraint wins (D > C > B > A). Every decision carries a human-readable
``reason`` and the concrete ``missing_deps`` so the index can show *why*.
"""

from __future__ import annotations

import re
import shutil

from .config import Config
from .model import Skill

# Tokens that look like shell commands worth checking with shutil.which().
# We only probe a curated allowlist to avoid false positives from prose.
_KNOWN_COMMANDS = {
    "ffmpeg", "ffprobe", "node", "npx", "pnpm", "yarn", "npm", "python", "python3",
    "pip", "pipx", "uv", "git", "gh", "rg", "fd", "jq", "yt-dlp", "playwright",
    "manim", "hf", "heygen", "codex", "docker", "magick", "convert", "sox",
    "browser-act", "mcporter", "arkcli", "openmontage", "voicebox", "genmedia",
}

# MCP server references look like mcp__<server>__<tool> or "MCP server <name>".
_MCP_RE = re.compile(r"\bmcp__([a-z0-9_\-]+)__", re.IGNORECASE)
_MCP_PROSE_RE = re.compile(r"\b([A-Za-z0-9_\-]+)\s+MCP\b")
# Prose matches are noisy ("the detailed MCP", "an s MCP client"...), so a prose
# token only counts as a server name if it is hyphenated/underscored or in this
# allowlist of servers commonly referenced in skills.
_MCP_PROSE_ALLOWLIST = {
    "notion", "firecrawl", "playwright", "devtools", "browser", "browserbase",
    "scrapling", "voicebox", "linear", "gmail", "heygen", "chrome", "puppeteer",
    "sheetagent", "github", "memory", "filesystem", "sequential-thinking",
    "aitoearn", "hf_jobs", "codex_apps", "context7", "supabase", "sentry",
}

# Words that signal "this is just methodology, but it talks to another agent".
_C_MARKERS = (
    "AGENTS.md", "CLAUDE.md", "--tools codex", "image_gen", "view_image",
    "tool_search", "toolsearch", "present-artifact", "/plugin", "claude code",
    "control-in-app-browser", "in-app browser",
)

# Words that signal platform-private internals — never migrate.
_D_MARKERS = (
    "codex-security", "computer-use", "control-chrome", "sites:sites-hosting",
    "sites:sites-building", "publish-artifact-to-sites", "plugin-creator",
    "skill-installer", "plugin-management", "scan id", "scanid",
    "documents:documents", "spreadsheets:excel-live-control",
    "template-creator",
)


def _referenced_commands(text: str) -> set[str]:
    found: set[str] = set()
    # fenced code blocks and inline `code` are the most reliable signal
    for chunk in re.findall(r"```.*?```", text, flags=re.DOTALL):
        for word in re.findall(r"\b([a-z0-9_\-]+)\b", chunk):
            if word in _KNOWN_COMMANDS:
                found.add(word)
    for chunk in re.findall(r"`([^`]+)`", text):
        first = chunk.strip().split()[0] if chunk.strip() else ""
        if first in _KNOWN_COMMANDS:
            found.add(first)
    return found


def _referenced_mcp(text: str) -> set[str]:
    found = {m.lower() for m in _MCP_RE.findall(text)}
    for token in _MCP_PROSE_RE.findall(text):
        t = token.lower()
        if t in _MCP_PROSE_ALLOWLIST or "-" in t or "_" in t:
            found.add(t)
    # Drop generic words that the prose regex over-captures.
    return {
        m for m in found
        if m not in {"the", "a", "an", "use", "call", "via", "with", "and", "or", "s", "to", "of"}
        and len(m) > 1
    }


def classify(skill: Skill, config: Config) -> Skill:
    """Mutate and return ``skill`` with category/reason/missing_deps set."""
    try:
        text = skill.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    low = text.lower()

    # --- D: platform-private -------------------------------------------------
    if skill.source.endswith("-system") or ".system" in str(skill.path):
        skill.category = "D"
        skill.category_reason = "lives in a platform .system root (private runtime skill)"
        return skill
    for marker in _D_MARKERS:
        if marker.lower() in low:
            skill.category = "D"
            skill.category_reason = f"references platform-private internal '{marker}'"
            return skill
    for marker in config.platform_private_markers:
        if marker.lower() in low and marker.lower() in {m.lower() for m in _D_MARKERS}:
            skill.category = "D"
            skill.category_reason = f"references platform-private internal '{marker}'"
            return skill

    # --- deps: missing external commands / MCP servers -----------------------
    missing: list[str] = []
    for cmd in sorted(_referenced_commands(text)):
        # 'python'/'python3' are ubiquitous; only flag if truly absent.
        if shutil.which(cmd) is None:
            missing.append(cmd)
    for server in sorted(_referenced_mcp(text)):
        # A configured dep in the [deps] table can vouch for an MCP server.
        dep = config.deps.get(server)
        if dep is not None and dep.available():
            continue
        missing.append(f"MCP:{server}")

    # --- C: needs rewrite for the target agent ------------------------------
    c_hits = [m for m in _C_MARKERS if m.lower() in low]
    if c_hits:
        skill.category = "C"
        skill.category_reason = (
            "references another agent's conventions/tools (" + ", ".join(sorted(set(c_hits))[:4]) + "); "
            "methodology reusable, text must be rewritten for the target"
        )
        skill.missing_deps = missing
        return skill

    # --- B: portable but missing deps ---------------------------------------
    if missing:
        skill.category = "B"
        skill.category_reason = "portable, but missing external dependencies"
        skill.missing_deps = missing
        return skill

    # --- A: portable and runnable -------------------------------------------
    skill.category = "A"
    skill.category_reason = "no platform-private references and all commands present"
    skill.missing_deps = []
    return skill


def classify_all(skills, config: Config) -> None:
    for skill in skills:
        classify(skill, config)
