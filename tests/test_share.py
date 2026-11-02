from pathlib import Path
import tempfile
import unittest

from openpush_scan import share
from openpush_scan.manifest import empty, validate


EXPECTED = ["platforms", "sdk", "app_version", "events", "event_property_keys", "tags", "tag_value_samples", "triggers", "trigger_value_samples", "outcomes", "aliases", "identity", "deep_links", "deep_links_full_urls", "capabilities", "locales", "local_notifications", "local_notification_copy", "screens", "strings", "release_notes", "inferences", "goal"]


class ShareTests(unittest.TestCase):
    def test_defaults_are_the_closed_category_list(self):
        self.assertEqual(list(share.DEFAULTS), EXPECTED)
        for default_off in ("tag_value_samples", "trigger_value_samples", "deep_links_full_urls", "local_notification_copy", "screens", "strings", "release_notes"):
            self.assertFalse(share.DEFAULTS[default_off])

    def test_apply_filters_categories_excludes_and_sources(self):
        doc = empty("0.1.0")
        doc["events"] = [
            {"name": "debug_boot", "property_keys": [], "call_count": 1, "platforms": ["ios"], "dynamic": False, "source": [{"file": "A.swift", "line": 1}]},
            {"name": "level_complete", "property_keys": ["level"], "call_count": 1, "platforms": ["ios"], "dynamic": False, "source": [{"file": "A.swift", "line": 2}]},
        ]
        doc["strings"] = [{"key": "welcome", "value": "Hello", "source": [{"file": "L", "line": 1}]}]
        profile = share.new_profile()
        profile["exclude"]["events"] = ["debug_*"]
        profile["goal"] = {"moment": "purchase", "event": "level_complete"}
        result = share.apply(profile, doc)
        self.assertEqual([item["name"] for item in result["events"]], ["level_complete"])
        self.assertEqual(result["strings"], [])
        self.assertFalse(result["shared_categories"]["strings"])
        self.assertNotIn("source", str(result))
        self.assertEqual(result["goal"]["moment"], "purchase")
        self.assertEqual(validate(result), [])

    def test_load_save_round_trip_stamps_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".openpush" / "scan-share.json"
            profile = share.new_profile("demo")
            share.save(path, profile)
            loaded = share.load(path)
            self.assertEqual(loaded["app"], "demo")
            self.assertTrue(loaded["reviewed_at"])
            self.assertTrue(loaded["reviewed_by"])


if __name__ == "__main__":
    unittest.main()
