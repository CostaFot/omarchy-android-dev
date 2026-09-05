"""Shared test plumbing: sys.path to bin/, a temp state dir, the fake adb
with a rule script and an argv log, recording scripts for the notifier
and wl-copy, and a closed adb server port so ensure_server() cannot see
a real server."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")
TESTS = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(TESTS, "fixtures")
FAKE_ADB = os.path.join(TESTS, "fakeadb.py")
HELPER = os.path.join(BIN, "omarchy-android-dev")
if BIN not in sys.path:
    sys.path.insert(0, BIN)

SERIAL = "emulator-5554"

DEVICE_RULES = [
    {"match": "start-server", "stdout": ""},
    {"match": "devices -l", "stdout_file": "devices_l.txt"},
    {"match": "emu avd name", "stdout_file": "emu_avd_name.txt"},
]

RECORDER = """#!/usr/bin/python3
import json, os, sys
with open(os.environ["RECORDER_LOG"], "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.buffer.read(64).hex() if not sys.stdin.isatty() else ""}) + "\\n")
"""

# A fake scrcpy / emulator / terminal / wl-paste: logs its argv to RECORDER_LOG
# under `tool`, answers from a rule list [match, stdout, code, sleep] baked in.
FAKE_TOOL = """#!/usr/bin/python3
import json, os, sys, time
argv = sys.argv[1:]
with open({log!r}, "a") as f:
    f.write(json.dumps({{"tool": {name!r}, "argv": argv}}) + "\\n")
for match, stdout, code, sleep in {rules!r}:
    if match is None or match in " ".join(argv):
        sys.stdout.write(stdout)
        sys.stdout.flush()
        if sleep:
            time.sleep(sleep)
        sys.exit(code)
sys.exit(0)
"""

# The bytes the fake adb prints for `exec-out screencap -p`: the PNG signature and some padding.
PNG_HEX = "89504e470d0a1a0a" + "49484452" + "78" * 100


def fixture(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return f.read()


class FakeAdbCase(unittest.TestCase):
    """A temp state dir, the fake adb and a clean environment per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = os.path.join(self.tmp.name, "state")
        self.log = os.path.join(self.tmp.name, "adb.log")
        self.script = os.path.join(self.tmp.name, "rules.json")
        self.recorder_log = os.path.join(self.tmp.name, "recorder.log")
        self.recorder = os.path.join(self.tmp.name, "recorder.py")
        with open(self.recorder, "w", encoding="utf-8") as f:
            f.write(RECORDER)
        os.chmod(self.recorder, 0o700)
        self.rules(DEVICE_RULES)
        self.env = {
            "OMARCHY_ANDROID_DEV_STATE_DIR": self.state_dir,
            "OMARCHY_ANDROID_DEV_PATH": FAKE_ADB,
            "OMARCHY_ANDROID_DEV_FAKE_SCRIPT": self.script,
            "OMARCHY_ANDROID_DEV_FAKE_LOG": self.log,
            "OMARCHY_ANDROID_DEV_NOTIFY": self.recorder,
            "OMARCHY_ANDROID_DEV_WL_COPY": self.recorder,
            "RECORDER_LOG": self.recorder_log,
            "ANDROID_ADB_SERVER_PORT": "9",
            "OMARCHY_SCREENSHOT_DIR": os.path.join(self.tmp.name, "shots"),
            "OMARCHY_SCREENRECORD_DIR": os.path.join(self.tmp.name, "casts"),
            # Nothing installed unless a test says so; no uwsm-app wrapper.
            "OMARCHY_ANDROID_DEV_SCRCPY": "/nonexistent",
            "OMARCHY_ANDROID_DEV_EMULATOR": "/nonexistent",
            "OMARCHY_ANDROID_DEV_TERMINAL": "/nonexistent",
            "OMARCHY_ANDROID_DEV_WL_PASTE": "/nonexistent",
            "OMARCHY_ANDROID_DEV_LAUNCHER": "",
        }
        cleared = ["ANDROID_HOME", "ANDROID_SDK_ROOT", "OMARCHY_ANDROID_DEV_DEBUG", "OMARCHY_ANDROID_DEV_TOTAL_BUDGET",
                   "XDG_PICTURES_DIR", "XDG_VIDEOS_DIR"]
        self._saved = {k: os.environ.get(k) for k in list(self.env) + cleared}
        for k in cleared:
            os.environ.pop(k, None)
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def rules(self, rules):
        with open(self.script, "w", encoding="utf-8") as f:
            json.dump(rules, f)

    def add_rules(self, *rules):
        """Prepend rules so they win over the device defaults and earlier additions."""
        with open(self.script, "r", encoding="utf-8") as f:
            current = json.load(f)
        self.rules(list(rules) + current)

    def calls(self):
        """Every argv the fake adb saw, as lists."""
        try:
            with open(self.log, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []

    def joined_calls(self):
        return [" ".join(c) for c in self.calls()]

    def fake_tool(self, name, rules=None, env_var=None):
        """Write a fake tool script; `rules` is a list of (match, stdout, code,
        sleep). With `env_var` the override is pointed at it for this test."""
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(FAKE_TOOL.format(log=self.recorder_log, name=name, rules=[list(r) for r in (rules or [(None, "", 0, 0)])]))
        os.chmod(path, 0o700)
        if env_var:
            os.environ[env_var] = path
        return path

    def tool_calls(self, name=None, wait=0):
        """The fake tools' argv lists, optionally one tool's, waiting up to
        `wait` seconds for a detached launch to have written its line."""
        deadline = time.monotonic() + wait
        while True:
            out = [r["argv"] for r in self.recorded() if "tool" in r and (name is None or r["tool"] == name)]
            if out or time.monotonic() >= deadline:
                return out
            time.sleep(0.05)

    def recorded(self):
        """What the notifier and wl-copy recorders saw, in order."""
        try:
            with open(self.recorder_log, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []

    def run_cli(self, *args, env=None, timeout=30):
        """bin/omarchy-android-dev as a subprocess, exactly as QML runs it."""
        full = dict(os.environ)
        full.update(env or {})
        proc = subprocess.run([sys.executable, HELPER, *args], capture_output=True, text=True, env=full, timeout=timeout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1, proc.stdout)
        doc = json.loads(lines[0])
        self.assertEqual(doc["schema_version"], 1)
        return doc
