"""text.py: what `input text` can type, how it is escaped, the clipboard."""

import unittest

import _paths  # noqa: F401
from _paths import FAKE_ADB, SERIAL, FakeAdbCase

from androiddev import text
from androiddev.adb import Adb, AdbError


class Text(FakeAdbCase):
    def setUp(self):
        super().setUp()
        self.adb = Adb(FAKE_ADB, "override", None)
        self.add_rules({"match": "shell input text", "stdout": ""})

    def test_spaces_become_percent_s_and_the_rest_is_quoted_for_the_device_shell(self):
        self.assertEqual(text.encode("hello world"), "hello%sworld")
        self.assertEqual(text.encode("it's $(x) `y` | z"), "'it'\"'\"'s%s$(x)%s`y`%s|%sz'")
        self.assertEqual(text.encode("a%sb"), "a%sb")  # input's own escape stays what it is

    def test_send_is_one_argv_entry(self):
        doc = text.send(self.adb, SERIAL, "hello world")
        self.assertEqual(doc["notice"], "Sent: hello world")
        self.assertEqual(doc["length"], 11)
        self.assertEqual(self.calls()[-1], ["-s", SERIAL, "shell", "input", "text", "hello%sworld"])
        text.send(self.adb, SERIAL, "rm -rf / ; echo")
        self.assertEqual(self.calls()[-1][-1], "'rm%s-rf%s/%s;%secho'")

    def test_refusals(self):
        for bad, words in (("", "Nothing"), ("héllo", "ASCII"), ("a\nb", "line"), ("x" * 501, "500"), ("tab\tx", "ASCII")):
            with self.assertRaises(AdbError) as cm:
                text.check(bad)
            self.assertEqual(cm.exception.code, "bad_args")
            self.assertIn(words, cm.exception.message)
        self.assertEqual(text.check("x" * 500), "x" * 500)

    def test_clipboard_through_wl_paste(self):
        self.fake_tool("wl-paste", [(None, "from the clipboard", 0, 0)], "OMARCHY_ANDROID_DEV_WL_PASTE")
        self.assertEqual(text.clipboard_text(), "from the clipboard")
        self.assertEqual(self.tool_calls("wl-paste"), [["--no-newline", "-t", "text"]])
        doc = self.run_cli("text", "clipboard")
        self.assertEqual(doc["notice"], "Sent the clipboard: from the clipboard")
        self.assertEqual(doc["source"], "clipboard")
        self.assertEqual(self.calls()[-1][-1], "from%sthe%sclipboard")

    def test_clipboard_edge_cases(self):
        with self.assertRaises(AdbError) as cm:
            text.clipboard_text()  # /nonexistent
        self.assertEqual(cm.exception.code, "no_tool")
        self.fake_tool("wl-paste", [(None, "", 1, 0)], "OMARCHY_ANDROID_DEV_WL_PASTE")
        with self.assertRaises(AdbError) as cm:
            text.clipboard_text()
        self.assertEqual(cm.exception.code, "bad_args")
        # An image on the clipboard: wl-paste refuses the text type (seen live 2026-09-05).
        path = self.fake_tool("wl-paste", [(None, "", 1, 0)], "OMARCHY_ANDROID_DEV_WL_PASTE")
        with open(path, "a", encoding="utf-8") as f:
            pass
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\necho 'Clipboard content is not available as requested type \"text\"' >&2\nexit 1\n")
        with self.assertRaises(AdbError) as cm:
            text.clipboard_text()
        self.assertEqual(cm.exception.message, "The clipboard does not hold text")
        self.fake_tool("wl-paste", [(None, "héllo", 0, 0)], "OMARCHY_ANDROID_DEV_WL_PASTE")
        self.assertEqual(self.run_cli("text", "clipboard")["error"]["code"], "bad_args")
        self.assertFalse(any("input" in c for c in self.calls()))

    def test_cli_shapes(self):
        self.assertEqual(self.run_cli("text", "send", "hi there")["notice"], "Sent: hi there")
        self.assertEqual(self.run_cli("text")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("text", "send")["error"]["code"], "bad_args")
        self.assertEqual(self.run_cli("text", "send", "a\nb")["error"]["code"], "bad_args")


if __name__ == "__main__":
    unittest.main()
