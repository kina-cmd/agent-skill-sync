"""Tests for skillsync — run with: python -m unittest discover tests -v"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skillsync.classifier import classify
from skillsync.config import Config, SourceRoot, TargetRoot
from skillsync.differ import diff_all, sync_state
from skillsync.frontmatter import parse_frontmatter
from skillsync.scanner import scan
from skillsync.sync import execute_sync, plan_sync


class TestFrontmatter(unittest.TestCase):
    def test_simple_scalars(self):
        doc = parse_frontmatter("---\nname: foo\ndescription: bar baz\n---\n# Body\n")
        self.assertEqual(doc.data["name"], "foo")
        self.assertEqual(doc.data["description"], "bar baz")
        self.assertEqual(doc.body.strip(), "# Body")

    def test_folded_block_scalar(self):
        text = "---\nname: genmedia\ndescription: >\n  line one\n  line two\n---\nbody"
        doc = parse_frontmatter(text)
        self.assertEqual(doc.data["description"], "line one line two")

    def test_literal_block_scalar(self):
        text = "---\nname: x\ndescription: |\n  keep\n  newlines\n---\n"
        doc = parse_frontmatter(text)
        self.assertEqual(doc.data["description"], "keep\nnewlines")

    def test_inline_list_and_block_list(self):
        text = "---\nname: x\ntags: [a, b, c]\nitems:\n  - one\n  - two\n---\n"
        doc = parse_frontmatter(text)
        self.assertEqual(doc.data["tags"], ["a", "b", "c"])
        self.assertEqual(doc.data["items"], ["one", "two"])

    def test_comment_and_quotes(self):
        text = "---\nname: 'quoted: colon'  # comment here\nflag: true\n---\n"
        doc = parse_frontmatter(text)
        self.assertEqual(doc.data["name"], "quoted: colon")
        self.assertIs(doc.data["flag"], True)

    def test_no_frontmatter(self):
        doc = parse_frontmatter("# just markdown\n")
        self.assertEqual(doc.data, {})
        self.assertTrue(doc.parse_warnings)


def _write_skill(root: Path, name: str, body: str, meta_name: str | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(
        f"---\nname: {meta_name or name}\ndescription: test skill {name}\n---\n{body}",
        encoding="utf-8",
    )
    return p


class TestClassifier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = Config(
            sources=[SourceRoot(label="src", path=self.root)],
            target=TargetRoot(label="tgt", path=self.root / "target"),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _skill(self, name: str, body: str):
        from skillsync.frontmatter import parse_file

        p = _write_skill(self.root, name, body)
        doc = parse_file(p)
        from skillsync.model import Skill

        return Skill(name=name, path=p, source="src", root=self.root, frontmatter=doc.data)

    def test_category_a_clean(self):
        s = self._skill("clean", "# Title\nUse `git` and `node` to do things.\n")
        classify(s, self.cfg)
        self.assertEqual(s.category, "A", s.category_reason)

    def test_category_b_missing_command(self):
        s = self._skill("needs-tool", "# Title\nRun this:\n```\nheygen create avatar\n```\n")
        classify(s, self.cfg)
        self.assertEqual(s.category, "B")
        self.assertIn("heygen", s.missing_deps)

    def test_category_c_other_agent_conventions(self):
        s = self._skill("claude-style", "# Title\nWrite rules into AGENTS.md and call image_gen.\n")
        classify(s, self.cfg)
        self.assertEqual(s.category, "C")

    def test_category_d_private_marker(self):
        s = self._skill("private", "# Title\nUse codex-security scan id to triage.\n")
        classify(s, self.cfg)
        self.assertEqual(s.category, "D")

    def test_system_root_is_d(self):
        sysroot = self.root / "sysroot"
        p = _write_skill(sysroot, "imagegen", "# x\n")
        cfg = Config(sources=[SourceRoot(label="codex-system", path=sysroot, system=True)])
        from skillsync.frontmatter import parse_file
        from skillsync.model import Skill

        doc = parse_file(p)
        s = Skill(name="imagegen", path=p, source="codex-system", root=sysroot, frontmatter=doc.data)
        classify(s, cfg)
        self.assertEqual(s.category, "D")


class TestScanDiffSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.src_root = base / "src"
        self.tgt_root = base / "tgt"
        self.src_root.mkdir()
        self.tgt_root.mkdir()
        self.cfg = Config(
            sources=[SourceRoot(label="src", path=self.src_root)],
            target=TargetRoot(label="tgt", path=self.tgt_root),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_picks_up_skills(self):
        _write_skill(self.src_root, "alpha", "# a\n")
        _write_skill(self.src_root, "beta", "# b\n")
        result = scan(self.cfg)
        self.assertEqual({s.name for s in result.skills}, {"alpha", "beta"})

    def test_diff_missing_identical_drifted(self):
        _write_skill(self.src_root, "new-one", "# n\n")
        _write_skill(self.src_root, "same-one", "# s\n")
        _write_skill(self.src_root, "diff-one", "# d source version\n")
        _write_skill(self.tgt_root, "same-one", "# s\n")
        _write_skill(self.tgt_root, "diff-one", "# d TARGET EDITED\n")

        result = scan(self.cfg)
        diff_all(result.skills, self.cfg)
        states = {s.name: sync_state(s) for s in result.skills}
        self.assertEqual(states["new-one"], "missing")
        self.assertEqual(states["same-one"], "identical")
        self.assertEqual(states["diff-one"], "drifted")

    def test_sync_plan_and_execute_with_backup(self):
        _write_skill(self.src_root, "portable", "# p\nuse `git` only\n")
        _write_skill(self.tgt_root, "portable", "# p OLD VERSION\nuse `git` only\n")

        result = scan(self.cfg)
        for s in result.skills:
            s.category = "A"
        report = plan_sync(result.skills, self.tgt_root, force=True)
        self.assertEqual(len(report.planned), 1)
        self.assertEqual(report.planned[0].action, "update")

        # Dry run changes nothing.
        execute_sync(report, self.tgt_root, dry_run=True)
        self.assertIn("OLD VERSION", (self.tgt_root / "portable" / "SKILL.md").read_text())

        execute_sync(report, self.tgt_root, dry_run=False)
        self.assertIn("# p\n", (self.tgt_root / "portable" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(len(report.backed_up), 1)
        backup_file = report.backed_up[0] / "SKILL.md"
        self.assertIn("OLD VERSION", backup_file.read_text())

    def test_sync_skips_venv_and_env(self):
        skill_dir = self.src_root / "heavy"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: heavy\n---\nbody", encoding="utf-8")
        (skill_dir / ".env").write_text("SECRET=abc", encoding="utf-8")
        venv = skill_dir / ".venv" / "Scripts"
        venv.mkdir(parents=True)
        (venv / "python.exe").write_text("fake", encoding="utf-8")

        result = scan(self.cfg)
        for s in result.skills:
            s.category = "A"
        report = plan_sync(result.skills, self.tgt_root)
        execute_sync(report, self.tgt_root)
        dest = self.tgt_root / "heavy"
        self.assertTrue((dest / "SKILL.md").exists())
        self.assertFalse((dest / ".env").exists())
        self.assertFalse((dest / ".venv").exists())

    def test_marketplace_nested_layout(self):
        # <cache>/<plugin>/<version>/skills/<name>/SKILL.md
        deep = self.src_root / "myplugin" / "1.0.0" / "skills" / "nested-skill"
        deep.mkdir(parents=True)
        (deep / "SKILL.md").write_text("---\nname: nested-skill\n---\nx", encoding="utf-8")
        cfg = Config(sources=[SourceRoot(label="cache", path=self.src_root, glob="**/skills/*/SKILL.md")])
        result = scan(cfg)
        self.assertEqual(len(result.skills), 1)
        # Marketplace layout yields a qualified "plugin:skill" name; the
        # frontmatter's declared name wins for display matching.
        self.assertIn(result.skills[0].name, {"nested-skill", "myplugin:nested-skill"})

    def test_line_endings_are_not_drift(self):
        src = self.src_root / "eol"
        src.mkdir()
        (src / "SKILL.md").write_bytes(b"---\nname: eol\n---\nline1\nline2\n")
        tgt = self.tgt_root / "eol"
        tgt.mkdir()
        (tgt / "SKILL.md").write_bytes(b"---\r\nname: eol\r\n---\r\nline1\r\nline2\r\n")
        result = scan(self.cfg)
        diff_all(result.skills, self.cfg)
        self.assertEqual(sync_state(result.skills[0]), "identical")


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root_a = base / "a"
        self.root_b = base / "b"
        self.root_a.mkdir()
        self.root_b.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _skill(self, root: Path, name: str, content: str, source: str):
        from skillsync.frontmatter import parse_file
        from skillsync.model import Skill

        p = _write_skill(root, name, content)
        doc = parse_file(p)
        return Skill(name=name, path=p, source=source, root=root, frontmatter=doc.data)

    def test_identical_copies_collapse(self):
        from skillsync.resolve import resolve

        s1 = self._skill(self.root_a, "shared", "# same\n", "codex")
        s2 = self._skill(self.root_b, "shared", "# same\n", "qoder-cn")
        resolved, dups, shadowed = resolve([s2, s1], source_priority=("codex", "qoder-cn"))
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].source, "codex")
        self.assertEqual(dups, [("shared", ["codex", "qoder-cn"])])
        self.assertEqual(shadowed, [])

    def test_variants_shadow_lower_priority(self):
        from skillsync.resolve import resolve

        s1 = self._skill(self.root_a, "v", "# version A\n", "codex")
        s2 = self._skill(self.root_b, "v", "# version B\n", "qoder-cn")
        resolved, dups, shadowed = resolve([s2, s1], source_priority=("codex", "qoder-cn"))
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].source, "codex")  # canonical wins
        self.assertEqual(dups, [])
        self.assertEqual(shadowed, [("v", "codex", ["qoder-cn"])])

    def test_qualified_names_match_bare(self):
        from skillsync.resolve import resolve

        s1 = self._skill(self.root_a, "tool", "# same\n", "codex-marketplace")
        s1.name = "agent-skills:tool"
        s2 = self._skill(self.root_b, "tool", "# same\n", "codex")
        resolved, dups, shadowed = resolve([s1, s2])
        self.assertEqual(len(resolved), 1)
        self.assertEqual(dups[0][0], "tool")

    def test_distinct_skills_same_basename_not_merged(self):
        from skillsync.resolve import resolve

        # agent-skills:test-driven-development → target "test-driven-development"
        # superpowers:test-driven-development  → target "superpowers-test-driven-development"
        s1 = self._skill(self.root_a, "test-driven-development", "# agent skills ver\n", "codex-marketplace")
        s1.name = "agent-skills:test-driven-development"
        s2 = self._skill(self.root_b, "test-driven-development", "# superpowers ver\n", "codex-marketplace")
        s2.name = "superpowers:test-driven-development"
        resolved, dups, shadowed = resolve([s1, s2])
        self.assertEqual(len(resolved), 2)  # two distinct skills, NOT merged
        names = {r.name for r in resolved}
        self.assertEqual(names, {"agent-skills:test-driven-development",
                                 "superpowers:test-driven-development"})


class TestSyncControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.codex = base / "codex"
        self.qoder = base / "qoder"
        self.tgt = base / "tgt"
        self.codex.mkdir()
        self.qoder.mkdir()
        self.tgt.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _skill(self, root, name, content, source, category="A"):
        from skillsync.frontmatter import parse_file
        from skillsync.model import Skill

        p = _write_skill(root, name, content)
        doc = parse_file(p)
        s = Skill(name=name, path=p, source=source, root=root, frontmatter=doc.data)
        s.category = category
        return s

    def test_drifted_only_never_adds_new(self):
        from skillsync.differ import diff_all
        from skillsync.config import Config, SourceRoot, TargetRoot
        from skillsync.sync import plan_sync

        existing = self._skill(self.codex, "have", "# new version\n", "codex")
        brand_new = self._skill(self.codex, "never-synced", "# x\n", "codex")
        # target has an OLD version of "have", nothing for "never-synced"
        _write_skill(self.tgt, "have", "# OLD version\n")

        cfg = Config(sources=[SourceRoot(label="codex", path=self.codex)],
                     target=TargetRoot(label="tgt", path=self.tgt))
        diff_all([existing, brand_new], cfg)

        report = plan_sync([existing, brand_new], self.tgt, force=True, drifted_only=True)
        planned_names = {i.skill.name for i in report.planned}
        self.assertEqual(planned_names, {"have"})
        self.assertNotIn("never-synced", planned_names)

    def test_source_priority_first_wins(self):
        from skillsync.sync import plan_sync

        # Same skill name from two roots, both would write to tgt/dup.
        codex_ver = self._skill(self.codex, "dup", "# from codex\n", "codex")
        qoder_ver = self._skill(self.qoder, "dup", "# from qoder\n", "qoder-cn")
        report = plan_sync([qoder_ver, codex_ver], self.tgt)
        updates = [i for i in report.planned if i.action == "copy"]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].skill.source, "codex")  # higher priority wins
        self.assertEqual(len(report.skipped), 1)
        self.assertIn("already planned", report.skipped[0].note)


class TestStateChangeDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.src = base / "src"
        self.tgt = base / "tgt"
        self.src.mkdir()
        self.tgt.mkdir()
        self.cfg = Config(
            sources=[SourceRoot(label="src", path=self.src)],
            target=TargetRoot(label="tgt", path=self.tgt),
        )
        self.state_path = base / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _scan(self):
        from skillsync.classifier import classify_all
        from skillsync.differ import diff_all
        from skillsync.scanner import scan

        r = scan(self.cfg)
        classify_all(r.skills, self.cfg)
        diff_all(r.skills, self.cfg)
        return r

    def test_first_run_is_baseline(self):
        from skillsync.state import compare, load_snapshot, save_snapshot, snapshot_from

        _write_skill(self.src, "a", "# a\n")
        r = self._scan()
        self.assertEqual(compare(None, r), [])
        save_snapshot(self.state_path, snapshot_from(r))
        self.assertIsNotNone(load_snapshot(self.state_path))

    def test_detects_content_new_and_removed(self):
        from skillsync.state import compare, load_snapshot, save_snapshot, snapshot_from

        _write_skill(self.src, "a", "# a v1\n")
        _write_skill(self.src, "gone", "# gone\n")
        r1 = self._scan()
        save_snapshot(self.state_path, snapshot_from(r1))

        # upstream: modify a, remove gone, add b
        (self.src / "a" / "SKILL.md").write_text("---\nname: a\n---\n# a v2\n", encoding="utf-8")
        import shutil

        shutil.rmtree(self.src / "gone")
        _write_skill(self.src, "b", "# b\n")
        r2 = self._scan()

        changes = compare(load_snapshot(self.state_path), r2)
        kinds = {(c.kind, c.key.split(":", 1)[1]) for c in changes}
        self.assertIn(("content", "a"), kinds)
        self.assertIn(("removed", "gone"), kinds)
        self.assertIn(("new", "b"), kinds)

    def test_corrupt_snapshot_treated_as_absent(self):
        from skillsync.state import compare, load_snapshot

        self.state_path.write_text("{ not json", encoding="utf-8")
        _write_skill(self.src, "a", "# a\n")
        r = self._scan()
        self.assertIsNone(load_snapshot(self.state_path))
        self.assertEqual(compare(None, r), [])


if __name__ == "__main__":
    unittest.main()
