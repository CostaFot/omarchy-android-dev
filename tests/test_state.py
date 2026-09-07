"""state.py: the private directory, descriptor reads, atomic writes, corruption."""

import json
import os
import stat
import unittest

import _paths  # noqa: F401
from _paths import FakeAdbCase

from androiddev import state as statemod
from androiddev.state import State


class Files(FakeAdbCase):
    def test_dir_is_private_and_writes_are_0600(self):
        s = State()
        s.select("emulator-5554")
        s.save()
        self.assertEqual(stat.S_IMODE(os.stat(self.state_dir).st_mode), 0o700)
        path = os.path.join(self.state_dir, "state.json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(State().selected, "emulator-5554")
        self.assertEqual([f for f in os.listdir(self.state_dir) if f.startswith(".tmp-")], [])

    def test_group_bits_on_the_dir_are_removed(self):
        os.makedirs(self.state_dir)
        os.chmod(self.state_dir, 0o755)
        State()
        self.assertEqual(stat.S_IMODE(os.stat(self.state_dir).st_mode), 0o700)

    def test_a_symlinked_dir_is_refused(self):
        target = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(target)
        os.symlink(target, self.state_dir)
        s = State()
        self.assertIsNone(s.dir)
        self.assertIn("symlink", s.error)
        s.select("x")
        s.save()  # nothing written anywhere
        self.assertEqual(os.listdir(target), [])

    def test_corrupt_state_is_moved_aside_and_reported_once(self):
        os.makedirs(self.state_dir, mode=0o700)
        path = os.path.join(self.state_dir, "state.json")
        with open(path, "w") as f:
            f.write("{not json")
        s = State()
        self.assertIsNone(s.selected)
        self.assertEqual(len(s.problems), 1)
        self.assertIn("unreadable", s.problems[0])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(any(f.startswith("state.json.bak.") for f in os.listdir(self.state_dir)))

    def test_a_symlinked_state_file_is_never_followed(self):
        os.makedirs(self.state_dir, mode=0o700)
        secret = os.path.join(self.tmp.name, "secret.json")
        with open(secret, "w") as f:
            json.dump({"selected": "stolen"}, f)
        os.symlink(secret, os.path.join(self.state_dir, "state.json"))
        s = State()
        self.assertIsNone(s.selected)
        self.assertIn("symlink", s.problems[0])
        self.assertFalse(os.path.lexists(os.path.join(self.state_dir, "state.json")))
        s.select("emulator-5554")
        s.save()
        with open(secret) as f:
            self.assertEqual(json.load(f), {"selected": "stolen"})  # untouched, before and after the write

    def test_oversized_and_wrong_shape_files(self):
        os.makedirs(self.state_dir, mode=0o700)
        path = os.path.join(self.state_dir, "state.json")
        with open(path, "w") as f:
            f.write("[" + "1," * 40000 + "1]")
        data, problem = statemod.read_json(path, default={})
        self.assertEqual(data, {})
        self.assertIn("too large", problem)
        with open(path, "w") as f:
            f.write("[1,2]")
        data, problem = statemod.read_json(path, default={})
        self.assertEqual(data, {})
        self.assertIn("wrong shape", problem)

    def test_recent_deeplinks_and_last_package(self):
        s = State()
        for i in range(12):
            s.add_deeplink(f"https://example.com/{i}")
        s.add_deeplink("https://example.com/11")
        s.set_last_package("emulator-5554", "com.foo")
        s.save()
        s2 = State()
        self.assertEqual(len(s2.recent_deeplinks), 10)
        self.assertEqual(s2.recent_deeplinks[0], "https://example.com/11")
        self.assertEqual(s2.last_package("emulator-5554"), "com.foo")

    def test_recent_apk_folders(self):
        s = State()
        for i in range(12):
            s.add_apk_dir(f"/home/x/apks/{i}")
        s.add_apk_dir("/home/x/apks/3")  # again: to the front, not twice
        s.add_apk_dir("")                # nothing to remember
        s.add_apk_dir("/home/x/" + "d" * 300)  # a path longer than one field is not remembered cut short
        s.save()
        s2 = State()
        self.assertEqual(len(s2.recent_apk_dirs), 10)
        self.assertEqual(s2.recent_apk_dirs[0], "/home/x/apks/3")
        self.assertEqual(s2.recent_apk_dirs.count("/home/x/apks/3"), 1)
        self.assertFalse(any(len(d) > 256 for d in s2.recent_apk_dirs))

    def test_junk_in_the_recent_folders_is_ignored(self):
        os.makedirs(self.state_dir, mode=0o700)
        with open(os.path.join(self.state_dir, "state.json"), "w") as f:
            json.dump({"recent_apk_dirs": ["/home/x/apks", 7, None, "", {"path": "/y"}]}, f)
        self.assertEqual(State().recent_apk_dirs, ["/home/x/apks"])

    def test_pairing_files_are_swept(self):
        s = State()
        path = s.pairing_png_path()
        self.assertTrue(path.startswith(s.dir))
        self.assertTrue(os.path.basename(path).startswith("pairing-"))
        for name in ("pairing-1.png", "pairing-22.png", "state.json"):
            with open(os.path.join(s.dir, name), "w", encoding="utf-8") as f:
                f.write("{}")
        self.assertEqual(s.sweep_pairing_files(), 2)
        self.assertEqual(sorted(os.listdir(s.dir)), ["state.json"])

    def test_reload_sees_what_another_run_wrote(self):
        watcher = State()
        self.assertIsNone(watcher.selected)
        other = State()
        other.select("emulator-5554")
        other.save()
        self.assertIsNone(watcher.selected)  # cached
        watcher.reload()
        self.assertEqual(watcher.selected, "emulator-5554")
        # Unsaved local changes survive a reload.
        watcher.select("ZY22")
        watcher.reload()
        self.assertEqual(watcher.selected, "ZY22")

    def test_package_cache_file_name_is_safe(self):
        self.assertEqual(statemod.file_token("localhost:5555"), "localhost_5555")
        self.assertEqual(statemod.file_token("../x"), ".._x")


if __name__ == "__main__":
    unittest.main()
