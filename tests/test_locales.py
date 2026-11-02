from pathlib import Path
import tempfile
import unittest

from openpush_scan.extract.locales import scan_locales


class LocaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_locales_strings_release_notes_and_ios_version(self):
        self.write("App/en.lproj/Localizable.strings", '"zebra" = "Z";\n"welcome_title" = "Welcome";')
        self.write("App/de.lproj/Localizable.strings", '"welcome_title" = "Willkommen";')
        self.write("app/src/main/res/values/strings.xml", '<resources><string name="back">Back</string></resources>')
        self.write("app/src/main/res/values-fr/strings.xml", '<resources><string name="back">Retour</string></resources>')
        self.write("App.xcodeproj/project.pbxproj", "MARKETING_VERSION = 2.4.0;")
        self.write("fastlane/metadata/en-US/release_notes.txt", "New levels and bug fixes")
        result = scan_locales(self.root)
        self.assertEqual(result["locales"], ["de", "en", "fr"])
        self.assertEqual(result["strings"][0]["key"], "back")
        self.assertLess([item["key"] for item in result["strings"]].index("welcome_title"), [item["key"] for item in result["strings"]].index("zebra"))
        self.assertEqual(result["app_version"], "2.4.0")
        self.assertEqual(result["release_notes"]["version"], "2.4.0")

    def test_android_version_and_trimmed_changelog(self):
        self.write("app/build.gradle.kts", 'versionName = "3.1.0"')
        self.write("CHANGELOG.md", "# Changes\n\n## 3.2.0\n" + "x" * 1300 + "\n\n## 3.1.0\nOld")
        result = scan_locales(self.root)
        self.assertEqual(result["app_version"], "3.1.0")
        self.assertEqual(result["release_notes"]["version"], "3.2.0")
        self.assertEqual(len(result["release_notes"]["text"]), 1200)


if __name__ == "__main__":
    unittest.main()
