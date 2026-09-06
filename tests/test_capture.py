"""capture.py: the screenshot file, clipboard and notification; the
recording stream against the fake adb."""

import json
import os
import signal
import subprocess
import sys
import time
import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, HELPER, PNG_HEX, SERIAL, FakeAdbCase

from androiddev import capture
from androiddev.adb import Adb, AdbError
from androiddev.cli import Settings

WARNING = "[Warning] Multiple displays were found, but no display id was specified!\n"


class Screenshot(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.adb = Adb(FAKE_ADB, "override", None)

    def test_screenshot_writes_copies_and_notifies(self):
        self.add_rules({"match": "exec-out screencap -p", "stdout_hex": PNG_HEX})
        doc = capture.screenshot(self.adb, SERIAL, Settings())
        self.assertTrue(os.path.exists(doc["path"]))
        self.assertTrue(doc["path"].startswith(os.environ["OMARCHY_SCREENSHOT_DIR"]))
        self.assertTrue(os.path.basename(doc["path"]).startswith("android-"))
        with open(doc["path"], "rb") as f:
            self.assertEqual(f.read(), bytes.fromhex(PNG_HEX))
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "exec-out", "screencap", "-p"])
        rec = self.recorded()
        self.assertEqual(len(rec), 2)
        self.assertEqual(rec[0]["argv"], ["--type", "image/png"])
        self.assertTrue(rec[0]["stdin"].startswith("89504e47"))
        self.assertIn("--image", rec[1]["argv"])
        self.assertIn(doc["path"], rec[1]["argv"])
        self.assertTrue(doc["copied"] and doc["notified"])
        self.assertIsNone(doc["warning"])

    def test_a_display_warning_before_the_png_is_stripped(self):
        self.add_rules({"match": "exec-out screencap -p", "stdout_hex": WARNING.encode().hex() + PNG_HEX})
        doc = capture.screenshot(self.adb, SERIAL, Settings())
        with open(doc["path"], "rb") as f:
            self.assertEqual(f.read(), bytes.fromhex(PNG_HEX))
        self.assertIn("Multiple displays", doc["warning"])

    def test_not_a_png_publishes_nothing(self):
        self.add_rules({"match": "exec-out screencap -p", "stdout": "error: closed\n"})
        with self.assertRaises(AdbError):
            capture.screenshot(self.adb, SERIAL, Settings())
        self.assertFalse(os.path.exists(os.environ["OMARCHY_SCREENSHOT_DIR"]))
        self.assertEqual(self.recorded(), [])

    def test_notify_setting_off_skips_the_notification(self):
        self.add_rules({"match": "exec-out screencap -p", "stdout_hex": PNG_HEX})
        doc = capture.screenshot(self.adb, SERIAL, Settings({"notify": False}))
        self.assertFalse(doc["notified"])
        self.assertEqual(len(self.recorded()), 1)  # wl-copy only

    def test_directory_rule(self):
        self.assertEqual(capture.screenshot_dir(Settings({"screenshotDir": "~/Shots"})), os.path.expanduser("~/Shots"))
        self.assertEqual(capture.screenshot_dir(Settings()), os.environ["OMARCHY_SCREENSHOT_DIR"])
        os.environ.pop("OMARCHY_SCREENSHOT_DIR")
        os.environ["XDG_PICTURES_DIR"] = "/tmp/pics"
        self.assertEqual(capture.screenshot_dir(Settings()), "/tmp/pics")
        dirs = capture.parse_user_dirs('XDG_PICTURES_DIR="$HOME/Pictures"\n# c\nXDG_VIDEOS_DIR="$HOME/Videos"\n', home="/h")
        self.assertEqual(dirs["XDG_PICTURES_DIR"], "/h/Pictures")
        self.assertEqual(dirs["XDG_VIDEOS_DIR"], "/h/Videos")

    def test_recording_directory_rule(self):
        self.assertEqual(capture.recording_dir(Settings({"recordingDir": "~/Casts"})), os.path.expanduser("~/Casts"))
        self.assertEqual(capture.recording_dir(Settings()), os.environ["OMARCHY_SCREENRECORD_DIR"])
        os.environ.pop("OMARCHY_SCREENRECORD_DIR")
        os.environ["XDG_VIDEOS_DIR"] = "/tmp/vids"
        self.assertEqual(capture.recording_dir(Settings()), "/tmp/vids")


MP4_HEX = "0000001c667479706d703432" + "00" * 20  # an ftyp box and padding


class Recording(FakeAdbCase):
    """`record` as a subprocess: the stream, the stop, the pull."""

    def setUp(self):
        super().setUp()
        self.add_rules(
            {"match": "shell screenrecord", "stdout": "", "sleep_after": 30},
            {"match": "shell stat -c %s", "stdout": "4096\n"},
            {"match": "pull /sdcard/omarchy-android-dev-", "stdout": "1 file pulled\n", "file_arg": -1, "file_hex": MP4_HEX},
            {"match": "shell rm -f /sdcard/omarchy-android-dev-", "stdout": ""},
        )

    def start(self):
        proc = subprocess.Popen([sys.executable, HELPER, "record"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ))
        self.addCleanup(self.close, proc)
        return proc

    def close(self, proc):
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()

    def wait_for_no_fake_adb(self):
        for _ in range(30):
            # Anchored to the fake's own command line, so a shell whose argv mentions the word is not counted.
            left = subprocess.run(["pgrep", "-af", r"^/usr/bin/python3 .*fakeadb\.py -s .* shell screenrecord"], capture_output=True, text=True).stdout
            if "screenrecord" not in left:
                break
            time.sleep(0.1)
        return left

    def test_sigint_pulls_removes_and_notifies(self):
        proc = self.start()
        first = json.loads(proc.stdout.readline())
        self.assertEqual(first["event"], "recording")
        self.assertEqual(first["command"], "record")
        self.assertTrue(first["ok"])
        self.assertEqual(first["selected"], SERIAL)
        self.assertTrue(first["device_path"].startswith("/sdcard/omarchy-android-dev-"))
        self.assertEqual(first["directory"], os.environ["OMARCHY_SCREENRECORD_DIR"])
        proc.send_signal(signal.SIGINT)
        final = json.loads(proc.stdout.readline())
        proc.wait(timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(final["event"], "recorded")
        self.assertTrue(final["ok"], final)
        self.assertTrue(final["notice"].startswith("Recording saved: "))
        self.assertTrue(os.path.basename(final["path"]).startswith("android-"))
        self.assertTrue(final["path"].endswith(".mp4"))
        with open(final["path"], "rb") as f:
            self.assertEqual(f.read(), bytes.fromhex(MP4_HEX))
        self.assertEqual(final["size"], len(bytes.fromhex(MP4_HEX)))
        self.assertTrue(final["removed"])
        self.assertIsNone(final["warning"])
        calls = self.joined_calls()
        device_path = first["device_path"]
        self.assertIn(f"-s {SERIAL} shell screenrecord {device_path}", calls)
        self.assertIn(f"-s {SERIAL} pull {device_path} {final['path']}", calls)
        self.assertIn(f"-s {SERIAL} shell rm -f {device_path}", calls)
        self.assertLess(calls.index(f"-s {SERIAL} pull {device_path} {final['path']}"), calls.index(f"-s {SERIAL} shell rm -f {device_path}"))
        headlines = [r["argv"][-2] if len(r["argv"]) >= 2 else "" for r in self.recorded()]
        self.assertIn("Recording the Android screen", headlines)
        self.assertIn("Android screen recording saved", headlines)
        self.assertNotIn("screenrecord", self.wait_for_no_fake_adb())

    def test_sigterm_ends_it_the_same_way(self):
        proc = self.start()
        json.loads(proc.stdout.readline())
        proc.terminate()
        final = json.loads(proc.stdout.readline())
        proc.wait(timeout=10)
        self.assertEqual(final["event"], "recorded")
        self.assertTrue(os.path.exists(final["path"]))

    def test_a_stop_before_screenrecord_starts_is_not_lost(self):
        # The handlers go in before the device lookup (the helper starts with SIGINT ignored under
        # the shell), so a `record stop` while `devices -l` is still running ends the run: nothing
        # printed, no screenrecord started, exit 0.
        self.add_rules({"match": "devices -l", "stdout_file": "devices_l.txt", "sleep": 3})
        proc = self.start()
        for _ in range(50):
            running = subprocess.run(["pgrep", "-af", r"^/usr/bin/python3 .*fakeadb\.py devices -l"], capture_output=True, text=True).stdout
            if running.strip():
                break
            time.sleep(0.1)
        self.assertTrue(running.strip(), "the fake adb never started listing devices")
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(out, "")
        self.assertFalse(any("screenrecord" in c for c in self.joined_calls()))

    def test_helper_killed_outright_takes_screenrecord_with_it(self):
        # The shell ends a Process it no longer wants with SIGKILL; the adb
        # child still goes (PDEATHSIG). The device file is the documented leftover.
        proc = self.start()
        json.loads(proc.stdout.readline())
        proc.kill()
        proc.wait(timeout=5)
        self.assertNotIn("screenrecord", self.wait_for_no_fake_adb())

    def test_screenrecord_failing_at_once_is_one_error_document(self):
        self.add_rules({"match": "shell screenrecord", "stdout": "", "stderr": "Unable to get output buffers (err=-38)\n", "code": 1})
        proc = self.start()
        final = json.loads(proc.stdout.readline())
        proc.wait(timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(final["event"], "error")
        self.assertFalse(final["ok"])
        self.assertEqual(final["error"]["code"], "adb_failed")
        self.assertIn("output buffers", final["error"]["message"])
        self.assertFalse(any("pull" in c for c in self.joined_calls()))
        self.assertFalse(os.path.exists(os.environ["OMARCHY_SCREENRECORD_DIR"]) and os.listdir(os.environ["OMARCHY_SCREENRECORD_DIR"]))

    def test_no_file_on_the_device_is_an_error_and_nothing_is_written(self):
        self.add_rules({"match": "shell stat -c %s", "stdout": "", "stderr": "stat: '/sdcard/x': No such file or directory\n", "code": 1})
        proc = self.start()
        json.loads(proc.stdout.readline())
        proc.send_signal(signal.SIGINT)
        final = json.loads(proc.stdout.readline())
        proc.wait(timeout=15)
        self.assertEqual(final["event"], "error")
        self.assertIn("no file", final["error"]["message"])
        self.assertEqual(os.listdir(os.environ["OMARCHY_SCREENRECORD_DIR"]), [])

    def test_record_without_a_device_is_one_document(self):
        self.add_rules({"match": "devices -l", "stdout": "List of devices attached\n"})
        doc = self.run_cli("record")
        self.assertEqual(doc["event"], "error")
        self.assertEqual(doc["error"]["code"], "no_device")
        self.assertEqual(self.run_cli("record", "extra")["error"]["code"], "bad_args")


if __name__ == "__main__":
    unittest.main()
