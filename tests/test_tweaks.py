"""tweaks.py: the batched read, the steps and the set commands."""

import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, SERIAL, FakeAdbCase, fixture

from androiddev import tweaks
from androiddev.adb import Adb, AdbError


class Parsing(unittest.TestCase):
    def test_fixture_states(self):
        raw = tweaks.parse_read(fixture("tweaks_read.txt"))
        self.assertEqual(tweaks.api_level(raw), 37)
        t = tweaks.states(raw)
        self.assertIs(t["dark"]["on"], False)
        self.assertEqual(t["dark"]["text"], "off")
        self.assertEqual(t["dark"]["label"], "Dark mode")
        self.assertEqual(t["font"]["value"], 1.0)
        self.assertEqual(t["font"]["text"], "1.0 · Default")
        self.assertEqual([s["text"] for s in t["font"]["steps"]], ["0.85", "1.0", "1.15", "1.3", "1.5", "1.8", "2.0"])
        self.assertEqual([s["text"] for s in t["font"]["steps"] if s["current"]], ["1.0"])
        self.assertEqual(t["font"]["steps"][2]["detail"], "Large · settings put system font_scale 1.15")
        self.assertEqual(t["font"]["steps"][5]["detail"], "settings put system font_scale 1.8")
        d = t["density"]
        self.assertEqual((d["physical"], d["override"], d["value"]), (420, None, 420))
        self.assertEqual(d["text"], "420 dpi")
        # The physical value scaled and made even, as Settings does; the 1.0 stop is the reset.
        self.assertEqual([(s["value"], s["word"], s["reset"]) for s in d["steps"]],
                         [(356, "Small", False), (420, "Default", True), (482, "Large", False), (546, "Larger", False), (608, "Largest", False)])
        self.assertEqual([s["text"] for s in d["steps"] if s["current"]], ["420 dpi"])
        self.assertEqual(d["steps"][1]["detail"], "Default · the physical density · wm density reset")
        self.assertEqual(d["steps"][2]["detail"], "Large · 115% of 420 · wm density 482")

    def test_override_and_dark_on(self):
        t = tweaks.states(tweaks.parse_read(fixture("tweaks_read_override.txt")))
        self.assertIs(t["dark"]["on"], True)
        self.assertEqual(t["font"]["text"], "1.15 · Large")
        d = t["density"]
        self.assertEqual((d["physical"], d["override"], d["value"]), (420, 482, 482))
        self.assertEqual(d["text"], "482 dpi · overridden (physical 420)")
        self.assertEqual([s["word"] for s in d["steps"] if s["current"]], ["Large"])

    def test_unknown_and_odd_values(self):
        t = tweaks.states({"night": "/system/bin/sh: cmd: not found", "font": "null"})
        self.assertIsNone(t["dark"]["on"])
        self.assertEqual(t["dark"]["text"], "unknown")
        self.assertEqual(t["font"]["value"], 1.0)  # null is never set
        self.assertIsNone(t["density"]["value"])
        self.assertEqual(t["density"]["text"], "unknown")
        self.assertEqual(t["density"]["steps"], [])
        t = tweaks.states({"night": "Night mode: auto", "font": "1.2", "physical": "420", "override": "420"})
        self.assertIsNone(t["dark"]["on"])
        self.assertEqual(t["dark"]["text"], "auto")
        self.assertEqual(t["font"]["text"], "1.2")  # not a step: no word
        self.assertEqual([s["current"] for s in t["font"]["steps"]], [False] * 7)
        # An override equal to the physical value is still an override: no stop is current.
        self.assertEqual([s["current"] for s in t["density"]["steps"]], [False] * 5)
        self.assertEqual(tweaks.states({"font": "abc"})["font"]["text"], "unknown")

    def test_scale_text(self):
        self.assertEqual([tweaks.scale_text(v) for v in (1, 1.0, 1.15, 0.85, 2, 1.3)], ["1.0", "1.0", "1.15", "0.85", "2.0", "1.3"])
        self.assertIsNone(tweaks.parse_scale("0.1"))
        self.assertIsNone(tweaks.parse_scale("x"))
        self.assertEqual(tweaks.parse_scale(" 1.15 "), 1.15)
        self.assertIsNone(tweaks.parse_density("71"))
        self.assertIsNone(tweaks.parse_density("1.5"))
        self.assertEqual(tweaks.parse_density("480"), 480)


class Setting(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.adb = Adb(FAKE_ADB, "override", None)
        self.add_rules(
            {"match": "echo api=", "stdout_file": "tweaks_read.txt"},
            {"match": "shell cmd uimode night", "stdout": ""},
            {"match": "shell settings put", "stdout": ""},
            {"match": "shell wm density", "stdout": ""},
        )

    def writes(self):
        markers = ("shell cmd uimode", "shell settings put", "shell wm density")
        return [c for c in self.joined_calls() if any(m in c for m in markers)]

    def test_dark_flips_off_to_on_and_takes_a_word(self):
        doc = tweaks.set_tweak(self.adb, SERIAL, "dark")
        self.assertEqual(doc["notice"], "Dark mode on")
        self.assertIs(doc["value"], True)
        tweaks.set_tweak(self.adb, SERIAL, "dark", "off")
        self.assertEqual(self.writes(), [f"-s {SERIAL} shell cmd uimode night yes", f"-s {SERIAL} shell cmd uimode night no"])
        with self.assertRaises(AdbError) as cm:
            tweaks.set_tweak(self.adb, SERIAL, "dark", "maybe")
        self.assertEqual(cm.exception.code, "bad_args")

    def test_dark_unknown_flips_to_on(self):
        self.add_rules({"match": "echo api=", "stdout": "api=28\nnight=/system/bin/sh: cmd: not found\nfont=null\nPhysical density: 320\n"})
        doc = tweaks.set_tweak(self.adb, SERIAL, "dark")
        self.assertEqual(doc["notice"], "Dark mode on")

    def test_font_steps_and_values(self):
        doc = tweaks.set_tweak(self.adb, SERIAL, "font")
        self.assertEqual(doc["notice"], "Font scale 1.15")
        self.assertEqual(doc["value"], 1.15)
        tweaks.set_tweak(self.adb, SERIAL, "font", "next")
        tweaks.set_tweak(self.adb, SERIAL, "font", "2")
        self.assertEqual(self.writes(), [
            f"-s {SERIAL} shell settings put system font_scale 1.15",
            f"-s {SERIAL} shell settings put system font_scale 1.15",  # the read still says 1.0
            f"-s {SERIAL} shell settings put system font_scale 2.0",
        ])
        # From the last step, next wraps to the first.
        self.add_rules({"match": "echo api=", "stdout": fixture("tweaks_read.txt").replace("font=1.0", "font=2.0")})
        self.assertEqual(tweaks.set_tweak(self.adb, SERIAL, "font")["notice"], "Font scale 0.85")
        for bad in ("0.1", "5", "big", "1.2.3"):
            with self.assertRaises(AdbError) as cm:
                tweaks.set_tweak(self.adb, SERIAL, "font", bad)
            self.assertEqual(cm.exception.code, "bad_args", bad)

    def test_density_steps_reset_and_values(self):
        doc = tweaks.set_tweak(self.adb, SERIAL, "density")
        self.assertEqual(doc["notice"], "Display scale 482 dpi")
        self.assertEqual(doc["value"], 482)
        tweaks.set_tweak(self.adb, SERIAL, "density", "560")
        doc = tweaks.set_tweak(self.adb, SERIAL, "density", "reset")
        self.assertEqual(doc["notice"], "Display scale reset to 420 dpi")
        self.assertIsNone(doc["value"])
        self.assertEqual(self.writes(), [
            f"-s {SERIAL} shell wm density 482",
            f"-s {SERIAL} shell wm density 560",
            f"-s {SERIAL} shell wm density reset",
        ])
        # From the Largest stop, next wraps to Small; from Small, next is the reset.
        self.add_rules({"match": "echo api=", "stdout_file": "tweaks_read_override.txt"})
        self.assertEqual(tweaks.set_tweak(self.adb, SERIAL, "density")["notice"], "Display scale 546 dpi")
        self.add_rules({"match": "echo api=", "stdout": fixture("tweaks_read_override.txt").replace("482", "608")})
        self.assertEqual(tweaks.set_tweak(self.adb, SERIAL, "density")["notice"], "Display scale 356 dpi")
        self.add_rules({"match": "echo api=", "stdout": fixture("tweaks_read_override.txt").replace("482", "356")})
        self.assertEqual(tweaks.set_tweak(self.adb, SERIAL, "density")["notice"], "Display scale reset to 420 dpi")
        for bad in ("10", "5000", "x", "1.5"):
            with self.assertRaises(AdbError) as cm:
                tweaks.set_tweak(self.adb, SERIAL, "density", bad)
            self.assertEqual(cm.exception.code, "bad_args", bad)

    def test_density_without_a_physical_value_cannot_step(self):
        self.add_rules({"match": "echo api=", "stdout": "api=37\nnight=Night mode: no\nfont=1.0\n"})
        with self.assertRaises(AdbError) as cm:
            tweaks.set_tweak(self.adb, SERIAL, "density")
        self.assertEqual(cm.exception.code, "adb_failed")
        # A value can still be set: wm answers for itself.
        self.assertEqual(tweaks.set_tweak(self.adb, SERIAL, "density", "480")["notice"], "Display scale 480 dpi")

    def test_unknown_tweak_and_failures(self):
        with self.assertRaises(AdbError) as cm:
            tweaks.set_tweak(self.adb, SERIAL, "coffee")
        self.assertEqual(cm.exception.code, "bad_args")
        self.add_rules({"match": "shell wm density", "stdout": "Error: density must be >= 72\n", "code": 255})
        with self.assertRaises(AdbError) as cm:
            tweaks.set_tweak(self.adb, SERIAL, "density", "100")
        self.assertTrue(cm.exception.message.startswith("Failed to set display scale: "), cm.exception.message)
        self.add_rules({"match": "shell cmd uimode night", "stderr": "error: x", "code": 1})
        with self.assertRaises(AdbError) as cm:
            tweaks.set_tweak(self.adb, SERIAL, "dark", "on")
        self.assertTrue(cm.exception.message.startswith("Failed to set dark mode: "))


if __name__ == "__main__":
    unittest.main()
