"""Display strings and every cap in one place.

Formatting is Python's job: QML renders the strings it is given and never
builds one from device data. Every list the helper emits is cut at a cap
below, every field is trimmed to MAX_FIELD characters with carriage
returns and control characters removed, and every byte read from a child
process is capped where it is produced (adb.run's bounded reader).
"""

import os
import re

MAX_FIELD = 256
MAX_DEVICES = 32
MAX_PACKAGES = 4000
MAX_PERMISSIONS = 512
MAX_AVDS = 64
MAX_APKS = 200
MAX_RECENT_DEEPLINKS = 10

CAP_DEFAULT = 256 * 1024          # adb stdout, most commands
CAP_PACKAGES = 1024 * 1024        # pm list packages, dumpsys package PKG
CAP_SCREENCAP = 20 * 1024 * 1024  # exec-out screencap -p
CAP_STDERR = 64 * 1024
CAP_STATE = 64 * 1024             # any state file
CAP_TRACK_FRAME = 64 * 1024       # one adb track-devices frame

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean(text, limit=MAX_FIELD):
    """One field: no CR, no ANSI escape sequences, no control characters,
    no tabs, at most `limit` chars."""
    s = str(text if text is not None else "")
    s = s.replace("\r", "").replace("\t", " ")
    s = _ANSI.sub("", s)
    s = _CONTROL.sub("", s)
    if len(s) > limit:
        s = s[:limit]
    return s


def lines(text):
    """Output lines with CRs stripped and adb's cold-start banner
    (`* daemon not running; starting now at tcp:5037`, `* daemon started
    successfully`) skipped. Blank lines are dropped."""
    out = []
    for raw in str(text or "").replace("\r", "").split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        out.append(line)
    return out


def cap_list(items, limit):
    items = list(items)
    return items[:limit] if len(items) > limit else items


def on_off(on):
    if on is None:
        return "unknown"
    return "on" if on else "off"


def humanize_model(model):
    return clean(model).replace("_", " ").strip()


def device_label(serial, model=None, avd=None):
    """`Pixel 10 Pro Fold (emulator-5554)` for an emulator with a known AVD,
    `sdk gphone16k x86 64 (emulator-5554)` from the model otherwise, the bare
    serial when nothing else is known."""
    name = humanize_model(avd) if avd else humanize_model(model)
    serial = clean(serial)
    return f"{name} ({serial})" if name else serial


def display_path(path):
    home = os.path.expanduser("~")
    p = str(path or "")
    if home and p.startswith(home):
        return "~" + p[len(home):]
    return p


def size_text(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def elapsed_text(seconds):
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        return "0:00"
    return f"{s // 60}:{s % 60:02d}"
