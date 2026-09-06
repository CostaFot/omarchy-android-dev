"""Screenshots and screen recordings, Omarchy's way.

Screenshots: the same directory rule as omarchy-capture-screenshot, the
file and the clipboard, a notification with the image. The bytes come
from `exec-out screencap -p` (no device temp file), capped at 20 MiB and
checked for a PNG signature before the file is published.

Recordings: `adb shell screenrecord` writes an mp4 on the device while
this helper waits; a SIGINT or SIGTERM (Ctrl-C, or the service's
`record stop`) ends the adb client (SIGTERM), adbd hangs up the shell,
screenrecord finishes the file, and the helper pulls it to the recording directory
(the same rule as omarchy-capture-screenrecording), removes the device
copy and notifies. Verified 2026-09-05 on the API 37 emulator: the file
stopped growing within half a second of the SIGINT with the `moov` atom
in place, the same shape as a `--time-limit` run.
"""

import os
import re
import signal
import subprocess
import threading
import time

from . import fmt, notify
from .adb import AdbError, _pump, die_with_parent

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_XDG_LINE = re.compile(r'^\s*(XDG_[A-Z_]+_DIR)\s*=\s*"?([^"\n]*)"?\s*$')


PREAMBLE_MAX = 4096


def split_png(data):
    """(png_bytes, warning_text). `screencap -p` on a device with several
    displays (a foldable emulator) prints `[Warning] Multiple displays were
    found...` on stdout ahead of the image, so the signature is looked for
    within the first PREAMBLE_MAX bytes and the text before it is returned
    as the warning. (None, None) when there is no PNG."""
    if data.startswith(PNG_MAGIC):
        return data, None
    at = data.find(PNG_MAGIC, 0, PREAMBLE_MAX + len(PNG_MAGIC))
    if at < 0:
        return None, None
    warning = fmt.clean(data[:at].decode("utf-8", errors="replace").strip(), 512)
    return data[at:], warning or None


def parse_user_dirs(text, home=None):
    home = home or os.path.expanduser("~")
    out = {}
    for line in str(text or "").split("\n"):
        m = _XDG_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2).replace("$HOME", home).replace("${HOME}", home)
    return out


def pictures_dir():
    """`${OMARCHY_SCREENSHOT_DIR:-${XDG_PICTURES_DIR:-$HOME/Pictures}}` with
    XDG_PICTURES_DIR sourced from ~/.config/user-dirs.dirs as the shell
    script does."""
    env = os.environ.get("OMARCHY_SCREENSHOT_DIR")
    if env:
        return os.path.expanduser(env)
    xdg = os.environ.get("XDG_PICTURES_DIR")
    if not xdg:
        try:
            with open(os.path.join(os.path.expanduser("~"), ".config", "user-dirs.dirs"), "r", encoding="utf-8") as f:
                xdg = parse_user_dirs(f.read()).get("XDG_PICTURES_DIR")
        except OSError:
            xdg = None
    return os.path.expanduser(xdg) if xdg else os.path.join(os.path.expanduser("~"), "Pictures")


def screenshot_dir(settings):
    configured = str(settings.get("screenshotDir") or "").strip()
    return os.path.expanduser(configured) if configured else pictures_dir()


def videos_dir():
    """`${OMARCHY_SCREENRECORD_DIR:-${XDG_VIDEOS_DIR:-$HOME/Videos}}`, as
    omarchy-capture-screenrecording resolves it."""
    env = os.environ.get("OMARCHY_SCREENRECORD_DIR")
    if env:
        return os.path.expanduser(env)
    xdg = os.environ.get("XDG_VIDEOS_DIR")
    if not xdg:
        try:
            with open(os.path.join(os.path.expanduser("~"), ".config", "user-dirs.dirs"), "r", encoding="utf-8") as f:
                xdg = parse_user_dirs(f.read()).get("XDG_VIDEOS_DIR")
        except OSError:
            xdg = None
    return os.path.expanduser(xdg) if xdg else os.path.join(os.path.expanduser("~"), "Videos")


def recording_dir(settings):
    configured = str(settings.get("recordingDir") or "").strip()
    return os.path.expanduser(configured) if configured else videos_dir()


def _ensure_dir(directory):
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        raise AdbError("internal", f"Cannot create {directory}: {e.strerror}") from e


def _fresh_path(directory, stem, ext):
    """An exclusive new file; a same-second collision gets a -2, -3 suffix."""
    for n in range(1, 100):
        name = f"{stem}{'' if n == 1 else f'-{n}'}{ext}"
        path = os.path.join(directory, name)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o644)
            return fd, path
        except FileExistsError:
            continue
    raise AdbError("internal", f"Could not create a new file in {directory}")


def screenshot(adb, serial, settings, device_label=None):
    result = adb.run(["exec-out", "screencap", "-p"], serial=serial, timeout=30, cap=fmt.CAP_SCREENCAP)
    data, warning = split_png(result.stdout)
    if data is None:
        raise AdbError("adb_failed", "screencap did not return a PNG" + (f": {result.stderr}" if result.stderr else ""), result.stderr)
    directory = screenshot_dir(settings)
    _ensure_dir(directory)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    fd, path = _fresh_path(directory, f"android-{stamp}", ".png")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except OSError as e:
        raise AdbError("internal", f"Cannot write {path}: {e.strerror}") from e
    copied = notify.copy_file(path, "image/png")
    notified = notify.send(settings, "Android screenshot saved to clipboard and file", fmt.display_path(path), image=path)
    return {
        "notice": f"Screenshot saved: {fmt.display_path(path)}",
        "path": path,
        "path_text": fmt.display_path(path),
        "size": len(data),
        "size_text": fmt.size_text(len(data)),
        "copied": copied,
        "notified": notified,
        "warning": warning,
    }


# ---- screen recording --------------------------------------------------------

DEVICE_RECORD_DIR = "/sdcard"
SETTLE_SECONDS = 5.0


def device_file_size(adb, serial, path):
    """The size of a device file through `stat -c %s`, or None."""
    try:
        result = adb.shell(serial, "stat", "-c", "%s", path, timeout=5)
    except AdbError:
        return None
    for line in result.lines():
        try:
            return int(line.strip())
        except ValueError:
            continue
    return None


def wait_for_file(adb, serial, path, budget=SETTLE_SECONDS):
    """screenrecord finishes the mp4 on its own after the hang-up; wait until
    the file is there and has stopped growing (two equal reads), at most
    `budget` seconds. Returns the last size seen (None: never there)."""
    deadline = time.monotonic() + budget
    last = None
    while time.monotonic() < deadline:
        size = device_file_size(adb, serial, path)
        if size is not None and size > 0 and size == last:
            return size
        last = size
        time.sleep(0.25)
    return last


# The one recording this helper runs: `stopping` once SIGINT or SIGTERM
# arrived, `proc` the adb client once it is started.
_session = {"stopping": False, "proc": None}


def _on_stop(signum, frame):
    # Ending the adb client (SIGTERM; the shell's children inherit an
    # ignored SIGINT) closes its connection; adbd hangs up the remote
    # shell and screenrecord, which handles SIGHUP, finishes the file.
    _session["stopping"] = True
    proc = _session["proc"]
    if proc is not None:
        try:
            proc.terminate()
        except OSError:
            pass


def arm_stop():
    """The recorder's stop: SIGINT or SIGTERM end the recording, and this
    helper dies with its parent. `dispatch` calls it before the device
    lookup, not just `record`: the shell starts the helper with SIGINT
    ignored, so until a handler is in place a `record stop` while the
    helper was still listing devices was simply dropped and the recording
    went on (the same window `pair qr` had, closed in 1.3.1). Idempotent."""
    die_with_parent()  # a killed shell must not leave this helper behind
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)


def record(adb, serial, settings, emit, device_label=None):
    """Stream: one `recording` event once screenrecord is running, then the
    final `recorded` document (or raises AdbError) when the recording ends,
    by signal or by screenrecord's own time limit (180 s by default). None
    when the stop came before screenrecord was started: nothing to pull,
    nothing to say."""
    arm_stop()  # dispatch armed it already; a direct caller gets it here
    if _session["stopping"]:
        return None
    directory = recording_dir(settings)
    _ensure_dir(directory)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    device_path = f"{DEVICE_RECORD_DIR}/omarchy-android-dev-{stamp}.mp4"
    stopping = _session
    proc = adb.popen(["shell", "screenrecord", device_path], serial=serial)
    _session["proc"] = proc
    started = time.time()
    if stopping["stopping"]:
        _on_stop(None, None)
    out = {"data": bytearray(), "truncated": False}
    err = {"data": bytearray(), "truncated": False}
    threading.Thread(target=_pump, args=(proc.stdout, fmt.CAP_DEFAULT, out, proc), daemon=True).start()
    threading.Thread(target=_pump, args=(proc.stderr, fmt.CAP_STDERR, err, proc), daemon=True).start()
    try:
        # screenrecord that cannot start (no encoder, a bad path) fails
        # within the first moments; give it that long before announcing.
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            notify.send(settings, "Recording the Android screen", device_label or serial)
            emit({
                "event": "recording",
                "device_path": device_path,
                "directory": directory,
                "directory_text": fmt.display_path(directory),
                "started_at": int(started),
            })
            proc.wait()
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
    seconds = max(0, int(time.time() - started))
    stderr = fmt.clean(bytes(err["data"]).decode("utf-8", errors="replace").strip(), 512)
    stdout = fmt.clean(bytes(out["data"]).decode("utf-8", errors="replace").strip(), 512)
    if not stopping["stopping"] and proc.returncode != 0:
        raise AdbError("adb_failed", "screenrecord failed" + (f": {stderr or stdout}" if stderr or stdout else f" (exit {proc.returncode})"), stderr)
    size_on_device = wait_for_file(adb, serial, device_path)
    if not size_on_device:
        raise AdbError("adb_failed", "screenrecord left no file on the device" + (f": {stderr or stdout}" if stderr or stdout else ""), stderr)
    fd, path = _fresh_path(directory, f"android-{stamp}", ".mp4")
    os.close(fd)
    try:
        adb.run(["pull", device_path, path], serial=serial, timeout=120)
    except AdbError as e:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise AdbError(e.code, f"Could not pull the recording: {e.message}", e.stderr) from e
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    warning = None
    try:
        adb.shell(serial, "rm", "-f", device_path, timeout=10)
        removed = True
    except AdbError as e:
        removed = False
        warning = f"The device copy could not be removed ({e.message}); it is at {device_path}"
    notified = notify.send(settings, "Android screen recording saved", fmt.display_path(path))
    return {
        "event": "recorded",
        "notice": f"Recording saved: {fmt.display_path(path)}",
        "path": path,
        "path_text": fmt.display_path(path),
        "size": size,
        "size_text": fmt.size_text(size),
        "seconds": seconds,
        "seconds_text": fmt.elapsed_text(seconds),
        "device_path": device_path,
        "removed": removed,
        "notified": notified,
        "warning": warning,
    }
