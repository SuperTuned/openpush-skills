"""Local commands must neither access credentials nor start remote work."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpush_scan.cli import main
from openpush_scan import share


class LocalBoundaryTests(unittest.TestCase):
    def test_scan_review_save_and_preview_stay_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "App.swift").write_text('OpenPush.trackEvent("purchase_completed")')
            manifest = root / "manifest.json"
            profile = root / "profile.json"
            output = io.StringIO()
            original_get = os.environ.get

            def local_environment(name, default=None):
                if name == "OPENPUSH_API_KEY":
                    self.fail("A local operation tried to access authentication")
                return original_get(name, default)

            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(os.environ, "get", side_effect=local_environment), \
                 patch("openpush_scan.cli.Client", side_effect=AssertionError("Remote client used")), \
                 patch("socket.socket", side_effect=AssertionError("Network used")), \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertEqual(main(["scan", str(root), "--out", str(manifest), "--json"]), 0)
                args = ["review", "--manifest", str(manifest), "--profile", str(profile)]
                # Missing profile is a local review state, not a login requirement.
                self.assertEqual(main(args + ["--non-interactive"]), 2)
                answers = iter(["skip", "toggle strings", "exclude events test_*", "save"])
                with patch("builtins.input", side_effect=lambda _: next(answers)):
                    self.assertEqual(main(args), 0)
                self.assertTrue(share.load(profile)["categories"]["strings"])
                self.assertEqual(main(args + ["--non-interactive"]), 0)
                preview = io.StringIO()
                with contextlib.redirect_stdout(preview):
                    self.assertEqual(main(["share", "--manifest", str(manifest), "--profile", str(profile), "--app", "demo", "--print"]), 0)
                self.assertEqual(json.loads(preview.getvalue()), share.apply(share.load(profile), json.loads(manifest.read_text())))
                # Scanning again with saved choices still does not call remote work.
                self.assertEqual(main(["scan", str(root), "--out", str(manifest), "--json"]), 0)
            for prompt in ("Set OPENPUSH_API_KEY", "Please log in", "connect to OpenPush"):
                self.assertNotIn(prompt, output.getvalue())


if __name__ == "__main__":
    unittest.main()
