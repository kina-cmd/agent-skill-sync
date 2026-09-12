# Contributing to agent-skill-sync

Thanks for your interest in improving `skillsync`!

## Ground rules

1. **Stdlib only.** Zero third-party runtime dependencies is a hard design
   constraint — it keeps `pipx install` instant and the tool usable inside
   locked-down environments. If you think a dependency is unavoidable, open an
   issue first to discuss.
2. **Never delete user data.** Anything in `sync.py` that touches the target
   root must go through the backup path (`.skillsync-backup/`) and be
   dry-run-able. No exceptions.
3. **Classification must explain itself.** Every category assignment carries a
   human-readable reason. If you add heuristics, keep this contract.
4. **Tests are required.** `python -m unittest discover tests` must pass. New
   behavior needs new tests; bug fixes need a regression test.

## Development setup

```bash
git clone https://github.com/kina-cmd/agent-skill-sync
cd agent-skill-sync
pip install -e .
python -m unittest discover tests -v
```

## Project layout

```
skillsync/
  frontmatter.py  YAML-subset parser (no PyYAML)
  model.py        Skill / ScanResult dataclasses
  config.py       root discovery + skillsync.toml
  scanner.py      walk roots → Skill records
  classifier.py   A/B/C/D heuristics + dependency probing
  differ.py       source ↔ target comparison (line-ending tolerant)
  resolve.py      cross-source dedupe: duplicates vs shadowed
  sync.py         safe copy engine (backup, dry-run, collision guard)
  report.py       INDEX.md / inventory.json generation
  cli.py          argparse entry point
```

## Making a change

1. Open an issue for anything non-trivial, so we can align before you write code.
2. Branch from `main`, keep commits focused.
3. Update `CHANGELOG.md` under an "Unreleased" section for user-visible changes.
4. Open a PR using the template; CI runs the test matrix (3.11–3.13, three OSes).

## Release process (maintainers)

1. Bump `version` in `pyproject.toml` and `__version__` in `skillsync/__init__.py`.
2. Move "Unreleased" changes into a dated section in `CHANGELOG.md`.
3. Tag: `git tag v<X.Y.Z> && git push origin v<X.Y.Z>`.
4. The `publish.yml` workflow builds and pushes to PyPI via trusted publishing
   (OIDC — no tokens stored in the repo).
