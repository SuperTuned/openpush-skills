from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


from openpush_scan import bundle


AGENTS = bundle.skill_dir() / "agents"
# In an openpush checkout the package is <repo>/scan/openpush_scan.
SCRIPT = bundle.package_dir().parents[1] / "server" / "scripts" / "scan_agents_check.py"
HAS_CHECK = SCRIPT.exists()


class AgentDefinitionTests(unittest.TestCase):
    @unittest.skipUnless(HAS_CHECK, "monorepo only: needs server/scripts/scan_agents_check.py")
    def test_shipped_agents_pass_contract_check(self):
        result = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(HAS_CHECK, "monorepo only: needs server/scripts/scan_agents_check.py")
    def test_removed_heading_fails_contract_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "agents"
            shutil.copytree(AGENTS, copy)
            scanner = copy / "openpush-scanner.md"
            scanner.write_text(scanner.read_text(encoding="utf-8").replace("## SIGNALS", "## OMITTED"), encoding="utf-8")
            result = subprocess.run([sys.executable, SCRIPT, "--skills-dir", copy], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing contract heading", result.stderr)

    def test_agent_specific_safety_language(self):
        scanner = (AGENTS / "openpush-scanner.md").read_text(encoding="utf-8")
        reviewer = (AGENTS / "openpush-program-reviewer.md").read_text(encoding="utf-8")
        instrumenter = (AGENTS / "openpush-instrumenter.md").read_text(encoding="utf-8")
        documenter = (AGENTS / "openpush-documenter.md").read_text(encoding="utf-8")
        self.assertIn("ROUTER HANDOFF: scan complete; continue immediately with the local review playbook.", scanner)
        self.assertIn("local manifest is the only file you may edit", scanner.lower())
        self.assertIn("active allowlist", scanner)
        self.assertIn("openpush-scan validate", scanner)
        self.assertNotIn("openpush_", reviewer)
        self.assertIn("do not edit until the router says", instrumenter.lower())
        self.assertIn("exactly one file", documenter.lower())


if __name__ == "__main__":
    unittest.main()
