"""devices.py: parsing, labels, serial resolution, the track stream."""

import json
import os
import subprocess
import sys
import time
import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, HELPER, SERIAL, FakeAdbCase, fixture

from androiddev import devices as devmod
from androiddev import fmt
from androiddev.adb import Adb, AdbError


class Parsing(unittest.TestCase):
    def test_devices_l(self):
        d = devmod.parse_devices_l(fixture("devices_l.txt"))
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["serial"], SERIAL)
        self.assertEqual(d[0]["state"], "device")
        self.assertEqual(d[0]["model"], "sdk_gphone16k_x86_64")
        self.assertEqual(d[0]["kind"], "emulator")

    def test_cold_start_banner_parses_to_one_device(self):
        d = devmod.parse_devices_l(fixture("devices_l_coldstart.txt"))
        self.assertEqual([x["serial"] for x in d], [SERIAL])

    def test_states_and_kinds(self):
        text = ("List of devices attached\n"
                "ZY22ABC\tunauthorized usb:1-2 transport_id:3\n"
                "192.168.1.5:5555\toffline transport_id:4\n"
                "0123\tno permissions (user in plugdev group; are your udev rules wrong?); see [http://x]\n"
                "localhost:5555\tdevice product:x model:Pixel_7 device:y transport_id:5\n")
        d = {x["serial"]: x for x in devmod.parse_devices_l(text)}
        self.assertEqual(d["ZY22ABC"]["state"], "unauthorized")
        self.assertEqual(d["ZY22ABC"]["kind"], "usb")
        self.assertEqual(d["192.168.1.5:5555"]["kind"], "wifi")
        self.assertEqual(d["0123"]["state"], "no permissions")
        self.assertEqual(d["localhost:5555"]["kind"], "emulator")
        self.assertEqual(d["localhost:5555"]["model"], "Pixel_7")

    def test_device_list_is_capped(self):
        text = "\n".join(f"serial{i}\tdevice" for i in range(100))
        self.assertEqual(len(devmod.parse_devices_l(text)), fmt.MAX_DEVICES)

    def test_avd_name(self):
        self.assertEqual(devmod.parse_avd_name(fixture("emu_avd_name.txt")), "Pixel_10_Pro_Fold")
        self.assertIsNone(devmod.parse_avd_name("OK\n"))

    def test_labels(self):
        self.assertEqual(fmt.device_label(SERIAL, "sdk_gphone16k_x86_64", "Pixel_10_Pro_Fold"), "Pixel 10 Pro Fold (emulator-5554)")
        self.assertEqual(fmt.device_label("ZY22", "Pixel_7_Pro", None), "Pixel 7 Pro (ZY22)")
        self.assertEqual(fmt.device_label("ZY22", "", None), "ZY22")
        self.assertEqual(fmt.device_detail("emulator", "device"), "Emulator · ready")
        self.assertEqual(fmt.device_detail("usb", "unauthorized"), "USB · needs authorising: accept the prompt on the device")
        self.assertEqual(fmt.device_detail("wifi", "offline"), "Wi-Fi · offline")
        self.assertEqual(fmt.device_detail("usb", "no permissions (user in plugdev group; are your udev rules wrong?)"), "USB · no permissions (user in plugdev group; are your udev rules wrong?)")

    def test_resolve_serial_rules(self):
        devices = [{"serial": "a"}, {"serial": "b"}]
        self.assertEqual(devmod.resolve_serial(devices, "b", None), "b")
        self.assertEqual(devmod.resolve_serial(devices, None, "a"), "a")
        self.assertEqual(devmod.resolve_serial(devices[:1], None, "zz"), "a")
        with self.assertRaises(AdbError) as cm:
            devmod.resolve_serial(devices, None, "zz")
        self.assertEqual(cm.exception.code, "many_devices")
        with self.assertRaises(AdbError) as cm:
            devmod.resolve_serial([], None, None)
        self.assertEqual(cm.exception.code, "no_device")
        with self.assertRaises(AdbError) as cm:
            devmod.resolve_serial(devices, "c", None)
        self.assertEqual(cm.exception.code, "no_device")

    def test_require_ready(self):
        devices = [{"serial": "a", "state": "unauthorized"}, {"serial": "b", "state": "offline"}, {"serial": "c", "state": "device"}]
        for serial, code in (("a", "unauthorized"), ("b", "offline")):
            with self.assertRaises(AdbError) as cm:
                devmod.require_ready(devices, serial)
            self.assertEqual(cm.exception.code, code)
        self.assertEqual(devmod.require_ready(devices, "c")["serial"], "c")

    def test_split_frames(self):
        buf = bytearray(b"0015emulator-5554\tdevice\n0000" + b"00")
        frames, rest = devmod.split_frames(buf)
        self.assertEqual(frames, ["emulator-5554\tdevice\n", ""])
        self.assertEqual(bytes(rest), b"00")


class Live(FakeAdbCase):
    def test_list_devices_labels_an_emulator_from_emu_avd_name(self):
        d = devmod.list_devices(Adb(FAKE_ADB, "override", None))
        self.assertEqual(d[0]["label"], "Pixel 10 Pro Fold (emulator-5554)")
        self.assertEqual(d[0]["detail"], "Emulator · ready")
        self.assertIn(["-s", SERIAL, "emu", "avd", "name"], self.calls())

    def test_track_streams_one_event_per_frame_and_leaves_no_child(self):
        self.add_rules({"match": "track-devices", "stdout": "0015emulator-5554\tdevice\n0000", "sleep_after": 30})
        proc = subprocess.Popen([sys.executable, HELPER, "track"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ))
        events = [json.loads(proc.stdout.readline()), json.loads(proc.stdout.readline())]
        proc.terminate()
        proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
        self.assertEqual(events[0]["event"], "devices")
        self.assertEqual(events[0]["added"], [SERIAL])
        self.assertTrue(events[0]["initial"])
        self.assertEqual(events[0]["selected"], SERIAL)
        # The fake answers `devices -l` with the same device for every frame, so the second frame reports no change.
        self.assertEqual(events[1]["added"], [])
        self.assertEqual(events[1]["removed"], [])
        self.assertFalse(events[1]["initial"])
        self.assertNotIn("track-devices", self.wait_for_no_fake_adb())

    def wait_for_no_fake_adb(self):
        for _ in range(20):
            left = subprocess.run(["pgrep", "-af", "fakeadb.py"], capture_output=True, text=True).stdout
            if "track-devices" not in left:
                break
            time.sleep(0.1)
        return left

    def test_track_helper_killed_outright_takes_adb_with_it(self):
        # The shell ends a helper it no longer wants with SIGKILL, which
        # cannot be forwarded; the adb child must still go (PDEATHSIG).
        self.add_rules({"match": "track-devices", "stdout": "0000", "sleep_after": 30})
        proc = subprocess.Popen([sys.executable, HELPER, "track"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ))
        json.loads(proc.stdout.readline())
        proc.kill()
        proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
        self.assertNotIn("track-devices", self.wait_for_no_fake_adb())

    def test_track_without_adb_prints_one_error_line(self):
        env = dict(os.environ, OMARCHY_ANDROID_DEV_PATH="/nonexistent")
        proc = subprocess.run([sys.executable, HELPER, "track"], capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(proc.returncode, 0)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        doc = json.loads(lines[0])
        self.assertEqual(doc["event"], "error")
        self.assertEqual(doc["error"]["code"], "no_adb")

    def test_track_reports_adb_going_away(self):
        self.add_rules({"match": "track-devices", "stdout": "0000", "stderr": "error: closed", "code": 1})
        proc = subprocess.run([sys.executable, HELPER, "track"], capture_output=True, text=True, env=dict(os.environ), timeout=10)
        self.assertEqual(proc.returncode, 0)
        docs = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([d["event"] for d in docs], ["devices", "error"])


if __name__ == "__main__":
    unittest.main()
