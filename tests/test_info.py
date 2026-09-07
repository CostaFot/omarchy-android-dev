"""info.py: the batched read parsed section by section, the emulator-shaped
and the empty answer, and the `info` command as one adb call."""

import json
import unittest

import _paths  # noqa: F401
from _paths import SERIAL, FakeAdbCase, fixture

from androiddev import info

EMULATOR_READ = """model=sdk_gphone64_x86_64
manufacturer=Google
brand=google
device=emu64xa
name=null
abi=x86_64
api=37
release=16
patch=2026-06-05
build=BP22.250325.006
type=user
brightness=102
brightness_mode=0
uptime=3725.10 14000.00
screen= mScreenState=OFF
focus= mCurrentFocus=null
top=
## battery
Current Battery Service state:
  AC powered: true
  USB powered: false
  Wireless powered: false
  status: 2
  health: 2
  present: true
  level: 100
  scale: 100
  voltage: 5000
  temperature: 250
  technology: Li-ion
## meminfo
MemTotal:        4023740 kB
MemAvailable:    2509932 kB
## df
Filesystem      1K-blocks    Used Available Use% Mounted on
/dev/block/dm-6   6084296 3010420   3057492  50% /data
## wm
Physical size: 1080x2400
Override size: 1000x2000
Physical density: 420
Override density: 482
## ip
2: radio0    inet 10.0.2.15/24 brd 10.0.2.255 scope global radio0\\       valid_lft forever preferred_lft forever
4: wlan0    inet 10.0.2.16/24 brd 10.0.2.255 scope global wlan0\\       valid_lft forever preferred_lft forever
## wifi
Wifi is enabled
WifiInfo: SSID: "AndroidWifi", BSSID: 00:13:10:85:fe:01, MAC: 02:15:b2:00:00:00, IP: /10.0.2.16, Security type: 0, Supplicant state: COMPLETED, Wi-Fi standard: 11n, RSSI: -50, Link speed: 200Mbps, Tx Link speed: 200Mbps, Frequency: 2447MHz, Net ID: 0
## end
"""


class Parsing(unittest.TestCase):
    def test_the_phones_read(self):
        # The HONOR phone over Wi-Fi with its VPN up (the SSID and the MACs replaced).
        raw = info.parse_read(fixture("info_read.txt"))
        s = info.sections(raw)
        self.assertEqual(list(s), list(info.SECTIONS))
        self.assertEqual({k: v["text"] for k, v in s.items()}, {
            "device": "HONOR PTP-N49",
            "android": "Android 16 · API 36",
            "battery": "86% · charging over USB",
            "network": "192.168.1.3 · CoffeeShop · -45 dBm",
            "screen": "1280x2800 · 560 dpi · on",
            "memory": "2.8 GB free of 11.0 GB",
            "storage": "371.2 GB free of 454.2 GB",
            "foreground": "com.brave.browser",
            "uptime": "2 d 23 h",
        })
        self.assertEqual(s["device"]["detail"], "Device · HONOR Magic7 Pro · HNPTPX · arm64-v8a")
        self.assertEqual(s["device"]["copy"], "PTP-N49")
        self.assertEqual(s["android"]["detail"], "Security patch 2026-07-01 · PTP-N49 10.0.0.161(C431E7R4P2) · user build")
        self.assertEqual((s["android"]["api"], s["android"]["release"], s["android"]["copy"]), (36, "16", "PTP-N49 10.0.0.161(C431E7R4P2)"))
        self.assertEqual(s["battery"]["detail"], "Battery · 41.0 °C · 4.40 V · Li-ion · health good")
        self.assertEqual((s["battery"]["level"], s["battery"]["status_text"], s["battery"]["sources"], s["battery"]["copy"]),
                         (86, "charging", ["over USB", "on AC"], "86%"))
        n = s["network"]
        self.assertEqual(n["detail"], "Network · wlan0 · 1080 Mbps · 5260 MHz · VPN tun0")
        self.assertEqual((n["ip"], n["interface"], n["ssid"], n["rssi"], n["link_speed"], n["frequency"], n["wifi"], n["vpn_interfaces"], n["copy"]),
                         ("192.168.1.3", "wlan0", "CoffeeShop", -45, 1080, 5260, "enabled", ["tun0"], "192.168.1.3"))
        # The access point's and the phone's MAC addresses stay on the device.
        self.assertNotIn("00:11:22:33:44:55", json.dumps(s))
        self.assertNotIn("02:00:00:aa:bb:cc", json.dumps(s))
        self.assertEqual(s["screen"]["detail"], "Screen · brightness 14, automatic")
        self.assertEqual((s["screen"]["size"], s["screen"]["density"], s["screen"]["state"], s["screen"]["copy"]), ("1280x2800", 560, "on", "1280x2800"))
        self.assertEqual(s["memory"]["detail"], "Memory · MemAvailable of MemTotal · 74% used")
        self.assertEqual(s["storage"]["detail"], "Storage · /data · 18% used")
        self.assertEqual(s["storage"]["mount"], "/data/user/0")
        # mCurrentFocus is null on this phone while it is awake: topResumedActivity answers.
        self.assertEqual(s["foreground"]["detail"], "Foreground · com.google.android.apps.chrome.Main")
        self.assertEqual(s["foreground"]["component"], "com.brave.browser/com.google.android.apps.chrome.Main")
        self.assertEqual(s["uptime"]["seconds"], 257684)
        for sec in s.values():
            for key in ("label", "text", "detail", "copy"):
                self.assertIsInstance(sec[key], str, key)

    def test_an_emulator_shaped_read(self):
        s = info.sections(info.parse_read(EMULATOR_READ))
        self.assertEqual(s["device"]["text"], "Google sdk gphone64 x86 64")
        self.assertEqual(s["device"]["detail"], "Device · emu64xa · x86_64")  # name null: dropped
        # A device_name that repeats the model (the emulator's `sdk_gphone64_x86_64`) is dropped too.
        s2 = info.sections(info.parse_read(EMULATOR_READ.replace("name=null", "name=sdk_gphone64_x86_64")))
        self.assertEqual(s2["device"]["detail"], "Device · emu64xa · x86_64")
        self.assertEqual(s2["device"]["name"], "sdk_gphone64_x86_64")
        self.assertEqual(s["android"]["text"], "Android 16 · API 37")
        self.assertEqual(s["battery"]["text"], "100% · charging on AC")
        self.assertEqual(s["battery"]["detail"], "Battery · 25.0 °C · 5.00 V · Li-ion · health good")
        self.assertEqual(s["network"]["text"], "10.0.2.16 · AndroidWifi · -50 dBm")  # wlan0 over radio0
        self.assertEqual(s["network"]["detail"], "Network · wlan0 · 200 Mbps · 2447 MHz")
        self.assertEqual(len(s["network"]["addresses"]), 2)
        self.assertEqual(s["screen"]["text"], "1000x2000 · 482 dpi · off · overridden")
        self.assertEqual(s["screen"]["detail"], "Screen · brightness 102, manual · physical 1080x2400 · physical 420 dpi")
        self.assertEqual(s["memory"]["text"], "2.4 GB free of 3.8 GB")
        self.assertEqual(s["memory"]["detail"], "Memory · MemAvailable of MemTotal · 38% used")
        self.assertEqual(s["storage"]["text"], "2.9 GB free of 5.8 GB")
        self.assertEqual(s["foreground"]["text"], "Nothing in the foreground")
        self.assertEqual(s["foreground"]["detail"], "Foreground · the screen is off or locked")
        self.assertIsNone(s["foreground"]["package"])
        self.assertEqual(s["uptime"]["text"], "1 h 2 min")

    def test_an_empty_read_is_unknowns_not_an_error(self):
        s = info.sections({})
        self.assertEqual({k: v["text"] for k, v in s.items()}, {
            "device": "unknown", "android": "unknown", "battery": "unknown", "network": "No IPv4 address", "screen": "unknown",
            "memory": "unknown", "storage": "unknown", "foreground": "Nothing in the foreground", "uptime": "unknown",
        })
        self.assertEqual(s["android"]["detail"], "Android")
        self.assertEqual(s["foreground"]["detail"], "Foreground")
        self.assertEqual(s["foreground"]["copy"], "")
        s = info.sections(info.parse_read("garbage\n## battery\nnonsense\n## end\n"))
        self.assertEqual(s["battery"]["text"], "unknown")

    def test_network_edge_cases(self):
        wlan = "3: wlan0    inet 10.0.0.5/24 brd 10.0.0.255 scope global wlan0\\       valid_lft 100sec preferred_lft 100sec"
        # Location off: the SSID reads <unknown ssid> and is left out.
        n = info.network_section({"#ip": [wlan], "#wifi": ["Wifi is enabled", "WifiInfo: SSID: <unknown ssid>, BSSID: 02:00:00:00:00:00, RSSI: -60, Link speed: 100Mbps, Frequency: 2412MHz"]})
        self.assertEqual(n["text"], "10.0.0.5 · -60 dBm")
        self.assertIsNone(n["ssid"])
        # Wi-Fi off and nothing else with an address.
        n = info.network_section({"#ip": [], "#wifi": ["Wifi is disabled"]})
        self.assertEqual((n["text"], n["wifi"], n["ip"]), ("No IPv4 address · Wi-Fi off", "disabled", None))
        # A tunnel alone is not the phone's address.
        n = info.network_section({"#ip": ["30: tun0    inet 10.5.0.2/16 scope global tun0\\       valid_lft forever preferred_lft forever"]})
        self.assertEqual((n["text"], n["detail"], n["vpn_interfaces"]), ("No IPv4 address", "Network · VPN tun0", ["tun0"]))
        # No wlan: the first non-tunnel interface (a plugged-in tablet on ethernet, the emulator's radio0).
        n = info.network_section({"#ip": ["2: eth0    inet 192.168.5.7/24 brd 192.168.5.255 scope global eth0\\       valid_lft forever preferred_lft forever"]})
        self.assertEqual((n["ip"], n["interface"], n["text"]), ("192.168.5.7", "eth0", "192.168.5.7"))
        # dumpsys wifi's older line, the same fields.
        n = info.network_section({"#ip": [wlan], "#wifi": ['mWifiInfo SSID: "Home", BSSID: 00:11:22:33:44:55, MAC: 02:00:00:00:00:00, RSSI: -70, Link speed: 72Mbps, Frequency: 2437MHz']})
        self.assertEqual(n["text"], "10.0.0.5 · Home · -70 dBm")

    def test_battery_words(self):
        def battery(**kv):
            return info.battery_section({"#battery": [f"  {k.replace('_', ' ')}: {v}" for k, v in kv.items()]})
        b = battery(level=500, scale=1000, status=3, health=3, temperature=380)
        self.assertEqual((b["level"], b["text"], b["detail"]), (50, "50% · discharging", "Battery · 38.0 °C · health overheated"))
        self.assertEqual(battery(level=100, status=5, USB_powered="true")["text"], "100% · full, over USB")
        self.assertEqual(battery(level=42, status=4)["text"], "42% · not charging")
        self.assertEqual(battery(level=42, status=1)["text"], "42%")
        self.assertEqual(battery(status=2, Wireless_powered="true")["text"], "charging wirelessly")
        self.assertEqual(battery(level=7)["copy"], "7%")

    def test_uptime_text(self):
        self.assertEqual([info.uptime_text(s) for s in (0, 40, 725, 3725, 90000, 257416.58)], ["0 s", "40 s", "12 min", "1 h 2 min", "1 d 1 h", "2 d 23 h"])

    def test_foreground_from_the_focus_line_first(self):
        raw = {"focus": "mCurrentFocus=Window{7b2e u0 com.example.app/com.example.app.ui.MainActivity}",
               "top": "topResumedActivity=ActivityRecord{1 u0 com.other/.Main t3}", "screen": "mScreenState=ON"}
        f = info.foreground_section(raw)
        self.assertEqual((f["package"], f["activity"], f["detail"]), ("com.example.app", "com.example.app.ui.MainActivity", "Foreground · .ui.MainActivity"))
        # A focus without a component (the notification shade) falls through to the resumed activity.
        raw["focus"] = "mCurrentFocus=Window{1234 u0 NotificationShade}"
        self.assertEqual(info.foreground_section(raw)["package"], "com.other")


class Command(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.add_rules({"match": "echo model=", "stdout_file": "info_read.txt"})

    def test_info_is_one_shell_call_with_the_sections(self):
        doc = self.run_cli("info")
        self.assertTrue(doc["ok"], doc.get("error"))
        self.assertEqual(doc["command"], "info")
        self.assertEqual(doc["selected"], SERIAL)
        self.assertEqual(list(doc["info"]), list(info.SECTIONS))
        self.assertEqual(doc["info"]["network"]["copy"], "192.168.1.3")
        self.assertEqual(doc["api"], 36)
        shells = [c for c in self.joined_calls() if " shell " in c]
        self.assertEqual(len(shells), 1, shells)
        self.assertTrue(shells[0].startswith(f"-s {SERIAL} shell echo model="), shells[0])
        self.assertIn("## end", shells[0])
        text = json.dumps(doc)
        self.assertNotIn("00:11:22:33:44:55", text)
        self.assertNotIn("02:00:00:aa:bb:cc", text)

    def test_info_takes_no_arguments(self):
        doc = self.run_cli("info", "battery")
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "bad_args")
        self.assertEqual([c for c in self.joined_calls() if " shell " in c], [])

    def test_info_needs_a_device(self):
        self.add_rules({"match": "devices -l", "stdout": "List of devices attached\n\n"})
        doc = self.run_cli("info")
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "no_device")


if __name__ == "__main__":
    unittest.main()
