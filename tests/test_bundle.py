import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from openpush_scan import bundle


PACKAGE = bundle.package_dir()
SKILL = bundle.skill_dir()
# In an openpush checkout the package is <repo>/scan/openpush_scan.
ROOT = PACKAGE.parents[1]
EXPORT = ROOT / "scripts" / "export_openpush_skills.sh"


def package_files(package):
    return {p.relative_to(package).as_posix() for p in package.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
            and p.relative_to(package).parts[0] != "skills"}


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.skill = self.tmp / "skill" / "openpush-scan"
        shutil.copytree(SKILL, self.skill)
        bundle.write(self.skill / "scripts")
        self.entry = self.skill / "scripts" / bundle.ENTRY
        self.project = self.tmp / "app"
        self.project.mkdir()
        (self.project / "App.swift").write_text('OpenPush.trackEvent("level_complete")\n', encoding="utf-8")

    def run_bundled(self, *args, stdin="", cwd=None):
        # -S -I: no site-packages (so no keyring), no PYTHONPATH, no user site.
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp),
               "XDG_CONFIG_HOME": str(self.tmp / "config")}
        return subprocess.run([sys.executable, "-S", "-I", str(self.entry), *args],
                              cwd=str(cwd or self.project), env=env, input=stdin,
                              capture_output=True, text=True, timeout=120)

    def test_bundle_is_the_package_without_its_skill_data(self):
        written = {p.relative_to(self.skill / "scripts").as_posix()
                   for p in (self.skill / "scripts").rglob("*") if p.is_file()}
        expected = {f"openpush_scan/{name}" for name in package_files(PACKAGE)} | {bundle.ENTRY}
        self.assertEqual(written, expected)
        self.assertTrue(os.access(self.entry, os.X_OK))
        for relative, source in bundle.files():
            self.assertEqual((self.skill / "scripts" / relative).read_bytes(), source.read_bytes())

    def test_scan_review_and_local_share_run_on_the_stdlib(self):
        version = self.run_bundled("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        scan = self.run_bundled("scan", ".", "--json")
        self.assertEqual(scan.returncode, 0, scan.stderr)
        self.assertEqual(json.loads(scan.stdout)["events"], 1)
        self.assertEqual(self.run_bundled("validate").returncode, 0)
        review = self.run_bundled("review", stdin="all\nsave\n")
        self.assertEqual(review.returncode, 0, review.stderr)
        self.assertIn("## OpenPush sharing review", review.stdout)
        self.assertTrue((self.project / ".openpush" / "scan-share.json").exists())
        again = self.run_bundled("review", "--non-interactive")
        self.assertEqual(again.returncode, 0, again.stderr)
        printed = self.run_bundled("share", "--print", "--app", "demo")
        self.assertEqual(printed.returncode, 0, printed.stderr)
        self.assertIn("level_complete", printed.stdout)
        workflow = self.run_bundled("ci", "--print-workflow")
        self.assertEqual(workflow.returncode, 0, workflow.stderr)
        for result in (version, scan, review, again, printed, workflow):
            self.assertNotIn("Traceback", result.stderr)

    def test_login_and_share_without_keyring_explain_the_fallback(self):
        self.assertEqual(self.run_bundled("scan", ".", "--json").returncode, 0)
        self.assertEqual(self.run_bundled("review", stdin="all\nsave\n").returncode, 0)
        for args in (("login",), ("share", "--app", "demo"), ("auth", "status"), ("logout",)):
            with self.subTest(command=args[0]):
                result = self.run_bundled(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn("need the keyring package", result.stderr)
                self.assertIn("uvx --from", result.stderr)
                self.assertIn("pipx run --spec", result.stderr)

    def test_bundled_installer_copies_the_skill_bundle_and_agents(self):
        target = self.tmp / "other"
        target.mkdir()
        result = self.run_bundled("install-skill", "--codex", "--project", cwd=target)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = target / ".agents" / "skills" / "openpush-scan"
        for path in self.skill.rglob("*"):
            relative = path.relative_to(self.skill)
            if path.is_file() and relative.parts[0] != "agents" and "__pycache__" not in relative.parts:
                self.assertEqual((installed / relative).read_bytes(), path.read_bytes(), relative)
        self.assertTrue(os.access(installed / "scripts" / bundle.ENTRY, os.X_OK))
        self.assertEqual(len(list((target / ".codex" / "agents").glob("*.toml"))), 4)

    @unittest.skipUnless(EXPORT.exists() and (ROOT / ".git").exists() and shutil.which("git"),
                         "openpush only: runs the public export")
    def test_export_has_one_scanner_copy_matching_the_package(self):
        out = self.tmp / "export"
        result = subprocess.run(["bash", str(EXPORT), str(out)], capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr)
        committed = self.tmp / "committed"
        committed.mkdir()
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", "HEAD", "scan/openpush_scan"],
                                 capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(committed)], input=archive.stdout, check=True)
        package = committed / "scan" / "openpush_scan"
        scripts = out / "skills" / "openpush-scan" / "scripts"
        self.assertEqual({p.relative_to(scripts / "openpush_scan").as_posix()
                          for p in (scripts / "openpush_scan").rglob("*") if p.is_file()},
                         package_files(package))
        for name in package_files(package):
            self.assertEqual((scripts / "openpush_scan" / name).read_bytes(), (package / name).read_bytes())
        self.assertEqual((scripts / bundle.ENTRY).read_text(encoding="utf-8"), bundle.ENTRY_SOURCE)
        self.assertEqual(sorted(p.name for p in out.rglob("openpush_scan") if p.is_dir()), ["openpush_scan"])
        self.assertFalse((out / "packages").exists())
        self.assertTrue((out / "pyproject.toml").is_file())


if __name__ == "__main__":
    unittest.main()
