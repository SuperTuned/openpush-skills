"""Windows behaviour, simulated on any platform.

Simulated here: the interpreter order (with a fake version probe), Windows config
and npx lock paths (pure Windows paths), a cp1252 console, Windows rename
semantics (rename onto an existing target fails), retries while a file is locked,
read-only files in a removed tree, and LF line endings.
Not covered without Windows: the real Microsoft Store stub, junctions created by
npx skills, real file locks and console code pages.
"""

import io
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from openpush_scan import auth, bundle, folder_swap, portable
from openpush_scan import install_record as record


SKILL = bundle.skill_dir()


class InterpreterOrderTests(unittest.TestCase):
    def test_order_matches_skill_md(self):
        setup = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(portable.PYTHON_CANDIDATES, (("python3",), ("py", "-3"), ("python",)))
        self.assertRegex(setup, r"try `python3`, then `py -3` \(the Windows launcher\), then `python`")

    def test_first_interpreter_with_python_3_9_wins(self):
        def probe(versions):
            return lambda command: versions.get(" ".join(command))
        # Windows without python3: the Store stub prints nothing, so py -3 is used.
        self.assertEqual(portable.choose_python(probe({"python3": None, "py -3": (3, 12), "python": (3, 11)})),
                         ("py", "-3"))
        self.assertEqual(portable.choose_python(probe({"python3": (3, 8), "python": (3, 10)})), ("python",))
        self.assertEqual(portable.choose_python(probe({"python3": (3, 9), "py -3": (3, 13)})), ("python3",))
        self.assertIsNone(portable.choose_python(probe({"python": (2, 7)})))

    def test_version_probe_reads_stdout_or_stderr_and_treats_silence_as_missing(self):
        def run_with(stdout, stderr="", error=None):
            def fake(*_args, **_kwargs):
                if error:
                    raise error
                return subprocess.CompletedProcess([], 0, stdout, stderr)
            return fake
        with patch("openpush_scan.portable.subprocess.run", run_with("Python 3.9.6\n")):
            self.assertEqual(portable.python_version(["python3"]), (3, 9))
        with patch("openpush_scan.portable.subprocess.run", run_with("", "Python 3.12.1\n")):
            self.assertEqual(portable.python_version(["py", "-3"]), (3, 12))
        with patch("openpush_scan.portable.subprocess.run", run_with("")):
            self.assertIsNone(portable.python_version(["python3"]))
        with patch("openpush_scan.portable.subprocess.run", run_with("", error=FileNotFoundError())):
            self.assertIsNone(portable.python_version(["py", "-3"]))


class WindowsPathTests(unittest.TestCase):
    def test_config_lives_in_appdata_on_windows(self):
        appdata = r"C:\Users\me\AppData\Roaming"
        self.assertEqual(auth.config_path({"APPDATA": appdata}, windows=True),
                         Path(appdata) / "openpush-scan" / "config.json")
        self.assertEqual(auth.config_path({"XDG_CONFIG_HOME": "/x"}, windows=False),
                         Path("/x/openpush-scan/config.json"))

    def test_npx_global_lock_uses_the_home_directory_on_windows(self):
        home = PureWindowsPath(r"C:\Users\me")
        self.assertEqual(record.npx_lock(home, True, environ={}),
                         PureWindowsPath(r"C:\Users\me\.agents\.skill-lock.json"))
        self.assertEqual(record.npx_lock(home, True, environ={"XDG_STATE_HOME": r"D:\state"}),
                         PureWindowsPath(r"D:\state\skills\.skill-lock.json"))
        self.assertEqual(record.npx_lock(PureWindowsPath(r"C:\work\app"), False, environ={}),
                         PureWindowsPath(r"C:\work\app\skills-lock.json"))

    def test_record_paths_are_written_with_forward_slashes(self):
        base = PureWindowsPath(r"C:\work\app")
        self.assertEqual(record.relative(base / ".codex" / "agents" / "openpush_scanner.toml", base),
                         ".codex/agents/openpush_scanner.toml")


class ConsoleTests(unittest.TestCase):
    def test_cp1252_stream_prints_question_marks_instead_of_failing(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        portable.safe_console(stream)
        stream.write("Version: 1.0 → 1.1 · done…")
        stream.flush()
        self.assertEqual(raw.getvalue().decode("cp1252"), "Version: 1.0 ? 1.1 · done…")

    def test_utf8_stream_is_left_alone(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        portable.safe_console(stream)
        self.assertEqual(stream.errors, "strict")

    def test_cli_runs_on_a_cp1252_console(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "openpush-scan"
            shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns("__pycache__"))
            bundle.write(skill / "scripts")
            app = Path(tmp) / "app"
            app.mkdir()
            (app / "App.swift").write_text('OpenPush.trackEvent("level_complete")\n', encoding="utf-8")
            env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "PYTHONIOENCODING": "cp1252"}
            run = lambda *args, stdin="": subprocess.run(  # noqa: E731
                [sys.executable, str(skill / "scripts" / bundle.ENTRY), *args], cwd=str(app), env=env,
                input=stdin.encode(), capture_output=True, timeout=120)
            scan = run("scan", ".", "--json")
            self.assertEqual(scan.returncode, 0, scan.stderr.decode("cp1252"))
            review = run("review", stdin="all\nsave\n")
            self.assertEqual(review.returncode, 0, review.stderr.decode("cp1252"))
            text = review.stdout.decode("cp1252")
            self.assertIn("## OpenPush sharing review", text)
            self.assertNotIn("Traceback", review.stderr.decode("cp1252"))


class FileTests(unittest.TestCase):
    def test_text_files_use_utf8_and_lf(self):
        calls = []
        real_open = open

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return real_open(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, patch("builtins.open", spy):
            portable.write_text(Path(tmp) / "a.json", "{}\n")
        self.assertEqual(calls[0]["newline"], "\n")
        self.assertEqual(calls[0]["encoding"], "utf-8")

    def test_tree_with_read_only_files_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "skill"
            (folder / "sub").mkdir(parents=True)
            locked = folder / "sub" / "SKILL.md"
            locked.write_text("x", encoding="utf-8")
            locked.chmod(stat.S_IREAD)
            (folder / "sub").chmod(stat.S_IREAD | stat.S_IEXEC)
            portable.remove_tree(folder)
            self.assertFalse(folder.exists())

    def test_link_is_removed_without_its_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "real"
            target.mkdir()
            (target / "SKILL.md").write_text("x", encoding="utf-8")
            link = Path(tmp) / "link"
            link.symlink_to(target, target_is_directory=True)
            self.assertTrue(portable.is_link(link))
            portable.remove_tree(link)
            self.assertFalse(link.exists() or link.is_symlink())
            self.assertTrue((target / "SKILL.md").exists())


class WindowsRenameTests(unittest.TestCase):
    def test_swap_never_renames_onto_an_existing_folder(self):
        real = os.rename

        def windows_rename(source, target):
            if os.path.lexists(target):
                raise FileExistsError(target)
            real(source, target)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".agents" / "skills" / "openpush-scan"
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text("old", encoding="utf-8")
            (root / "stale.txt").write_text("old", encoding="utf-8")
            source = Path(tmp) / "SKILL.md"
            source.write_text("new", encoding="utf-8")
            with patch("openpush_scan.portable.os.rename", windows_rename):
                replaced = folder_swap.replace(root, [(Path("SKILL.md"), source)], lambda staging: None)
            self.assertTrue(replaced)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["SKILL.md"])
            self.assertEqual((root / "SKILL.md").read_text(encoding="utf-8"), "new")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [".agents", "SKILL.md"])

    def test_rename_retries_while_windows_holds_a_file(self):
        calls = {"n": 0}

        def locked_twice(source, target):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("in use")

        with patch("openpush_scan.portable.os.name", "nt"), \
             patch("openpush_scan.portable.os.rename", locked_twice), \
             patch("openpush_scan.portable.time.sleep") as sleep:
            portable.rename("a", "b")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(sleep.call_count, 2)
        with patch("openpush_scan.portable.os.rename", side_effect=PermissionError("in use")):
            with self.assertRaises(PermissionError):
                portable.rename("a", "b")


if __name__ == "__main__":
    unittest.main()
