"""capture.py: the screenshot file, clipboard and notification."""

import os
import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, PNG_HEX, SERIAL, FakeAdbCase

from androiddev import capture
from androiddev.adb import Adb, AdbError
from androiddev.cli import Settings

WARNING = "[Warning] Multiple displays were found, but no display id was specified!\n"


class Screenshot(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.adb = Adb(FAKE_ADB, "override", None)

    def test_screenshot_writes_copies_and_notifies(self):
        self.add_rules({"match": "exec-out screencap -p", "stdout_hex": PNG_HEX})
        doc = capture.screenshot(self.adb, SERIAL, Settings())
        self.assertTrue(os.path.exists(doc["path"]))
        self.assertTrue(doc["path"].startswith(os.environ["OMARCHY_SCREENSHOT_DIR"]))
        self.assertTrue(os.path.basename(doc["path"]).startswith("android-"))
        with open(doc["path"], "rb") as f:
            self.assertEqual(f.read(), bytes.fromhex(PNG_HEX))
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "exec-out", "screencap", "-p"])
        rec = self.recorded()
        self.assertEqual(len(rec), 2)
        self.assertEqual(rec[0]["argv"], ["--type", "image/png"])
        self.assertTrue(rec[0]["stdin"].startswith("89504e47"))
        self.assertIn("--image", rec[1]["argv"])
        self.assertIn(doc["path"], rec[1]["argv"])
        self.assertTrue(doc["copied"] and doc["notified"])
        self.assertIsNone(doc["warning"])

    def test_a_display_warning_before_the_png_is_stripped(self):
        self.add_rules({"match": "exec-out screencap -p", "stdout_hex": WARNING.encode().hex() + PNG_HEX})
        doc = capture.screenshot(self.adb, SERIAL, Settings())
        with open(doc["path"], "rb") as f:
            self.assertEqual(f.read(), bytes.fromhex(PNG_HEX))
        self.assertIn("Multiple displays", doc["warning"])

    def test_not_a_png_publishes_nothing(self):
        self.add_rules({"match": "exec-out screencap -p", "stdout": "error: closed\n"})
        with self.assertRaises(AdbError):
            capture.screenshot(self.adb, SERIAL, Settings())
        self.assertFalse(os.path.exists(os.environ["OMARCHY_SCREENSHOT_DIR"]))
        self.assertEqual(self.recorded(), [])

    def test_notify_setting_off_skips_the_notification(self):
        self.add_rules({"match": "exec-out screencap -p", "stdout_hex": PNG_HEX})
        doc = capture.screenshot(self.adb, SERIAL, Settings({"notify": False}))
        self.assertFalse(doc["notified"])
        self.assertEqual(len(self.recorded()), 1)  # wl-copy only

    def test_directory_rule(self):
        self.assertEqual(capture.screenshot_dir(Settings({"screenshotDir": "~/Shots"})), os.path.expanduser("~/Shots"))
        self.assertEqual(capture.screenshot_dir(Settings()), os.environ["OMARCHY_SCREENSHOT_DIR"])
        os.environ.pop("OMARCHY_SCREENSHOT_DIR")
        os.environ["XDG_PICTURES_DIR"] = "/tmp/pics"
        self.assertEqual(capture.screenshot_dir(Settings()), "/tmp/pics")
        dirs = capture.parse_user_dirs('XDG_PICTURES_DIR="$HOME/Pictures"\n# c\nXDG_VIDEOS_DIR="$HOME/Videos"\n', home="/h")
        self.assertEqual(dirs["XDG_PICTURES_DIR"], "/h/Pictures")


if __name__ == "__main__":
    unittest.main()
