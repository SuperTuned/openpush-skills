import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpush_scan import share
from openpush_scan.auth import AuthError
from openpush_scan.cli import main
from openpush_scan.client import ClientError
from openpush_scan.manifest import empty


class CliShareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.json"
        self.profile = self.root / "profile.json"
        doc = empty("0.1.0")
        doc["app_version"] = "2.4.0"
        self.manifest.write_text(json.dumps(doc), encoding="utf-8")
        profile = share.new_profile("demo", "https://example.test")
        share.save(self.profile, profile)

    def tearDown(self):
        self.temp.cleanup()

    def args(self, command):
        return [command, "--manifest", str(self.manifest), "--profile", str(self.profile)]

    def test_share_requires_login_when_no_api_key(self):
        session = type("FakeSession", (), {
            "server": "https://example.test", "config": {}})()
        with patch.dict(os.environ, {}, clear=True), \
             patch("openpush_scan.cli.Session", return_value=session), \
             patch("openpush_scan.cli.OAuthClient.catalog",
                   side_effect=AuthError("Not signed in. Run `openpush-scan login` first.")), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            code = main(self.args("share"))
        self.assertEqual(2, code)
        self.assertIn("openpush-scan login", err.getvalue())

    def test_interactive_share_previews_then_confirms(self):
        catalog = {"workspaces": [{"id": "tc", "name": "Example Game", "apps": [
            {"id": "example-game", "name": "Example Game", "role": "manager", "can_share": True}
        ]}]}
        session = type("FakeSession", (), {
            "server": "https://example.test",
            "config": {"workspace": {"id": "tc", "name": "Example Game"}},
        })()
        prepared = {"confirm_token": "opc_one", "preview": {
            "shared_categories": {"events": True}, "counts": {"events": 2},
            "app_version": {"from": "2.3.0", "to": "2.4.0"},
            "diff": {"added": {"events": ["one"]}, "removed": {}}, "affected": [],
        }}
        with patch.dict(os.environ, {}, clear=True), \
             patch("openpush_scan.cli.Session", return_value=session), \
             patch("openpush_scan.cli.OAuthClient") as oauth_type, \
             patch("openpush_scan.cli.OAuthManifestClient") as client_type, \
             patch("builtins.input", return_value="yes"), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            oauth_type.return_value.catalog.return_value = catalog
            oauth_type.return_value.app_token.return_value = "secret-token"
            client_type.return_value.prepare.return_value = prepared
            client_type.return_value.confirm.return_value = {
                "result": {"manifest_id": "man_1", "suggestions": {"generated": 3}}}
            code = main(self.args("share") + ["--app", "example-game"])
        self.assertEqual(code, 0)
        self.assertIn("OpenPush share preview", out.getvalue())
        self.assertIn("Workspace: Example Game (tc)", out.getvalue())
        self.assertIn("• events: 2", out.getvalue())
        client_type.return_value.confirm.assert_called_once_with("example-game", "opc_one")

    def test_declining_the_server_preview_discards_the_upload(self):
        catalog = {"workspaces": [{"id": "tc", "name": "Example Game", "apps": [
            {"id": "example-game", "name": "Example Game", "role": "manager", "can_share": True}
        ]}]}
        session = type("FakeSession", (), {
            "server": "https://example.test",
            "config": {"workspace": {"id": "tc", "name": "Example Game"}},
        })()
        with patch.dict(os.environ, {}, clear=True), \
             patch("openpush_scan.cli.Session", return_value=session), \
             patch("openpush_scan.cli.OAuthClient") as oauth_type, \
             patch("openpush_scan.cli.OAuthManifestClient") as client_type, \
             patch("builtins.input", return_value="no"):
            oauth_type.return_value.catalog.return_value = catalog
            oauth_type.return_value.app_token.return_value = "secret-token"
            client_type.return_value.prepare.return_value = {
                "confirm_token": "opc_decline", "preview": {}}
            code = main(self.args("share") + ["--app", "example-game"])
        self.assertEqual(0, code)
        client_type.return_value.discard.assert_called_once_with(
            "example-game", "opc_decline")
        client_type.return_value.confirm.assert_not_called()

    def test_share_print_never_needs_a_key_or_network(self):
        out = io.StringIO()
        with patch("openpush_scan.cli.Session", side_effect=AssertionError("authentication used")), \
             patch("openpush_scan.cli.OAuthManifestClient", side_effect=AssertionError("network used")), \
             contextlib.redirect_stdout(out):
            code = main(self.args("share") + ["--print"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), share.apply(share.load(self.profile), json.loads(self.manifest.read_text())))

    def test_ci_renders_diff_and_only_fails_on_affected_when_requested(self):
        diff = {"added": {"events": ["new_event"], "deep_links": []}, "removed": {"events": [], "deep_links": ["myapp://old"]}, "version": {"old": "2.3.0", "new": "2.4.0"}, "affected": ['template "Cart" (deep_link myapp://old)']}
        with patch.dict(os.environ, {"OPENPUSH_API_KEY": "k"}), patch("openpush_scan.cli.Client.diff_manifest", return_value=diff):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(self.args("ci") + ["--fail-on-broken-links"])
        self.assertEqual(code, 1)
        self.assertIn("Added events (1)", out.getvalue())
        self.assertIn("Affected: template", out.getvalue())

    def test_ci_unreachable_is_a_concise_failure(self):
        with patch.dict(os.environ, {"OPENPUSH_API_KEY": "k"}), \
             patch("openpush_scan.cli.Client.diff_manifest",
                   side_effect=ClientError("Could not reach https://example.test: refused")), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            code = main(self.args("ci"))
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue().strip(),
                         "Could not reach https://example.test: refused")
        self.assertNotIn("Traceback", err.getvalue())

    def test_first_on_version_change_share_uploads(self):
        with patch.dict(os.environ, {"OPENPUSH_API_KEY": "k"}), \
             patch("openpush_scan.cli.Client.latest_version", return_value=None), \
             patch("openpush_scan.cli.Client.put_manifest",
                   return_value={"id": "man_first"}) as upload:
            code = main(self.args("share") + ["--on-version-change"])
        self.assertEqual(code, 0)
        upload.assert_called_once()


if __name__ == "__main__":
    unittest.main()
