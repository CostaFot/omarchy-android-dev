"""End-to-end: bin/omarchy-android-dev as a subprocess, exactly as QML runs it."""

import json
import os
import subprocess
import sys
import time
import unittest

import _paths  # noqa: F401
from _paths import HELPER, SERIAL, FakeAdbCase

TWO_DEVICES = (
    "List of devices attached\n"
    "emulator-5554\tdevice product:x model:sdk_gphone device:y transport_id:1\n"
    "ZY22\tdevice product:p model:Pixel_7 device:d transport_id:2\n"
)


class Cli(FakeAdbCase):
    def test_garbage_arguments_still_exit_zero_with_json(self):
        doc = self.run_cli("bogus", "--nope")
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "bad_args")
        self.assertEqual(doc["command"], "bogus")

    def test_no_arguments_prints_usage(self):
        doc = self.run_cli()
        self.assertEqual(doc["error"]["code"], "bad_args")
        self.assertIn("screenshot", doc["error"]["message"])

    def test_bad_settings_json_and_bad_serial_are_bad_args(self):
        self.assertEqual(self.run_cli("--settings", "{nope", "status")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("--serial", "bad serial", "devices")["error"]["code"], "bad_args")

    def test_no_adb_is_a_document_not_a_crash(self):
        doc = self.run_cli("devices", env={"OMARCHY_ANDROID_DEV_PATH": "/nonexistent"})
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "no_adb")
        self.assertEqual(doc["devices"], [])
        self.assertIsNone(doc["adb"]["path"])
        doc = self.run_cli("status", env={"OMARCHY_ANDROID_DEV_PATH": "/nonexistent"})
        self.assertEqual(doc["error"]["code"], "no_adb")
        self.assertIn("tools", doc)

    def test_status_shape(self):
        self.add_rules({"match": "version", "stdout": "Android Debug Bridge version 1.0.41\nVersion 37.0.1-15733141\n"})
        doc = self.run_cli("status")
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["adb"]["source"], "override")
        self.assertEqual(doc["adb_version"], "37.0.1")
        self.assertEqual(doc["selected"], SERIAL)
        self.assertEqual(set(doc["tools"]), {"scrcpy", "emulator", "terminal", "wl_copy"})
        self.assertEqual(doc["state_dir"], self.state_dir)
        self.assertRegex(doc["version"], r"^\d+\.\d+\.\d+$")

    def test_devices_marks_the_only_device_selected(self):
        doc = self.run_cli("devices")
        self.assertEqual(doc["devices"][0]["label"], "Pixel 10 Pro Fold (emulator-5554)")
        self.assertTrue(doc["devices"][0]["selected"])
        self.assertEqual(doc["selected"], SERIAL)

    def test_select_persists_and_an_unattached_serial_is_refused(self):
        doc = self.run_cli("select", SERIAL)
        self.assertEqual(doc["notice"], "Selected Pixel 10 Pro Fold (emulator-5554)")
        with open(os.path.join(self.state_dir, "state.json")) as f:
            self.assertEqual(json.load(f)["selected"], SERIAL)
        doc = self.run_cli("select", "ZY22")
        self.assertEqual(doc["error"]["code"], "no_device")

    def test_two_devices_need_a_pick(self):
        self.add_rules({"match": "devices -l", "stdout": TWO_DEVICES})
        doc = self.run_cli("toggles")
        self.assertEqual(doc["error"]["code"], "many_devices")
        self.add_rules({"match": "echo api=", "stdout_file": "toggles_read.txt"})
        doc = self.run_cli("--serial", "ZY22", "toggles")
        self.assertTrue(doc["ok"], doc)
        self.assertIn("-s ZY22 shell echo api=", " ".join(self.joined_calls()))
        self.run_cli("select", "ZY22")
        doc = self.run_cli("toggles")
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["selected"], "ZY22")

    def test_unauthorized_device_is_its_own_error(self):
        self.add_rules({"match": "devices -l", "stdout": "List of devices attached\nZY22\tunauthorized transport_id:2\n"})
        doc = self.run_cli("packages")
        self.assertEqual(doc["error"]["code"], "unauthorized")
        self.assertIn("accept", doc["error"]["message"])

    def test_toggle_and_toggles(self):
        self.add_rules(
            {"match": "echo api=", "stdout_file": "toggles_read.txt"},
            {"match": "shell settings put", "stdout": ""},
        )
        self.assertEqual(self.run_cli("toggle", "touches")["notice"], "Show touches on")
        self.assertEqual(self.run_cli("toggles")["toggles"]["bluetooth"]["text"], "on")
        self.assertEqual(self.run_cli("toggle", "coffee")["error"]["code"], "bad_args")

    def test_argument_validation_and_deeplink(self):
        self.assertEqual(self.run_cli("app", "launch", "com.foo;rm")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("app", "dance", "com.foo")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("deeplink", "no scheme")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("perms", "grant")["error"]["code"], "bad_args")
        self.add_rules({"match": "shell am start", "stdout": ""})
        doc = self.run_cli("deeplink", "https://example.com")
        self.assertEqual(doc["notice"], "Launched: https://example.com")
        self.assertEqual(doc["recent_deeplinks"], ["https://example.com"])

    def test_too_much_output_rides_in_the_envelope(self):
        self.add_rules({"match": "shell pm list packages", "bytes": 10 * 1024 * 1024, "sleep_after": 20})
        started = time.monotonic()
        doc = self.run_cli("packages")
        self.assertEqual(doc["error"]["code"], "too_much_output")
        self.assertLess(time.monotonic() - started, 10)

    def test_process_budget_answers_a_timeout_document(self):
        self.add_rules({"match": "shell pm list packages", "stdout": "", "sleep": 30})
        started = time.monotonic()
        doc = self.run_cli("packages", env={"OMARCHY_ANDROID_DEV_TOTAL_BUDGET": "1"})
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(doc["error"]["code"], "timeout")

    def test_state_corrupt_rides_with_the_answer(self):
        os.makedirs(self.state_dir, mode=0o700)
        with open(os.path.join(self.state_dir, "state.json"), "w") as f:
            f.write("nope")
        doc = self.run_cli("devices")
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["error"]["code"], "state_corrupt")
        self.assertEqual(len(doc["devices"]), 1)

    def test_help_lists_every_command(self):
        doc = self.run_cli("help")
        usages = [c["usage"].split()[0] for c in doc["commands"]]
        for name in ("status", "devices", "select", "track", "packages", "package", "app", "perms", "deeplink", "screenshot", "toggles", "toggle"):
            self.assertIn(name, usages)

    def test_debug_logs_argv_on_stderr_only(self):
        env = dict(os.environ, OMARCHY_ANDROID_DEV_DEBUG="1")
        proc = subprocess.run([sys.executable, HELPER, "devices"], capture_output=True, text=True, env=env)
        self.assertEqual(len(proc.stdout.splitlines()), 1)
        self.assertIn("devices -l", proc.stderr)


if __name__ == "__main__":
    unittest.main()
