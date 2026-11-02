import importlib.util
from pathlib import Path
import unittest

from openpush_scan import bundle
from openpush_scan.manifest import empty
from openpush_scan.redact import RULES, apply


# In an openpush checkout the package is <repo>/scan/openpush_scan.
SERVER_MANIFEST = bundle.package_dir().parents[1] / "server" / "manifest.py"


class RedactionTests(unittest.TestCase):
    def test_sensitive_values_are_removed_and_queries_are_stripped(self):
        doc = empty("0.1.0")
        doc["strings"] = [{"key": "contact", "value": "Contact help@example.com"}]
        doc["tags"] = [{"key": "blob", "value_samples": ["a" * 40], "platforms": ["ios"]}]
        doc["screens"] = [{"name": "Cart", "route": "/Users/dev/App/Cart.swift"}]
        doc["deep_links"] = [{"kind": "custom_scheme", "scheme": "myapp", "host": None, "path": "/cart", "platforms": ["ios"], "full_urls": ["myapp://cart?token=abc"]}]
        cleaned, report = apply(doc)
        self.assertEqual(cleaned["strings"], [])
        self.assertEqual(cleaned["tags"][0]["value_samples"], [])
        self.assertEqual(cleaned["screens"][0]["route"], None)
        self.assertEqual(cleaned["deep_links"][0]["full_urls"], ["myapp://cart"])
        self.assertEqual(report["dropped"], 4)

    def test_jwt_drops_all_release_notes(self):
        doc = empty("0.1.0")
        doc["release_notes"] = {"version": "1.0", "locale": "en", "text": "eyJabcdefghijk.abcdefghijk.abcdefghijk"}
        cleaned, report = apply(doc)
        self.assertIsNone(cleaned["release_notes"])
        self.assertEqual(report["by_rule"]["jwt"], 1)

    def test_aws_access_key_is_removed(self):
        doc = empty("0.1.0")
        doc["strings"] = [{"key": "api_key", "value": "AKIAABCDEFGHIJKLMNOP"}]
        cleaned, report = apply(doc)
        self.assertEqual(cleaned["strings"], [])
        self.assertEqual(report["by_rule"]["secret-shaped"], 1)

    @unittest.skipUnless(SERVER_MANIFEST.exists(), "monorepo only: compares with server/manifest.py")
    def test_server_rules_are_identical(self):
        server_path = SERVER_MANIFEST
        spec = importlib.util.spec_from_file_location("server_manifest_rules", server_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        ours = [(name, pattern.pattern, action) for name, pattern, action in RULES]
        theirs = [(name, pattern.pattern, action) for name, pattern, action in module.RULES]
        self.assertEqual(ours, theirs)


if __name__ == "__main__":
    unittest.main()
