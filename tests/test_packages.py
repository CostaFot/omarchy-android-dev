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

    def test_activity_processes_fallback_takes_the_same_uid_range_as_ps(self):
        running = pkgmod.parse_activity_processes(fixture("dumpsys_activity_processes.txt"))
        self.assertIn(TEMPLATE, running)
        self.assertIn("com.google.android.googlequicksearchbox", running)  # only a :interactor row in the fixture
        self.assertIn("com.google.android.projection.gearhead", running)  # a :car sub-process
        self.assertIn("com.android.systemui", running)  # a system app with an app uid, as ps counts it
        self.assertNotIn("system", running)  # /1000
        self.assertNotIn("com.android.dynsystem", running)  # /1000 too
        self.assertNotIn("com.android.vending", running)  # a work-profile user, /u10a145
        self.assertNotIn("com.android.chrome", running)  # an isolated process, /u0i4
        self.assertFalse(any(n.startswith(".") for n in running))  # `.adservices` is no package name
        self.assertEqual(pkgmod.parse_activity_processes(""), set())

    def test_foreground_from_dumpsys_window(self):
        self.assertEqual(pkgmod.parse_foreground(fixture("dumpsys_window.txt")), "com.android.chrome")
        self.assertIsNone(pkgmod.parse_foreground("mCurrentFocus=null\n"))

    def test_top_resumed_fallback(self):
        text = "    topResumedActivity=ActivityRecord{2d8 u0 com.foo.bar/.MainActivity t12}\n"
        self.assertEqual(pkgmod.parse_top_resumed(text), "com.foo.bar")

    def test_resolve_activity_takes_the_component_line(self):
        self.assertEqual(pkgmod.parse_resolve_activity(fixture("resolve_activity.txt"), "com.android.chrome"), "com.android.chrome/com.google.android.apps.chrome.Main")
        self.assertIsNone(pkgmod.parse_resolve_activity("No activity found\n", "com.android.chrome"))

    def test_launcher_activities_are_every_component_of_the_package(self):
        text = fixture("query_activities.txt")
        self.assertEqual(pkgmod.parse_launcher_activities(text, TEMPLATE), [
            TEMPLATE + "/com.costafotiadis.androidtemplate.ui.activity.MainActivity",
            TEMPLATE + "/leakcanary.internal.activity.LeakLauncherActivity",
        ])
        self.assertEqual(pkgmod.parse_launcher_activities(text + text, TEMPLATE)[1:], [TEMPLATE + "/leakcanary.internal.activity.LeakLauncherActivity"])  # once each
        self.assertEqual(pkgmod.parse_launcher_activities(text, "com.android.chrome"), [])  # another package's lines are not ours
        self.assertEqual(pkgmod.parse_launcher_activities("No activities found\n", TEMPLATE), [])
        self.assertEqual(pkgmod.parse_launcher_activities("com.a.b/.Main\ncom.a.b/../x\ncom.a.b/.Main;rm\n", "com.a.b"), ["com.a.b/.Main"])
        self.assertTrue(pkgmod.valid_component("com.a.b/.Main", "com.a.b"))
        self.assertTrue(pkgmod.valid_component("com.a.b/com.a.b.ui.Main$Inner", "com.a.b"))
        self.assertFalse(pkgmod.valid_component("com.a.b/", "com.a.b"))
        self.assertFalse(pkgmod.valid_component("com.a.bc/.Main", "com.a.b"))
        self.assertFalse(pkgmod.valid_component("com.a.b/.Main x", "com.a.b"))
        self.assertEqual(fmt.activity_label(TEMPLATE + "/com.costafotiadis.androidtemplate.ui.activity.MainActivity", TEMPLATE), "com.costafotiadis.androidtemplate.ui.activity.MainActivity")
        self.assertEqual(fmt.activity_label("com.a.b/com.a.b.ui.Main", "com.a.b"), ".ui.Main")
        self.assertEqual(fmt.activity_label("com.a.b/.Main", "com.a.b"), ".Main")
        self.assertEqual(fmt.launcher_text(0), "No launcher activity")
        self.assertEqual(fmt.launcher_text(1), "1 launcher activity")
        self.assertEqual(fmt.launcher_text(2), "2 launcher activities")

    def test_launch_choice_is_the_pick_while_the_package_still_has_it(self):
        two = ["com.a.b/.Main", "com.a.b/.Leaks"]
        self.assertEqual(pkgmod.launch_choice(two, None), ("com.a.b/.Main", False))
        self.assertEqual(pkgmod.launch_choice(two, "com.a.b/.Leaks"), ("com.a.b/.Leaks", True))
        self.assertEqual(pkgmod.launch_choice(two, "com.a.b/.Gone"), ("com.a.b/.Main", False))
        self.assertEqual(pkgmod.launch_choice([], "com.a.b/.Gone"), (None, False))

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
        self.assertFalse(any("dumpsys activity processes" in c for c in calls))  # ps had the rows
        self.assertTrue(os.path.exists(os.path.join(self.state_dir, "packages-emulator-5554.json")))

    def test_ps_without_the_user_column_falls_back_to_dumpsys_activity_processes(self):
        self.add_rules(
            {"match": "shell ps -A", "stdout": "  PID  NAME\n 1117 com.android.systemui\n 4102 " + TEMPLATE + "\n"},
            {"match": "shell dumpsys activity processes", "stdout_file": "dumpsys_activity_processes.txt"},
        )
        doc = pkgmod.list_packages(Adb(FAKE_ADB, "override", None), SERIAL, State(), Settings())
        self.assertEqual(doc["packages"][0]["name"], TEMPLATE)
        self.assertEqual(doc["packages"][0]["section"], "Running")
        self.assertFalse(doc["packages"][1]["running"])
        self.assertIn(f"-s {SERIAL} shell dumpsys activity processes", self.joined_calls())

    def test_a_failing_ps_falls_back_the_same_way(self):
        self.add_rules(
            {"match": "shell ps -A", "stderr": "ps: bad -A\n", "code": 1},
            {"match": "shell dumpsys activity processes", "stdout_file": "dumpsys_activity_processes.txt"},
        )
        doc = pkgmod.list_packages(Adb(FAKE_ADB, "override", None), SERIAL, State(), Settings())
        self.assertEqual(doc["packages"][0]["detail"], "running")
        self.assertIn(f"-s {SERIAL} shell dumpsys activity processes", self.joined_calls())

    def test_both_reads_failing_lists_nothing_as_running(self):
        self.add_rules(
            {"match": "shell ps -A", "stdout": "  PID  NAME\n"},
            {"match": "shell dumpsys activity processes", "stderr": "error: closed\n", "code": 1},
        )
        doc = pkgmod.list_packages(Adb(FAKE_ADB, "override", None), SERIAL, State(), Settings())
        self.assertFalse(any(p["running"] for p in doc["packages"]))

    def test_show_system_apps_drops_the_third_party_flag(self):
        pkgmod.list_packages(Adb(FAKE_ADB, "override", None), SERIAL, State(), Settings({"showSystemApps": True}))
        self.assertIn(f"-s {SERIAL} shell pm list packages", self.joined_calls())
        self.assertNotIn(f"-s {SERIAL} shell pm list packages -3", self.joined_calls())

    def test_package_info_lists_the_launcher_activities_and_the_pick(self):
        """One query-activities call scoped to the package gives the list;
        `launcher_activity` is what Launch starts: the remembered pick when
        the package still declares it, else the first."""
        self.add_rules({"match": "query-activities", "stdout_file": "query_activities.txt"},
                       {"match": "shell dumpsys package " + TEMPLATE, "stdout": "Packages:\n  Package [" + TEMPLATE + "] (1):\n    versionName=0.0.1\n    flags=[ DEBUGGABLE HAS_CODE ]\n"})
        adb = Adb(FAKE_ADB, "override", None)
        state = State()
        main = TEMPLATE + "/com.costafotiadis.androidtemplate.ui.activity.MainActivity"
        leaks = TEMPLATE + "/leakcanary.internal.activity.LeakLauncherActivity"
        info = pkgmod.package_info(adb, SERIAL, state, TEMPLATE)
        self.assertEqual(info["launcher_activity"], main)
        self.assertFalse(info["launcher_picked"])
        self.assertEqual(info["launcher_text"], "2 launcher activities")
        self.assertEqual(info["launcher_detail"], main + " · 2 launcher activities")
        self.assertEqual(info["launcher_activities"], [
            {"component": main, "label": "com.costafotiadis.androidtemplate.ui.activity.MainActivity", "chosen": True},
            {"component": leaks, "label": "leakcanary.internal.activity.LeakLauncherActivity", "chosen": False},
        ])
        query = [c for c in self.calls() if "query-activities" in c]
        self.assertEqual(query, [["-s", SERIAL, "shell", "cmd", "package", "query-activities", "--brief", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-p", TEMPLATE]])
        self.assertFalse(any("resolve-activity" in c for c in self.joined_calls()))  # the query answered
        state.set_launch_activity(TEMPLATE, leaks)
        info = pkgmod.package_info(adb, SERIAL, state, TEMPLATE)
        self.assertEqual(info["launcher_activity"], leaks)
        self.assertTrue(info["launcher_picked"])
        self.assertEqual([a["chosen"] for a in info["launcher_activities"]], [False, True])
        state.set_launch_activity(TEMPLATE, TEMPLATE + "/.Gone")
        info = pkgmod.package_info(adb, SERIAL, state, TEMPLATE)
        self.assertEqual((info["launcher_activity"], info["launcher_picked"]), (main, False))

    def test_launcher_activities_fall_back_to_resolve_activity(self):
        """A shell whose query answers nothing gets the old resolve-activity
        read, in its two spellings; one activity at most, never picked."""
        self.add_rules({"match": "query-activities", "stdout": "No activities found\n"},
                       {"match": "shell dumpsys package com.android.chrome", "stdout_file": "dumpsys_package_pkg.txt"})
        adb = Adb(FAKE_ADB, "override", None)
        info = pkgmod.package_info(adb, SERIAL, State(), "com.android.chrome")
        self.assertEqual(info["launcher_activity"], "com.android.chrome/com.google.android.apps.chrome.Main")
        self.assertEqual(info["launcher_text"], "1 launcher activity")
        self.assertEqual(info["launcher_detail"], info["launcher_activity"])
        self.assertEqual(len(info["launcher_activities"]), 1)
        self.assertIn(f"-s {SERIAL} shell cmd package resolve-activity --brief -c android.intent.category.LAUNCHER com.android.chrome", self.joined_calls())
        self.add_rules({"match": "resolve-activity", "stdout": "No activity found\n"})
        info = pkgmod.package_info(adb, SERIAL, State(), "com.android.chrome")
        self.assertIsNone(info["launcher_activity"])
        self.assertEqual(info["launcher_text"], "No launcher activity")
        self.assertEqual(info["launcher_detail"], "No launcher activity")
        self.assertIn(f"-s {SERIAL} shell pm resolve-activity --brief -c android.intent.category.LAUNCHER com.android.chrome", self.joined_calls())

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
