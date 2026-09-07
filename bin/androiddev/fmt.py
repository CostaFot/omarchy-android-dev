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
MAX_RECENT_APK_DIRS = 10
MAX_MDNS_SERVICES = 32

CAP_DEFAULT = 256 * 1024          # adb stdout, most commands
CAP_QR_PNG = 1024 * 1024          # qrencode's PNG on stdout
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


def package_tags(running, foreground, debuggable):
    """The second line of a package row, as on Windows: `foreground` or
    `running`, then `debuggable`; empty when the package is neither."""
    tags = []
    if foreground:
        tags.append("foreground")
    elif running:
        tags.append("running")
    if debuggable:
        tags.append("debuggable")
    return " · ".join(tags)


def humanize_model(model):
    return clean(model).replace("_", " ").strip()


def device_label(serial, model=None, avd=None):
    """`Pixel 10 Pro Fold (emulator-5554)` for an emulator with a known AVD,
    `sdk gphone16k x86 64 (emulator-5554)` from the model otherwise, the bare
    serial when nothing else is known."""
    name = humanize_model(avd) if avd else humanize_model(model)
    serial = clean(serial)
    return f"{name} ({serial})" if name else serial


KIND_TEXT = {"emulator": "Emulator", "usb": "USB", "wifi": "Wi-Fi"}
STATE_TEXT = {"device": "ready", "unauthorized": "needs authorising: accept the prompt on the device", "offline": "offline"}


def device_detail(kind, state):
    """`Emulator · ready`, `USB · needs authorising: accept the prompt on the
    device`, `USB · no permissions (…)`: the hub's line under the label."""
    kind_text = KIND_TEXT.get(kind, clean(kind))
    state_text = STATE_TEXT.get(state, clean(state))
    return f"{kind_text} · {state_text}" if state_text else kind_text


def avd_detail(serial):
    """`Running · emulator-5554` or `Stopped`: the Tools page's line under an AVD."""
    return f"Running · {clean(serial)}" if serial else "Stopped"


# ---- wireless debugging --------------------------------------------------------

MDNS_MISSING_TEXT = ("This adb has no mDNS (the android-tools one does not): pair with a code instead, "
                     "or point adbPath at the SDK platform-tools adb")
QR_SCAN_TEXT = "Scan it from Developer options › Wireless debugging › Pair device with QR code"
QR_WARNING_TEXT = "Only from that screen: a camera app reads this code as Wi-Fi credentials and can knock the phone off its network"
SERVICE_TEXT = {"pairing": "Pairing", "connect": "Wireless debugging"}
VPN_TEXT = ("If nothing on Wi-Fi ever answers, it may be isolating the LAN: let LAN traffic through "
            "(NordVPN: LAN Discovery) or disconnect it while pairing")


def vpn_label(interfaces):
    """`A VPN is up: nordlynx`: the Wireless page's note while a tunnel
    interface is up on this machine."""
    names = ", ".join(clean(n, 32) for n in interfaces)
    return f"A VPN is up: {names}" if names else "A VPN is up"


def vpn_hint(interfaces):
    """What a timed-out connect or pairing gets appended while a tunnel
    interface is up: the phone may be fine and the VPN in the way."""
    if not interfaces:
        return ""
    names = ", ".join(clean(n, 32) for n in interfaces)
    return f" · a VPN is up ({names}); if it isolates the LAN, nothing here reaches the phone"


def service_detail(kind, address):
    """`Pairing · 192.168.1.5:37123` / `Wireless debugging · 192.168.1.5:41235`:
    the line under an mDNS service on the Wireless page."""
    return f"{SERVICE_TEXT.get(kind, clean(kind))} · {clean(address)}"


def connected_notice(address):
    return f"Connected over Wi-Fi: {clean(address)}"


def disconnected_notice(address):
    return f"Disconnected: {clean(address)}"


def paired_notice(label):
    return f"Paired with {clean(label)}"


def go_wireless_notice(address):
    return f"Now over Wi-Fi: {clean(address)} · the cable can come out"


def usb_notice(label):
    return f"Back to USB: {clean(label)}"


def window_text(seconds):
    """`2 minutes`, `90 seconds`: how long a pairing code is shown."""
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        return "a while"
    if s >= 120 and s % 60 == 0:
        return f"{s // 60} minutes"
    return f"{s} seconds"


ADB_SOURCES = {
    "override": "from OMARCHY_ANDROID_DEV_PATH",
    "setting": "from the adbPath setting",
    "env": "from the SDK in $ANDROID_HOME or $ANDROID_SDK_ROOT",
    "home": "found in ~/Android/Sdk",
    "path": "found on PATH",
}


def adb_source_text(source):
    return ADB_SOURCES.get(str(source or ""), "found")


def display_path(path):
    """`~/Downloads` for a path under the home directory, the path itself
    otherwise. The separator is required: `/home/costa-backup/apks` is not
    under `/home/costa`, and since 1.6.0 a display path goes back into the
    APKs page's folder box, where `expanduser` has to return what came in."""
    home = os.path.expanduser("~")
    p = str(path or "")
    if home and (p == home or p.startswith(home + os.sep)):
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
