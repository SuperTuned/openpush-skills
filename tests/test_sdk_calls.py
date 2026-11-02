import json
from pathlib import Path
import tempfile
import unittest

from openpush_scan.extract.sdk_calls import scan_sdk_calls
from openpush_scan.manifest import empty, validate


class SdkCallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_swift_calls_merge_and_dynamic_calls_are_counted(self):
        self.write("App/Events.swift", '''
OpenPush.trackEvent("level_complete", properties: ["level": level, "score": score])
OpenPush.trackEvent("level_complete", properties: ["score": score])
OpenPush.trackEvent("purchase_completed")
OpenPush.trackEvent(eventName)
OpenPush.User.addTag(key: "plan", value: "pro")
OpenPush.InAppMessages.addTrigger("paywall_shown", withValue: "yes")
OpenPush.login(externalId, authHash: hash) { _ in }
OpenPush.LiveActivities.start()
''')
        self.write("Package.resolved", json.dumps({"pins": [{
            "location": "https://github.com/SuperTuned/openpush-ios",
            "state": {"version": "1.1.1"},
        }]}))
        result = scan_sdk_calls(self.root)
        events = {item["name"]: item for item in result["events"]}
        self.assertEqual(events["level_complete"]["call_count"], 2)
        self.assertEqual(events["level_complete"]["property_keys"], ["level", "score"])
        self.assertIn("purchase_completed", events)
        self.assertEqual(result["dynamic_counts"]["events"], 1)
        self.assertEqual(result["tags"][0]["key"], "plan")
        self.assertEqual(result["triggers"][0]["key"], "paywall_shown")
        self.assertEqual(result["identity"], {"login": True, "logout": False, "auth_hash": True})
        self.assertTrue(result["capabilities"]["live_activities"])
        self.assertEqual(result["sdk"]["ios"]["version_hint"], "1.1.1")

    def test_android_shim_and_unity_calls(self):
        self.write("android/Main.kt", '''
OpenPush.trackEvent("add_to_cart", mapOf("sku" to sku))
OneSignal.User.addTag("tier", "gold")
''')
        self.write("unity/Game.cs", '''
OpenPush.TrackEvent("stage_cleared");
OpenPush.InAppMessages.AddTrigger("shop_open", "yes");
''')
        result = scan_sdk_calls(self.root)
        self.assertEqual({item["name"] for item in result["events"]}, {"add_to_cart", "stage_cleared"})
        self.assertEqual(next(item for item in result["events"] if item["name"] == "add_to_cart")["property_keys"], ["sku"])
        self.assertEqual(result["tags"][0]["key"], "tier")
        self.assertEqual(result["triggers"][0]["key"], "shop_open")
        self.assertTrue(result["capabilities"]["onesignal_compat"])
        self.assertEqual(result["platforms"], ["android", "unity"])

    def test_cross_platform_merge_and_ignored_directories(self):
        self.write("ios/App.swift", 'OpenPush.trackEvent("level_complete")')
        self.write("android/App.kt", 'OpenPush.trackEvent("level_complete")')
        self.write("Pods/Noise.swift", 'OpenPush.trackEvent("ignored")')
        self.write("ignored/Nope.swift", 'OpenPush.trackEvent("also_ignored")')
        self.write(".openpush-scan-ignore", "ignored/**\n")
        result = scan_sdk_calls(self.root)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["call_count"], 2)
        self.assertEqual(result["events"][0]["platforms"], ["android", "ios"])

    def test_podfile_lock_alone_reports_ios_sdk_version(self):
        self.write("Podfile.lock", "  - OpenPush (1.7.3)\n")
        result = scan_sdk_calls(self.root)
        self.assertEqual(result["sdk"]["ios"]["version_hint"], "1.7.3")
        self.assertEqual(result["sdk"]["ios"]["modules"], [])
        self.assertEqual(result["platforms"], ["ios"])
        self.assertEqual(result["events"], [])

    def test_unity_manifest_normalizes_package_version_hints(self):
        cases = {
            "1.0.1": "1.0.1",
            "ssh://git@github.com/SuperTuned/openpush-unity.git#1.0.1": "1.0.1",
            "https://github.com/SuperTuned/openpush-unity.git#v1.2.3": "v1.2.3",
            "https://github.com/SuperTuned/openpush-unity.git": None,
            "https://github.com/SuperTuned/openpush-unity.git#": None,
            None: None,
        }
        for dependency, expected in cases.items():
            with self.subTest(dependency=dependency):
                self.write("Packages/manifest.json", json.dumps({
                    "dependencies": {"ai.openpush.unity": dependency},
                }))
                result = scan_sdk_calls(self.root)
                self.assertEqual(result["sdk"]["unity"]["version_hint"], expected)

                manifest = empty("0.1.0")
                manifest["platforms"] = result["platforms"]
                manifest["sdk"] = result["sdk"]
                self.assertEqual(validate(manifest), [])

    def test_analytics_events_are_discovered_but_distinguished_from_openpush(self):
        self.write("unity/EventNames.cs", '''
public static class EventName {
    public const string level_finished = "level_finished";
    public const string daily_reward_claimed = "daily_reward_claimed";
}
public static class FieldName {
    public const string reward_id = "reward_id";
}
''')
        self.write("unity/Game.cs", '''
Telemetry.TrackEvent(EventName.level_finished,
    new Dictionary<string, object> { ["level_id"] = levelId });
OpenPush.TrackEvent("level_finished");
FirebaseAnalytics.LogEvent("store_opened");
// GameAnalytics.NewDesignEvent("commented_event");

void ReportReward() {
    const string eventName = EventName.daily_reward_claimed;
    var properties = new Dictionary<string, object> {
        { FieldName.reward_id, rewardId },
        ["streak_day"] = streakDay,
    };
    TrackEvent(eventName, properties);
}
''')
        self.write("unity/Plugins/Vendor.cs",
                   'GameAnalytics.NewDesignEvent("vendor_internal_event");')

        result = scan_sdk_calls(self.root)
        events = {item["name"]: item for item in result["events"]}
        self.assertEqual(events["level_finished"]["providers"],
                         ["analytics", "openpush"])
        self.assertEqual(events["level_finished"]["property_keys"], ["level_id"])
        self.assertEqual(events["daily_reward_claimed"]["providers"], ["analytics"])
        self.assertEqual(events["daily_reward_claimed"]["property_keys"],
                         ["reward_id", "streak_day"])
        self.assertEqual(events["store_opened"]["providers"], ["firebase"])
        self.assertNotIn("commented_event", events)
        self.assertNotIn("vendor_internal_event", events)

        doc = empty("0.1.0")
        doc["platforms"] = result["platforms"]
        doc["sdk"] = result["sdk"]
        doc["events"] = result["events"]
        self.assertEqual(validate(doc), [])

    def test_analytics_allowlist_limits_manifest_to_used_and_enabled_events(self):
        self.write("unity/EventNames.cs", '''
public static class EventName {
    public const string allowed = "allowed_event";
    public const string removed = "removed_event";
    public const string unused = "unused_event";
}
''')
        self.write("unity/Analytics.cs", '''
Telemetry.TrackEvent(EventName.allowed);
Telemetry.TrackEvent(EventName.removed);
OpenPush.TrackEvent("direct_openpush_event");
FirebaseAnalytics.LogEvent("firebase_event");
''')
        self.write("unity/Managers/AnalyticsManager.cs", '''
public class AnalyticsManager {
    private static readonly HashSet<string> AllowedEventNames = new HashSet<string> {
        EventName.allowed,
        EventName.unused,
        // EventName.removed,
    };

    public void SendAnalyticsEvent(string eventName) {
        if (!AllowedEventNames.Contains(eventName)) return;
        _amplitude.logEvent(eventName);
    }
}
''')

        result = scan_sdk_calls(self.root)
        events = {item["name"]: item for item in result["events"]}

        self.assertEqual(set(events), {
            "allowed_event", "direct_openpush_event", "firebase_event",
        })
        self.assertEqual(events["allowed_event"]["providers"], ["analytics"])
        self.assertEqual(events["direct_openpush_event"]["providers"], ["openpush"])
        self.assertEqual(events["firebase_event"]["providers"], ["firebase"])
        self.assertNotIn("removed_event", events)
        self.assertNotIn("unused_event", events)
        self.assertEqual(result["warnings"], [
            "Analytics event allowlist applied: excluded 1 called event "
            "that is not currently enabled."
        ])

    def test_event_named_collection_without_transport_gate_does_not_filter(self):
        self.write("unity/Game.cs", '''
Telemetry.TrackEvent("first_event");
Telemetry.TrackEvent("second_event");
private static readonly HashSet<string> AllowedEventNames = new HashSet<string> {
    "first_event",
};
''')

        result = scan_sdk_calls(self.root)

        self.assertEqual(
            {item["name"] for item in result["events"]},
            {"first_event", "second_event"},
        )

    def test_local_wrapper_forwarding_to_analytics_is_followed(self):
        self.write("unity/EventNames.cs", '''
public static class EventName {
    public const string inbox_opened = "inbox_opened";
}
''')
        self.write("unity/InboxAnalytics.cs", '''
public static void InboxOpened() {
    Track(EventName.inbox_opened, new Dictionary<string, object> {
        { "entry_source", "push" },
    });
}

private static void Track(string eventName, Dictionary<string, object> props) {
    Telemetry.TrackEvent(eventName, props);
}
''')

        result = scan_sdk_calls(self.root)
        event = result["events"][0]

        self.assertEqual(event["name"], "inbox_opened")
        self.assertEqual(event["providers"], ["analytics"])
        self.assertEqual(event["property_keys"], ["entry_source"])

    def test_any_track_or_send_event_wrapper_is_detected(self):
        self.write("unity/EventNames.cs", '''
public static class EventName {
    public const string shop_opened = "shop_opened";
}
''')
        self.write("unity/Game.cs", '''
GameEvents.TrackGameEvent("level_up");
SendAnalyticsEvent(EventName.shop_opened);
Telemetry.TrackEvent("tutorial_complete", new Dictionary<string, object> { ["step"] = step });
''')
        self.write("ios/App.swift", '''
Analytics.shared.trackEvent("onboarding_done", properties: ["source": "push"])
sendAnalyticsEvent("profile_saved")
''')
        self.write("android/App.kt", '''
analytics.trackScreenEvent("settings_opened", mapOf("tab" to tab))
''')
        self.write("android/Share.java", '''
Tracker.sendCustomEvent("share_tapped");
''')

        result = scan_sdk_calls(self.root)
        events = {item["name"]: item for item in result["events"]}

        self.assertEqual(set(events), {
            "level_up", "shop_opened", "tutorial_complete", "onboarding_done",
            "profile_saved", "settings_opened", "share_tapped",
        })
        for item in events.values():
            self.assertEqual(item["providers"], ["analytics"])
            self.assertEqual(item["call_count"], 1)
        self.assertEqual(events["level_up"]["platforms"], ["unity"])
        self.assertEqual(events["onboarding_done"]["platforms"], ["ios"])
        self.assertEqual(events["settings_opened"]["platforms"], ["android"])
        self.assertEqual(events["share_tapped"]["platforms"], ["android"])
        self.assertEqual(events["tutorial_complete"]["property_keys"], ["step"])
        self.assertEqual(events["onboarding_done"]["property_keys"], ["source"])
        self.assertEqual(events["settings_opened"]["property_keys"], ["tab"])

    def test_near_miss_wrapper_names_and_dynamic_arguments_are_ignored(self):
        self.write("unity/Game.cs", '''
Player.TrackPosition("spawn");
gameObject.SendMessage("OnHit");
Tracker.TrackEventually("later");
TrackGameEvent(eventName);
TrackGameEvent(42);
''')
        self.write("ios/App.swift", '''
tracker.trackEventually("later_ios")
sendMessage("hello")
''')
        self.write("android/App.kt", '''
tracker.trackPosition("spawn_android")
''')

        result = scan_sdk_calls(self.root)

        self.assertEqual(result["events"], [])

    def test_wrapper_calls_are_not_double_counted_with_openpush_calls(self):
        self.write("unity/Game.cs", '''
public static void TrackGameEvent(string name) {
    OpenPush.TrackEvent(name);
}

TrackGameEvent("level_up");
OpenPush.TrackEvent("purchase");
''')
        self.write("ios/App.swift", 'OpenPush.trackEvent("purchase")')

        result = scan_sdk_calls(self.root)
        events = {item["name"]: item for item in result["events"]}

        self.assertEqual(set(events), {"level_up", "purchase"})
        self.assertEqual(events["level_up"]["call_count"], 1)
        self.assertEqual(events["level_up"]["providers"], ["analytics"])
        self.assertEqual(events["purchase"]["call_count"], 2)
        self.assertEqual(events["purchase"]["providers"], ["openpush"])
        self.assertEqual(events["purchase"]["platforms"], ["ios", "unity"])


if __name__ == "__main__":
    unittest.main()
