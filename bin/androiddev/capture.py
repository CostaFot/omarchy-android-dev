"""Screenshots, Omarchy's way: the same directory rule as
omarchy-capture-screenshot, the file and the clipboard, a notification
with the image. The bytes come from `exec-out screencap -p` (no device
temp file), capped at 20 MiB and checked for a PNG signature before the
file is published.
"""

import os
import re
import time

from . import fmt, notify
from .adb import AdbError

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
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        raise AdbError("internal", f"Cannot create {directory}: {e.strerror}") from e
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
