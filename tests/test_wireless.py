"""wireless.py: addresses and mDNS parsing, connect and disconnect, pairing
with a code on stdin, the QR session as a subprocess, going cable-free."""

import json
import os
import signal
import stat
import subprocess
import sys
import time
import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, HELPER, PNG_HEX, SERIAL, FakeAdbCase, fixture

from androiddev import wireless
from androiddev.adb import Adb, AdbError, Result

USB = "ZY22ABCDEF"
WIFI = "192.168.1.5:5555"
PAIR_ADDR = "192.168.1.5:37123"
PHONE_LINE = f"{USB}               device product:cheetah model:Pixel_7 device:cheetah transport_id:3\n"
WIFI_LINE = f"{WIFI}      device product:cheetah model:Pixel_7 device:cheetah transport_id:4\n"
# The entry adb's server makes on its own for a paired phone: the mDNS instance and service, no colon.
MDNS_SERIAL = "adb-ZY22ABCDEF-xyMD0H._adb-tls-connect._tcp."
MDNS_INSTANCE = "adb-ZY22ABCDEF-xyMD0H"
MDNS_LINE = f"{MDNS_SERIAL}      device product:cheetah model:Pixel_7 device:cheetah transport_id:5\n"
HEADER = "List of devices attached\n"
MDNS_OK = "mdns daemon version [adb discovery 0.0.0]\n"
MDNS_HEADER = "List of discovered mdns services\n"
PAIRED = f"Successfully paired to {PAIR_ADDR} [guid=adb-ZY22ABCDEF-xyMD0H]\n"


def result(stdout="", stderr="", code=0):
    return Result(["adb"], code, stdout.encode("utf-8"), stderr)


class Parsing(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(wireless.valid_address("192.168.1.5:5555"), "192.168.1.5:5555")
        self.assertEqual(wireless.valid_address(" 192.168.1.5 "), "192.168.1.5:5555")
        self.assertEqual(wireless.valid_address("phone.local:41235"), "phone.local:41235")
        self.assertEqual(wireless.valid_address("192.168.1.5:041235"), "192.168.1.5:41235")
        for bad in ("", "192.168.1.5:0", "192.168.1.5:70000", "192.168.1.5:abc", "192.168.1.300:5555", "192.168.1:5555",
                    "[fe80::1]:5555", "fe80::1", "-s", "-s:5555", "a b:5555", "192.168.1.5:5555:1", "x" * 300):
            self.assertIsNone(wireless.valid_address(bad), bad)
        with self.assertRaises(Exception) as cm:
            wireless.check_address("[fe80::1]:5555")
        self.assertEqual(cm.exception.code, "bad_args")
        self.assertIn("IPv6", cm.exception.message)
        with self.assertRaises(Exception) as cm:
            wireless.check_address("nope nope")
        self.assertIn("ip:port", cm.exception.message)
        # The 256-character field rule holds for the whole address (host 249 + `:65535`).
        self.assertEqual(wireless.valid_address("h" * 249 + ":65535"), "h" * 249 + ":65535")
        self.assertIsNone(wireless.valid_address("h" * 250 + ":65535"))
        self.assertLessEqual(len(wireless.valid_address("h" * 249 + ":65535")), 255)

    def test_the_terminal_wait_for_the_code_fits_the_budget(self):
        # On a tty `read_code` prompts and waits, but never past the run's alarm: a full minute under
        # the 60 s budget answered `timeout` instead of "no code". A code typed in time is read as is.
        master, slave = os.openpty()
        stream = os.fdopen(slave, "rb", buffering=0)
        old = signal.signal(signal.SIGALRM, lambda *a: None)
        signal.setitimer(signal.ITIMER_REAL, 8)
        try:
            started = time.monotonic()
            with self.assertRaises(AdbError) as cm:
                wireless.read_code(stream)
            self.assertEqual(cm.exception.code, "bad_args")
            self.assertLess(time.monotonic() - started, 6)
            os.write(master, b"123456\n")
            self.assertEqual(wireless.read_code(stream), "123456")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
            stream.close()
            os.close(master)

    def test_mdns_services(self):
        rows = wireless.parse_mdns_services(fixture("mdns_services.txt"))
        self.assertEqual([(r["kind"], r["instance"], r["address"]) for r in rows],
                         [("pairing", "omarchy-android-dev-ab12", "192.168.1.5:37123"),
                          ("connect", "adb-ZY22ABCDEF-xyMD0H", "192.168.1.5:41235")])
        self.assertEqual(rows[0]["detail"], "Pairing · 192.168.1.5:37123")
        self.assertEqual(rows[1]["detail"], "Wireless debugging · 192.168.1.5:41235")
        self.assertEqual(rows[1]["port"], 41235)
        self.assertEqual(wireless.parse_mdns_services("adb: mdns is not supported by this version of adb.\n"), [])
        self.assertEqual(wireless.parse_mdns_services(MDNS_HEADER), [])

    def test_connect_is_classified_by_text_not_exit_code(self):
        self.assertEqual(wireless.classify_connect(result("connected to 192.168.1.5:5555\n"))[0], True)
        self.assertEqual(wireless.classify_connect(result("already connected to 192.168.1.5:5555\n"))[0], True)
        self.assertEqual(wireless.classify_connect(result("* daemon not running; starting now at tcp:5037\n* daemon started successfully\nconnected to 192.168.1.5:5555\n"))[0], True)
        ok, text = wireless.classify_connect(result("failed to connect to '192.168.1.5:5555': Connection refused\n"))
        self.assertFalse(ok)
        self.assertIn("refused", text)
        self.assertFalse(wireless.classify_connect(result("cannot connect to 192.168.1.5:5555: No route to host\n"))[0])
        self.assertFalse(wireless.classify_connect(result("", "error: something\n", 1))[0])

    def test_pair_is_classified_by_text(self):
        ok, text, guid = wireless.classify_pair(result(PAIRED))
        self.assertTrue(ok)
        self.assertEqual(guid, "adb-ZY22ABCDEF-xyMD0H")
        ok, text, guid = wireless.classify_pair(result("Failed: Wrong password or connection was dropped.\n"))
        self.assertFalse(ok)
        self.assertIn("wrong code", text)
        ok, text, _ = wireless.classify_pair(result("", "Failed to parse address for pairing: bad\n", 1))
        self.assertFalse(ok)
        self.assertIn("parse address", text)

    def test_phone_addresses(self):
        self.assertEqual(wireless.parse_ip_route(fixture("ip_route.txt")), "192.168.1.5")
        self.assertEqual(wireless.parse_ip_route("192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.9\n"), "192.168.1.9")
        self.assertIsNone(wireless.parse_ip_route("10.0.0.0/8 dev rmnet0 proto kernel scope link src 10.20.30.40\n"))
        self.assertEqual(wireless.parse_inet_addr(fixture("ip_addr_wlan0.txt")), "192.168.1.7")
        self.assertIsNone(wireless.parse_inet_addr(""))

    def test_code_and_payload(self):
        self.assertEqual(wireless.valid_code(" 123456 "), "123456")
        for bad in ("12345", "1234567", "abc123", ""):
            self.assertIsNone(wireless.valid_code(bad))
        self.assertEqual(wireless.qr_payload("n", "p"), "WIFI:T:ADB;S:n;P:p;;")
        name, password = wireless.make_pairing_secret()
        self.assertTrue(name.startswith("omarchy-android-dev-"))
        self.assertRegex(password, r"^\d{8}$")


class Connect(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.add_rules(
            {"match": f"connect {WIFI}", "stdout": f"connected to {WIFI}\n"},
            {"match": f"-s {WIFI} get-state", "stdout": "device\n"},
            {"match": "disconnect", "stdout": f"disconnected {WIFI}\n"},
        )

    def test_connect_waits_for_ready_and_remembers_the_address(self):
        doc = self.run_cli("connect", "192.168.1.5")
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["notice"], f"Connected over Wi-Fi: {WIFI}")
        self.assertEqual(doc["state"], "device")
        self.assertNotIn("recent_addresses", doc)
        calls = self.joined_calls()
        self.assertIn(f"connect {WIFI}", calls)
        self.assertLess(calls.index(f"connect {WIFI}"), calls.index(f"-s {WIFI} get-state"))
        self.assertIn("devices", doc)
        # Nothing is remembered: a paired phone reconnects on its own.
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "state.json")))

    def test_exit_zero_failure_is_an_error(self):
        self.add_rules({"match": f"connect {WIFI}", "stdout": f"failed to connect to '{WIFI}': Connection refused\n"})
        doc = self.run_cli("connect", WIFI)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn("refused", doc["error"]["message"])
        self.assertFalse(any("get-state" in c for c in self.joined_calls()))

    def test_connected_but_offline_is_its_own_code(self):
        self.add_rules({"match": f"-s {WIFI} get-state", "stdout": "", "stderr": "error: device offline\n", "code": 1})
        started = time.monotonic()
        doc = self.run_cli("connect", WIFI)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "offline")
        self.assertIn("Wireless debugging", doc["error"]["message"])
        self.assertGreaterEqual(time.monotonic() - started, wireless.STATE_WAIT - 0.5)
        self.assertGreaterEqual(len([c for c in self.joined_calls() if "get-state" in c]), 2)
        self.add_rules({"match": f"-s {WIFI} get-state", "stdout": "unauthorized\n"})
        self.assertEqual(self.run_cli("connect", WIFI)["error"]["code"], "unauthorized")

    def test_a_hanging_connect_has_its_own_deadline(self):
        self.add_rules({"match": f"connect {WIFI}", "stdout": "", "sleep": 30})
        started = time.monotonic()
        doc = self.run_cli("connect", WIFI, env={"OMARCHY_ANDROID_DEV_TOTAL_BUDGET": "0"})
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "timeout")
        self.assertLess(time.monotonic() - started, 15)
        self.assertNotIn("VPN", doc["error"]["message"])

    def test_a_timed_out_connect_names_the_vpn_that_is_up(self):
        # Seen 2026-09-05: NordVPN with LAN Discovery off dropped every packet to the phone and the
        # helper saw only timeouts. With a tunnel interface up, the timeout and the failure text say so.
        self.interface("nordlynx", kind=65534)
        self.interface("enp6s0", kind=1)
        self.add_rules({"match": f"connect {WIFI}", "stdout": "", "sleep": 30})
        doc = self.run_cli("connect", WIFI, env={"OMARCHY_ANDROID_DEV_TOTAL_BUDGET": "0"})
        self.assertEqual(doc["error"]["code"], "timeout")
        self.assertIn("a VPN is up (nordlynx)", doc["error"]["message"])
        self.add_rules({"match": f"connect {WIFI}", "stdout": f"failed to connect to '{WIFI}': Connection timed out\n"})
        doc = self.run_cli("connect", WIFI)
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn("failed to connect", doc["error"]["message"])
        self.assertIn("a VPN is up (nordlynx)", doc["error"]["message"])
        # A tunnel that is down is not a VPN in the way.
        self.interface("nordlynx", kind=65534, up=False)
        doc = self.run_cli("connect", WIFI)
        self.assertNotIn("VPN", doc["error"]["message"])

    def test_bad_addresses_never_reach_adb(self):
        for bad in ("[fe80::1]:5555", "nope nope", "-s"):
            doc = self.run_cli("connect", bad)
            self.assertEqual(doc["error"]["code"], "bad_args", bad)
        self.assertEqual(self.run_cli("connect")["error"]["code"], "bad_args")
        self.assertFalse(any(c.startswith("connect") for c in self.joined_calls()))
        self.assertIn("IPv6", self.run_cli("connect", "[fe80::1]:5555")["error"]["message"])

    def test_disconnect(self):
        doc = self.run_cli("disconnect", WIFI)
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["notice"], f"Disconnected: {WIFI}")
        self.assertIn(["disconnect", WIFI], self.calls())
        self.add_rules({"match": "disconnect", "stdout": "", "stderr": f"error: no such device '{WIFI}'\n", "code": 1})
        self.assertTrue(self.run_cli("disconnect", WIFI)["ok"])
        self.add_rules({"match": "disconnect", "stdout": "", "stderr": "error: something else\n", "code": 1})
        self.assertEqual(self.run_cli("disconnect", WIFI)["error"]["code"], "adb_failed")

    def test_disconnect_takes_the_name_of_an_auto_connected_phone(self):
        self.add_rules({"match": "disconnect", "stdout": f"disconnected {MDNS_SERIAL}\n"})
        doc = self.run_cli("disconnect", MDNS_SERIAL)
        self.assertTrue(doc["ok"], doc)
        self.assertIn(["disconnect", MDNS_SERIAL], self.calls())
        self.assertEqual(doc["notice"], f"Disconnected: {MDNS_INSTANCE}")
        # Only that shape: an underscore anywhere else is still refused.
        self.assertEqual(self.run_cli("disconnect", "some_thing")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("connect", MDNS_SERIAL)["error"]["code"], "bad_args")


class PairCode(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.add_rules({"match": f"pair {PAIR_ADDR}", "stdin": True, "stdout": PAIRED})

    def test_the_code_goes_on_stdin_never_argv(self):
        self.add_rules({"match": "devices -l", "stdout": HEADER + PHONE_LINE + WIFI_LINE})
        doc = self.run_cli("pair", "code", PAIR_ADDR, input="123456\n")
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["guid"], "adb-ZY22ABCDEF-xyMD0H")
        self.assertIn(["pair", PAIR_ADDR, "<stdin>123456"], self.calls())
        for call in self.calls():
            for arg in call:
                self.assertNotIn("123456", arg.replace("<stdin>123456", ""))
        # The Wi-Fi entry adb connected on its own is found and selected.
        self.assertEqual(doc["serial"], WIFI)
        self.assertEqual(doc["selected"], WIFI)
        self.assertEqual(doc["notice"], f"Paired with Pixel 7 ({WIFI})")
        self.assertEqual(self.run_cli("devices")["selected"], WIFI)

    def test_an_auto_connected_name_is_the_wifi_entry(self):
        # After a pair, adb's server connects on its own and the entry carries the mDNS name, not
        # ip:port. The fake lists it throughout (so it is in `before`, the paired-again case), and
        # the connect service under its instance name says which host it is on.
        self.add_rules({"match": "devices -l", "stdout": HEADER + PHONE_LINE + MDNS_LINE},
                       {"match": "mdns services", "stdout_file": "mdns_services.txt"})
        doc = self.run_cli("pair", "code", PAIR_ADDR, input="123456\n")
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["serial"], MDNS_SERIAL)
        self.assertEqual(doc["selected"], MDNS_SERIAL)
        self.assertEqual(doc["notice"], f"Paired with Pixel 7 ({MDNS_INSTANCE})")
        self.assertEqual(doc["label"], f"Pixel 7 ({MDNS_INSTANCE})")  # the serial stays the whole name
        self.assertEqual([d["kind"] for d in doc["devices"]], ["usb", "wifi"])
        self.assertTrue(any("mdns services" in c for c in self.joined_calls()))
        self.assertEqual(self.run_cli("devices")["selected"], MDNS_SERIAL)
        # A different host: nothing found, the pairing is still good.
        self.add_rules({"match": f"pair 192.168.1.9:37123", "stdin": True, "stdout": PAIRED})
        doc = self.run_cli("pair", "code", "192.168.1.9:37123", input="123456\n", env={"OMARCHY_ANDROID_DEV_TOTAL_BUDGET": "0"})
        self.assertTrue(doc["ok"], doc)
        self.assertIsNone(doc["serial"])

    def test_no_new_device_is_still_a_good_pairing(self):
        doc = self.run_cli("pair", "code", PAIR_ADDR, input="123456\n", env={"OMARCHY_ANDROID_DEV_TOTAL_BUDGET": "0"})
        self.assertTrue(doc["ok"], doc)
        self.assertIsNone(doc["serial"])
        self.assertEqual(doc["notice"], "Paired with 192.168.1.5")

    def test_wrong_code_text_is_a_failure(self):
        self.add_rules({"match": f"pair {PAIR_ADDR}", "stdin": True, "stdout": "Failed: Wrong password or connection was dropped.\n"})
        doc = self.run_cli("pair", "code", PAIR_ADDR, input="123456\n")
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn("wrong code", doc["error"]["message"])

    def test_a_pairing_that_cannot_reach_the_phone_names_the_vpn(self):
        self.interface("tun0", kind=65534)
        self.add_rules({"match": f"pair {PAIR_ADDR}", "stdin": True, "stdout": "Failed: Unable to start pairing client.\n"})
        doc = self.run_cli("pair", "code", PAIR_ADDR, input="123456\n")
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn("a VPN is up (tun0)", doc["error"]["message"])
        # A wrong code means the phone was reached: no hint.
        self.add_rules({"match": f"pair {PAIR_ADDR}", "stdin": True, "stdout": "Failed: Wrong password or connection was dropped.\n"})
        doc = self.run_cli("pair", "code", PAIR_ADDR, input="123456\n")
        self.assertNotIn("VPN", doc["error"]["message"])

    def test_bad_codes_and_addresses_never_reach_adb(self):
        for code in ("12345\n", "abc123\n", "", "\n"):
            doc = self.run_cli("pair", "code", PAIR_ADDR, input=code)
            self.assertEqual(doc["error"]["code"], "bad_args", code)
        self.assertEqual(self.run_cli("pair", "code", "[fe80::1]:37123", input="123456\n")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("pair", "code")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("pair", "qr", "extra")["error"]["code"], "bad_args")
        self.assertFalse(any(c.startswith("pair") for c in self.joined_calls()))

    def test_a_silent_stdin_is_no_code_not_a_hang(self):
        # The store can start `pair code` with nothing to write; the helper
        # must answer, not sit on the pipe until the budget.
        started = time.monotonic()
        proc = subprocess.Popen([sys.executable, HELPER, "pair", "code", PAIR_ADDR], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=dict(os.environ))
        try:
            out, _ = proc.communicate(timeout=wireless.CODE_WAIT + 10)
        finally:
            proc.stdin.close()
        doc = json.loads(out.splitlines()[0])
        self.assertEqual(doc["error"]["code"], "bad_args")
        self.assertLess(time.monotonic() - started, wireless.CODE_WAIT + 5)


class GoWireless(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.add_rules(
            {"match": "devices -l", "stdout": HEADER + PHONE_LINE},
            {"match": f"-s {USB} shell ip route", "stdout_file": "ip_route.txt"},
            {"match": f"-s {USB} tcpip 5555", "stdout": "restarting in TCP mode port: 5555\n"},
            {"match": f"connect {WIFI}", "stdout": f"connected to {WIFI}\n"},
            {"match": f"-s {WIFI} get-state", "stdout": "device\n"},
            {"match": f"-s {WIFI} usb", "stdout": "restarting in USB mode\n"},
            {"match": f"-s {USB} usb", "stdout": "restarting in USB mode\n"},
            {"match": f"disconnect {WIFI}", "stdout": f"disconnected {WIFI}\n"},
        )

    def test_tcpip_connects_and_selects_the_wifi_entry(self):
        doc = self.run_cli("tcpip")
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["address"], WIFI)
        self.assertEqual(doc["usb_serial"], USB)
        self.assertEqual(doc["selected"], WIFI)
        self.assertEqual(doc["notice"], f"Now over Wi-Fi: {WIFI} · the cable can come out")
        calls = self.joined_calls()
        order = [calls.index(f"-s {USB} shell ip route"), calls.index(f"-s {USB} tcpip 5555"), calls.index(f"connect {WIFI}"), calls.index(f"-s {WIFI} get-state")]
        self.assertEqual(order, sorted(order))
        with open(os.path.join(self.state_dir, "state.json"), encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual(state["selected"], WIFI)
        self.assertNotIn("recent_addresses", state)

    def test_the_ip_fallback_and_no_ip_at_all(self):
        self.add_rules({"match": f"-s {USB} shell ip route", "stdout": ""}, {"match": f"-s {USB} shell ip -f inet addr show wlan0", "stdout_file": "ip_addr_wlan0.txt"},
                       {"match": "connect 192.168.1.7:5555", "stdout": "connected to 192.168.1.7:5555\n"}, {"match": "-s 192.168.1.7:5555 get-state", "stdout": "device\n"})
        self.assertEqual(self.run_cli("tcpip")["address"], "192.168.1.7:5555")
        self.add_rules({"match": f"-s {USB} shell ip -f inet addr show wlan0", "stdout": ""})
        doc = self.run_cli("tcpip", USB)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn("Wi-Fi", doc["error"]["message"])
        self.assertEqual([c for c in self.joined_calls() if "tcpip 5555" in c], [f"-s {USB} tcpip 5555"])  # the first run's only

    def test_only_a_plugged_phone_goes_wireless(self):
        self.add_rules({"match": "devices -l", "stdout": HEADER + PHONE_LINE + WIFI_LINE + f"{SERIAL}          device product:sdk model:sdk device:emu transport_id:1\n"})
        self.assertEqual(self.run_cli("tcpip", SERIAL)["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("tcpip", WIFI)["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("tcpip")["error"]["code"], "many_devices")
        self.assertEqual(self.run_cli("tcpip", "nope", "extra")["error"]["code"], "bad_args")
        self.assertFalse(any("tcpip 5555" in c for c in self.joined_calls()))

    def test_usb_puts_the_selection_back(self):
        self.run_cli("tcpip")
        self.add_rules({"match": "devices -l", "stdout": HEADER + PHONE_LINE + WIFI_LINE})
        doc = self.run_cli("usb", WIFI)
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["notice"], f"Back to USB: Pixel 7 ({WIFI})")
        calls = self.calls()
        self.assertIn(["-s", WIFI, "usb"], calls)
        # The dead entry is disconnected right after, or adb keeps it `offline` for minutes.
        self.assertLess(calls.index(["-s", WIFI, "usb"]), calls.index(["disconnect", WIFI]))
        self.assertEqual(doc["disconnected"], [WIFI])
        self.assertEqual(doc["selected"], USB)
        with open(os.path.join(self.state_dir, "state.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["selected"], USB)
        self.add_rules({"match": "devices -l", "stdout": HEADER + f"{SERIAL}          device product:sdk model:sdk device:emu transport_id:1\n"})
        self.assertEqual(self.run_cli("usb", SERIAL)["error"]["code"], "bad_args")

    def test_serial_on_the_command_line_stays_the_reported_selection(self):
        # `--serial X usb Y`: X is this run's device, whatever `usb` did to Y (before 1.4.1 the
        # command overwrote the flag and reported the state's selection instead).
        self.add_rules({"match": "devices -l", "stdout": HEADER + PHONE_LINE + WIFI_LINE})
        doc = self.run_cli("--serial", USB, "usb", WIFI)
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["disconnected"], [WIFI])
        self.assertEqual(doc["selected"], USB)
        self.assertEqual([d["serial"] for d in doc["devices"] if d["selected"]], [USB])
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "state.json")))  # nothing was selected for good

    def test_usb_on_the_plugged_entry_keeps_the_selection(self):
        # `usb` names the USB phone itself (or `usb ""` over IPC resolves to it): the phone is still
        # on the cable, so the selection stays. Before 1.3.2 it was cleared and the hub said No device.
        self.run_cli("select", USB)
        for args in ((USB,), ()):
            doc = self.run_cli("usb", *args)
            self.assertTrue(doc["ok"], doc)
            self.assertEqual(doc["notice"], f"Back to USB: Pixel 7 ({USB})")
            self.assertEqual(doc["selected"], USB)
            self.assertEqual([d["serial"] for d in doc["devices"]], [USB])
            with open(os.path.join(self.state_dir, "state.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["selected"], USB)
        self.assertEqual(self.calls().count(["-s", USB, "usb"]), 2)
        # With no ip:port entry there is nothing to disconnect and no address to read.
        self.assertFalse(any(c[0] == "disconnect" or "ip route" in " ".join(c) for c in self.calls()))
        # A Wi-Fi entry that is not the selection moves nothing either.
        self.add_rules({"match": "devices -l", "stdout": HEADER + PHONE_LINE + WIFI_LINE})
        doc = self.run_cli("usb", WIFI)
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["selected"], USB)
        self.assertEqual(doc["disconnected"], [WIFI])

    def test_usb_on_the_plugged_entry_drops_its_dead_wifi_entries(self):
        # The phone's own ip:port entry (its Wi-Fi address, read before adbd restarts) is disconnected;
        # another phone's is not; an mDNS-named entry is adb's own to find again. A dropped selection
        # moves to the phone on the cable.
        other = "192.168.1.9:5555      device product:oriole model:Pixel_6 device:oriole transport_id:6\n"
        self.add_rules({"match": "devices -l", "stdout": HEADER + PHONE_LINE + WIFI_LINE + other + MDNS_LINE},
                       {"match": f"-s {MDNS_SERIAL} usb", "stdout": "restarting in USB mode\n"})
        self.run_cli("select", WIFI)
        doc = self.run_cli("usb", USB)
        self.assertTrue(doc["ok"], doc)
        calls = self.calls()
        self.assertLess(calls.index(["-s", USB, "shell", "ip", "route"]), calls.index(["-s", USB, "usb"]))
        self.assertLess(calls.index(["-s", USB, "usb"]), calls.index(["disconnect", WIFI]))
        self.assertEqual(doc["disconnected"], [WIFI])
        self.assertEqual(doc["selected"], USB)
        with open(os.path.join(self.state_dir, "state.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["selected"], USB)
        self.assertNotIn(["disconnect", "192.168.1.9:5555"], calls)
        # Back to USB on the mDNS-named entry: adb usb, and no disconnect.
        doc = self.run_cli("usb", MDNS_SERIAL)
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["disconnected"], [])
        self.assertIn(["-s", MDNS_SERIAL, "usb"], self.calls())
        self.assertEqual(self.calls().count(["disconnect", WIFI]), 1)

    def test_a_failed_disconnect_does_not_fail_back_to_usb(self):
        self.add_rules({"match": "devices -l", "stdout": HEADER + PHONE_LINE + WIFI_LINE},
                       {"match": f"disconnect {WIFI}", "stdout": "", "stderr": "error: no such device\n", "code": 1})
        doc = self.run_cli("usb", WIFI)
        self.assertTrue(doc["ok"], doc)
        self.assertEqual(doc["notice"], f"Back to USB: Pixel 7 ({WIFI})")
        self.add_rules({"match": f"disconnect {WIFI}", "stdout": "", "stderr": "error: something else\n", "code": 1})
        self.assertTrue(self.run_cli("usb", WIFI)["ok"])

    def test_go_wireless_stops_retrying_when_a_try_would_outlive_the_budget(self):
        # Every connect fails at once here; with 8 s of budget no second try fits (a try can take 13 s
        # on a LAN that drops packets), so the answer is the specific error with the address that
        # listens, not the bare `timeout` the alarm used to produce after 20 s of retries.
        self.add_rules({"match": f"connect {WIFI}", "stdout": f"failed to connect to {WIFI}\n"})
        started = time.monotonic()
        doc = self.run_cli("tcpip", env={"OMARCHY_ANDROID_DEV_TOTAL_BUDGET": "8"})
        self.assertLess(time.monotonic() - started, 6.0)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn(f"listens on {WIFI}", doc["error"]["message"])
        self.assertIn("failed to connect", doc["error"]["message"])
        self.assertEqual(self.calls().count(["connect", WIFI]), 1)
        self.assertEqual(self.calls().count(["-s", USB, "tcpip", "5555"]), 1)


class Status(FakeAdbCase):
    def test_wireless_with_mdns(self):
        self.add_rules({"match": "mdns check", "stdout": MDNS_OK}, {"match": "mdns services", "stdout_file": "mdns_services.txt"},
                       {"match": "devices -l", "stdout": HEADER + PHONE_LINE + WIFI_LINE + f"{SERIAL}          device product:sdk model:sdk device:emu transport_id:1\n"})
        doc = self.run_cli("wireless")
        self.assertTrue(doc["ok"], doc)
        self.assertTrue(doc["mdns"]["available"])
        self.assertTrue(doc["mdns"]["supported"])
        self.assertIn("mdns daemon version", doc["mdns"]["text"])
        self.assertEqual([s["kind"] for s in doc["services"]], ["pairing", "connect"])
        self.assertFalse(doc["services"][1]["attached"])
        self.assertEqual([d["serial"] for d in doc["wifi_devices"]], [WIFI])
        self.assertEqual([d["serial"] for d in doc["usb_devices"]], [USB])
        self.assertFalse(doc["qrencode"]["found"])
        self.assertEqual(doc["port"], 5555)
        self.assertEqual(doc["pair_seconds"], 120)
        self.assertNotIn("recent_addresses", doc)
        self.assertEqual(doc["vpn"], {"up": False, "interfaces": [], "label": None, "text": None})

    def test_a_vpn_interface_that_is_up_is_in_the_document(self):
        self.add_rules({"match": "mdns check", "stdout": MDNS_OK}, {"match": "mdns services", "stdout": MDNS_HEADER})
        self.interface("nordlynx", kind=65534)
        self.interface("ppp0", kind=512)
        self.interface("tun1", kind=65534, up=False)
        self.interface("wlp7s0", kind=1)
        self.interface("lo", kind=772)
        doc = self.run_cli("wireless")
        self.assertTrue(doc["vpn"]["up"])
        self.assertEqual(doc["vpn"]["interfaces"], ["nordlynx", "ppp0"])
        self.assertEqual(doc["vpn"]["label"], "A VPN is up: nordlynx, ppp0")
        self.assertIn("LAN Discovery", doc["vpn"]["text"])
        # Without adb the check still runs: the note is worth showing on its own.
        doc = self.run_cli("wireless", env={"OMARCHY_ANDROID_DEV_PATH": "/nonexistent"})
        self.assertEqual(doc["error"]["code"], "no_adb")
        self.assertTrue(doc["vpn"]["up"])
        # An unreadable sysfs is no VPN, never an error.
        doc = self.run_cli("wireless", env={"OMARCHY_ANDROID_DEV_NET_DIR": "/nonexistent"})
        self.assertTrue(doc["ok"], doc)
        self.assertFalse(doc["vpn"]["up"])

    def test_vpn_interfaces_reads_sysfs_only(self):
        self.interface("wg_home", kind=65534)
        self.interface("bad name", kind=65534)
        self.assertEqual(wireless.vpn_interfaces(self.net_dir), ["wg_home"])
        self.assertEqual(wireless.vpn_interfaces("/nonexistent"), [])
        for i in range(12):
            self.interface(f"tun{i}", kind=65534)
        self.assertEqual(len(wireless.vpn_interfaces(self.net_dir)), wireless.MAX_VPN_INTERFACES)

    def test_an_auto_connected_phone_is_a_wifi_device_and_its_service_is_attached(self):
        self.add_rules({"match": "mdns check", "stdout": MDNS_OK}, {"match": "mdns services", "stdout_file": "mdns_services.txt"},
                       {"match": "devices -l", "stdout": HEADER + PHONE_LINE + MDNS_LINE})
        doc = self.run_cli("wireless")
        self.assertTrue(doc["ok"], doc)
        self.assertEqual([d["serial"] for d in doc["wifi_devices"]], [MDNS_SERIAL])
        self.assertEqual([d["serial"] for d in doc["usb_devices"]], [USB])
        connect = [s for s in doc["services"] if s["kind"] == "connect"][0]
        self.assertTrue(connect["attached"])  # by its instance name, the page does not offer to connect again

    def test_without_mdns_the_other_paths_stay(self):
        self.add_rules({"match": "mdns check", "stdout": "", "stderr": "adb: mdns is not supported by this version of adb.\n", "code": 1})
        doc = self.run_cli("wireless")
        self.assertTrue(doc["ok"], doc)
        self.assertFalse(doc["mdns"]["available"])
        self.assertIs(doc["mdns"]["supported"], False)
        self.assertIn("pair with a code", doc["mdns"]["text"])
        self.assertEqual(doc["services"], [])
        self.assertFalse(any("mdns services" in c for c in self.joined_calls()))

    def test_a_dead_server_is_not_no_mdns(self):
        # `mdns check` failing for any other reason is adb's own line as `adb_failed`, with the page's
        # lists still there; before 1.3.3 it was the missing-mDNS text, which tells the user to change
        # adbPath (seen on the SDK adb after `adb kill-server`).
        self.add_rules({"match": "mdns check", "stdout": "", "stderr": "error: cannot connect to daemon\n", "code": 1},
                       {"match": "devices -l", "stdout": HEADER + PHONE_LINE})
        doc = self.run_cli("wireless")
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn("cannot connect to daemon", doc["error"]["message"])
        self.assertFalse(doc["mdns"]["available"])
        self.assertIsNone(doc["mdns"]["supported"])
        self.assertEqual(doc["mdns"]["text"], doc["error"]["message"])
        self.assertNotIn("adbPath", doc["mdns"]["text"])
        self.assertEqual([d["serial"] for d in doc["usb_devices"]], [USB])
        self.assertEqual(doc["services"], [])
        self.assertFalse(any("mdns services" in c for c in self.joined_calls()))

    def test_a_failing_device_list_asks_adb_nothing_more(self):
        # The page's error path used to run the mDNS check and the services listing against the adb
        # that had just failed: two more calls, up to 10 s, before the error reached the panel.
        self.add_rules({"match": "devices -l", "stdout": "", "stderr": "error: cannot connect to daemon\n", "code": 1})
        doc = self.run_cli("wireless")
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIsNone(doc["mdns"]["supported"])
        self.assertIsNone(doc["mdns"]["text"])
        self.assertFalse(any("mdns" in c for c in self.joined_calls()))

    def test_without_adb(self):
        doc = self.run_cli("wireless", env={"OMARCHY_ANDROID_DEV_PATH": "/nonexistent"})
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "no_adb")
        self.assertEqual(doc["wifi_devices"], [])
        self.assertFalse(doc["mdns"]["available"])
        self.assertEqual(self.run_cli("wireless", "extra")["error"]["code"], "bad_args")


class PairQr(FakeAdbCase):
    """`pair qr` as a subprocess: the PNG, the wait, the pair, the cleanup."""

    def setUp(self):
        super().setUp()
        self.add_rules({"match": "mdns check", "stdout": MDNS_OK}, {"match": "mdns services", "stdout": MDNS_HEADER})
        self.qrencode = self.fake_tool("qrencode", [(None, "hex:" + PNG_HEX, 0, 0)], "OMARCHY_ANDROID_DEV_QRENCODE")

    def start(self, env=None):
        full = dict(os.environ)
        full.update(env or {})
        proc = subprocess.Popen([sys.executable, HELPER, "pair", "qr"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=full)
        self.addCleanup(self.close, proc)
        return proc

    def close(self, proc):
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()

    def pngs(self):
        return sorted(n for n in os.listdir(self.state_dir) if n.startswith("pairing-"))

    def wait_for_no_fake_adb(self):
        for _ in range(30):
            left = subprocess.run(["pgrep", "-af", r"^/usr/bin/python3 .*fakeadb\.py (mdns|pair) "], capture_output=True, text=True).stdout
            if not left.strip():
                break
            time.sleep(0.1)
        return left

    def first_line(self, proc):
        first = json.loads(proc.stdout.readline())
        self.assertEqual(first["command"], "pair")
        return first

    def test_scan_pair_and_clean_up(self):
        proc = self.start()
        first = self.first_line(proc)
        self.assertEqual(first["event"], "pairing")
        self.assertTrue(first["ok"])
        self.assertEqual(first["seconds"], 120)
        path = first["qr_path"]
        self.assertEqual(os.path.dirname(path), self.state_dir)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), bytes.fromhex(PNG_HEX))
        name = first["name"]
        self.assertTrue(name.startswith("omarchy-android-dev-"))
        # qrencode got the payload on stdin, and nothing secret on argv.
        tool = self.tool_calls("qrencode", wait=2)
        self.assertEqual(tool, [["-o", "-", "-t", "PNG", "-s", "6", "-m", "2", "-l", "M"]])
        payload = bytes.fromhex([r for r in self.recorded() if r.get("tool") == "qrencode"][0]["stdin"]).decode()
        self.assertRegex(payload, r"^WIFI:T:ADB;S:" + name + r";P:\d{8};;$")
        password = payload.split("P:")[1].rstrip(";")
        self.assertNotIn(password, json.dumps(first))
        # The phone scans it: the pairing service appears under our name.
        self.add_rules({"match": "mdns services", "stdout": MDNS_HEADER + f"{name}\t_adb-tls-pairing._tcp\t{PAIR_ADDR}\n"},
                       {"match": f"pair {PAIR_ADDR}", "stdin": True, "stdout": PAIRED},
                       {"match": "devices -l", "stdout": HEADER + WIFI_LINE})
        final = json.loads(proc.stdout.readline())
        # The state is saved before the line goes out (the tracker's next frame reads it), and the
        # fresh device list rides along like `pair code`'s.
        with open(os.path.join(self.state_dir, "state.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["selected"], WIFI)
        self.assertIn(WIFI, [d["serial"] for d in final["devices"]])
        proc.wait(timeout=15)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(final["event"], "paired")
        self.assertTrue(final["ok"], final)
        self.assertEqual(final["address"], PAIR_ADDR)
        self.assertEqual(final["serial"], WIFI)
        self.assertEqual(final["selected"], WIFI)
        self.assertEqual(final["notice"], f"Paired with Pixel 7 ({WIFI})")
        self.assertIn(["pair", PAIR_ADDR, "<stdin>" + password], self.calls())
        self.assertNotIn(password, json.dumps(final))
        self.assertEqual(self.pngs(), [])
        self.assertEqual(self.run_cli("devices")["selected"], WIFI)

    def test_sigint_removes_the_code_and_prints_nothing(self):
        proc = self.start()
        self.first_line(proc)
        self.assertEqual(len(self.pngs()), 1)
        time.sleep(0.3)
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(out, "")
        self.assertEqual(self.pngs(), [])
        self.assertEqual(self.wait_for_no_fake_adb().strip(), "")

    def test_a_cancel_before_the_mdns_check_is_not_lost(self):
        # The handlers go in before the server check and the first adb call (`mdns check`), so a
        # `pair stop` in those first moments ends the session: nothing printed, no PNG, no adb left.
        self.add_rules({"match": "mdns check", "stdout": MDNS_OK, "sleep": 3})
        proc = self.start()
        for _ in range(50):
            running = subprocess.run(["pgrep", "-af", r"^/usr/bin/python3 .*fakeadb\.py mdns check"], capture_output=True, text=True).stdout
            if running.strip():
                break
            time.sleep(0.1)
        self.assertTrue(running.strip(), "the fake adb never started the mDNS check")
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(out, "")
        self.assertEqual(self.pngs(), [])
        self.assertEqual(self.wait_for_no_fake_adb().strip(), "")

    def test_sigterm_does_the_same(self):
        proc = self.start()
        self.first_line(proc)
        proc.terminate()
        out, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(out, "")
        self.assertEqual(self.pngs(), [])

    def test_a_killed_session_leaves_the_code_until_the_next_sweeps_it(self):
        proc = self.start()
        self.first_line(proc)
        proc.kill()
        proc.wait(timeout=5)
        self.assertEqual(len(self.pngs()), 1)
        self.assertEqual(self.wait_for_no_fake_adb().strip(), "")
        again = self.start()
        second = self.first_line(again)
        self.assertEqual(self.pngs(), [os.path.basename(second["qr_path"])])

    def test_no_mdns_is_one_error_line_and_no_code(self):
        self.add_rules({"match": "mdns check", "stdout": "", "stderr": "adb: mdns is not supported by this version of adb.\n", "code": 1})
        proc = self.start()
        out, _ = proc.communicate(timeout=10)
        doc = json.loads(out.splitlines()[0])
        self.assertEqual(doc["event"], "error")
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn("pair with a code", doc["error"]["message"])
        self.assertEqual(self.tool_calls("qrencode"), [])
        self.assertEqual(self.pngs(), [])

    def test_a_dead_server_is_its_own_error_not_no_mdns(self):
        self.add_rules({"match": "mdns check", "stdout": "", "stderr": "error: cannot connect to daemon\n", "code": 1})
        proc = self.start()
        out, _ = proc.communicate(timeout=10)
        doc = json.loads(out.splitlines()[0])
        self.assertEqual(doc["event"], "error")
        self.assertEqual(doc["error"]["code"], "adb_failed")
        self.assertIn("cannot connect to daemon", doc["error"]["message"])
        self.assertNotIn("pair with a code", doc["error"]["message"])
        self.assertEqual(self.pngs(), [])

    def test_no_qrencode_is_no_tool(self):
        os.environ["OMARCHY_ANDROID_DEV_QRENCODE"] = "/nonexistent"
        proc = self.start()
        out, _ = proc.communicate(timeout=10)
        doc = json.loads(out.splitlines()[0])
        self.assertEqual(doc["error"]["code"], "no_tool")
        self.assertIn("qrencode", doc["error"]["message"])
        self.assertEqual(self.pngs(), [])

    def test_nobody_scans_is_a_timeout(self):
        proc = self.start(env={"OMARCHY_ANDROID_DEV_PAIR_SECONDS": "2"})
        first = self.first_line(proc)
        self.assertEqual(first["seconds"], 2)
        final = json.loads(proc.stdout.readline())
        proc.wait(timeout=10)
        self.assertEqual(final["event"], "error")
        self.assertEqual(final["error"]["code"], "timeout")
        self.assertIn("2 seconds", final["error"]["message"])
        self.assertEqual(self.pngs(), [])

    def test_without_adb(self):
        proc = self.start(env={"OMARCHY_ANDROID_DEV_PATH": "/nonexistent"})
        out, _ = proc.communicate(timeout=10)
        self.assertEqual(json.loads(out.splitlines()[0])["error"]["code"], "no_adb")


class Direct(FakeAdbCase):
    """The module against the fake adb without the CLI."""

    def test_wait_ready_reports_the_last_state(self):
        adb = Adb(FAKE_ADB, "override", None)
        self.add_rules({"match": "get-state", "stdout": "offline\n"})
        self.assertEqual(wireless.wait_ready(adb, WIFI, budget=0.5), "offline")
        self.add_rules({"match": "get-state", "stdout": "device\n"})
        self.assertEqual(wireless.wait_ready(adb, WIFI, budget=0.5), "device")

    def test_the_paired_entry_is_the_one_on_the_pairing_host(self):
        # A second known phone whose Wireless debugging comes on during the wait is on another host
        # and is never taken (before 1.3.2 the first new Wi-Fi entry anywhere was).
        adb = Adb(FAKE_ADB, "override", None)
        other = "192.168.1.9:5555      device product:oriole model:Pixel_6 device:oriole transport_id:6\n"
        self.add_rules({"match": "devices -l", "stdout": HEADER + PHONE_LINE + other})
        self.assertIsNone(wireless.wifi_device_on(adb, "192.168.1.5", budget=0.5))
        self.assertEqual(wireless.wifi_device_on(adb, "192.168.1.9", budget=0.5)["serial"], "192.168.1.9:5555")
        # An ip:port entry on the host is found at once, with its label and without mDNS.
        self.add_rules({"match": "devices -l", "stdout": HEADER + other + WIFI_LINE})
        found = wireless.wifi_device_on(adb, "192.168.1.5", budget=0.5)
        self.assertEqual((found["serial"], found["label"]), (WIFI, f"Pixel 7 ({WIFI})"))
        self.assertFalse(any("mdns services" in c for c in self.joined_calls()))
        # An mDNS-named entry is placed by the host its connect service advertises.
        self.add_rules({"match": "devices -l", "stdout": HEADER + other + MDNS_LINE},
                       {"match": "mdns services", "stdout_file": "mdns_services.txt"})
        self.assertEqual(wireless.wifi_device_on(adb, "192.168.1.5", budget=0.5)["serial"], MDNS_SERIAL)
        self.assertIsNone(wireless.wifi_device_on(adb, "192.168.1.7", budget=0.5))
        # An offline entry on the host is not ready, so it is not the phone yet.
        self.add_rules({"match": "devices -l", "stdout": HEADER + WIFI_LINE.replace("device product", "offline product")})
        self.assertIsNone(wireless.wifi_device_on(adb, "192.168.1.5", budget=0.5))
        self.assertFalse(any("emu avd name" in c for c in self.joined_calls()))

    def test_mdns_available(self):
        adb = Adb(FAKE_ADB, "override", None)
        self.add_rules({"match": "mdns check", "stdout": MDNS_OK})
        self.assertEqual(wireless.mdns_available(adb)[0], True)
        self.add_rules({"match": "mdns check", "stdout": "adb: mdns is not supported by this version of adb.\n"})
        ok, text = wireless.mdns_available(adb)
        self.assertFalse(ok)
        self.assertIn("mDNS", text)
        self.add_rules({"match": "mdns check", "stdout": "", "stderr": "error: cannot connect to daemon\n", "code": 1})
        with self.assertRaises(AdbError) as caught:
            wireless.mdns_available(adb)
        self.assertEqual(caught.exception.code, "adb_failed")
        self.assertIn("cannot connect to daemon", caught.exception.message)
        self.assertNotIn("adbPath", caught.exception.message)

    def test_go_wireless_retries_through_its_window_without_an_alarm(self):
        # No alarm armed in this process (time_left() is None), so the window alone bounds the retries.
        adb = Adb(FAKE_ADB, "override", None)
        self.add_rules({"match": f"-s {USB} shell ip route", "stdout_file": "ip_route.txt"},
                       {"match": f"-s {USB} tcpip 5555", "stdout": "restarting in TCP mode port: 5555\n"},
                       {"match": f"connect {WIFI}", "stdout": f"failed to connect to {WIFI}\n"})
        for name, value in (("TCPIP_WINDOW", 2.5), ("TCPIP_SETTLE", 0.0)):
            self.addCleanup(setattr, wireless, name, getattr(wireless, name))
            setattr(wireless, name, value)
        self.assertIsNone(wireless.time_left())
        with self.assertRaises(AdbError) as caught:
            wireless.go_wireless(adb, USB, None, "Pixel 7")
        self.assertEqual(caught.exception.code, "adb_failed")
        self.assertIn(f"listens on {WIFI}", caught.exception.message)
        self.assertGreaterEqual(self.calls().count(["connect", WIFI]), 2)


if __name__ == "__main__":
    unittest.main()
