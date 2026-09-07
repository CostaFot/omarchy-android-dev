"""The hardware keys: `adb shell input keyevent CODE` by name. The strip
the plugin draws beside the scrcpy window presses these (scrcpy has them
as Mod shortcuts and shows nothing on screen), and `key NAME` gives each
one an IPC verb for a keybinding. `wake` and `sleep` are the two the
strip does not show: a phone asleep answers no mDNS query, so a script
can wake it before pairing; sleep is what Power does on a phone that is
awake, without the toggle."""

from .adb import AdbError

# name → (Android KeyEvent code, the label the notice and the strip use)
KEYS = {
    "back": (4, "Back"),
    "home": (3, "Home"),
    "recents": (187, "Recents"),
    "power": (26, "Power"),
    "volup": (24, "Volume up"),
    "voldown": (25, "Volume down"),
    "wake": (224, "Wake"),
    "sleep": (223, "Sleep"),
}
NAMES = list(KEYS)


def press(adb, serial, name):
    """One `input keyevent`; the answer names the key. An unknown name is
    bad_args before adb runs."""
    if name not in KEYS:
        raise AdbError("bad_args", "key takes one of: " + " ".join(NAMES))
    code, label = KEYS[name]
    try:
        adb.shell(serial, "input", "keyevent", str(code), timeout=10)
    except AdbError as e:
        raise AdbError(e.code, f"Could not press {label}: {e.message}", e.stderr) from e
    return {"notice": f"{label} pressed", "key": name, "keycode": code, "label": label}
