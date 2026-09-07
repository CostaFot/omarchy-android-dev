"""Where the helper keeps its files, and how it reads and writes them.

State dir: ${XDG_STATE_HOME:-~/.local/state}/omarchy/costafot.android-dev/
(override with OMARCHY_ANDROID_DEV_STATE_DIR; tests point it at a temp dir).

Rules, all of them from marketplace reviews of other plugins:
- the directory is created 0700 and verified on every run: not a symlink,
  a directory, owned by us, no group/other bits (fixed with chmod);
  a directory that fails the check is not used at all (StateError);
- reads open with O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC, fstat the descriptor,
  require a regular file under CAP_STATE bytes and read through it;
- writes go to an exclusive 0600 temp file in the same directory, fsync,
  then os.replace; there is no /tmp fallback anywhere;
- a symlinked, oversized or unparsable file is moved aside as
  `<name>.bak.<ts>` and reported once as `state_corrupt`.
"""

import errno
import json
import os
import re
import stat
import tempfile
import time

from . import PLUGIN_ID, fmt


class StateError(Exception):
    pass


def state_dir():
    d = os.environ.get("OMARCHY_ANDROID_DEV_STATE_DIR")
    if not d:
        base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
        d = os.path.join(base, "omarchy", PLUGIN_ID)
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
    except OSError as e:
        raise StateError(f"cannot create the state directory {d}: {e.strerror}") from e
    _verify_dir(d)
    return d


def _verify_dir(d):
    try:
        st = os.lstat(d)
    except OSError as e:
        raise StateError(f"cannot stat the state directory {d}: {e.strerror}") from e
    if stat.S_ISLNK(st.st_mode):
        raise StateError(f"the state directory {d} is a symlink; refusing to use it")
    if not stat.S_ISDIR(st.st_mode):
        raise StateError(f"{d} is not a directory")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise StateError(f"the state directory {d} is not owned by this user")
    if st.st_mode & 0o077:
        try:
            os.chmod(d, 0o700)
        except OSError as e:
            raise StateError(f"cannot make {d} private: {e.strerror}") from e


def _move_aside(path):
    aside = f"{path}.bak.{int(time.time())}"
    try:
        os.rename(path, aside)  # rename never follows the last component
    except OSError:
        return None
    return aside


def read_json(path, default=None):
    """(data, problem). `problem` is a human sentence when the file was
    unusable and has been moved aside; the data is then `default`."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return default, None
    except OSError as e:
        if e.errno == errno.ELOOP:
            aside = _move_aside(path)
            return default, f"{os.path.basename(path)} was a symlink and has been set aside" + (f" (backup: {aside})" if aside else "")
        return default, f"{os.path.basename(path)} could not be opened ({e.strerror})"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            os.close(fd)
            aside = _move_aside(path)
            return default, f"{os.path.basename(path)} was not a regular file and has been set aside"
        if st.st_size > fmt.CAP_STATE:
            os.close(fd)
            aside = _move_aside(path)
            return default, f"{os.path.basename(path)} was too large ({st.st_size} bytes) and has been set aside" + (f" (backup: {aside})" if aside else "")
        with os.fdopen(fd, "rb") as f:
            raw = f.read(fmt.CAP_STATE + 1)
    except OSError as e:
        return default, f"{os.path.basename(path)} could not be read ({e.strerror})"
    if len(raw) > fmt.CAP_STATE:
        aside = _move_aside(path)
        return default, f"{os.path.basename(path)} was too large and has been set aside"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        aside = _move_aside(path)
        return default, f"{os.path.basename(path)} was unreadable and has been reset" + (f" (backup: {aside})" if aside else "")
    if default is not None and not isinstance(data, type(default)):
        aside = _move_aside(path)
        return default, f"{os.path.basename(path)} had the wrong shape and has been reset" + (f" (backup: {aside})" if aside else "")
    return data, None


def write_json(path, data):
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)  # O_EXCL, 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def file_token(serial):
    """A serial as a file-name fragment (`localhost:5555` → `localhost_5555`)."""
    return _SAFE.sub("_", str(serial or ""))[:128] or "none"


class State:
    """state.json (selected serial, last package per serial, recent deep
    links, recent APK folders) and packages-<serial>.json (the last
    package list). Loaded lazily, written only by save() when something
    changed."""

    def __init__(self):
        self.dir = None
        self.error = None      # a StateError message: the dir is unusable, nothing is read or written
        self.problems = []     # state_corrupt notes for the envelope
        self._doc = None
        self._dirty = False
        try:
            self.dir = state_dir()
        except StateError as e:
            self.error = str(e)

    # -- state.json ------------------------------------------------------

    def _path(self, name):
        return os.path.join(self.dir, name) if self.dir else None

    def _load(self):
        if self._doc is not None:
            return self._doc
        self._doc = {"selected": None, "last_package": {}, "recent_deeplinks": [], "recent_apk_dirs": []}
        if not self.dir:
            return self._doc
        data, problem = read_json(self._path("state.json"), default={})
        if problem:
            self.problems.append(problem)
        if isinstance(data, dict):
            if isinstance(data.get("selected"), str):
                self._doc["selected"] = fmt.clean(data["selected"])
            if isinstance(data.get("last_package"), dict):
                self._doc["last_package"] = {fmt.clean(k): fmt.clean(v) for k, v in data["last_package"].items() if isinstance(v, str)}
            if isinstance(data.get("recent_deeplinks"), list):
                self._doc["recent_deeplinks"] = [fmt.clean(u, 2048) for u in data["recent_deeplinks"] if isinstance(u, str)][:fmt.MAX_RECENT_DEEPLINKS]
            if isinstance(data.get("recent_apk_dirs"), list):
                self._doc["recent_apk_dirs"] = [fmt.clean(d) for d in data["recent_apk_dirs"] if isinstance(d, str) and d][:fmt.MAX_RECENT_APK_DIRS]
        return self._doc

    def reload(self):
        """Forget the cached document so the next read sees what another
        helper run wrote (the tracker calls this once per frame)."""
        if not self._dirty:
            self._doc = None

    @property
    def selected(self):
        return self._load()["selected"]

    def select(self, serial):
        doc = self._load()
        if doc["selected"] != serial:
            doc["selected"] = serial
            self._dirty = True

    def last_package(self, serial):
        return self._load()["last_package"].get(serial)

    def set_last_package(self, serial, pkg):
        doc = self._load()
        if doc["last_package"].get(serial) != pkg:
            doc["last_package"][serial] = pkg
            self._dirty = True

    @property
    def recent_deeplinks(self):
        return list(self._load()["recent_deeplinks"])

    def add_deeplink(self, url):
        doc = self._load()
        recent = [u for u in doc["recent_deeplinks"] if u != url]
        recent.insert(0, url)
        doc["recent_deeplinks"] = recent[:fmt.MAX_RECENT_DEEPLINKS]
        self._dirty = True

    @property
    def recent_apk_dirs(self):
        return list(self._load()["recent_apk_dirs"])

    def add_apk_dir(self, path):
        """The folder an APK was installed from, newest first. A path that
        `clean` would change (longer than one field, a tab or a control
        character in a folder name) is not remembered at all: the panel
        hands these back as the folder to list, and a path cut short or
        rewritten would name another folder or none."""
        raw = str(path or "")
        d = fmt.clean(raw)
        if not d or d != raw:
            return
        doc = self._load()
        recent = [p for p in doc["recent_apk_dirs"] if p != d]
        recent.insert(0, d)
        doc["recent_apk_dirs"] = recent[:fmt.MAX_RECENT_APK_DIRS]
        self._dirty = True

    def save(self):
        if not self._dirty or not self.dir:
            return
        write_json(self._path("state.json"), self._load())
        self._dirty = False

    # -- pairing-<pid>.png --------------------------------------------------

    def pairing_png_path(self):
        """Where a `pair qr` session writes its code: a 0600 file in the
        private dir, named after the helper's pid, removed when the session
        ends. None when the dir is unusable."""
        return self._path(f"pairing-{os.getpid()}.png")

    def sweep_pairing_files(self):
        """Remove the codes earlier sessions left behind (a SIGKILLed helper
        cannot remove its own). Returns how many went."""
        if not self.dir:
            return 0
        gone = 0
        try:
            names = os.listdir(self.dir)
        except OSError:
            return 0
        for name in names:
            if name.startswith("pairing-") and name.endswith(".png"):
                try:
                    os.unlink(os.path.join(self.dir, name))
                    gone += 1
                except OSError:
                    pass
        return gone

    # -- packages-<serial>.json -------------------------------------------

    def package_cache(self, serial):
        """{name: {debuggable: bool|None}} from the last list for that device."""
        if not self.dir:
            return {}
        data, problem = read_json(self._path(f"packages-{file_token(serial)}.json"), default={})
        if problem:
            self.problems.append(problem)
        out = {}
        if isinstance(data, dict):
            for name, info in data.items():
                if isinstance(name, str) and isinstance(info, dict):
                    d = info.get("debuggable")
                    out[fmt.clean(name)] = {"debuggable": d if isinstance(d, bool) else None}
        return out

    def write_package_cache(self, serial, cache):
        if not self.dir:
            return
        write_json(self._path(f"packages-{file_token(serial)}.json"), cache)

    def lock_path(self):
        return self._path("adb-server.lock")
