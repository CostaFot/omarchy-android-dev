"""scrcpy, the emulator's AVDs and logcat in a terminal: the things the
plugin starts and then leaves alone.

Every launch here is detached (its own session, stdin/stdout/stderr on
/dev/null, SIGINT back at its default) and, when `uwsm-app` is present,
wrapped in it the way Omarchy's own launchers are, so the window gets its
own scope and outlives the helper and the shell. Nothing launched here is
ever signalled by the plugin: an emulator stops through `adb emu kill`,
which the emulator handles itself; scrcpy and the terminal are closed by
the user. The helper only waits half a second to catch a tool that fails
at once.

scrcpy runs with `ADB` set to the adb the helper resolved, so it talks to
the same binary and server as everything else here: the `scrcpy` package
depends on `android-tools`, which puts a second adb on PATH, and scrcpy
would otherwise pick that one.

Test knobs: OMARCHY_ANDROID_DEV_SCRCPY / _EMULATOR / _TERMINAL / _QRENCODE name the
binaries (a non-executable value means "not installed"), and
OMARCHY_ANDROID_DEV_LAUNCHER replaces `uwsm-app` (an empty value runs the
tool directly).
"""

import os
import re
import shutil
import subprocess
import time

from . import APP_NAME, fmt, notify
from .adb import AdbError, _debug, run_bounded, sdk_root

AVD_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
LIST_AVDS_TIMEOUT = 15
LAUNCH_GRACE = 0.5


def _override(var, find):
    value = os.environ.get(var)
    if value is not None:
        return value if value and os.path.isfile(value) and os.access(value, os.X_OK) else None
    return find()


def _executable(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def scrcpy_path():
    return _override("OMARCHY_ANDROID_DEV_SCRCPY", lambda: shutil.which("scrcpy"))


def emulator_path(adb_path=None):
    """The SDK's emulator next to adb's platform-tools, else the home SDK's,
    else PATH."""
    def find():
        root = sdk_root(adb_path) if adb_path else None
        candidates = []
        if root:
            candidates.append(os.path.join(root, "emulator", "emulator"))
        candidates.append(os.path.join(os.path.expanduser("~"), "Android", "Sdk", "emulator", "emulator"))
        for c in candidates:
            if _executable(c):
                return c
        return shutil.which("emulator")
    return _override("OMARCHY_ANDROID_DEV_EMULATOR", find)


def terminal_path():
    return _override("OMARCHY_ANDROID_DEV_TERMINAL", lambda: shutil.which("xdg-terminal-exec"))


def qrencode_path():
    """`qrencode` draws the Wi-Fi pairing code (wireless.py); it is in
    Omarchy's base package set."""
    return _override("OMARCHY_ANDROID_DEV_QRENCODE", lambda: shutil.which("qrencode"))


def launcher_path():
    """`uwsm-app`, Omarchy's way of giving a launched app its own scope;
    None runs the tool directly."""
    value = os.environ.get("OMARCHY_ANDROID_DEV_LAUNCHER")
    if value is not None:
        return value if _executable(value) else None
    return shutil.which("uwsm-app")


def tool(path):
    return {"found": bool(path), "path": path}


def find_all(adb_path=None):
    """The `tools` block of `status` and `tools`."""
    return {
        "scrcpy": tool(scrcpy_path()),
        "emulator": tool(emulator_path(adb_path)),
        "terminal": tool(terminal_path()),
        "wl_copy": tool(notify.wl_copy_path()),
        "wl_paste": tool(notify.wl_paste_path()),
        "qrencode": tool(qrencode_path()),
    }


# ---- AVDs -------------------------------------------------------------------

def parse_avd_list(text):
    """`emulator -list-avds`: one name per line; anything that is not a
    name (an `INFO |` line on newer emulators) is dropped."""
    out = []
    for line in fmt.lines(text):
        name = line.strip()
        if AVD_RE.match(name) and name not in out:
            out.append(name)
    return fmt.cap_list(out, fmt.MAX_AVDS)


def list_avds(emulator):
    if not emulator:
        return []
    try:
        result = run_bounded([emulator, "-list-avds"], timeout=LIST_AVDS_TIMEOUT)
    except AdbError as e:
        raise AdbError("no_tool", f"emulator -list-avds failed: {e.message}", e.stderr) from e
    if result.code != 0:
        raise AdbError("no_tool", "emulator -list-avds failed" + (f": {result.stderr}" if result.stderr else f" (exit {result.code})"), result.stderr)
    return parse_avd_list(result.text)


def running_avds(devices):
    """AVD name → serial for every ready emulator in a device list."""
    out = {}
    for d in devices or []:
        if d.get("kind") == "emulator" and d.get("state") == "device" and d.get("avd"):
            out.setdefault(d["avd"], d["serial"])
    return out


def describe(adb_path, settings, devices, avds=None):
    """The `tools` payload: what is installed, the AVDs with Running or
    Stopped, the scrcpy arguments the settings add (`scrcpy_args`, what
    `tool scrcpy` appends: the screen-off flags, then scrcpyArgs)."""
    found = find_all(adb_path)
    emulator = found["emulator"]["path"]
    names = avds if avds is not None else (list_avds(emulator) if emulator else [])
    running = running_avds(devices)
    rows = []
    for name in names:
        serial = running.get(name)
        rows.append({
            "name": name,
            "running": serial is not None,
            "serial": serial,
            "detail": fmt.avd_detail(serial),
        })
    return {
        "tools": found,
        "avds": rows,
        "avd_count": len(rows),
        "scrcpy_args": fmt.clean(" ".join(scrcpy_extra_args(settings))),
        "screen_off": bool(settings.get("mirrorScreenOff")),
    }


# ---- launching ---------------------------------------------------------------

def _reset_signals():
    import signal
    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except (OSError, ValueError):
        pass


def launch(argv, name, env=None):
    """Start argv detached and make sure it survived its first moments.
    `env` adds variables to the tool's environment. Returns nothing; raises
    AdbError(no_tool) when it could not start or exited at once."""
    launcher = launcher_path()
    full = ([launcher, "--"] if launcher else []) + list(argv)
    _debug("launch " + " ".join(full))
    environ = dict(os.environ, **env) if env else None
    try:
        proc = subprocess.Popen(full, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                close_fds=True, start_new_session=True, preexec_fn=_reset_signals, env=environ)
    except OSError as e:
        raise AdbError("no_tool", f"Cannot start {name}: {e.strerror}") from e
    try:
        proc.wait(timeout=LAUNCH_GRACE)
    except subprocess.TimeoutExpired:
        return
    if proc.returncode != 0:
        raise AdbError("no_tool", f"{name} exited at once (code {proc.returncode})")


# What the mirrorScreenOff setting adds: the device's own screen goes dark
# while the mirror runs (scrcpy turns it back on when it exits) and, plugged
# in, the device stays awake; the user's scrcpyArgs follow so they win.
SCREEN_OFF_ARGS = ["--turn-screen-off", "--stay-awake"]


def scrcpy_extra_args(settings):
    flags = list(SCREEN_OFF_ARGS) if settings.get("mirrorScreenOff") else []
    return flags + str(settings.get("scrcpyArgs") or "").split()


def scrcpy(serial, settings, label=None, adb_path=None):
    path = scrcpy_path()
    if not path:
        raise AdbError("no_tool", "scrcpy is not installed")
    argv = [path, "-s", serial, "--window-title", APP_NAME] + scrcpy_extra_args(settings)
    launch(argv, "scrcpy", env={"ADB": adb_path} if adb_path else None)
    return {"notice": f"scrcpy started: {label or serial}", "argv": argv[1:]}


# A cold boot: the emulator starts the system fresh instead of resuming
# the AVD's saved snapshot (quickboot, its default), the way out of a
# snapshot that misbehaves. The snapshot is saved again on exit as usual.
COLD_BOOT_ARGS = ["-no-snapshot-load"]


def avd_start(emulator, name, avds, running, cold=False):
    if not emulator:
        raise AdbError("no_tool", "No emulator found next to adb, in ~/Android/Sdk or on PATH")
    if not AVD_RE.match(name or ""):
        raise AdbError("bad_args", "avd NAME")
    if name not in avds:
        raise AdbError("bad_args", f"No AVD named {name}")
    if name in running:
        raise AdbError("bad_args", f"{name} is already running ({running[name]})")
    argv = [emulator, "-avd", name] + (list(COLD_BOOT_ARGS) if cold else [])
    launch(argv, "emulator")
    return {"notice": f"Starting {name} (cold boot)" if cold else f"Starting {name}", "avd": name, "cold": bool(cold), "argv": argv[1:]}


def avd_stop(adb, serial, label=None):
    """`adb -s SERIAL emu kill`; the emulator shuts itself down."""
    try:
        adb.run(["emu", "kill"], serial=serial, timeout=10, check=False)
    except AdbError as e:
        raise AdbError(e.code, f"Could not stop the emulator: {e.message}", e.stderr) from e
    return {"notice": f"Stopping {label or serial}", "serial": serial}


def pid_of(adb, serial, pkg):
    try:
        result = adb.shell(serial, "pidof", pkg, timeout=10, check=False)
    except AdbError:
        return None
    for line in result.lines():
        for token in line.split():
            if token.isdigit():
                return int(token)
    return None


def logcat(adb, serial, pkg=None, label=None):
    """`adb -s SERIAL logcat [--pid=PID]` in the default terminal, the way
    omarchy-launch-terminal opens one (`uwsm-app -- xdg-terminal-exec`)."""
    terminal = terminal_path()
    if not terminal:
        raise AdbError("no_tool", "No terminal launcher found (xdg-terminal-exec)")
    argv = [terminal, "--title=" + APP_NAME + " · logcat" + (f" · {pkg}" if pkg else ""), adb.path, "-s", serial, "logcat"]
    if pkg:
        pid = pid_of(adb, serial, pkg)
        if pid is None:
            raise AdbError("adb_failed", f"{pkg} is not running; launch it first, then follow its log")
        argv.append(f"--pid={pid}")
    launch(argv, "the terminal")
    return {"notice": f"Logcat for {pkg} in a terminal" if pkg else f"Logcat for {label or serial} in a terminal",
            "package": pkg, "argv": argv[1:]}
