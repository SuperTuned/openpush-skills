import contextlib
import io
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os

from openpush_scan.cli import main
from openpush_scan import bundle
from openpush_scan import __version__
from openpush_scan import install_record as record
from openpush_scan.installer import _frontmatter

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None


SKILL = bundle.skill_dir()
SKILLS = SKILL.parent
AGENTS = sorted((SKILL / "agents").glob("*.md"))
SKILL_FILES = sorted(p.relative_to(SKILL) for p in SKILL.rglob("*")
                     if p.is_file() and p.relative_to(SKILL).parts[0] not in ("agents", "scripts"))


class InstallerTests(unittest.TestCase):
    def run_install(self, root, *flags, home=None, which=None):
        out, err = io.StringIO(), io.StringIO()
        with patch("pathlib.Path.cwd", return_value=Path(root)), \
             patch("pathlib.Path.home", return_value=Path(home or root)), \
             patch("shutil.which", side_effect=which or (lambda name: None)), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["install-skill", *flags, "--from", str(SKILLS)])
        self.stderr = err.getvalue()
        return code, out.getvalue()

    def assert_skill_copied(self, root):
        for relative in SKILL_FILES:
            self.assertEqual((root / relative).read_bytes(), (SKILL / relative).read_bytes(), relative)
        self.assertFalse((root / "agents").exists(), "agent definitions stay out of the skill folder")
        for relative, source in bundle.files():
            self.assertEqual((root / "scripts" / relative).read_bytes(), source.read_bytes(), relative)
        self.assertEqual((root / "scripts" / bundle.ENTRY).read_text(encoding="utf-8"), bundle.ENTRY_SOURCE)
        self.assertTrue(os.access(root / "scripts" / bundle.ENTRY, os.X_OK))
        self.assertFalse((root / "scripts" / "openpush_scan" / "skills").exists())

    def test_claude_install_is_byte_identical_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = self.run_install(tmp, "--claude", "--project")
            self.assertEqual(code, 0)
            self.assert_skill_copied(Path(tmp) / ".claude" / "skills" / "openpush-scan")
            for agent in AGENTS:
                self.assertEqual((Path(tmp) / ".claude" / "agents" / agent.name).read_bytes(), agent.read_bytes())
            installed = Path(tmp) / ".claude" / "skills" / "openpush-scan" / "SKILL.md"
            before = installed.read_bytes()
            code, output = self.run_install(tmp, "--claude", "--project")
            self.assertEqual(code, 0)
            self.assertIn("Exists:", output)
            self.assertNotIn("Wrote:", output)
            self.assertEqual(installed.read_bytes(), before)

    def test_force_replaces_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_install(tmp, "--codex", "--project")
            installed = Path(tmp) / ".agents" / "skills" / "openpush-scan" / "SKILL.md"
            installed.write_text("stale", encoding="utf-8")
            code, output = self.run_install(tmp, "--codex", "--project", "--force")
            self.assertEqual(code, 0)
            self.assertNotIn("Exists:", output)
            self.assertEqual(installed.read_bytes(), (SKILL / "SKILL.md").read_bytes())

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11")
    def test_codex_uses_shared_skills_dir_and_toml_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_install(tmp, "--codex", "--project")
            self.assertEqual(code, 0)
            self.assert_skill_copied(Path(tmp) / ".agents" / "skills" / "openpush-scan")
            self.assertFalse((Path(tmp) / ".codex" / "skills").exists())
            for agent in AGENTS:
                fields, body = _frontmatter(agent.read_text(encoding="utf-8"))
                name = agent.stem.replace("-", "_")
                data = tomllib.loads((Path(tmp) / ".codex" / "agents" / f"{name}.toml").read_text())
                self.assertEqual(set(data), {"name", "description", "developer_instructions"})
                self.assertEqual(data["name"], name)
                self.assertEqual(data["description"], fields["description"])
                self.assertIn(body.strip(), data["developer_instructions"])
                self.assertIn(f"Use only these tools: {fields['tools']}.", data["developer_instructions"])
            self.assertIn("Codex: run $openpush-scan. Its four agents run as subagents.", output)
            entry = (Path(tmp) / ".agents" / "skills" / "openpush-scan" / "scripts" / "openpush-scan").as_posix()
            with patch("openpush_scan.portable.python_version",
                       lambda command: (3, 12) if command == ("py", "-3") else None):
                _, windows_like = self.run_install(tmp, "--codex", "--project", "--force")
            self.assertIn(f"Bundled scanner: py -3 {entry}", windows_like)

    def test_cursor_uses_native_skill_and_agent_dirs_without_a_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_install(tmp, "--cursor", "--project")
            self.assertEqual(code, 0)
            self.assert_skill_copied(Path(tmp) / ".agents" / "skills" / "openpush-scan")
            self.assertFalse((Path(tmp) / ".cursor" / "rules").exists())
            for agent in AGENTS:
                source, body = _frontmatter(agent.read_text(encoding="utf-8"))
                fields, rendered = _frontmatter((Path(tmp) / ".cursor" / "agents" / agent.name).read_text())
                self.assertEqual(fields["name"], source["name"])
                self.assertNotIn("model", fields)
                self.assertNotIn("tools", fields)
                self.assertIn(body.strip(), rendered)
                self.assertEqual(fields.get("readonly") == "true", source["tools"] == "Read")
            self.assertIn("Cursor: run /openpush-scan.", output)

    def test_copilot_agents_use_agent_md_and_tool_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_install(tmp, "--copilot", "--project")[0], 0)
            self.assert_skill_copied(Path(tmp) / ".agents" / "skills" / "openpush-scan")
            scanner, _ = _frontmatter((Path(tmp) / ".github" / "agents" / "openpush-scanner.agent.md").read_text())
            self.assertEqual(scanner["tools"], '["read", "search", "edit", "execute"]')
            reviewer, _ = _frontmatter((Path(tmp) / ".github" / "agents" / "openpush-program-reviewer.agent.md").read_text())
            self.assertEqual(reviewer["tools"], '["read"]')
            self.assertTrue(reviewer["description"].startswith('"'))
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as project:
            self.assertEqual(self.run_install(project, "--copilot", "--user", home=home)[0], 0)
            self.assertTrue((Path(home) / ".copilot" / "agents" / "openpush-scanner.agent.md").exists())
            self.assertTrue((Path(home) / ".agents" / "skills" / "openpush-scan" / "SKILL.md").exists())
            self.assertEqual(list(Path(project).iterdir()), [])

    def test_gemini_agents_list_gemini_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_install(tmp, "--gemini", "--project")[0], 0)
            text = (Path(tmp) / ".gemini" / "agents" / "openpush-documenter.md").read_text()
            self.assertTrue(text.startswith(
                "---\nname: openpush-documenter\n"
            ))
            self.assertIn("tools:\n  - read_file\n  - grep_search\n  - glob\n  - write_file\n---\n", text)
            reviewer = (Path(tmp) / ".gemini" / "agents" / "openpush-program-reviewer.md").read_text()
            self.assertIn("tools:\n  - read_file\n---\n", reviewer)

    def test_opencode_agents_map_tools_to_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_install(tmp, "--opencode", "--project")[0], 0)
            instrumenter = (Path(tmp) / ".opencode" / "agents" / "openpush-instrumenter.md").read_text()
            self.assertIn("mode: subagent\n", instrumenter)
            self.assertIn('  edit: allow\n  webfetch: deny\n  bash:\n    "*": deny\n'
                          '    "git diff *": allow\n    "git status": allow\n---\n', instrumenter)
            reviewer = (Path(tmp) / ".opencode" / "agents" / "openpush-program-reviewer.md").read_text()
            self.assertIn("  edit: deny\n  webfetch: deny\n  bash: deny\n---\n", reviewer)
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as project:
            self.assertEqual(self.run_install(project, "--opencode", "--user", home=home)[0], 0)
            self.assertTrue((Path(home) / ".config" / "opencode" / "agents" / "openpush-scanner.md").exists())

    def test_skill_only_targets_say_they_run_sequentially(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_install(tmp, "--amp", "--windsurf", "--kiro", "--project")
            self.assertEqual(code, 0)
            self.assert_skill_copied(Path(tmp) / ".agents" / "skills" / "openpush-scan")
            self.assert_skill_copied(Path(tmp) / ".kiro" / "skills" / "openpush-scan")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [".agents", ".kiro"])
            for label in ("Amp", "Windsurf", "Kiro"):
                self.assertIn(f"{label}: ask it to use the openpush-scan skill. It has no subagent files, "
                              "so the skill runs the four steps one after another.", output)

    def test_shared_skill_is_written_once_for_several_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_install(tmp, "--codex", "--cursor", "--copilot", "--project")
            self.assertEqual(code, 0)
            skill = Path(tmp) / ".agents" / "skills" / "openpush-scan" / "SKILL.md"
            self.assertEqual(output.count(f"Wrote: {skill}\n"), 1)
            self.assertNotIn("Exists:", output)

    def test_all_installs_for_detected_agents_plus_named_ones(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as project:
            (Path(home) / ".codex").mkdir()
            code, output = self.run_install(
                project, "--all", "--kiro", "--project", home=home,
                which=lambda name: "/usr/bin/gemini" if name == "gemini" else None,
            )
            self.assertEqual(code, 0)
            installed = sorted(p.name for p in Path(project).iterdir())
            self.assertEqual(installed, [".agents", ".codex", ".gemini", ".kiro"])
            for label in ("Codex", "Gemini CLI", "Kiro"):
                self.assertIn(f"{label}: ", output)
            self.assertNotIn("Claude Code: ", output)

    def test_all_with_nothing_detected_names_the_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_install(tmp, "--all", "--project")
            self.assertEqual(code, 2)
            self.assertEqual(output, "")
            self.assertIn("--codex", self.stderr)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_read_only_project_refuses_before_any_partial_write(self):
        for flags in (("--claude",), ("--codex", "--cursor", "--copilot", "--gemini", "--opencode")):
            with tempfile.TemporaryDirectory() as tmp:
                os.chmod(tmp, 0o555)
                try:
                    code, output = self.run_install(tmp, *flags, "--project")
                    self.assertEqual(code, 1)
                    self.assertEqual(output, "")
                    self.assertIn(str(Path(tmp)), self.stderr)
                    self.assertEqual(list(Path(tmp).iterdir()), [])
                finally:
                    os.chmod(tmp, 0o755)


    def run_uninstall(self, root, *flags, home=None):
        out, err = io.StringIO(), io.StringIO()
        with patch("pathlib.Path.cwd", return_value=Path(root)), \
             patch("pathlib.Path.home", return_value=Path(home or root)), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["uninstall-skill", *flags])
        self.stderr = err.getvalue()
        return code, out.getvalue()

    def test_marker_records_version_and_agent_files_per_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_install(tmp, "--codex", "--amp", "--project")
            marker = json.loads((Path(tmp) / ".agents" / "skills" / "openpush-scan" / record.MARKER).read_text())
            self.assertEqual(marker["name"], "openpush-scan")
            self.assertEqual(marker["version"], __version__)
            self.assertEqual(marker["targets"]["amp"], [])
            self.assertEqual(sorted(marker["targets"]["codex"]),
                             sorted(f".codex/agents/{a.stem.replace('-', '_')}.toml" for a in AGENTS))

    def test_force_removes_stale_files_but_never_the_users_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.run_install(tmp, "--codex", "--project")
            root = base / ".agents" / "skills" / "openpush-scan"
            stale_module = root / "scripts" / "openpush_scan" / "retired_module.py"
            stale_module.write_text("old = True\n", encoding="utf-8")
            stale_agent = base / ".codex" / "agents" / "openpush_retired.toml"
            stale_agent.write_text('name = "openpush_retired"\n', encoding="utf-8")
            mine = base / ".codex" / "agents" / "my_reviewer.toml"
            mine.write_text('name = "my_reviewer"\n', encoding="utf-8")
            marker = json.loads((root / record.MARKER).read_text())
            marker["targets"]["codex"].append(".codex/agents/openpush_retired.toml")
            (root / record.MARKER).write_text(json.dumps(marker))
            code, output = self.run_install(tmp, "--codex", "--project", "--force")
            self.assertEqual(code, 0, self.stderr)
            self.assertFalse(stale_module.exists())
            self.assertFalse(stale_agent.exists())
            self.assertIn(f"Removed: {stale_agent}", output)
            self.assertEqual(mine.read_text(), 'name = "my_reviewer"\n')
            self.assertEqual(sorted(p.name for p in root.parent.iterdir()), ["openpush-scan"])
            self.assert_skill_copied(root)
            self.assertNotIn(".codex/agents/openpush_retired.toml",
                             json.loads((root / record.MARKER).read_text())["targets"]["codex"])

    def test_folder_with_a_foreign_skill_is_refused_before_any_write(self):
        for force in ((), ("--force",)):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / ".agents" / "skills" / "openpush-scan"
                root.mkdir(parents=True)
                (root / "SKILL.md").write_text("---\nname: something-else\ndescription: x\n---\n", encoding="utf-8")
                code, output = self.run_install(tmp, "--codex", "--claude", "--project", *force)
                self.assertEqual(code, 1)
                self.assertEqual(output, "")
                self.assertIn("Refusing to change", self.stderr)
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [".agents"])
                self.assertEqual(sorted(p.name for p in root.iterdir()), ["SKILL.md"])

    def test_skill_folder_from_npx_is_ours_by_its_skill_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".agents" / "skills" / "openpush-scan"
            root.mkdir(parents=True)
            (root / "SKILL.md").write_bytes((SKILL / "SKILL.md").read_bytes())
            (root / "leftover.md").write_text("old", encoding="utf-8")
            code, output = self.run_install(tmp, "--codex", "--project")
            self.assertEqual(code, 0, self.stderr)
            self.assertIn(f"Exists: {root} (use --force to replace)", output)
            self.assertTrue((root / "leftover.md").exists())
            marker = json.loads((root / record.MARKER).read_text())
            self.assertIsNone(marker["version"])
            self.assertEqual(len(marker["targets"]["codex"]), len(AGENTS))
            code, output = self.run_install(tmp, "--codex", "--project", "--force")
            self.assertEqual(code, 0, self.stderr)
            self.assertFalse((root / "leftover.md").exists())
            self.assert_skill_copied(root)

    def test_uninstall_removes_what_one_target_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.run_install(tmp, "--codex", "--cursor", "--project")
            mine = base / ".cursor" / "agents" / "mine.md"
            mine.write_text("mine", encoding="utf-8")
            root = base / ".agents" / "skills" / "openpush-scan"
            code, output = self.run_uninstall(tmp, "--codex", "--project")
            self.assertEqual(code, 0)
            self.assertEqual(list((base / ".codex" / "agents").iterdir()), [])
            self.assertIn(f"Kept: {root} (still installed for Cursor)", output)
            self.assertTrue((root / "SKILL.md").exists())
            code, output = self.run_uninstall(tmp, "--cursor", "--project")
            self.assertEqual(code, 0)
            self.assertIn(f"Removed: {root}", output)
            self.assertFalse(root.exists())
            self.assertEqual([p.name for p in (base / ".cursor" / "agents").iterdir()], ["mine.md"])
            self.assertIn("Not installed:", self.run_uninstall(tmp, "--cursor", "--project")[1])

    def test_uninstall_all_in_home(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as project:
            self.run_install(project, "--claude", "--codex", "--opencode", "--kiro", "--user", home=home)
            mine = Path(home) / ".claude" / "agents" / "mine.md"
            mine.write_text("mine", encoding="utf-8")
            code, output = self.run_uninstall(project, "--all", "--user", home=home)
            self.assertEqual(code, 0)
            left = sorted(p.relative_to(home).as_posix() for p in Path(home).rglob("*") if p.is_file())
            self.assertEqual(left, [".claude/agents/mine.md"])
            self.assertEqual(list(Path(project).iterdir()), [])

    def test_uninstall_without_a_record_keeps_agent_files_and_refuses_foreign_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.run_install(tmp, "--codex", "--project")
            root = base / ".agents" / "skills" / "openpush-scan"
            (root / record.MARKER).unlink()
            code, output = self.run_uninstall(tmp, "--codex", "--project")
            self.assertEqual(code, 0)
            self.assertFalse(root.exists())
            self.assertEqual(len(list((base / ".codex" / "agents").iterdir())), len(AGENTS))
            self.assertIn("Left alone:", output)
            foreign = base / ".claude" / "skills" / "openpush-scan"
            foreign.mkdir(parents=True)
            (foreign / "SKILL.md").write_text("---\nname: other\n---\n", encoding="utf-8")
            code, output = self.run_uninstall(tmp, "--claude", "--project")
            self.assertEqual(code, 1)
            self.assertIn("Not removed:", output)
            self.assertTrue((foreign / "SKILL.md").exists())

    # npx skills: folders it manages are left to it.

    def make_npx_folder(self, base, lock):
        root = Path(base) / ".agents" / "skills" / "openpush-scan"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_bytes((SKILL / "SKILL.md").read_bytes())
        (root / "from-npx.md").write_text("npx", encoding="utf-8")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"version": 1, "skills": {"openpush-scan": {"source": "x"}}}), encoding="utf-8")
        return root

    def snapshot(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def test_npx_project_folder_is_never_replaced_or_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "skills-lock.json"
            root = self.make_npx_folder(tmp, lock)
            before, lock_before = self.snapshot(root), lock.read_bytes()
            code, output = self.run_install(tmp, "--codex", "--project", "--force")
            self.assertEqual(code, 0, self.stderr)
            self.assertIn(f"Managed by npx skills: {root} was left as it is; "
                          "run npx skills update openpush-scan", output)
            self.assertEqual(self.snapshot(root), before)
            sidecar = Path(tmp) / ".agents" / record.MARKER
            listed = json.loads(sidecar.read_text())["targets"]["codex"]
            self.assertEqual(len(listed), len(AGENTS))
            self.assertTrue(all((Path(tmp) / rel).is_file() for rel in listed))
            code, output = self.run_uninstall(tmp, "--codex", "--project")
            self.assertEqual(code, 0)
            self.assertIn(f"Managed by npx skills: {root} was left as it is; "
                          "run npx skills remove openpush-scan", output)
            self.assertNotIn("-g", output.splitlines()[-1])
            self.assertEqual(self.snapshot(root), before)
            self.assertEqual(lock.read_bytes(), lock_before)
            self.assertFalse(sidecar.exists())
            self.assertEqual(list((Path(tmp) / ".codex" / "agents").iterdir()), [])

    def test_npx_global_folder_points_to_the_global_command(self):
        for xdg in (False, True):
            with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as project:
                state = Path(home) / "state"
                lock = state / "skills" / ".skill-lock.json" if xdg else Path(home) / ".agents" / ".skill-lock.json"
                root = self.make_npx_folder(home, lock)
                env = {"XDG_STATE_HOME": str(state)} if xdg else {}
                with patch.dict(os.environ, env, clear=False):
                    if not xdg:
                        os.environ.pop("XDG_STATE_HOME", None)
                    code, output = self.run_install(project, "--codex", "--user", home=home)
                    self.assertEqual(code, 0, self.stderr)
                    self.assertIn("run npx skills update openpush-scan -g", output)
                    code, output = self.run_uninstall(project, "--codex", "--user", home=home)
                self.assertIn("run npx skills remove openpush-scan -g", output)
                self.assertTrue((root / "from-npx.md").exists())

    def test_without_an_npx_lock_entry_the_folder_follows_the_usual_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "skills-lock.json"
            root = self.make_npx_folder(tmp, lock)
            lock.write_text(json.dumps({"version": 1, "skills": {"another-skill": {}}}), encoding="utf-8")
            code, output = self.run_install(tmp, "--codex", "--project", "--force")
            self.assertEqual(code, 0, self.stderr)
            self.assertIn(f"Replaced: {root}", output)
            self.assertFalse((root / "from-npx.md").exists())

    # Atomic --force: staging outside the skills folders, rollback on any failure.

    def assert_untouched(self, base, root, before, entries):
        self.assertEqual(self.snapshot(root), before)
        self.assertEqual(sorted(p.name for p in Path(base).iterdir()), entries)
        self.assertEqual([p.name for p in root.parent.iterdir()], ["openpush-scan"])

    def test_failed_or_interrupted_force_keeps_the_old_folder(self):
        def failing(real, fail_on, error):
            calls = {"n": 0}
            def wrapper(*args, **kwargs):
                calls["n"] += 1
                if calls["n"] == fail_on:
                    raise error
                return real(*args, **kwargs)
            return wrapper
        cases = [
            ("copy", "openpush_scan.folder_swap.shutil.copy2", shutil.copy2, 3, OSError("disk full")),
            ("old to backup", "openpush_scan.portable.os.rename", os.rename, 1, OSError("busy")),
            ("new to final", "openpush_scan.portable.os.rename", os.rename, 2, OSError("busy")),
            ("interrupted copy", "openpush_scan.folder_swap.shutil.copy2", shutil.copy2, 2, KeyboardInterrupt()),
            ("interrupted swap", "openpush_scan.portable.os.rename", os.rename, 2, KeyboardInterrupt()),
        ]
        for label, target, real, fail_on, error in cases:
            with self.subTest(step=label), tempfile.TemporaryDirectory() as tmp:
                self.run_install(tmp, "--codex", "--project")
                root = Path(tmp) / ".agents" / "skills" / "openpush-scan"
                (root / "old-only.txt").write_text("old", encoding="utf-8")
                before = self.snapshot(root)
                entries = sorted(p.name for p in Path(tmp).iterdir())
                with patch(target, side_effect=failing(real, fail_on, error)):
                    if isinstance(error, KeyboardInterrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            self.run_install(tmp, "--codex", "--project", "--force")
                    else:
                        code, _ = self.run_install(tmp, "--codex", "--project", "--force")
                        self.assertEqual(code, 1)
                self.assert_untouched(tmp, root, before, entries)

    def test_successful_force_leaves_nothing_beside_the_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_install(tmp, "--codex", "--claude", "--project")
            entries = sorted(p.name for p in Path(tmp).iterdir())
            self.assertEqual(self.run_install(tmp, "--codex", "--claude", "--project", "--force")[0], 0)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), entries)
            for skills in (Path(tmp) / ".agents" / "skills", Path(tmp) / ".claude" / "skills"):
                self.assertEqual([p.name for p in skills.iterdir()], ["openpush-scan"])

    def test_leftovers_from_an_interrupted_run_are_cleaned_up(self):
        for command in ("install-skill", "uninstall-skill"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                staging = base / ".openpush-scan-staging-abc123"
                staging.mkdir()
                (staging / "SKILL.md").write_bytes((SKILL / "SKILL.md").read_bytes())
                backup = base / ".openpush-scan-backup-abc123"
                backup.mkdir()
                record.write(backup / record.MARKER, record.new("0.0.1"))
                foreign = base / ".openpush-scan-staging-not-ours"
                foreign.mkdir()
                (foreign / "notes.txt").write_text("keep", encoding="utf-8")
                lookalike = base / ".openpush-scan-stagingX"
                lookalike.mkdir()
                if command == "install-skill":
                    code, output = self.run_install(tmp, "--codex", "--project")
                else:
                    code, output = self.run_uninstall(tmp, "--codex", "--project")
                self.assertEqual(code, 0)
                self.assertFalse(staging.exists())
                self.assertFalse(backup.exists())
                self.assertIn(f"Removed leftover: {staging}", output)
                self.assertTrue((foreign / "notes.txt").exists())
                self.assertTrue(lookalike.exists())

if __name__ == "__main__":
    unittest.main()
