"""apk.py: the folder listing and the sequential install, with the results
per file and the failure text out of adb's line."""

import json
import os
import subprocess
import sys
import time
import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, HELPER, SERIAL, FakeAdbCase

from androiddev import apk, fmt
from androiddev.adb import Adb, AdbError, PartialError
from androiddev.cli import Settings

SUCCESS = "Performing Streamed Install\nSuccess\n"
FAILURE = "adb: failed to install /x/b.apk: Failure [INSTALL_FAILED_INVALID_APK: Package couldn't be installed]\n"


class Listing(FakeAdbCase):
    def folder(self, *names):
        d = os.path.join(self.tmp.name, "apks")
        os.makedirs(d, exist_ok=True)
        for n in names:
            with open(os.path.join(d, n), "wb") as f:
                f.write(b"PK" * 600)
        return d

    def test_lists_top_level_apks_sorted_with_sizes(self):
        d = self.folder("b.apk", "A.APK", "notes.txt", "c.apk.bak")
        os.makedirs(os.path.join(d, "sub.apk"))  # a directory with the suffix is not a file
        doc = apk.list_apks(d)
        self.assertTrue(doc["exists"])
        self.assertEqual([a["name"] for a in doc["apks"]], ["A.APK", "b.apk"])
        self.assertEqual(doc["apks"][0]["size"], 1200)
        self.assertEqual(doc["apks"][0]["size_text"], "1.2 KB")
        self.assertEqual(doc["count"], 2)
        self.assertFalse(doc["truncated"])
        self.assertTrue(doc["dir_text"].endswith("apks"))

    def test_a_missing_folder_is_not_an_error(self):
        doc = apk.list_apks(os.path.join(self.tmp.name, "nope"))
        self.assertFalse(doc["exists"])
        self.assertEqual(doc["apks"], [])

    def test_the_default_folder_is_the_setting(self):
        self.assertEqual(apk.apk_dir(Settings()), os.path.expanduser("~/Downloads"))
        self.assertEqual(apk.apk_dir(Settings({"apkDir": "~/apks"})), os.path.expanduser("~/apks"))
        self.assertEqual(apk.apk_dir(Settings({"apkDir": "~/apks"}), "/tmp/x"), "/tmp/x")
        self.assertEqual(apk.apk_dir(Settings({"apkDir": ""})), os.path.expanduser("~/Downloads"))

    def test_cli_list_needs_no_device(self):
        d = self.folder("a.apk")
        self.add_rules({"match": "devices -l", "stdout": "List of devices attached\n"})
        doc = self.run_cli("apk", "list", d)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["count"], 1)
        self.assertEqual(self.run_cli("--settings", '{"apkDir": "%s"}' % d, "apk", "list")["count"], 1)
        self.assertEqual(self.run_cli("apk")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("apk", "dance")["error"]["code"], "bad_args")


class Install(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.adb = Adb(FAKE_ADB, "override", None)
        self.dir = os.path.join(self.tmp.name, "apks")
        os.makedirs(self.dir)
        self.a = self.write("a.apk")
        self.b = self.write("b.apk")

    def write(self, name):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(b"PK")
        return path

    def test_one_file_installs_with_r_and_t(self):
        self.add_rules({"match": "install -r -t", "stdout": SUCCESS})
        doc = apk.install(self.adb, SERIAL, [self.a])
        self.assertEqual(doc["notice"], "Installed: a.apk")
        self.assertEqual(doc["installed"], 1)
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "install", "-r", "-t", self.a])

    def test_one_failing_file_is_an_error_with_the_failure_text(self):
        self.add_rules({"match": "install -r -t", "stdout": "Performing Streamed Install\n", "stderr": FAILURE, "code": 1})
        with self.assertRaises(PartialError) as cm:
            apk.install(self.adb, SERIAL, [self.b])
        self.assertEqual(cm.exception.message, "Install failed: Failure [INSTALL_FAILED_INVALID_APK: Package couldn't be installed]")
        self.assertFalse(cm.exception.payload["results"][0]["ok"])

    def test_several_files_run_in_order_with_one_result_each(self):
        self.add_rules(
            {"match": "install -r -t " + self.a, "stdout": SUCCESS},
            {"match": "install -r -t " + self.b, "stdout": "", "stderr": FAILURE, "code": 1},
        )
        with self.assertRaises(PartialError) as cm:
            apk.install(self.adb, SERIAL, [self.a, self.b])
        payload = cm.exception.payload
        self.assertEqual(payload["notice"], "Installed 1/2 APKs")
        self.assertEqual([r["ok"] for r in payload["results"]], [True, False])
        self.assertEqual(payload["results"][1]["message"], "Failure [INSTALL_FAILED_INVALID_APK: Package couldn't be installed]")
        self.assertIn("b.apk: Failure", cm.exception.message)
        installs = [c for c in self.calls() if "install" in c]
        self.assertEqual([c[-1] for c in installs], [self.a, self.b])
        self.add_rules({"match": "install -r -t", "stdout": SUCCESS})
        self.assertEqual(apk.install(self.adb, SERIAL, [self.a, self.b])["notice"], "Installed 2/2 APKs")

    def test_paths_are_checked_before_adb_runs(self):
        with self.assertRaises(AdbError) as cm:
            apk.check_path(os.path.join(self.dir, "missing.apk"))
        self.assertEqual(cm.exception.code, "bad_args")
        with self.assertRaises(AdbError):
            apk.check_path(self.write("notes.txt"))
        self.assertEqual(apk.check_path(self.a), self.a)

    def test_cli_install_end_to_end(self):
        self.add_rules({"match": "install -r -t", "stdout": SUCCESS})
        doc = self.run_cli("apk", "install", self.a)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["notice"], "Installed: a.apk")
        self.assertEqual(doc["selected"], SERIAL)
        doc = self.run_cli("apk", "install", os.path.join(self.dir, "missing.apk"))
        self.assertEqual(doc["error"]["code"], "bad_args")
        self.assertFalse(any("install" in c for c in self.calls() if "missing" in " ".join(c)))
        self.add_rules({"match": "install -r -t", "stdout": "", "stderr": FAILURE, "code": 1})
        doc = self.run_cli("apk", "install", self.a, self.b)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["installed"], 0)
        self.assertEqual(len(doc["results"]), 2)
        self.assertEqual(doc["error"]["code"], "adb_failed")


class RecentFolders(FakeAdbCase):
    """The folders installed from, remembered like the recent deep links."""

    def setUp(self):
        super().setUp()
        self.dir = os.path.join(self.tmp.name, "apks")
        self.other = os.path.join(self.tmp.name, "nightly")
        for d in (self.dir, self.other):
            os.makedirs(d)
            with open(os.path.join(d, "a.apk"), "wb") as f:
                f.write(b"PK")

    def test_an_install_remembers_the_folder_and_a_listing_does_not(self):
        self.add_rules({"match": "install -r -t", "stdout": SUCCESS})
        self.assertEqual(self.run_cli("apk", "list", self.dir)["recent_apk_dirs"], [])
        doc = self.run_cli("apk", "install", os.path.join(self.dir, "a.apk"))
        self.assertTrue(doc["ok"])
        self.assertEqual([d["path"] for d in doc["recent_apk_dirs"]], [self.dir])
        # And it rides on every document the page and the hub read.
        self.assertEqual([d["path"] for d in self.run_cli("apk", "list", self.other)["recent_apk_dirs"]], [self.dir])
        self.assertEqual([d["path"] for d in self.run_cli("status")["recent_apk_dirs"]], [self.dir])
        self.assertIn("path_text", self.run_cli("status")["recent_apk_dirs"][0])

    def test_newest_first_without_repeats(self):
        self.add_rules({"match": "install -r -t", "stdout": SUCCESS})
        self.run_cli("apk", "install", os.path.join(self.dir, "a.apk"))
        self.run_cli("apk", "install", os.path.join(self.other, "a.apk"))
        doc = self.run_cli("apk", "install", os.path.join(self.dir, "a.apk"))
        self.assertEqual([d["path"] for d in doc["recent_apk_dirs"]], [self.dir, self.other])

    def test_a_failed_install_remembers_the_folder_too(self):
        self.add_rules({"match": "install -r -t", "stdout": "", "stderr": FAILURE, "code": 1})
        doc = self.run_cli("apk", "install", os.path.join(self.dir, "a.apk"))
        self.assertFalse(doc["ok"])
        self.assertEqual([d["path"] for d in doc["recent_apk_dirs"]], [self.dir])

    def test_nothing_is_remembered_when_the_path_is_refused(self):
        doc = self.run_cli("apk", "install", os.path.join(self.dir, "missing.apk"))
        self.assertEqual(doc["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("apk", "list", self.dir)["recent_apk_dirs"], [])

    def test_the_folder_is_absolute_whatever_was_typed(self):
        self.assertEqual(apk.dir_of("b.apk"), os.getcwd())
        self.assertEqual(apk.dir_of("~/apks/b.apk"), os.path.expanduser("~/apks"))
        self.assertEqual(apk.dir_of(os.path.join(self.dir, "a.apk")), self.dir)

    def test_the_listed_dir_is_the_string_the_remembered_folder_is_matched_on(self):
        # The page hides the folder on screen by comparing `dir` with a
        # remembered `path`; a trailing slash or a `..` must not split them.
        self.add_rules({"match": "install -r -t", "stdout": SUCCESS})
        self.run_cli("apk", "install", os.path.join(self.dir, "a.apk"))
        for typed in (self.dir + "/", self.dir + "//", os.path.join(self.dir, "..", "apks")):
            self.assertEqual(self.run_cli("apk", "list", typed)["dir"], self.dir)
        self.assertEqual(apk.apk_dir(Settings({"apkDir": self.dir + "/"})), self.dir)

    def test_the_folder_text_the_page_hands_back_lists_the_same_folder(self):
        # `path_text` goes into the folder box, so `apk list path_text` has
        # to reach the folder `path` names, home prefix or not.
        home = os.path.join(self.tmp.name, "home")
        sibling = os.path.join(self.tmp.name, "home-backup", "apks")
        for d in (os.path.join(home, "apks"), sibling):
            os.makedirs(d)
            with open(os.path.join(d, "a.apk"), "wb") as f:
                f.write(b"PK")
        self.add_rules({"match": "install -r -t", "stdout": SUCCESS})
        env = {"HOME": home}
        for folder in (os.path.join(home, "apks"), sibling):
            doc = self.run_cli("apk", "install", os.path.join(folder, "a.apk"), env=env)
            entry = doc["recent_apk_dirs"][0]
            self.assertEqual(entry["path"], folder)
            listed = self.run_cli("apk", "list", entry["path_text"], env=env)
            self.assertEqual(listed["dir"], folder)
            self.assertTrue(listed["exists"])
            self.assertEqual(listed["count"], 1)
        saved = os.environ["HOME"]
        os.environ["HOME"] = home
        try:
            self.assertEqual(fmt.display_path(os.path.join(home, "apks")), "~/apks")
            self.assertEqual(fmt.display_path(home), "~")
            self.assertEqual(fmt.display_path(sibling), sibling)  # a sibling of the home dir is not under it
        finally:
            os.environ["HOME"] = saved

    def test_nothing_is_remembered_without_a_device(self):
        self.add_rules({"match": "devices -l", "stdout": "List of devices attached\n"})
        doc = self.run_cli("apk", "install", os.path.join(self.dir, "a.apk"))
        self.assertEqual(doc["error"]["code"], "no_device")
        self.assertNotIn("recent_apk_dirs", doc)
        self.assertEqual(self.run_cli("apk", "list", self.dir)["recent_apk_dirs"], [])
        self.assertFalse(any("install" in c for c in self.joined_calls()))

    def test_several_folders_in_one_install_are_remembered_in_order(self):
        self.add_rules({"match": "install -r -t", "stdout": SUCCESS})
        doc = self.run_cli("apk", "install", os.path.join(self.dir, "a.apk"), os.path.join(self.other, "a.apk"))
        self.assertTrue(doc["ok"])
        self.assertEqual([d["path"] for d in doc["recent_apk_dirs"]], [self.other, self.dir])

    def test_what_another_run_wrote_during_the_install_survives(self):
        # The run holds its state snapshot from the start and an install is
        # long; the folders are added to a fresh read, never to that snapshot.
        self.add_rules({"match": "install -r -t", "stdout": SUCCESS, "sleep": 2})
        proc = subprocess.Popen([sys.executable, HELPER, "apk", "install", os.path.join(self.dir, "a.apk")],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ))
        try:
            time.sleep(0.8)
            self.assertEqual(self.run_cli("select", SERIAL)["selected"], SERIAL)
            out, err = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertEqual(proc.returncode, 0, err)
        self.assertTrue(json.loads(out.splitlines()[-1])["ok"])
        with open(os.path.join(self.state_dir, "state.json"), encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual(state["selected"], SERIAL)
        self.assertEqual(state["recent_apk_dirs"], [self.dir])


if __name__ == "__main__":
    unittest.main()
