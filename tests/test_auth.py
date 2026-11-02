import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from openpush_scan.auth import AuthError, SERVICE, Session
from openpush_scan.cli import main


class SecureStore:
    priority = 1
    values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


class AuthTests(unittest.TestCase):
    def setUp(self):
        SecureStore.values = {}
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "config.json"
        backend = SecureStore()
        module = types.SimpleNamespace(
            get_keyring=lambda: backend,
            get_password=backend.get_password,
            set_password=backend.set_password,
            delete_password=backend.delete_password,
            errors=types.SimpleNamespace(PasswordDeleteError=KeyError),
        )
        self.keyring = patch.dict("sys.modules", {"keyring": module})
        self.keyring.start()

    def tearDown(self):
        self.keyring.stop()
        self.temp.cleanup()

    def test_tokens_live_only_in_the_secure_store(self):
        session = Session(self.path)
        bundle = {"access_token": "opat_secret", "refresh_token": "oprt_secret"}
        session.put_bundle(session.account_name(), bundle)
        session.config["account"] = {"email": "user@example.test"}
        session.save()
        self.assertEqual(bundle, session.token_bundle(session.account_name()))
        text = self.path.read_text()
        self.assertNotIn("opat_secret", text)
        self.assertNotIn("oprt_secret", text)
        self.assertIn((SERVICE, session.account_name()), SecureStore.values)

    def test_workspace_use_resolves_a_unique_prefix(self):
        session = Session(self.path)
        catalog = {"workspaces": [{"id": "tc", "name": "Example Game", "apps": []}]}
        with patch("openpush_scan.cli.Session", return_value=session), \
             patch("openpush_scan.cli.OAuthClient") as oauth, \
             patch("builtins.print") as output:
            oauth.return_value.catalog.return_value = catalog
            self.assertEqual(0, main(["workspace", "use", "exa"]))
        self.assertEqual({"id": "tc", "name": "Example Game"},
                         json.loads(self.path.read_text())["workspace"])
        output.assert_called_once()

    def test_insecure_keyring_is_refused(self):
        class Plaintext:
            priority = 1
        Plaintext.__module__ = "keyrings.alt.file"
        with patch("keyring.get_keyring", return_value=Plaintext()):
            with self.assertRaisesRegex(AuthError, "secure OS credential store"):
                Session(self.path).token_bundle("account")


if __name__ == "__main__":
    unittest.main()
