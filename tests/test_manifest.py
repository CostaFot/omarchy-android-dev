"""manifest.json is the one place the settings are declared. The helper
(cli.SETTING_DEFAULTS), the store (Store.qml helperSettingKeys) and the
Settings page (Panel.qml settingsDefaults) each repeat the list by hand;
these tests tie the copies together so a drift fails here, not in a
user's bar. The IPC help text is pinned to the panel's page list the same
way."""

import json
import os
import re
import unittest

import _paths  # noqa: F401
from _paths import ROOT
from androiddev.cli import SETTING_DEFAULTS

with open(os.path.join(ROOT, "manifest.json"), encoding="utf-8") as f:
    MANIFEST = json.load(f)
WIDGET = MANIFEST["barWidget"]
SCHEMA = {e["key"]: e for e in WIDGET["schema"]}


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def js_literal(text, name, close):
    """The JSON of `name: (...)` or `name: [...]` in a QML file."""
    m = re.search(re.escape(name) + r"\s*:\s*\(?\s*(\{.*?\}|\[.*?\])\s*\)?" if close == "}" else
                  re.escape(name) + r"\s*:\s*(\[.*?\])", text, re.S)
    assert m, f"{name} not found"
    literal = re.sub(r"(?<=[{,\s])(\w+)\s*:", r'"\1":', m.group(1))
    return json.loads(literal)


class ManifestMatchesTheHelper(unittest.TestCase):
    def test_defaults_and_schema_are_the_helpers(self):
        self.assertEqual(WIDGET["defaults"], SETTING_DEFAULTS)
        self.assertEqual([e["key"] for e in WIDGET["schema"]], list(SETTING_DEFAULTS))
        for key, value in SETTING_DEFAULTS.items():
            self.assertEqual(SCHEMA[key]["defaultValue"], value, key)
            self.assertEqual(SCHEMA[key]["type"], "boolean" if isinstance(value, bool) else SCHEMA[key]["type"], key)
            self.assertIn(SCHEMA[key]["type"], ("path", "string", "boolean"), key)
            self.assertTrue(SCHEMA[key]["label"] and SCHEMA[key]["description"], key)

    def test_version_is_the_manifests(self):
        from androiddev import plugin_version
        self.assertEqual(plugin_version(), MANIFEST["version"])
        self.assertRegex(MANIFEST["version"], r"^\d+\.\d+\.\d+$")


class ManifestMatchesTheQml(unittest.TestCase):
    def setUp(self):
        self.panel = read("Panel.qml")
        self.store = read("Store.qml")
        self.service = read("Service.qml")

    def test_store_sends_every_setting_the_helper_knows(self):
        keys = js_literal(self.store, "helperSettingKeys", "]")
        self.assertEqual(keys, list(SETTING_DEFAULTS))

    def test_panel_defaults_are_the_manifest_defaults(self):
        m = re.search(r"settingsDefaults:\s*\(\{(.*?)\}\)", self.panel, re.S)
        self.assertIsNotNone(m, "Panel.qml has no settingsDefaults literal")
        literal = "{" + re.sub(r"(\w+)\s*:", r'"\1":', m.group(1)) + "}"
        self.assertEqual(json.loads(literal), WIDGET["defaults"])

    def test_panel_form_covers_every_setting_once(self):
        text_keys = js_literal(self.panel, "settingsTextKeys", "]")
        bool_keys = js_literal(self.panel, "settingsBoolKeys", "]")
        self.assertEqual(text_keys + bool_keys, list(SETTING_DEFAULTS))
        self.assertEqual([k for k in SETTING_DEFAULTS if isinstance(SETTING_DEFAULTS[k], bool)], bool_keys)
        for key in text_keys:
            self.assertIn(f"id: {key}Field", self.panel, key)
        for key in bool_keys:
            self.assertIn(f"id: {key}Toggle", self.panel, key)

    def test_help_lists_the_pages_the_panel_opens(self):
        pages = js_literal(self.panel, "ipcPages", "]")
        m = re.search(r'"  page NAME\s+open the panel on a page: ([a-z ]+)"', self.service)
        self.assertIsNotNone(m, "Service.qml help has no page line")
        self.assertEqual(m.group(1).split(), pages)
        self.assertIn("settings", pages)

    def test_ipc_has_no_go_wireless_verbs(self):
        # Go wireless and Back to USB left the panel and the IPC surface in
        # 1.4.0 (pairing covers them); the helper keeps `tcpip` and `usb`
        # for the terminal. A row or a verb coming back is a decision, not
        # a drift.
        for verb in ("tcpip", "usb"):
            self.assertNotIn(f"function {verb}(", self.service, verb)
            self.assertNotIn(f'"  {verb} ', self.service, verb)
            self.assertNotIn(f'action: "{verb}"', self.panel, verb)
        self.assertNotIn("Plugged phones", self.panel)

    def test_help_names_every_setting(self):
        for key in SETTING_DEFAULTS:
            self.assertIn(key, self.service, key)
        self.assertIn("omarchy bar set costafot.android-dev KEY VALUE", self.service)


if __name__ == "__main__":
    unittest.main()
