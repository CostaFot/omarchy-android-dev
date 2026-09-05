"""tools.py: what is found, the AVDs with Running or Stopped, and the
detached launches (scrcpy, the emulator, logcat in a terminal)."""

import os
import time
import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, SERIAL, FakeAdbCase, fixture

from androiddev import tools
from androiddev.adb import Adb, AdbError
from androiddev.cli import Settings

TWO_EMULATORS = (
    "List of devices attached\n"
    "emulator-5554\tdevice product:sdk_gphone16k_x86_64 model:sdk_gphone16k_x86_64 device:emu64xa16k transport_id:1\n"
    "emulator-5556\tdevice product:sdk_gphone16k_x86_64 model:sdk_gphone16k_x86_64 device:emu64xa16k transport_id:2\n"
)


class Describe(FakeAdbCase):
    def test_nothing_installed(self):
        doc = self.run_cli("tools")
        self.assertTrue(doc["ok"])
        self.assertEqual({k: v["found"] for k, v in doc["tools"].items()},
                         {"scrcpy": False, "emulator": False, "terminal": False, "wl_copy": True, "wl_paste": False})  # wl-copy is the recorder
        self.assertEqual(doc["avds"], [])
        self.assertEqual(doc["selected"], SERIAL)

    def test_avds_are_matched_against_the_running_emulators(self):
        self.fake_tool("emulator", [("-list-avds", fixture("list_avds.txt"), 0, 0)], "OMARCHY_ANDROID_DEV_EMULATOR")
        doc = self.run_cli("--settings", '{"scrcpyArgs": "--keyboard=uhid"}', "tools")
        self.assertTrue(doc["tools"]["emulator"]["found"])
        self.assertEqual(doc["avds"], [
            {"name": "Medium_Phone", "running": False, "serial": None, "detail": "Stopped"},
            {"name": "Pixel_10_Pro_Fold", "running": True, "serial": SERIAL, "detail": "Running · emulator-5554"},
        ])
        self.assertEqual(doc["scrcpy_args"], "--keyboard=uhid")
        self.assertEqual(self.tool_calls("emulator"), [["-list-avds"]])

    def test_parse_avd_list_drops_chatter(self):
        self.assertEqual(tools.parse_avd_list("INFO    | Storing crashdata in: /tmp/x\nMedium_Phone\nbad name\nMedium_Phone\n"), ["Medium_Phone"])

    def test_tools_without_adb_still_lists_the_avds(self):
        self.fake_tool("emulator", [("-list-avds", fixture("list_avds.txt"), 0, 0)], "OMARCHY_ANDROID_DEV_EMULATOR")
        doc = self.run_cli("tools", env={"OMARCHY_ANDROID_DEV_PATH": "/nonexistent"})
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "no_adb")
        self.assertEqual([a["running"] for a in doc["avds"]], [False, False])


class Launches(FakeAdbCase):
    def test_scrcpy_is_launched_detached_with_the_title_and_the_extra_args(self):
        self.fake_tool("scrcpy", [(None, "", 0, 3)], "OMARCHY_ANDROID_DEV_SCRCPY")
        started = time.monotonic()
        doc = self.run_cli("--settings", '{"scrcpyArgs": "--keyboard=uhid --mouse=uhid"}', "tool", "scrcpy")
        self.assertLess(time.monotonic() - started, 2.5)  # the fake sleeps 3 s; the helper did not wait for it
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["notice"], "scrcpy started: Pixel 10 Pro Fold (emulator-5554)")
        self.assertEqual(self.tool_calls("scrcpy", wait=2), [["-s", SERIAL, "--window-title", "Android Dev", "--keyboard=uhid", "--mouse=uhid"]])

    def test_scrcpy_missing_or_failing_at_once(self):
        self.assertEqual(self.run_cli("tool", "scrcpy")["error"]["code"], "no_tool")
        self.fake_tool("scrcpy", [(None, "", 2, 0)], "OMARCHY_ANDROID_DEV_SCRCPY")
        doc = self.run_cli("tool", "scrcpy")
        self.assertEqual(doc["error"]["code"], "no_tool")
        self.assertIn("exited at once (code 2)", doc["error"]["message"])

    def test_avd_start_and_its_refusals(self):
        self.fake_tool("emulator", [("-list-avds", fixture("list_avds.txt"), 0, 0), ("-avd", "", 0, 3)], "OMARCHY_ANDROID_DEV_EMULATOR")
        doc = self.run_cli("tool", "avd", "Pixel_10_Pro_Fold")
        self.assertEqual(doc["error"]["code"], "bad_args")
        self.assertEqual(doc["error"]["message"], "Pixel_10_Pro_Fold is already running (emulator-5554)")
        self.assertEqual(self.run_cli("tool", "avd", "Nope")["error"]["message"], "No AVD named Nope")
        self.assertEqual(self.run_cli("tool", "avd", "bad name")["error"]["code"], "bad_args")
        started = time.monotonic()
        doc = self.run_cli("tool", "avd", "Medium_Phone")
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual(doc["notice"], "Starting Medium_Phone")
        self.assertIn(["-avd", "Medium_Phone"], self.tool_calls("emulator", wait=2))

    def test_avd_start_works_without_adb(self):
        self.fake_tool("emulator", [("-list-avds", fixture("list_avds.txt"), 0, 0)], "OMARCHY_ANDROID_DEV_EMULATOR")
        doc = self.run_cli("tool", "avd", "Medium_Phone", env={"OMARCHY_ANDROID_DEV_PATH": "/nonexistent"})
        self.assertTrue(doc["ok"], doc)

    def test_avd_stop_is_emu_kill_on_that_serial(self):
        self.add_rules({"match": "emu kill", "stdout": "OK: killing emulator, bye bye\n"})
        doc = self.run_cli("tool", "avd-stop", SERIAL)
        self.assertEqual(doc["notice"], "Stopping Pixel 10 Pro Fold (emulator-5554)")
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "emu", "kill"])
        self.assertEqual(self.run_cli("tool", "avd-stop", "ZY22")["error"]["code"], "no_device")
        self.add_rules({"match": "devices -l", "stdout": "List of devices attached\nZY22\tdevice model:Pixel_7 transport_id:2\n"})
        self.assertEqual(self.run_cli("tool", "avd-stop", "ZY22")["error"]["message"], "ZY22 is not an emulator")

    def test_logcat_opens_a_terminal_following_the_pid(self):
        self.fake_tool("xdg-terminal-exec", [(None, "", 0, 3)], "OMARCHY_ANDROID_DEV_TERMINAL")
        self.add_rules({"match": "shell pidof com.android.chrome", "stdout": "4242\n"})
        doc = self.run_cli("tool", "logcat", "com.android.chrome")
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["notice"], "Logcat for com.android.chrome in a terminal")
        calls = self.tool_calls("xdg-terminal-exec", wait=2)
        self.assertEqual(calls, [["--title=Android Dev · logcat · com.android.chrome", FAKE_ADB, "-s", SERIAL, "logcat", "--pid=4242"]])
        self.assertEqual(self.run_cli("status")["last_package"], "com.android.chrome")

    def test_logcat_without_a_package_and_with_a_stopped_one(self):
        self.fake_tool("xdg-terminal-exec", [(None, "", 0, 3)], "OMARCHY_ANDROID_DEV_TERMINAL")
        doc = self.run_cli("tool", "logcat")
        self.assertEqual(doc["notice"], "Logcat for Pixel 10 Pro Fold (emulator-5554) in a terminal")
        self.assertEqual(self.tool_calls("xdg-terminal-exec", wait=2)[0][-1], "logcat")
        self.add_rules({"match": "shell pidof", "stdout": "", "code": 1})
        doc = self.run_cli("tool", "logcat", "com.stopped")
        self.assertFalse(doc["ok"])
        self.assertIn("not running", doc["error"]["message"])
        self.assertEqual(len(self.tool_calls("xdg-terminal-exec")), 1)

    def test_logcat_without_a_terminal_and_bad_arguments(self):
        self.assertEqual(self.run_cli("tool", "logcat")["error"]["code"], "no_tool")
        self.assertEqual(self.run_cli("tool", "logcat", "bad;pkg")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("tool")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("tool", "dance")["error"]["code"], "bad_args")

    def test_launched_tools_get_no_pipes_from_the_helper(self):
        """A detached child must not hold the helper's stdout: the store's
        collector waits for EOF on it."""
        script = self.fake_tool("scrcpy", [(None, "", 0, 0)], "OMARCHY_ANDROID_DEV_SCRCPY")
        with open(script, "a", encoding="utf-8") as f:
            pass
        # Replace the fake with one that reports where its stdout points.
        with open(script, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/python3\nimport json, os, sys\n"
                    f"open({self.recorder_log!r}, 'a').write(json.dumps({{'tool': 'scrcpy', 'argv': [os.readlink('/proc/self/fd/1'), os.readlink('/proc/self/fd/0')]}}) + '\\n')\n")
        self.run_cli("tool", "scrcpy")
        calls = self.tool_calls("scrcpy", wait=2)
        self.assertEqual(calls, [["/dev/null", "/dev/null"]])


if __name__ == "__main__":
    unittest.main()
