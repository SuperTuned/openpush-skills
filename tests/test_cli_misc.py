import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from openpush_scan import share
from openpush_scan.cli import main
from openpush_scan.manifest import empty


class MiscCommandTests(unittest.TestCase):
    def test_explain_renders_every_category(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["explain"]), 0)
        for category in share.DEFAULTS:
            self.assertIn(category, out.getvalue())

    def test_workflow_contains_release_guard_and_secret(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["ci", "--print-workflow"]), 0)
        self.assertIn("--on-version-change", out.getvalue())
        self.assertIn("secrets.OPENPUSH_API_KEY", out.getvalue())
        public = 'pipx run --spec "git+https://github.com/SuperTuned/openpush-skills"'
        self.assertEqual(out.getvalue().count("git+https://"), 3)
        self.assertEqual(out.getvalue().count(public), 3)

    def test_validate_checks_a_model_reconciled_local_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(empty("0.1.0")), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["validate", "--manifest", str(path)]), 0)
        self.assertIn("Manifest valid:", out.getvalue())

    def test_validate_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text("not-json", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(main(["validate", "--manifest", str(path)]), 1)
        self.assertIn("Manifest is not valid JSON", err.getvalue())


if __name__ == "__main__":
    unittest.main()
