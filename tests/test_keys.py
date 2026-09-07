"""keys.py: the hardware keys as `input keyevent` by name."""

import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, SERIAL, FakeAdbCase

from androiddev import keys
from androiddev.adb import Adb, AdbError


class Keys(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.adb = Adb(FAKE_ADB, "override", None)
        self.add_rules({"match": "input keyevent", "stdout": ""})

    def test_the_table(self):
        self.assertEqual(keys.NAMES, ["back", "home", "recents", "power", "volup", "voldown", "wake", "sleep"])
        codes = [code for code, _ in keys.KEYS.values()]
        self.assertEqual(len(set(codes)), len(codes))
        self.assertTrue(all(isinstance(c, int) and c > 0 for c in codes))
        self.assertTrue(all(label for _, label in keys.KEYS.values()))
        self.assertEqual(keys.KEYS["back"], (4, "Back"))
        self.assertEqual(keys.KEYS["recents"], (187, "Recents"))

    def test_press_is_one_keyevent_on_the_device(self):
        doc = keys.press(self.adb, SERIAL, "back")
        self.assertEqual(doc, {"notice": "Back pressed", "key": "back", "keycode": 4, "label": "Back"})
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "shell", "input", "keyevent", "4"])
        keys.press(self.adb, SERIAL, "voldown")
        self.assertEqual(self.calls()[-1][-1], "25")

    def test_an_unknown_key_never_reaches_adb(self):
        with self.assertRaises(AdbError) as cm:
            keys.press(self.adb, SERIAL, "menu; reboot")
        self.assertEqual(cm.exception.code, "bad_args")
        self.assertEqual([c for c in self.calls() if "keyevent" in c], [])
        for args in (("key",), ("key", "bogus"), ("key", "back", "home")):
            doc = self.run_cli(*args)
            self.assertFalse(doc["ok"])
            self.assertEqual(doc["error"]["code"], "bad_args", args)
            self.assertIn("back", doc["error"]["message"])

    def test_the_command(self):
        doc = self.run_cli("key", "home")
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["command"], "key")
        self.assertEqual(doc["notice"], "Home pressed")
        self.assertEqual(doc["selected"], SERIAL)
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "shell", "input", "keyevent", "3"])

    def test_a_failing_keyevent_names_the_key(self):
        self.add_rules({"match": "input keyevent", "stdout": "", "stderr": "error: closed", "code": 1})
        doc = self.run_cli("key", "power")
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn("Could not press Power", doc["error"]["message"])

    def test_needs_a_ready_device(self):
        self.add_rules({"match": "devices -l", "stdout": "List of devices attached\n"})
        doc = self.run_cli("key", "back")
        self.assertEqual(doc["error"]["code"], "no_device")
        self.assertEqual([c for c in self.calls() if "keyevent" in c], [])


if __name__ == "__main__":
    unittest.main()
