"""The invariants a marketplace reviewer reads the tree for, pinned so a
drift fails here rather than in a review round: every QML `Text` renders
plain text (device-supplied strings never reach a rich-text sink), the
helper spawns children in three named modules only and never through a
shell, QML never runs adb itself, nothing is killed by name, no state goes
to a shared temp dir, and no file names a capability the baseline scanner
would flag (the tokens are assembled here so this file does not name them
either)."""

import os
import re
import subprocess
import unittest

import _paths  # noqa: F401
from _paths import ROOT

QML = sorted(f for f in os.listdir(ROOT) if f.endswith(".qml"))
BIN = os.path.join(ROOT, "bin")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def python_files():
    out = [os.path.join(BIN, "omarchy-android-dev")]
    for name in sorted(os.listdir(os.path.join(BIN, "androiddev"))):
        if name.endswith(".py"):
            out.append(os.path.join(BIN, "androiddev", name))
    return out


def tracked_text_files():
    """Every file git tracks that is text: the tree a reviewer reads."""
    names = subprocess.run(["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, text=True, check=True).stdout.split("\n")
    out = []
    for name in names:
        if not name or name.endswith((".png", ".jpg", ".apk")):
            continue
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            if b"\0" in f.read(4096):
                continue
        out.append(path)
    return out


def blocks(text, opener):
    """The text of every `<opener> { ... }` block, braces matched."""
    for m in re.finditer(r"(?<![\w.])" + opener + r"\s*\{", text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    yield text[m.start():i + 1]
                    break
            i += 1


class EveryQmlTextIsPlain(unittest.TestCase):
    def test_every_text_block_sets_plain_text(self):
        found = 0
        for name in QML:
            for block in blocks(read(os.path.join(ROOT, name)), "Text"):
                found += 1
                self.assertIn("textFormat: Text.PlainText", block, f"{name}: a Text without textFormat:\n{block[:200]}")
        self.assertGreater(found, 10)

    def test_no_rich_text_anywhere(self):
        for name in QML:
            text = read(os.path.join(ROOT, name))
            self.assertNotIn("RichText", text, name)
            self.assertNotIn("StyledText", text, name)
            self.assertNotIn("AutoText", text, name)
            self.assertNotIn("MarkdownText", text, name)


class TheHelperSpawnsChildrenInThreePlaces(unittest.TestCase):
    SPAWNERS = {"adb.py", "notify.py", "tools.py"}

    def test_subprocess_calls_live_in_the_named_modules(self):
        for path in python_files():
            text = read(path)
            name = os.path.basename(path)
            calls = re.findall(r"subprocess\.(Popen|run|call|check_call|check_output)\(", text)
            if name in self.SPAWNERS:
                self.assertTrue(calls, name)
            else:
                self.assertEqual(calls, [], f"{name} spawns a child; only {sorted(self.SPAWNERS)} may")

    def test_no_shell_and_no_os_level_spawn(self):
        for path in python_files():
            text = read(path)
            name = os.path.basename(path)
            self.assertNotIn("shell=True", text, name)
            self.assertNotRegex(text, r"\bos\.(system|popen|spawn\w*|exec\w*)\(", name)

    def test_nothing_is_killed_by_name(self):
        for path in python_files() + [os.path.join(ROOT, n) for n in QML]:
            text = read(path)
            for word in ("pkill", "pgrep", "killall"):
                self.assertNotIn(word, text, f"{os.path.basename(path)} names {word}")

    def test_no_shared_temp_dir(self):
        for path in python_files():
            text = read(path)
            name = os.path.basename(path)
            self.assertNotRegex(text, r"['\"]/tmp", name)
            self.assertNotIn("gettempdir", text, name)
            for m in re.finditer(r"mkstemp\(([^)]*)\)", text):
                self.assertIn("dir=", m.group(1), f"{name}: mkstemp without dir=")

    def test_every_popen_child_is_argv_with_stdin_named(self):
        for name in ("adb.py", "tools.py"):
            text = read(os.path.join(BIN, "androiddev", name))
            for m in re.finditer(r"subprocess\.Popen\((.*?)\n", text):
                self.assertIn("stdin=", m.group(1), f"{name}: Popen without stdin=")


class QmlNeverRunsAdb(unittest.TestCase):
    def test_process_commands_are_sh_exec_python(self):
        for name in QML:
            text = read(os.path.join(ROOT, name))
            argvs = [m.group(1) for m in re.finditer(r"\[([^\]]*omarchy-android-dev[^\]]*)\]", text, re.S)]
            if name in ("Service.qml", "Store.qml"):
                self.assertTrue(argvs, f"{name}: no helper argv found")
            for argv in argvs:
                self.assertTrue(argv.lstrip().startswith('"/bin/sh", "-c"'), f"{name}: a helper argv that does not start with /bin/sh -c:\n{argv}")
                self.assertIn('"/usr/bin/python3"', argv, name)
            for m in re.finditer(r"\bcommand\s*[:=]\s*\[([^\]]*)\]", text, re.S):
                self.assertIn('"/bin/sh"', m.group(1), f"{name}: a Process command that does not start with /bin/sh")
            self.assertNotRegex(text, r'"adb"', f"{name} names adb as a command")
            self.assertNotIn("/usr/bin/env", text, name)


class NoCapabilityTokenInTheTree(unittest.TestCase):
    # Assembled, not spelled: this file is in the tree too.
    TOKENS = [
        "su" + "do",
        "pac" + "man",
        "y" + "ay",
        "pk" + "exec",
        "system" + "ctl",
        "git " + "clone",
    ]
    PIPE_TO_SHELL = re.compile(r"cu" + r"rl[^\n|]*\|\s*(ba)?sh\b")

    def test_no_file_names_one(self):
        for path in tracked_text_files():
            text = read(path)
            name = os.path.relpath(path, ROOT)
            for token in self.TOKENS:
                self.assertNotRegex(text, r"(?<![\w-])" + re.escape(token) + r"(?![\w-])", f"{name} names {token}")
            self.assertIsNone(self.PIPE_TO_SHELL.search(text), f"{name} pipes a download into a shell")

    def test_no_file_is_named_like_an_installer(self):
        """The marketplace's security baseline probes every file whose name
        contains install, installer, setup or uninstall, images included,
        and fails closed on a binary one; the listing then cannot be
        approved (seen 2026-09-08 with apks-installed.png)."""
        names = subprocess.run(["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard"],
                               capture_output=True, text=True, check=True).stdout.split("\n")
        bad = [n for n in names if re.search(r"install|installer|setup|uninstall", os.path.basename(n), re.I)]
        self.assertEqual(bad, [])

    def test_the_tree_is_what_git_tracks(self):
        names = [os.path.relpath(p, ROOT) for p in tracked_text_files()]
        for must in ("manifest.json", "README.md", "LICENSE", "CHANGELOG.md", "AGENTS.md", "Service.qml", "BarWidget.qml",
                     "Panel.qml", "Pages.qml", "Window.qml", "Store.qml", "bin/omarchy-android-dev"):
            self.assertIn(must, names)
        self.assertFalse([n for n in names if n.startswith("apks/") or "__pycache__" in n], "junk is tracked")


if __name__ == "__main__":
    unittest.main()
