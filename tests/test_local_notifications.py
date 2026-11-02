from pathlib import Path
import tempfile
import unittest

from openpush_scan.extract.local_notifications import scan_local_notifications


class LocalNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_ios_copy_and_localized_body(self):
        self.write("App/en.lproj/Localizable.strings", '"streak_body" = "Keep it going";')
        self.write("App/Reminders.swift", '''
let content = UNMutableNotificationContent()
content.title = "Daily streak"
content.body = NSLocalizedString("streak_body", comment: "")
let trigger = UNCalendarNotificationTrigger(dateMatching: parts, repeats: true)
''')
        item = scan_local_notifications(self.root)[0]
        self.assertEqual((item["trigger"], item["title"], item["body"]), ("calendar", "Daily streak", "Keep it going"))
        self.assertEqual(item["body_key"], "streak_body")

    def test_android_and_unity_notifications(self):
        self.write("app/src/main/res/values/strings.xml", '<resources><string name="reminder_body">Come back</string></resources>')
        self.write("app/src/main/java/Reminders.kt", '''
NotificationCompat.Builder(context, "daily")
 .setContentTitle("Daily reward")
 .setContentText(context.getString(R.string.reminder_body))
AlarmManager.setExact(0, at, pending)
''')
        self.write("Assets/Scripts/Reminders.cs", '''
var n = new iOSNotification { Title = "Reward", Body = "Ready", FireTime = when };
''')
        items = scan_local_notifications(self.root)
        android = next(item for item in items if item["platforms"] == ["android"])
        unity = next(item for item in items if item["platforms"] == ["unity"])
        self.assertEqual((android["title"], android["body"]), ("Daily reward", "Come back"))
        self.assertEqual((unity["trigger"], unity["title"]), ("time_interval", "Reward"))


if __name__ == "__main__":
    unittest.main()
