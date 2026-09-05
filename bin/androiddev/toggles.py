"""The nine developer toggles: read all in one `adb shell`, flip one with
the Windows commands verbatim (plus pointer location, Bluetooth and
SystemUI's demo mode).

The read is a single fixed shell script (no device data in it), so the
Toggles page costs one round trip instead of ten.
"""

from . import fmt
from .adb import AdbError

NAMES = ("animations", "touches", "pointer", "layout", "airplane", "wifi", "data", "bluetooth", "demo")

LABELS = {
    "animations": "Animations",
    "touches": "Show touches",
    "pointer": "Pointer location",
    "layout": "Layout bounds",
    "airplane": "Airplane mode",
    "wifi": "Wi-Fi",
    "data": "Mobile data",
    "bluetooth": "Bluetooth",
    "demo": "Demo mode",
}

_KEYS = (
    "global:window_animation_scale", "global:transition_animation_scale", "global:animator_duration_scale",
    "system:show_touches", "system:pointer_location", "global:airplane_mode_on",
    "global:wifi_on", "global:mobile_data", "global:bluetooth_on",
    "global:sysui_demo_allowed", "global:sysui_tuner_demo_on",
)

# SystemUI's demo mode (Developer options > System UI demo mode): the status
# bar with a fixed clock, a full battery and full signal, no notification
# icons; what store screenshots are taken with. `sysui_demo_allowed` is the
# gate, and every command is one broadcast to SystemUI. AOSP mirrors the
# shown state into `sysui_tuner_demo_on`; a vendor SystemUI may not (an HONOR
# phone on Android 16 keeps it at 0), so the plugin reads "on" from either
# key and clears the gate on exit, which makes its own flips read back right.
DEMO_ACTION = "com.android.systemui.demo"
DEMO_ENTER = (
    ("enter",),
    ("clock", "-e", "hhmm", "1200"),
    ("notifications", "-e", "visible", "false"),
    ("battery", "-e", "level", "100", "-e", "plugged", "false"),
    ("network", "-e", "wifi", "show", "-e", "level", "4"),
    ("network", "-e", "mobile", "show", "-e", "datatype", "none", "-e", "level", "4"),
    ("status", "-e", "bluetooth", "hide", "-e", "mute", "hide"),
)
DEMO_EXIT = (("exit",),)

READ_SCRIPT = (
    'echo api=$(getprop ro.build.version.sdk); echo layout=$(getprop debug.layout); '
    'for k in ' + " ".join(_KEYS) + '; do echo "$k=$(settings get ${k%%:*} ${k#*:})"; done'
)


def parse_read(text):
    raw = {}
    for line in fmt.lines(text):
        key, sep, value = line.strip().partition("=")
        if sep:
            raw[key] = fmt.clean(value, 64)
    return raw


def _is_on(value, default=None):
    v = (value or "").strip().lower()
    if v in ("", "null"):
        return default
    if v in ("1", "true", "on"):
        return True
    if v in ("0", "false", "off"):
        return False
    return None


def _scale_on(value):
    """Animations are on unless the scale is 0 (`null` = never set = 1.0)."""
    v = (value or "").strip().lower()
    if v in ("", "null"):
        return True
    try:
        return float(v) != 0.0
    except ValueError:
        return None


def states(raw):
    on = {
        "animations": _scale_on(raw.get("global:window_animation_scale")),
        "touches": _is_on(raw.get("system:show_touches"), default=False),
        "pointer": _is_on(raw.get("system:pointer_location"), default=False),
        "layout": _is_on(raw.get("layout"), default=False),
        "airplane": _is_on(raw.get("global:airplane_mode_on"), default=False),
        "wifi": _is_on(raw.get("global:wifi_on")),
        "data": _is_on(raw.get("global:mobile_data")),
        "bluetooth": _is_on(raw.get("global:bluetooth_on")),
        "demo": bool(_is_on(raw.get("global:sysui_tuner_demo_on"), default=False)
                     or _is_on(raw.get("global:sysui_demo_allowed"), default=False)),
    }
    return {name: {"on": on[name], "text": fmt.on_off(on[name]), "label": LABELS[name]} for name in NAMES}


def api_level(raw):
    try:
        return int(raw.get("api") or 0)
    except ValueError:
        return 0


def read_all(adb, serial):
    raw = parse_read(adb.shell(serial, READ_SCRIPT).text)
    return {"toggles": states(raw), "api": api_level(raw)}


def _put(adb, serial, namespace, key, value):
    adb.shell(serial, "settings", "put", namespace, key, value)


def _demo(adb, serial, command):
    adb.shell(serial, "am", "broadcast", "-a", DEMO_ACTION, "-e", "command", *command)


def flip(adb, serial, name, want=None):
    """Set toggle `name` to `want` (True/False), or the opposite of its
    current state when `want` is None. Returns the fresh toggles."""
    if name not in NAMES:
        raise AdbError("bad_args", f"Unknown toggle '{name}'; one of {', '.join(NAMES)}")
    before = read_all(adb, serial)
    current = before["toggles"][name]["on"]
    target = (not current) if want is None else bool(want)
    label = LABELS[name]
    try:
        if name == "animations":
            value = "1" if target else "0"
            for key in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
                _put(adb, serial, "global", key, value)
        elif name == "touches":
            _put(adb, serial, "system", "show_touches", "1" if target else "0")
        elif name == "pointer":
            _put(adb, serial, "system", "pointer_location", "1" if target else "0")
        elif name == "layout":
            adb.shell(serial, "setprop", "debug.layout", "true" if target else "false")
            adb.shell(serial, "service", "call", "activity", "1599295570")
        elif name == "airplane":
            if before["api"] >= 30:
                adb.shell(serial, "cmd", "connectivity", "airplane-mode", "enable" if target else "disable")
            else:
                _put(adb, serial, "global", "airplane_mode_on", "1" if target else "0")
                adb.shell(serial, "am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "true" if target else "false")
        elif name == "wifi":
            adb.shell(serial, "svc", "wifi", "enable" if target else "disable")
        elif name == "data":
            adb.shell(serial, "svc", "data", "enable" if target else "disable")
        elif name == "bluetooth":
            adb.shell(serial, "svc", "bluetooth", "enable" if target else "disable")
        elif name == "demo":
            if target:
                _put(adb, serial, "global", "sysui_demo_allowed", "1")
                for command in DEMO_ENTER:
                    _demo(adb, serial, command)
            else:
                for command in DEMO_EXIT:
                    _demo(adb, serial, command)
                _put(adb, serial, "global", "sysui_demo_allowed", "0")
    except AdbError as e:
        raise AdbError(e.code, f"Failed to set {label.lower()}: {e.message}", e.stderr) from e
    after = read_all(adb, serial)
    return {"notice": f"{label} {fmt.on_off(target)}", "toggle": name, "on": target, "toggles": after["toggles"], "api": after["api"]}
