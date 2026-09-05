"""toggles.py: the batched read and the flip commands."""

import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, SERIAL, FakeAdbCase, fixture

from androiddev import toggles
from androiddev.adb import Adb, AdbError


class Parsing(unittest.TestCase):
    def test_fixture_states(self):
        raw = toggles.parse_read(fixture("toggles_read.txt"))
        self.assertEqual(toggles.api_level(raw), 37)
        t = toggles.states(raw)
        self.assertEqual({k: v["text"] for k, v in t.items()},
                         {"animations": "on", "touches": "off", "pointer": "off", "layout": "off",
                          "airplane": "off", "wifi": "on", "data": "on", "bluetooth": "on", "demo": "off"})
        self.assertEqual(t["bluetooth"]["label"], "Bluetooth")
        self.assertEqual(t["demo"]["label"], "Demo mode")
        self.assertIs(t["touches"]["on"], False)

    def test_unknown_values_are_null_not_off(self):
        t = toggles.states({"global:wifi_on": "", "global:window_animation_scale": "0"})
        self.assertIsNone(t["wifi"]["on"])
        self.assertEqual(t["wifi"]["text"], "unknown")
        self.assertIs(t["animations"]["on"], False)

    def test_demo_is_on_from_either_key_and_never_unknown(self):
        # AOSP mirrors the shown state into sysui_tuner_demo_on; a vendor
        # SystemUI may leave it at 0, so the gate the plugin sets counts too.
        self.assertIs(toggles.states({"global:sysui_tuner_demo_on": "1"})["demo"]["on"], True)
        self.assertIs(toggles.states({"global:sysui_demo_allowed": "1", "global:sysui_tuner_demo_on": "0"})["demo"]["on"], True)
        self.assertIs(toggles.states({"global:sysui_demo_allowed": "0", "global:sysui_tuner_demo_on": "0"})["demo"]["on"], False)
        self.assertIs(toggles.states({})["demo"]["on"], False)


class Flipping(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.adb = Adb(FAKE_ADB, "override", None)
        self.add_rules(
            {"match": "echo api=", "stdout_file": "toggles_read.txt"},
            {"match": "shell settings put", "stdout": ""},
            {"match": "shell setprop", "stdout": ""},
            {"match": "shell service call", "stdout": "Result: Parcel(00000000)\n"},
            {"match": "shell cmd connectivity", "stdout": ""},
            {"match": "shell svc", "stdout": ""},
            {"match": "shell am broadcast", "stdout": "Broadcast completed: result=0\n"},
        )

    def writes(self):
        markers = ("shell settings put", "shell setprop", "shell svc", "shell cmd", "shell service", "shell am")
        return [c for c in self.joined_calls() if any(m in c for m in markers)]

    def test_touches_flips_off_to_on(self):
        doc = toggles.flip(self.adb, SERIAL, "touches")
        self.assertEqual(doc["notice"], "Show touches on")
        self.assertEqual(self.writes(), [f"-s {SERIAL} shell settings put system show_touches 1"])

    def test_animations_off_is_three_puts(self):
        doc = toggles.flip(self.adb, SERIAL, "animations")
        self.assertEqual(doc["notice"], "Animations off")
        self.assertEqual(self.writes(), [
            f"-s {SERIAL} shell settings put global window_animation_scale 0",
            f"-s {SERIAL} shell settings put global transition_animation_scale 0",
            f"-s {SERIAL} shell settings put global animator_duration_scale 0",
        ])

    def test_layout_bounds_sets_the_prop_and_pokes_the_activity_service(self):
        toggles.flip(self.adb, SERIAL, "layout", True)
        self.assertEqual(self.writes(), [f"-s {SERIAL} shell setprop debug.layout true", f"-s {SERIAL} shell service call activity 1599295570"])

    def test_airplane_uses_cmd_connectivity_on_api_30_and_up(self):
        toggles.flip(self.adb, SERIAL, "airplane", True)
        self.assertEqual(self.writes(), [f"-s {SERIAL} shell cmd connectivity airplane-mode enable"])

    def test_airplane_falls_back_to_settings_and_broadcast_before_api_30(self):
        old = fixture("toggles_read.txt").replace("api=37", "api=29")
        self.add_rules({"match": "echo api=", "stdout": old})
        toggles.flip(self.adb, SERIAL, "airplane", True)
        self.assertEqual(self.writes(), [
            f"-s {SERIAL} shell settings put global airplane_mode_on 1",
            f"-s {SERIAL} shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true",
        ])

    def test_wifi_data_bluetooth_use_svc(self):
        toggles.flip(self.adb, SERIAL, "wifi")
        toggles.flip(self.adb, SERIAL, "data", True)
        toggles.flip(self.adb, SERIAL, "bluetooth", False)
        self.assertEqual(self.writes(), [f"-s {SERIAL} shell svc wifi disable", f"-s {SERIAL} shell svc data enable", f"-s {SERIAL} shell svc bluetooth disable"])

    def test_demo_on_opens_the_gate_and_sends_the_broadcasts(self):
        doc = toggles.flip(self.adb, SERIAL, "demo")
        self.assertEqual(doc["notice"], "Demo mode on")
        b = f"-s {SERIAL} shell am broadcast -a com.android.systemui.demo -e command "
        self.assertEqual(self.writes(), [
            f"-s {SERIAL} shell settings put global sysui_demo_allowed 1",
            b + "enter",
            b + "clock -e hhmm 1200",
            b + "notifications -e visible false",
            b + "battery -e level 100 -e plugged false",
            b + "network -e wifi show -e level 4",
            b + "network -e mobile show -e datatype none -e level 4",
            b + "status -e bluetooth hide -e mute hide",
        ])

    def test_demo_off_is_exit_then_the_gate_closed(self):
        on = fixture("toggles_read.txt").replace("sysui_demo_allowed=null", "sysui_demo_allowed=1")
        self.add_rules({"match": "echo api=", "stdout": on})
        doc = toggles.flip(self.adb, SERIAL, "demo")
        self.assertEqual(doc["notice"], "Demo mode off")
        self.assertEqual(self.writes(), [
            f"-s {SERIAL} shell am broadcast -a com.android.systemui.demo -e command exit",
            f"-s {SERIAL} shell settings put global sysui_demo_allowed 0",
        ])

    def test_unknown_toggle_and_failures(self):
        with self.assertRaises(AdbError) as cm:
            toggles.flip(self.adb, SERIAL, "coffee")
        self.assertEqual(cm.exception.code, "bad_args")
        self.add_rules({"match": "shell svc", "stderr": "error: x", "code": 1})
        with self.assertRaises(AdbError) as cm:
            toggles.flip(self.adb, SERIAL, "wifi")
        self.assertTrue(cm.exception.message.startswith("Failed to set wi-fi: "))


if __name__ == "__main__":
    unittest.main()
