import copy
import unittest

from openpush_scan import manifest


class ManifestTests(unittest.TestCase):
    def test_empty_manifest_is_valid(self):
        self.assertEqual(manifest.validate(manifest.empty("0.1.0")), [])

    def test_manifest_version_is_closed(self):
        doc = manifest.empty("0.1.0")
        doc["manifest_version"] = 2
        self.assertIn("manifest_version: not in enum", manifest.validate(doc))

    def test_event_names_follow_server_pattern(self):
        doc = manifest.empty("0.1.0")
        doc["events"] = [
            {
                "name": "checkout/complete",
                "property_keys": [],
                "call_count": 1,
                "platforms": ["ios"],
                "dynamic": False,
            }
        ]
        self.assertIn("events[0].name: does not match pattern", manifest.validate(doc))

    def test_event_cap_is_enforced(self):
        doc = manifest.empty("0.1.0")
        event = {
            "name": "event",
            "property_keys": [],
            "call_count": 1,
            "platforms": ["ios"],
            "dynamic": False,
        }
        doc["events"] = [copy.deepcopy(event) for _ in range(501)]
        self.assertIn("events: more than 500 items", manifest.validate(doc))

    def test_event_providers_are_schema_validated(self):
        doc = manifest.empty("0.1.0")
        doc["events"] = [{
            "name": "level_finished", "property_keys": [], "call_count": 1,
            "platforms": ["unity"], "providers": ["amplitude"], "dynamic": False,
        }]
        self.assertEqual(manifest.validate(doc), [])
        doc["events"][0]["providers"] = ["not a provider"]
        self.assertIn("events[0].providers[0]: does not match pattern",
                      manifest.validate(doc))

    def test_strip_sources_is_recursive_and_does_not_mutate_input(self):
        doc = manifest.empty("0.1.0")
        doc["events"] = [
            {
                "name": "checkout_complete",
                "property_keys": [],
                "call_count": 1,
                "platforms": ["ios"],
                "dynamic": False,
                "source": [{"file": "App/Checkout.swift", "line": 42}],
                "nested": {"source": [{"file": "Other.swift", "line": 3}]},
            }
        ]
        stripped = manifest.strip_sources(doc)
        self.assertNotIn("source", stripped["events"][0])
        self.assertNotIn("source", stripped["events"][0]["nested"])
        self.assertIn("source", doc["events"][0])

    def test_digest_is_stable_across_key_order(self):
        self.assertEqual(
            manifest.digest({"b": 2, "a": {"d": 4, "c": 3}}),
            manifest.digest({"a": {"c": 3, "d": 4}, "b": 2}),
        )

    def test_inference_basis_is_a_token(self):
        doc = manifest.empty("0.1.0")
        doc["inferences"] = [
            {
                "kind": "category",
                "value": "ecommerce",
                "basis": "because it has a paywall",
            }
        ]
        self.assertIn("inferences[0].basis: does not match pattern", manifest.validate(doc))

    def test_goal_moment_is_closed(self):
        doc = manifest.empty("0.1.0")
        doc["goal"] = {"moment": "revenue", "event": None}
        self.assertIn("goal.moment: not in enum", manifest.validate(doc))

    def test_all_is_a_valid_goal_without_an_event(self):
        doc = manifest.empty("0.1.0")
        doc["goal"] = {"moment": "all", "event": None}
        self.assertEqual(manifest.validate(doc), [])

    def test_release_notes_are_capped(self):
        doc = manifest.empty("0.1.0")
        doc["release_notes"] = {"version": "1.0", "locale": "en", "text": "x" * 1300}
        self.assertIn(
            "release_notes.text: longer than 1200 characters", manifest.validate(doc)
        )

    def test_nullable_sections_are_valid(self):
        doc = manifest.empty("0.1.0")
        doc["goal"] = None
        doc["release_notes"] = None
        self.assertEqual(manifest.validate(doc), [])


if __name__ == "__main__":
    unittest.main()
