"""Command-line interface for skillsync."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .classifier import classify_all
from .config import load_config
from .differ import diff_all, sync_state
from .model import CATEGORIES
from .report import to_markdown, write_outputs
from .scanner import scan
from .sync import execute_sync, plan_sync


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skillsync",
        description="Scan, classify and sync AI-agent skills across toolchains.",
    )
    parser.add_argument("--version", action="version", version=f"skillsync {__version__}")
    parser.add_argument("--config", help="path to a skillsync.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="scan roots and print a one-line-per-skill summary")
    p_scan.add_argument("--source", action="append", help="extra source root label=path")
    p_scan.add_argument("--category", choices=[*CATEGORIES, "?"], help="filter by category")
    p_scan.add_argument("--json", action="store_true", help="emit JSON inventory")

    p_status = sub.add_parser("status", help="show counts and sync state (missing/drifted/identical)")

    p_index = sub.add_parser("index", help="generate INDEX.md + inventory.json")
    p_index.add_argument("--out", default=".", help="output directory (default: cwd)")
    p_index.add_argument("--lang", choices=["zh", "en"], default="zh")

    p_sync = sub.add_parser("sync", help="copy portable skills into the target root")
    p_sync.add_argument("--categories", default="A", help="comma list, e.g. A,B (default: A)")
    p_sync.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    p_sync.add_argument("--force", action="store_true", help="update drifted copies (backs them up first)")
    p_sync.add_argument("--prefix", default="", help="prefix added to every synced skill name")

    return parser


def _apply_extra_sources(cfg, extras: list[str] | None) -> None:
    if not extras:
        return
    from .config import DEFAULT_GLOB, SourceRoot

    for item in extras:
        if "=" not in item:
            print(f"[warn] ignoring --source without '=': {item}", file=sys.stderr)
            continue
        label, _, path = item.partition("=")
        cfg.sources.append(
            SourceRoot(label=label.strip(), path=Path(path.strip()).expanduser(), glob=DEFAULT_GLOB)
        )


def _do_scan(cfg, args) -> int:
    result = scan(cfg)
    classify_all(result.skills, cfg)
    diff_all(result.skills, cfg)
    if args.json:
        from .report import to_json

        print(to_json(result))
        return 0
    skills = result.skills
    if getattr(args, "category", None):
        skills = [s for s in skills if s.category == args.category]
    for s in sorted(skills, key=lambda x: (x.category, x.source, x.name)):
        state = sync_state(s)
        deps = (" [" + ",".join(s.missing_deps) + "]") if s.missing_deps else ""
        print(f"{s.category}  {state:9}  {s.source:18} {s.name}{deps}")
    counts = Counter(s.category for s in result.skills)
    print(
        f"\n{len(result.skills)} skills | "
        + " ".join(f"{c}={counts.get(c, 0)}" for c in CATEGORIES)
        + (f" ?={counts.get('?', 0)}" if counts.get("?") else "")
    )
    if result.errors:
        print(f"{len(result.errors)} warning(s); rerun with --json for detail", file=sys.stderr)
    return 0


def _do_status(cfg, _args) -> int:
    result = scan(cfg)
    classify_all(result.skills, cfg)
    diff_all(result.skills, cfg)
    counts = Counter(s.category for s in result.skills)
    sync_counts = Counter(sync_state(s) for s in result.skills)
    print("skillsync status")
    print("================")
    if cfg.target:
        print(f"target: {cfg.target.label} -> {cfg.target.path} ({'exists' if cfg.target.path.is_dir() else 'MISSING'})")
    for label, path in result.roots_scanned:
        n = sum(1 for s in result.skills if s.source == label)
        print(f"source: {label:20} {n:3} skills   {path}")
    print("\nby category:")
    for c in (*CATEGORIES, "?"):
        if counts.get(c):
            print(f"  {c}: {counts[c]}")
    print("\nsync state:")
    for state in ("identical", "drifted", "missing"):
        print(f"  {state:10}: {sync_counts.get(state, 0)}")
    drifted = [s for s in result.skills if sync_state(s) == "drifted"]
    if drifted:
        print("\ndrifted (source != target):")
        for s in sorted(drifted, key=lambda x: x.name)[:40]:
            print(f"  - {s.name}")
        if len(drifted) > 40:
            print(f"  ... and {len(drifted) - 40} more")
    return 0


def _do_index(cfg, args) -> int:
    result = scan(cfg)
    classify_all(result.skills, cfg)
    diff_all(result.skills, cfg)
    out_dir = Path(args.out).expanduser()
    paths = write_outputs(result, out_dir, lang=args.lang)
    for p in paths:
        print(f"wrote {p}")
    # Also echo the markdown to stdout for quick piping.
    print()
    print(to_markdown(result, lang=args.lang)[:2000])
    return 0


def _do_sync(cfg, args) -> int:
    if cfg.target is None or not cfg.target.path.is_dir():
        print("[error] target root missing; set [target] in skillsync.toml", file=sys.stderr)
        return 2
    result = scan(cfg)
    classify_all(result.skills, cfg)
    diff_all(result.skills, cfg)
    cats = tuple(c.strip().upper() for c in args.categories.split(",") if c.strip())
    collisions = {s.name for s in result.skills if s.name.startswith(args.prefix)} if args.prefix else set()
    report = plan_sync(
        result.skills,
        cfg.target.path,
        categories=cats,
        prefix_collisions=collisions,
        force=args.force,
        name_prefix=args.prefix,
    )
    mode = "DRY RUN" if args.dry_run else "SYNC"
    print(f"{mode}: categories={'+'.join(cats)} target={cfg.target.path}")
    for item in report.planned:
        print(f"  [{item.action}] {item.skill.name} -> {item.dest}  {item.note}")
    for item in report.skipped:
        print(f"  [skip]  {item.skill.name}  ({item.note})")
    if not report.planned:
        print("  nothing to do.")
        return 0
    if args.dry_run:
        print(f"\ndry run: {len(report.planned)} action(s) would run. Re-run without --dry-run to apply.")
        return 0
    execute_sync(report, cfg.target.path, dry_run=False)
    print(f"\ncopied={len(report.copied)} updated={len(report.updated)} errors={len(report.errors)}")
    for b in report.backed_up:
        print(f"  backed up -> {b}")
    for e in report.errors:
        print(f"  [error] {e}", file=sys.stderr)
    return 1 if report.errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    _apply_extra_sources(cfg, getattr(args, "source", None))

    handlers = {
        "scan": _do_scan,
        "status": _do_status,
        "index": _do_index,
        "sync": _do_sync,
    }
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
