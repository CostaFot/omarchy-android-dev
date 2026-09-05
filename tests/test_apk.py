"""apk.py: the folder listing and the sequential install, with the results
per file and the failure text out of adb's line."""

import os
import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, SERIAL, FakeAdbCase

from androiddev import apk
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


if __name__ == "__main__":
    unittest.main()
