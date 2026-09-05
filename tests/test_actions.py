"""actions.py: the argv each action sends and the Windows notices."""

import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, SERIAL, FakeAdbCase

from androiddev import actions
from androiddev.adb import Adb, AdbError

CHROME = "com.android.chrome"
ACTIVITY = "com.android.chrome/com.google.android.apps.chrome.Main"
NASTY_URL = "myapp://open?id=1&x='\"$(rm)"


class Actions(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.adb = Adb(FAKE_ADB, "override", None)
        self.add_rules(
            {"match": "resolve-activity", "stdout_file": "resolve_activity.txt"},
            {"match": "shell am ", "stdout": "Starting: Intent\n"},
            {"match": "shell pm clear", "stdout": "Success\n"},
            {"match": "shell pm grant", "stdout": ""},
            {"match": "shell pm revoke", "stdout": ""},
            {"match": "shell dumpsys package", "stdout_file": "dumpsys_package_pkg.txt"},
        )

    def test_launch_resolves_then_starts(self):
        doc = actions.launch(self.adb, SERIAL, CHROME)
        self.assertEqual(doc["notice"], "Launched com.android.chrome")
        calls = self.calls()
        self.assertEqual(calls[-2], ["-s", SERIAL, "shell", "cmd", "package", "resolve-activity", "--brief", "-c", "android.intent.category.LAUNCHER", CHROME])
        self.assertEqual(calls[-1], ["-s", SERIAL, "shell", "am", "start", "-n", ACTIVITY])

    def test_launch_without_a_launcher_activity(self):
        self.add_rules({"match": "resolve-activity", "stdout": "No activity found\n"})
        with self.assertRaises(AdbError) as cm:
            actions.launch(self.adb, SERIAL, "com.no.launcher")
        self.assertEqual(cm.exception.message, "Could not resolve launcher activity for com.no.launcher")

    def test_force_stop_kill_clear(self):
        self.assertEqual(actions.force_stop(self.adb, SERIAL, CHROME)["notice"], "Force stopped com.android.chrome")
        self.assertEqual(actions.kill(self.adb, SERIAL, CHROME)["notice"], "Killed process: com.android.chrome")
        self.assertEqual(actions.clear(self.adb, SERIAL, CHROME)["notice"], "Cleared data for com.android.chrome")
        joined = self.joined_calls()
        self.assertIn(f"-s {SERIAL} shell am force-stop {CHROME}", joined)
        self.assertIn(f"-s {SERIAL} shell am kill {CHROME}", joined)
        self.assertIn(f"-s {SERIAL} shell pm clear {CHROME}", joined)

    def test_restart_and_clear_restart_partial_failures_keep_the_windows_texts(self):
        self.assertEqual(actions.restart(self.adb, SERIAL, CHROME)["notice"], "Restarted com.android.chrome")
        self.assertEqual(actions.clear_restart(self.adb, SERIAL, CHROME)["notice"], "Cleared data and restarted com.android.chrome")
        self.add_rules({"match": "resolve-activity", "stdout": ""})
        with self.assertRaises(AdbError) as cm:
            actions.clear_restart(self.adb, SERIAL, CHROME)
        self.assertEqual(cm.exception.message, "Data cleared, but could not resolve launcher activity for com.android.chrome")
        with self.assertRaises(AdbError) as cm:
            actions.restart(self.adb, SERIAL, CHROME)
        self.assertEqual(cm.exception.message, "App stopped, but could not resolve launcher activity for com.android.chrome")

    def test_clear_failure_on_stdout_is_reported(self):
        self.add_rules({"match": "shell pm clear", "stdout": "Failed\n"})
        with self.assertRaises(AdbError) as cm:
            actions.clear(self.adb, SERIAL, "com.nope")
        self.assertEqual(cm.exception.message, "Failed to clear data: Failed")

    def test_uninstall_uses_the_host_verb_and_reads_the_failure_line(self):
        self.add_rules({"match": "uninstall", "stdout": "Success\n"})
        self.assertEqual(actions.uninstall(self.adb, SERIAL, CHROME)["notice"], "Uninstalled com.android.chrome")
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "uninstall", CHROME])
        self.add_rules({"match": "uninstall", "stdout": "Failure [DELETE_FAILED_INTERNAL_ERROR]\n", "code": 1})
        with self.assertRaises(AdbError) as cm:
            actions.uninstall(self.adb, SERIAL, CHROME)
        self.assertEqual(cm.exception.message, "Failed to uninstall: Failure [DELETE_FAILED_INTERNAL_ERROR]")

    def test_grant_and_revoke_all_count_every_runtime_permission(self):
        doc = actions.grant_all(self.adb, SERIAL, CHROME)
        self.assertEqual(doc["notice"], "Granted 13/13 permissions")
        self.assertEqual(sum(1 for c in self.joined_calls() if f"shell pm grant {CHROME} android.permission." in c), 13)
        doc = actions.revoke_all(self.adb, SERIAL, CHROME)
        self.assertEqual(doc["notice"], "Revoked 3/3 permissions")  # only the granted ones
        self.add_rules({"match": "shell pm grant", "stderr": "Error: Unknown permission", "code": 1})
        doc = actions.grant_all(self.adb, SERIAL, CHROME)
        self.assertEqual(doc["notice"], "Granted 0/13 permissions")
        self.assertEqual(len(doc["failed"]), 13)

    def test_no_runtime_permissions(self):
        self.add_rules({"match": "shell dumpsys package", "stdout": "Packages:\n  Package [com.x] (1):\n    flags=[ HAS_CODE ]\n"})
        self.assertEqual(actions.grant_all(self.adb, SERIAL, "com.x")["notice"], "No runtime permissions found")
        self.assertEqual(actions.revoke_all(self.adb, SERIAL, "com.x")["notice"], "No granted runtime permissions found")

    def test_deeplink_is_one_argv_entry_with_optional_package_scope(self):
        doc = actions.deeplink(self.adb, SERIAL, "https://example.com/a?x=1")
        self.assertEqual(doc["notice"], "Launched: https://example.com/a?x=1")
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", "https://example.com/a?x=1"])
        doc = actions.deeplink(self.adb, SERIAL, NASTY_URL, CHROME)
        self.assertEqual(doc["notice"], "Opened: " + NASTY_URL)
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "shell", "am", "start", "-p", CHROME, "-a", "android.intent.action.VIEW", "-d", NASTY_URL])

    def test_urls_are_validated_before_adb_runs(self):
        before = len(self.calls())
        for bad in ("https://example.com/a b", "example.com", "", "http://x\ny"):
            with self.assertRaises(AdbError) as cm:
                actions.deeplink(self.adb, SERIAL, bad)
            self.assertEqual(cm.exception.code, "bad_args")
        self.assertEqual(len(self.calls()), before)
        self.assertTrue(actions.valid_url("https://example.com"))
        self.assertTrue(actions.valid_url("myapp://open"))


if __name__ == "__main__":
    unittest.main()
