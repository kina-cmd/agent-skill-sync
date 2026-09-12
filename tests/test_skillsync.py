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


if __name__ == "__main__":
    unittest.main()
