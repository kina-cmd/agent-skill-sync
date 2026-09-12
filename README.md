# agent-skill-sync

[![CI](https://github.com/kina-cmd/agent-skill-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/kina-cmd/agent-skill-sync/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/skillsync)](https://pypi.org/project/skillsync/)
[![Python](https://img.shields.io/pypi/pyversions/skillsync)](https://pypi.org/project/skillsync/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**`skillsync`** — scan, classify and sync AI-agent skills (`SKILL.md` files) across toolchains.

If you use several AI coding agents (OpenAI Codex, Claude Code, WorkBuddy, …), you end up with
skill libraries scattered across different directories, in different layouts, some copied, some
stale, some requiring dependencies you never installed. `skillsync` turns that mess into one
honest inventory — automatically.

Zero dependencies. Pure Python ≥ 3.11 stdlib.

## What it does

```
┌──────────────┐   ┌──────────────┐   ┌────────────────┐
│ ~/.codex/    │   │ marketplace  │   │ ~/.claude/     │   … any number of
│   skills/    │   │ plugin cache │   │   skills/      │       source roots
└──────┬───────┘   └──────┬───────┘   └───────┬────────┘
       └──────────────┬───┴───────────────────┘
                      ▼
              ┌───────────────┐     classify every skill:
              │  scan + parse │     A portable · B missing deps
              │  frontmatter  │     C rewrite needed · D platform-private
              └───────┬───────┘
                      ▼
              ┌───────────────┐     diff against target:
              │ INDEX.md      │     identical · drifted · missing
              │ inventory.json│
              └───────┬───────┘
                      ▼
              ┌───────────────┐     optional, safe copy:
              │ skillsync sync│     dry-run first, backups, never deletes,
              └───────────────┘     skips .venv/.env/node_modules
```

### The A/B/C/D migration taxonomy

| Category | Meaning | Action |
|---|---|---|
| **A** | Portable — no platform-private references, every referenced command exists | copy & use |
| **B** | Portable but missing external deps (a CLI, an MCP server) | install deps, then copy |
| **C** | References another agent's conventions (`AGENTS.md`, `image_gen`, …) | rewrite for your target |
| **D** | Bound to the source platform's private runtime | don't migrate |

Classification is heuristic, conservative, and **every decision ships a reason** —
the index shows *why* a skill landed in each bucket, and *which* dependencies are missing
(probed live with `shutil.which` / your `[deps]` table).

## Install

```bash
pipx install skillsync        # recommended: isolated CLI install
pip install skillsync         # or into your environment

# from source, without installing:
git clone https://github.com/kina-cmd/agent-skill-sync && cd agent-skill-sync
python -m skillsync.cli --help
```

## Usage

```bash
# What do I have, and in what state?
skillsync status

# One line per skill: category, sync state, source, missing deps
skillsync scan
skillsync scan --category B          # only the ones needing deps
skillsync scan --json                # machine-readable inventory

# Generate a full index (INDEX.md + inventory.json) you can commit
# or paste into a "tool reuse" skill for your agent to read
skillsync index --out ./output --lang zh

# Sync portable skills into the target root — plan first, always
skillsync sync --dry-run
skillsync sync --categories A
skillsync sync --categories A,B --force    # update drifted copies (backs them up)
```

### Sync safety rules

* Never overwrites without `--force`; a forced update first moves the old copy to
  `<target>/.skillsync-backup/` — nothing is ever deleted.
* `.venv/`, `.env`, `node_modules/`, `__pycache__/` are always excluded from copies,
  so secrets and 500 MB virtualenvs never travel silently.
* `--dry-run` prints the exact plan and touches nothing.

## Configuration

By default, `skillsync` auto-discovers the well-known roots on your machine
(`~/.codex/skills`, `~/.codex/plugins/cache`, `~/.claude/skills` → target `~/.workbuddy/skills`).

Override or extend with `skillsync.toml` (looked up in `./` then `$XDG_CONFIG_HOME/skillsync/`):

```toml
[target]
label = "workbuddy"
path  = "~/.workbuddy/skills"

[[sources]]
label = "codex"
path  = "~/.codex/skills"

[[sources]]
label = "codex-marketplace"
path  = "~/.codex/plugins/cache"
glob  = "**/skills/*/SKILL.md"

[[sources]]
label  = "codex-system"
path   = "~/.codex/skills/.system"
system = true              # platform-private → always category D

[deps]
# Teach the classifier that a dep is satisfied even if not on PATH:
voicebox = { kind = "path", value = "~/App/Voicebox/voicebox.exe" }
ffmpeg   = "ffmpeg"                                   # shorthand: check PATH
notion   = { kind = "env",  value = "NOTION_TOKEN" }  # check env var
```

See [`skillsync.example.toml`](skillsync.example.toml) for a complete example.

## Typical workflow: keeping an index skill fresh

Many people maintain a hand-written "local tool reuse" index for their agent.
It rots the moment a skill is added upstream. Instead:

```bash
skillsync index --out ~/.workbuddy/skills/local-tool-reuse/generated --lang zh
```

…on a schedule or a git hook, and let the agent read a generated file that is
always true. `inventory.json` is stable, machine-readable output for further tooling.

## Development

```bash
python -m unittest discover tests -v
```

## Design notes

* **No PyYAML.** The frontmatter parser implements exactly the YAML subset skill
  files use (scalars, folded/literal blocks, inline and block lists), and fails soft —
  unparsable lines become warnings, never crashes.
* **No network.** Everything is local filesystem inspection.
* **Qualified names.** Marketplace plugin caches nest skills as
  `<plugin>/<version>/skills/<name>/`; these are reported as `plugin:name` so
  collisions are visible.

## License

MIT © 2026 kina-cmd
