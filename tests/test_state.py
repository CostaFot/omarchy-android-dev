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

    def test_package_cache_file_name_is_safe(self):
        self.assertEqual(statemod.file_token("localhost:5555"), "localhost_5555")
        self.assertEqual(statemod.file_token("../x"), ".._x")


if __name__ == "__main__":
    unittest.main()
