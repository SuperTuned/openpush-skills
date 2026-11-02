import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpush_scan.cli import main
from openpush_scan.manifest import strip_sources, validate


class ScanCommandTests(unittest.TestCase):
    def test_scan_writes_a_valid_local_manifest_and_json_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "App.swift"
            source.write_text('OpenPush.trackEvent("level_complete", properties: ["level": level])\nOpenPush.trackEvent(eventName)', encoding="utf-8")
            out = root / "manifest.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["scan", str(root), "--out", str(out), "--json"])
            self.assertEqual(code, 0)
            summary = json.loads(stdout.getvalue())
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(validate(strip_sources(doc)), [])
            self.assertEqual(summary["events"], 1)
            self.assertEqual(summary["dynamic_counts"]["events"], 1)

    def test_scan_refuses_an_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["scan", tmp])
            self.assertEqual(code, 1)
            self.assertIn("No OpenPush SDK calls or app manifests found", stderr.getvalue())

    def test_plain_scan_continues_into_guided_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "App.swift").write_text(
                'OpenPush.trackEvent("level_complete")', encoding="utf-8"
            )
            out = root / "manifest.json"
            profile = root / ".openpush" / "scan-share.json"
            stdout = io.StringIO()
            answers = iter(["all", "save"])
            with patch("builtins.input", side_effect=lambda _prompt="": next(answers)), \
                 contextlib.redirect_stdout(stdout):
                code = main([
                    "scan", str(root), "--out", str(out),
                    "--profile", str(profile),
                ])

            text = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertTrue(profile.exists())
            self.assertIn("## OpenPush sharing review", text)
            self.assertIn("Reply `save` or `looks good`", text)
            self.assertGreaterEqual(text.count("## OpenPush sharing review"), 2)
            self.assertIn("Do you want to share this final selection with OpenPush?", text)


if __name__ == "__main__":
    unittest.main()
