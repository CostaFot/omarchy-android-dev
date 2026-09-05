"""adb.py: resolution, the bounded reader, deadlines, error classification, the server lock."""

import os
import socket
import threading
import time
import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, SERIAL, FakeAdbCase

from androiddev import adb as adbmod
from androiddev import fmt
from androiddev.adb import Adb, AdbError
from androiddev.cli import Settings


class Resolution(FakeAdbCase):
    def test_override_env_wins_and_a_bad_override_means_no_adb(self):
        self.assertEqual(adbmod.resolve(Settings()), (FAKE_ADB, "override"))
        os.environ["OMARCHY_ANDROID_DEV_PATH"] = "/nonexistent/adb"
        self.assertEqual(adbmod.resolve(Settings()), (None, None))

    def test_setting_then_env_then_home_then_path(self):
        os.environ.pop("OMARCHY_ANDROID_DEV_PATH")
        sdk = os.path.join(self.tmp.name, "sdk", "platform-tools")
        os.makedirs(sdk)
        fake = os.path.join(sdk, "adb")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(fake, 0o700)
        self.assertEqual(adbmod.resolve(Settings({"adbPath": fake})), (fake, "setting"))
        self.assertEqual(adbmod.resolve(Settings({"adbPath": sdk})), (fake, "setting"))  # a directory works too
        os.environ["ANDROID_HOME"] = os.path.join(self.tmp.name, "sdk")
        self.assertEqual(adbmod.resolve(Settings({"adbPath": "/nonexistent"})), (fake, "env"))
        os.environ.pop("ANDROID_HOME")
        saved_path = os.environ.get("PATH", "")
        os.environ["PATH"] = sdk + os.pathsep + saved_path
        try:
            path, source = adbmod.resolve(Settings())
        finally:
            os.environ["PATH"] = saved_path
        self.assertIn(source, ("home", "path"))  # "home" on a machine with ~/Android/Sdk
        self.assertEqual(adbmod.sdk_root(fake), os.path.join(self.tmp.name, "sdk"))


class Runner(FakeAdbCase):
    def adb(self):
        return Adb(FAKE_ADB, "override", None)

    def test_serial_is_argv_on_every_device_call(self):
        self.add_rules({"match": "shell echo", "stdout": "hi\n"})
        r = self.adb().shell(SERIAL, "echo", "hi")
        self.assertEqual(r.text, "hi\n")
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "shell", "echo", "hi"])

    def test_too_much_output_kills_the_child_and_is_an_error(self):
        self.add_rules({"match": "shell big", "bytes": 10 * 1024 * 1024, "sleep_after": 20})
        started = time.monotonic()
        with self.assertRaises(AdbError) as cm:
            self.adb().shell(SERIAL, "big", cap=256 * 1024)
        self.assertEqual(cm.exception.code, "too_much_output")
        self.assertLess(time.monotonic() - started, 10)  # killed, not waited for

    def test_timeout_terminates_the_child(self):
        self.add_rules({"match": "shell slow", "stdout": "", "sleep": 30})
        started = time.monotonic()
        with self.assertRaises(AdbError) as cm:
            self.adb().shell(SERIAL, "slow", timeout=1)
        self.assertEqual(cm.exception.code, "timeout")
        self.assertLess(time.monotonic() - started, 5)

    def test_failure_lines_on_stdout_fail_the_call(self):
        self.add_rules({"match": "uninstall com.foo", "stdout": "Failure [DELETE_FAILED_INTERNAL_ERROR]\n", "code": 0})
        with self.assertRaises(AdbError) as cm:
            self.adb().run(["uninstall", "com.foo"], serial=SERIAL)
        self.assertEqual(cm.exception.code, "adb_failed")
        self.assertIn("DELETE_FAILED_INTERNAL_ERROR", cm.exception.message)

    def test_stderr_classification(self):
        cases = [
            ("error: device unauthorized.\nThis adb server's $ADB_VENDOR_KEYS is not set", "unauthorized"),
            ("error: device offline", "offline"),
            ("error: no devices/emulators found", "no_device"),
            ("adb: device 'ZY22' not found", "no_device"),
            ("error: more than one device/emulator", "many_devices"),
            ("error: closed", "adb_failed"),
        ]
        for stderr, code in cases:
            self.add_rules({"match": "shell probe", "stderr": stderr, "code": 1})
            with self.assertRaises(AdbError) as cm:
                self.adb().shell(SERIAL, "probe")
            self.assertEqual(cm.exception.code, code, stderr)

    def test_check_false_returns_the_failed_result(self):
        self.add_rules({"match": "shell nope", "stderr": "error: x", "code": 1})
        r = self.adb().shell(SERIAL, "nope", check=False)
        self.assertEqual(r.code, 1)

    def test_no_adb_when_the_binary_cannot_start(self):
        with self.assertRaises(AdbError) as cm:
            Adb("/nonexistent/adb", "setting", None).run(["devices"])
        self.assertEqual(cm.exception.code, "no_adb")

    def test_version_parses_the_version_line(self):
        self.add_rules({"match": "version", "stdout": "Android Debug Bridge version 1.0.41\nVersion 37.0.1-15733141\nInstalled as /x/adb\n"})
        self.assertEqual(self.adb().version(), "37.0.1")

    def test_banner_lines_and_control_characters(self):
        self.assertEqual(fmt.lines("* daemon not running; starting now at tcp:5037\n* daemon started successfully\nList of devices attached\r\nX\tdevice\n\n"),
                         ["List of devices attached", "X\tdevice"])
        self.assertEqual(fmt.clean("a\rb\x1b[31mc\td" + "e" * 300)[:8], "abc deee")
        self.assertEqual(len(fmt.clean("x" * 1000)), fmt.MAX_FIELD)


class ServerLock(FakeAdbCase):
    def test_two_helpers_at_once_start_the_server_once(self):
        self.add_rules({"match": "start-server", "stdout": "", "sleep": 1.0})
        results = []

        def one():
            results.append(self.run_cli("devices"))

        threads = [threading.Thread(target=one) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 2)
        starts = [c for c in self.joined_calls() if c == "start-server"]
        self.assertEqual(len(starts), 1, self.joined_calls())
        self.assertTrue(os.path.exists(os.path.join(self.state_dir, "adb-server.lock")))

    def test_start_server_is_skipped_when_the_port_answers(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        os.environ["ANDROID_ADB_SERVER_PORT"] = str(srv.getsockname()[1])
        try:
            self.run_cli("devices")
        finally:
            srv.close()
        self.assertNotIn("start-server", self.joined_calls())


if __name__ == "__main__":
    unittest.main()
