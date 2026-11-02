from pathlib import Path
import plistlib
import tempfile
import unittest

from openpush_scan.extract.deep_links import scan_deep_links


ANDROID_MANIFEST = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android">
<application><activity><intent-filter android:autoVerify="true">
<action android:name="android.intent.action.VIEW" />
<data android:scheme="https" android:host="example.com" android:pathPrefix="/cart" />
</intent-filter><intent-filter><action android:name="android.intent.action.VIEW" />
<data android:scheme="myapp" /></intent-filter></activity></application></manifest>'''


class DeepLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, content, binary=False):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            with path.open("wb") as stream:
                plistlib.dump(content, stream)
        else:
            path.write_text(content, encoding="utf-8")

    def test_ios_android_and_code_literals(self):
        self.write("ios/App/Info.plist", {"CFBundleURLTypes": [{"CFBundleURLSchemes": ["myapp"]}]}, True)
        self.write("ios/App/App.entitlements", {"com.apple.developer.associated-domains": ["applinks:links.example.com?mode=developer"]}, True)
        self.write("android/app/src/main/AndroidManifest.xml", ANDROID_MANIFEST)
        self.write("ios/App/Cart.swift", 'let target = "myapp://cart/123"')
        result = scan_deep_links(self.root)
        custom = next(item for item in result if item["scheme"] == "myapp" and item["path"] is None)
        self.assertEqual(custom["platforms"], ["android", "ios"])
        literal = next(item for item in result if item["scheme"] == "myapp" and item["path"] == "/cart/123")
        self.assertEqual(literal["full_urls"], ["myapp://cart/123"])
        self.assertTrue(any(item["kind"] == "universal_link" and item["host"] == "links.example.com" for item in result))
        self.assertTrue(any(item["kind"] == "app_link" and item["host"] == "example.com" and item["path"] == "/cart" for item in result))

    def test_unity_scheme_and_malformed_plist_warning(self):
        self.write("ProjectSettings/ProjectSettings.asset", "iOSURLSchemes:\n  - unitygame\n")
        self.write("Bad/Info.plist", "not a plist")
        result = scan_deep_links(self.root)
        self.assertTrue(any(item["scheme"] == "unitygame" for item in result))
        self.assertTrue(any("could not parse plist" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
