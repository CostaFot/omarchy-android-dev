"""manifest.json is the one place the settings are declared. The helper
(cli.SETTING_DEFAULTS), the store (Store.qml helperSettingKeys) and the
Settings page (Pages.qml settingsDefaults) each repeat the list by hand;
these tests tie the copies together so a drift fails here, not in a
user's bar. The IPC help text and the service's page list are pinned to
the pages' own list the same way, and the window entry point to its
kind."""

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
        self.panel = read("Pages.qml")
        self.store = read("Store.qml")
        self.service = read("Service.qml")

    def test_store_sends_every_setting_the_helper_knows(self):
        keys = js_literal(self.store, "helperSettingKeys", "]")
        self.assertEqual(keys, list(SETTING_DEFAULTS))

    def test_panel_defaults_are_the_manifest_defaults(self):
        m = re.search(r"settingsDefaults:\s*\(\{(.*?)\}\)", self.panel, re.S)
        self.assertIsNotNone(m, "Pages.qml has no settingsDefaults literal")
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

    def test_the_window_verb_takes_the_same_pages(self):
        # `window PAGE` checks the name in the service (the window may not
        # have registered yet); the list is the pages' own.
        pages = js_literal(self.panel, "ipcPages", "]")
        self.assertEqual(js_literal(self.service, "pageNames", "]"), pages)
        self.assertIn("function window(mode: string): string", self.service)
        self.assertRegex(self.service, r'"  window open\|close\|toggle\|PAGE')

    def test_the_window_is_the_panel_kind(self):
        # The pages as a toplevel: the `panel` kind with Window.qml as its
        # entry point, which the shell's panel loader creates and hands the
        # service (kinds must keep `bar-widget` and `service` beside it).
        self.assertEqual(MANIFEST["kinds"], ["service", "bar-widget", "panel"])
        self.assertEqual(MANIFEST["entryPoints"]["panel"], "Window.qml")
        for kind, entry in (("service", "Service.qml"), ("barWidget", "BarWidget.qml"), ("panel", "Window.qml")):
            self.assertEqual(MANIFEST["entryPoints"][kind], entry)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, entry)), entry)
        self.assertIs(MANIFEST["keepLoaded"], True)
        window = read("Window.qml")
        self.assertIn("FloatingWindow {", window)
        self.assertIn('title: "Android Dev"', window)
        # Both hosts show the one component.
        self.assertIn("Pages {", window)
        self.assertIn("Pages {", read("Panel.qml"))

    def test_the_pages_live_once(self):
        # The refactor that made the window possible: Panel.qml is the popup
        # wrapper and Pages.qml the content; a page renderer in either host
        # is the drift this pins.
        popup = read("Panel.qml")
        for fn in ("hubRows", "packageRows", "toggleRows", "wirelessRows", "saveSettings"):
            self.assertIn(f"function {fn}(", self.panel, fn)
            self.assertNotIn(f"function {fn}(", popup, fn)
            self.assertNotIn(f"function {fn}(", read("Window.qml"), fn)

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

    def test_open_as_window_is_wired(self):
        # The `openAsWindow` setting (1.8.0): the glyph's two clicks and the
        # one-key verbs pick their surface through the service, the window
        # verb stays explicit, and the hub's Open as a window row is the
        # popup's alone (the window never shows it).
        self.assertIs(SETTING_DEFAULTS["openAsWindow"], False)
        self.assertIn('flag("openAsWindow", false)', self.store)
        for fn in ("openMain", "closeMain", "toggleMain", "toggleOther", "showPageMain"):
            self.assertIn(f"function {fn}(", self.service, fn)
        for verb, fn in (("open", "openMain"), ("show", "openMain"), ("close", "closeMain"), ("hide", "closeMain"),
                         ("toggle", "toggleMain"), ("page", "showPageMain")):
            self.assertRegex(self.service, rf"function {verb}\([^)]*\): string \{{ return root\.{fn}\(", verb)
        self.assertIn("function window(mode: string): string { return root.windowVerb(mode) }", self.service)
        widget = read("BarWidget.qml")
        self.assertIn("Qt.RightButton", widget)
        self.assertIn("root.openAsWindow", widget)
        self.assertIn('action: "openwindow"', self.panel)
        self.assertIn("if (inPopup)", self.panel)
        self.assertIn("inPopup: true", read("Panel.qml"))
        self.assertNotIn("inPopup", read("Window.qml"))

    def test_cold_boot_and_the_launcher_picker_are_wired(self):
        # 1.9.0: the boot picker under a stopped AVD row and the launcher
        # picker under Launch are two pages the IPC `page` verb never opens
        # (they need an AVD or a package); the cold boot has its own verb.
        pages = js_literal(self.panel, "ipcPages", "]")
        for page in ("avdboot", "launchpick"):
            self.assertIn(f'page: "{page}"', self.panel, page)
            self.assertNotIn(page, pages)
        self.assertIn('["tool", "avd", row.avd].concat(row.cold ? ["cold"] : [])', self.panel)
        self.assertIn('act(["app", "launch", row.pkg, row.component]', self.panel)
        self.assertIn("function avdcold(name: string): string", self.service)
        self.assertIn('root.act(["tool", "avd", n, "cold"])', self.service)
        self.assertRegex(self.service, r'"  avdcold NAME\s')

    def test_the_tweaks_page_is_wired(self):
        # 1.10.0: the Tweaks page (dark mode, the font scale, the display
        # density) is an IPC page; its two pickers are not (they need the
        # page's document under them); the three verbs reach the helper's
        # `tweak` and the store reads `tweaks` like the toggles.
        pages = js_literal(self.panel, "ipcPages", "]")
        self.assertIn("tweaks", pages)
        self.assertIn('page: "tweaks"', self.panel)
        for page in ("fontpick", "densitypick"):
            self.assertIn(f'page: "{page}"', self.panel, page)
            self.assertNotIn(page, pages)
        self.assertIn('act(["tweak", row.name])', self.panel)
        self.assertIn('act(["tweak", "font", String(row.value)])', self.panel)
        self.assertIn('act(["tweak", "density", row.reset ? "reset" : String(row.value)])', self.panel)
        self.assertIn("function refreshTweaks()", self.store)
        self.assertIn("tweaks", js_literal(self.store, "readCommands", "]"))
        self.assertIn("tweaks = d.tweaks", self.store)
        for verb in ("dark", "fontscale", "density"):
            self.assertRegex(self.service, rf"function {verb}\([a-z]+: string\): string", verb)
            self.assertRegex(self.service, rf'"  {verb} ', verb)
        self.assertIn('root.act(["tweak", "dark", m])', self.service)
        self.assertIn('root.act(["tweak", "density", "reset"])', self.service)

    def test_the_mirror_keys_are_wired(self):
        # 1.11.0: the strip beside the scrcpy window (MirrorKeys.qml, owned
        # by the service, off with the `mirrorKeys` setting): a layer-shell
        # window that never takes keyboard focus, matched to the mirror by
        # the title `tool scrcpy` sets and scrcpy's app id (the plugin's own
        # window shares the title), polling Hyprland's client list while a
        # mirror is up because a drag sends no event; every key is one
        # `key NAME` run, and the verb's names are the helper's.
        from androiddev import keys
        strip = read("MirrorKeys.qml")
        self.assertIs(SETTING_DEFAULTS["mirrorKeys"], True)
        self.assertIn('flag("mirrorKeys", true)', self.store)
        self.assertIn("MirrorKeys {", self.service)
        self.assertIn("keysEnabled: root.store.mirrorKeys", self.service)
        self.assertEqual(js_literal(self.service, "keyNames", "]"), keys.NAMES)
        self.assertIn("function key(name: string): string { return root.pressKey(name) }", self.service)
        self.assertIn('return act(["key", n], function(doc)', self.service)
        self.assertRegex(self.service, r'"  key NAME\s')
        self.assertIn("mirror: mirrorKeys.statusObject()", self.service)
        self.assertIn("WlrLayershell.keyboardFocus: WlrKeyboardFocus.None", strip)
        self.assertIn("exclusionMode: ExclusionMode.Ignore", strip)
        self.assertIn('readonly property string mirrorTitle: "Android Dev"', strip)
        self.assertIn('readonly property string mirrorAppId: "scrcpy"', strip)
        self.assertIn("Hyprland.refreshToplevels()", strip)
        for name in ("back", "home", "recents", "volup", "voldown", "power", "screenshot", "record"):
            self.assertIn(f'key: "{name}"', strip, name)
        self.assertNotIn('key: "wake"', strip)
        self.assertNotIn("Process {", strip)
        self.assertIn("--window-title", read("bin/androiddev/tools.py"))
        self.assertIn('id: mirrorKeysToggle', self.panel)

    def test_the_device_info_page_is_wired(self):
        # 1.12.0: the Device info page is an IPC page (`page info`, `window
        # info`), first on the hub; its rows are the helper's `info`
        # sections in the helper's order, the store reads `info` like the
        # toggles, and Enter copies a value through the service (wl-copy as
        # argv, a literal notice).
        from androiddev import info
        pages = js_literal(self.panel, "ipcPages", "]")
        self.assertIn("info", pages)
        self.assertEqual(js_literal(self.service, "pageNames", "]"), pages)
        self.assertIn('page: "info"', self.panel)
        self.assertEqual(js_literal(self.panel, "infoOrder", "]"), list(info.SECTIONS))
        self.assertEqual(sorted(js_literal(self.panel, "infoGlyphs", "}")), sorted(s for s in info.SECTIONS if s != "battery"))
        self.assertIn('action: "copyinfo"', self.panel)
        self.assertIn("service.copyText(row.value)", self.panel)
        self.assertIn("function refreshInfo()", self.store)
        self.assertIn("info", js_literal(self.store, "readCommands", "]"))
        self.assertIn("deviceInfo = d.info", self.store)
        self.assertIn("deviceInfo = null", self.store)
        self.assertIn("function copyText(text)", self.service)
        self.assertIn('Quickshell.execDetached(["wl-copy", "--", t])', self.service)
        self.assertNotIn("wl-copy", self.panel)

    def test_help_names_every_setting(self):
        for key in SETTING_DEFAULTS:
            self.assertIn(key, self.service, key)
        self.assertIn("omarchy bar set costafot.android-dev KEY VALUE", self.service)


if __name__ == "__main__":
    unittest.main()
