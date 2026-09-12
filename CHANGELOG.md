# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-09-12

### Added

- `skillsync check` — change detection between runs. Records a snapshot
  (content hash + category + sync state per skill) and reports what moved
  upstream since the last run: new / removed / content-changed /
  re-classified / newly-drifted skills. Exit code is always 0 so it is safe
  to run from cron and scheduled tasks.
- `skillsync index` now prints the same change report before regenerating
  outputs, and refreshes the snapshot baseline.
- Snapshot location: `$XDG_CONFIG_HOME/skillsync/state.json` (or
  `%APPDATA%/skillsync/state.json` on Windows), overridable with `--state`.

## [0.2.0] - 2026-09-12

### Added

- Auto-discovery of the remaining major Agent Skills adopters: GitHub Copilot
  (`~/.copilot/skills`), Gemini CLI (`~/.gemini/skills`), Cursor
  (`~/.cursor/skills`) and OpenCode (`~/.config/opencode/skills`), alongside
  the existing Codex and Claude Code roots.
- Source priority extended for the new roots:
  codex-marketplace > codex > qoder-cn > qoder > claude > copilot > gemini >
  cursor > opencode.

## [0.1.0] - 2026-09-12

Initial release.

### Added

- `skillsync scan` — one-line-per-skill inventory with category, sync state and missing deps; `--json` for machine-readable output.
- `skillsync status` — counts by category and sync state, drift details, dedupe/shadow summary.
- `skillsync index` — generates `INDEX.md` (human) + `inventory.json` (machine) from a live scan.
- `skillsync sync` — copies portable skills into the target root with `--dry-run`, `--force` (backup-before-overwrite into `.skillsync-backup/`), `--drifted-only`, `--source` filters and destination collision guard.
- A/B/C/D migration classifier with live dependency probing (`shutil.which`, MCP references, `[deps]` table) and per-skill reasons.
- Cross-source resolution: identical copies collapse; stale lower-priority copies are shadowed by the canonical source (priority: codex-marketplace > codex > qoder-cn > qoder > claude).
- Line-ending-insensitive drift detection (CRLF/LF copies no longer count as drifted).
- Target-name mapping: `superpowers:X` maps to prefixed target dirs; bare names fall back to prefix variants.
- Dependency-free YAML-subset frontmatter parser (no PyYAML).
- Auto-discovery of Codex / Codex system / Codex marketplace / Claude skill roots; `skillsync.toml` for overrides and extra roots (e.g. Qoder-CN).
- 23 unit tests; CI matrix across Python 3.11–3.13 on Linux/Windows/macOS.

[0.1.0]: https://github.com/kina-cmd/agent-skill-sync/releases/tag/v0.1.0
