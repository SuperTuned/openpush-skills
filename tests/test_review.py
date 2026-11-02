import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpush_scan.cli import main
from openpush_scan.manifest import empty
from openpush_scan import review, share


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.json"
        doc = empty("0.1.0")
        doc["events"] = [{"name": "purchase_completed", "property_keys": [], "call_count": 1, "platforms": ["ios"], "dynamic": False}]
        self.manifest.write_text(json.dumps(doc), encoding="utf-8")
        self.profile = self.root / ".openpush" / "scan-share.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_noninteractive_requires_profile(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["review", "--manifest", str(self.manifest), "--profile", str(self.profile), "--non-interactive"])
        self.assertEqual(code, 2)
        self.assertIn("No share profile", out.getvalue())

    def test_noninteractive_renders_table_and_footers(self):
        profile = share.new_profile()
        share.save(self.profile, profile)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["review", "--manifest", str(self.manifest), "--profile", str(self.profile), "--non-interactive"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("| Selection | Category | Detected | Default | What OpenPush uses it for |", text)
        self.assertIn("| Not selected | Strings (`strings`) | 0 | Off |", text)
        self.assertIn("| Selected | Events (`events`) | 1 | On |", text)
        self.assertIn("Nothing has been uploaded", text)
        self.assertIn("before exclusions", text)
        rows = [line for line in text.splitlines() if line.startswith("| ")][2:]
        self.assertEqual(len(rows), len(share.DEFAULTS))
        self.assertTrue(all(len(row.split("|")) == 7 for row in rows))
        self.assertIn("Never shared:", text)
        self.assertIn("Dynamic calls not readable:", text)
        self.assertIn("Goal: not set", text)

    def test_scripted_review_updates_goal_toggle_and_exclude(self):
        answers = iter(["goal purchase purchase_completed", "toggle strings", "exclude events test_*", "save"])
        out = io.StringIO()
        with patch("builtins.input", lambda _prompt="": next(answers)), \
             contextlib.redirect_stdout(out):
            code = main(["review", "--manifest", str(self.manifest), "--profile", str(self.profile)])
        self.assertEqual(code, 0)
        profile = share.load(self.profile)
        self.assertEqual(profile["goal"]["moment"], "purchase")
        self.assertTrue(profile["categories"]["strings"])
        self.assertEqual(profile["exclude"]["events"], ["test_*"])
        self.assertGreaterEqual(out.getvalue().count("## OpenPush sharing review"), 2)
        self.assertIn("Do you want to share this final selection with OpenPush?", out.getvalue())

    def test_invalid_goal_is_rejected(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["review", "--manifest", str(self.manifest), "--profile", str(self.profile), "--goal", "revenue"])
        self.assertEqual(code, 2)
        self.assertIn("Goal must be one of", out.getvalue())

    def test_all_keeps_every_moment_without_an_event(self):
        answers = iter(["all", "save"])
        with patch("builtins.input", lambda _prompt="": next(answers)):
            code = main(["review", "--manifest", str(self.manifest),
                         "--profile", str(self.profile)])
        self.assertEqual(code, 0)
        self.assertEqual(share.load(self.profile)["goal"],
                         {"moment": "all", "event": None})

    def test_show_events_identifies_analytics_provider_and_local_source(self):
        out = []
        review._show("events", {"events": [{
            "name": "level_finished", "providers": ["amplitude"],
            "source": [{"file": "Game/Level.cs", "line": 42}],
        }]}, out.append)
        self.assertEqual(out, ["level_finished  via amplitude  Game/Level.cs:42"])


if __name__ == "__main__":
    unittest.main()
