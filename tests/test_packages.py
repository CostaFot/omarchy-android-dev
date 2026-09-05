"""packages.py: the parsers and the list against the fake adb."""

import os
import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, SERIAL, FakeAdbCase, fixture

from androiddev import fmt
from androiddev import packages as pkgmod
from androiddev.adb import Adb
from androiddev.cli import Settings
from androiddev.state import State

TEMPLATE = "com.costafotiadis.androidtemplate.compose.debug"

DEBUGGABLE_DUMP = (
    "Packages:\n"
    "  Package [com.example.debuggable] (1):\n"
    "    versionName=1.0\n"
    "    versionCode=1 minSdk=29\n"
    "    flags=[ HAS_CODE DEBUGGABLE ]\n"
    "    User 0: installed=true\n"
    "      runtime permissions:\n"
    "        android.permission.CAMERA: granted=true, flags=[ X]\n"
)


class Parsing(unittest.TestCase):
    def test_pm_list(self):
        self.assertEqual(pkgmod.parse_pm_list(fixture("pm_list_3.txt")), [TEMPLATE, "com.example.debuggable", "org.example.other"])

    def test_ps_running_counts_subprocesses_for_their_package(self):
        running = pkgmod.parse_ps(fixture("ps_A.txt"))
        self.assertIn(TEMPLATE, running)
        self.assertIn("com.google.android.googlequicksearchbox", running)  # only a :interactor row in the fixture
        self.assertNotIn("init", running)

    def test_foreground_from_dumpsys_window(self):
        self.assertEqual(pkgmod.parse_foreground(fixture("dumpsys_window.txt")), "com.android.chrome")
        self.assertIsNone(pkgmod.parse_foreground("mCurrentFocus=null\n"))

    def test_top_resumed_fallback(self):
        text = "    topResumedActivity=ActivityRecord{2d8 u0 com.foo.bar/.MainActivity t12}\n"
        self.assertEqual(pkgmod.parse_top_resumed(text), "com.foo.bar")

    def test_resolve_activity_takes_the_component_line(self):
        self.assertEqual(pkgmod.parse_resolve_activity(fixture("resolve_activity.txt"), "com.android.chrome"), "com.android.chrome/com.google.android.apps.chrome.Main")
        self.assertIsNone(pkgmod.parse_resolve_activity("No activity found\n", "com.android.chrome"))

    def test_package_dump(self):
        info = pkgmod.parse_package_dump(fixture("dumpsys_package_pkg.txt"), "com.android.chrome")
        self.assertTrue(info["found"])
        self.assertEqual(info["version_name"], "149.0.7827.5")
        self.assertEqual(info["version_code"], "782700538")
        self.assertFalse(info["debuggable"])
        perms = info["runtime_permissions"]
        self.assertEqual(len(perms), 13)  # one block; the hidden system copy is not read twice
        self.assertEqual(perms[0], {"name": "android.permission.POST_NOTIFICATIONS", "granted": False})
        self.assertEqual(sum(1 for p in perms if p["granted"]), 3)

    def test_package_dump_debuggable_and_missing(self):
        self.assertTrue(pkgmod.parse_package_dump(DEBUGGABLE_DUMP, "com.example.debuggable")["debuggable"])
        self.assertFalse(pkgmod.parse_package_dump("Unable to find package: com.y\n", "com.y")["found"])

    def test_sort_and_sections(self):
        packages = [
            {"name": "d.other", "running": False, "foreground": False, "debuggable": False},
            {"name": "c.debug", "running": False, "foreground": False, "debuggable": True},
            {"name": "b.running", "running": True, "foreground": False, "debuggable": None},
            {"name": "a.fg", "running": True, "foreground": True, "debuggable": None},
            {"name": "a.other", "running": False, "foreground": False, "debuggable": None},
        ]
        ordered = pkgmod.sort_packages(packages)
        self.assertEqual([p["name"] for p in ordered], ["a.fg", "b.running", "c.debug", "a.other", "d.other"])
        self.assertEqual([pkgmod.section_of(p) for p in ordered], ["Foreground", "Running", "Debuggable", "Other", "Other"])

    def test_package_tags(self):
        self.assertEqual(fmt.package_tags(True, True, True), "foreground · debuggable")
        self.assertEqual(fmt.package_tags(True, False, None), "running")
        self.assertEqual(fmt.package_tags(False, False, True), "debuggable")
        self.assertEqual(fmt.package_tags(False, False, None), "")

    def test_valid_package_names(self):
        self.assertTrue(pkgmod.valid_package("com.android.chrome"))
        self.assertTrue(pkgmod.valid_package("a_b.c1"))
        self.assertFalse(pkgmod.valid_package("com.foo; rm -rf"))
        self.assertFalse(pkgmod.valid_package(""))
        self.assertFalse(pkgmod.valid_package("-x"))


class Listing(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.add_rules(
            {"match": "shell pm list packages", "stdout_file": "pm_list_3.txt"},
            {"match": "shell ps -A", "stdout_file": "ps_A.txt"},
            {"match": "shell dumpsys window", "stdout_file": "dumpsys_window.txt"},
            {"match": "shell dumpsys package com.example.debuggable", "stdout": DEBUGGABLE_DUMP},
            {"match": "resolve-activity", "stdout_file": "resolve_activity.txt"},
        )

    def test_list_is_three_cheap_calls_with_serial_and_third_party_by_default(self):
        adb = Adb(FAKE_ADB, "override", None)
        doc = pkgmod.list_packages(adb, SERIAL, State(), Settings())
        self.assertEqual([p["name"] for p in doc["packages"]], [TEMPLATE, "com.example.debuggable", "org.example.other"])
        self.assertEqual(doc["packages"][0]["section"], "Running")
        self.assertEqual(doc["packages"][0]["detail"], "running")
        self.assertIsNone(doc["packages"][1]["debuggable"])  # unknown until the package is opened
        self.assertEqual(doc["packages"][1]["detail"], "")
        calls = self.joined_calls()
        self.assertIn(f"-s {SERIAL} shell pm list packages -3", calls)
        self.assertIn(f"-s {SERIAL} shell ps -A", calls)
        self.assertIn(f"-s {SERIAL} shell dumpsys window", calls)
        self.assertFalse(any("dumpsys package packages" in c for c in calls))
        self.assertTrue(os.path.exists(os.path.join(self.state_dir, "packages-emulator-5554.json")))

    def test_show_system_apps_drops_the_third_party_flag(self):
        pkgmod.list_packages(Adb(FAKE_ADB, "override", None), SERIAL, State(), Settings({"showSystemApps": True}))
        self.assertIn(f"-s {SERIAL} shell pm list packages", self.joined_calls())
        self.assertNotIn(f"-s {SERIAL} shell pm list packages -3", self.joined_calls())

    def test_package_info_fills_debuggable_into_the_next_list(self):
        adb = Adb(FAKE_ADB, "override", None)
        state = State()
        info = pkgmod.package_info(adb, SERIAL, state, "com.example.debuggable")
        self.assertTrue(info["debuggable"])
        self.assertEqual(info["version_name"], "1.0")
        self.assertEqual(info["runtime_permissions"], [{"name": "android.permission.CAMERA", "granted": True}])
        self.assertEqual(state.last_package(SERIAL), "com.example.debuggable")
        doc = pkgmod.list_packages(adb, SERIAL, State(), Settings())
        by_name = {p["name"]: p for p in doc["packages"]}
        self.assertTrue(by_name["com.example.debuggable"]["debuggable"])
        self.assertEqual(by_name["com.example.debuggable"]["section"], "Debuggable")
        self.assertEqual(by_name["com.example.debuggable"]["detail"], "debuggable")


if __name__ == "__main__":
    unittest.main()
