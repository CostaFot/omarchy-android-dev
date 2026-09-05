"""`bin/omarchy-android-dev` — the contract between the QML plugin and adb.

    omarchy-android-dev [--settings '<json>'] [--serial S] <command> [args...]

Every invocation prints exactly ONE line of JSON and exits 0, even when it
failed: errors ride inside the document under `error`. `track` is the
streaming exception: one JSON line per event, still never a traceback.
A helper that could exit non-zero or print a traceback would be a helper
that can blank the bar.

Envelope: schema_version, command, ok, error, generated_at, adb{path,
source}, selected, then the command's own payload. See AGENTS.md for the
per-command shapes.
"""

import json
import os
import signal
import sys
import threading
import time

from . import PLUGIN_ID, actions, adb as adbmod, capture, devices as devmod, fmt, packages as pkgmod, plugin_version, toggles as togmod
from .adb import Adb, AdbError, PartialError
from .state import State

SCHEMA_VERSION = 1

SETTING_DEFAULTS = {
    "adbPath": "",
    "screenshotDir": "",
    "apkDir": "~/Downloads",
    "scrcpyArgs": "",
    "notify": True,
    "deviceNotifications": True,
    "confirmUninstall": True,
    "showSystemApps": False,
}

HELP = [
    ("status", "adb path and source, devices, selected device, last package, recent deep links, tools, versions"),
    ("devices", "attached devices with labels; the selected one marked"),
    ("select SERIAL", "remember SERIAL as the selected device"),
    ("track", "stream one JSON line per device change (adb track-devices)"),
    ("packages", "installed packages: Foreground, Running, Debuggable, Other"),
    ("package PKG", "version, debuggable, launcher activity, runtime permissions"),
    ("app launch|restart|force-stop|kill|clear|clear-restart|uninstall PKG", "the per-package actions"),
    ("perms grant|revoke PKG", "grant or revoke every runtime permission"),
    ("deeplink URL [PKG]", "am start -a VIEW -d URL, scoped to PKG when given"),
    ("screenshot", "screencap to the pictures dir, clipboard and a notification"),
    ("toggles", "the eight developer toggles with their state"),
    ("toggle NAME [on|off]", "flip (or set) animations, touches, pointer, layout, airplane, wifi, data, bluetooth"),
    ("help", "this list"),
]


class BadArgs(Exception):
    pass


class Deadline(BaseException):
    """The whole-process budget ran out. A BaseException so no `except
    Exception` on the way up can swallow it."""


_TRUE_WORDS = ("true", "1", "yes", "on")
_FALSE_WORDS = ("false", "0", "no", "off", "")


def coerce_setting(default, value):
    """A setting takes the type of its default. `omarchy bar set ID KEY false`
    without --json stores the string "false", so a boolean accepts the
    words as well as a JSON boolean; anything else keeps the default."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        word = str(value).strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
        return default
    if isinstance(value, (str, int, float)):
        return str(value)
    return default


class Settings:
    """Whitelisted scalars from the plugin's shell.json entry, passed by the
    store as `--settings '<json>'`; unknown keys are ignored."""

    def __init__(self, overrides=None):
        self.values = dict(SETTING_DEFAULTS)
        for key, value in (overrides or {}).items():
            if key in SETTING_DEFAULTS and value is not None:
                self.values[key] = coerce_setting(SETTING_DEFAULTS[key], value)

    def get(self, key, fallback=None):
        return self.values.get(key, fallback)


def total_budget():
    try:
        return float(os.environ.get("OMARCHY_ANDROID_DEV_TOTAL_BUDGET") or 60)
    except ValueError:
        return 60.0


def _arm_deadline():
    budget = total_budget()
    if budget <= 0 or not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        return lambda: None

    def on_alarm(signum, frame):
        raise Deadline(budget)

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, budget)

    def disarm():
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

    return disarm


def envelope(command, ok=True, error=None, adb=None, **payload):
    doc = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "ok": bool(ok),
        "error": error,
        "generated_at": int(time.time()),
        "adb": adb or {"path": None, "source": None},
    }
    doc.update(payload)
    return doc


def _parse_global(argv):
    overrides = {}
    serial = None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--settings" or a.startswith("--settings="):
            raw = argv[i + 1] if a == "--settings" else a[len("--settings="):]
            if a == "--settings":
                if i + 1 >= len(argv):
                    raise BadArgs("--settings needs a JSON argument")
                i += 1
            try:
                parsed = json.loads(raw)
            except ValueError as e:
                raise BadArgs(f"--settings is not valid JSON: {e}") from e
            if not isinstance(parsed, dict):
                raise BadArgs("--settings must be a JSON object")
            overrides.update(parsed)
        elif a == "--serial" or a.startswith("--serial="):
            serial = argv[i + 1] if a == "--serial" else a[len("--serial="):]
            if a == "--serial":
                if i + 1 >= len(argv):
                    raise BadArgs("--serial needs a value")
                i += 1
            if not devmod.valid_serial(serial):
                raise BadArgs("--serial is not a device serial")
        else:
            rest.append(a)
        i += 1
    return Settings(overrides), serial, rest


class Context:
    def __init__(self, settings, serial):
        self.settings = settings
        self.explicit_serial = serial
        self.state = State()
        path, source = adbmod.resolve(settings)
        self.adb = Adb(path, source, self.state) if path else None
        self._devices = None

    def adb_info(self):
        return self.adb.describe() if self.adb else {"path": None, "source": None}

    def require_adb(self):
        if not self.adb:
            raise AdbError("no_adb", "No adb found. Set adbPath in the plugin settings, or install the android-tools package or the SDK platform-tools")
        self.adb.ensure_server()
        return self.adb

    def devices(self, refresh=False):
        if self._devices is None or refresh:
            self._devices = devmod.list_devices(self.require_adb())
            devmod.mark_selected(self._devices, self.selected())
        return self._devices

    def selected(self):
        """The serial the payload reports: explicit, else remembered-if-attached, else the only one."""
        if self._devices is None:
            self.devices()
        try:
            return devmod.resolve_serial(self._devices, self.explicit_serial, self.state.selected)
        except AdbError:
            return None

    def device(self):
        """(adb, serial) for a device command, or raises no_device / many_devices / unauthorized / offline."""
        adb = self.require_adb()
        serial = devmod.resolve_serial(self.devices(), self.explicit_serial, self.state.selected)
        devmod.require_ready(self.devices(), serial)
        return adb, serial


# ---- commands --------------------------------------------------------------

def _tool(path):
    return {"found": bool(path), "path": path}


def _which(name):
    import shutil
    return shutil.which(name)


def cmd_status(ctx, args):
    adb = ctx.adb
    root = adbmod.sdk_root(adb.path) if adb else None
    emulator = os.path.join(root, "emulator", "emulator") if root else None
    if not (emulator and os.access(emulator, os.X_OK)):
        emulator = _which("emulator")
    payload = {
        "version": plugin_version(),
        "python": sys.version.split()[0],
        "state_dir": ctx.state.dir,
        "state_dir_text": fmt.display_path(ctx.state.dir) if ctx.state.dir else None,
        "tools": {
            "scrcpy": _tool(_which("scrcpy")),
            "emulator": _tool(emulator),
            "terminal": _tool(_which("xdg-terminal-exec")),
            "wl_copy": _tool(_which("wl-copy")),
        },
        "devices": [],
        "selected": None,
        "last_package": None,
        "recent_deeplinks": ctx.state.recent_deeplinks,
    }
    try:
        ctx.require_adb()
        payload["adb_version"] = adb.version()
        payload["devices"] = ctx.devices()
        payload["selected"] = ctx.selected()
        if payload["selected"]:
            payload["last_package"] = ctx.state.last_package(payload["selected"])
    except AdbError as e:
        raise PartialError(payload, e) from e
    return payload


def cmd_devices(ctx, args):
    return {"devices": ctx.devices(), "selected": ctx.selected()}


def cmd_select(ctx, args):
    if len(args) != 1 or not devmod.valid_serial(args[0]):
        raise BadArgs("select SERIAL")
    serial = args[0]
    devices = ctx.devices()
    if serial not in [d["serial"] for d in devices]:
        raise AdbError("no_device", f"Device {serial} is not attached")
    ctx.state.select(serial)
    devmod.mark_selected(devices, serial)
    ctx.explicit_serial = serial
    label = next((d["label"] for d in devices if d["serial"] == serial), serial)
    return {"devices": devices, "selected": serial, "notice": f"Selected {label}"}


def cmd_packages(ctx, args):
    adb, serial = ctx.device()
    payload = pkgmod.list_packages(adb, serial, ctx.state, ctx.settings)
    payload["last_package"] = ctx.state.last_package(serial)
    return payload


def _package_arg(args, usage):
    if len(args) < 1 or not pkgmod.valid_package(args[-1]):
        raise BadArgs(usage)
    return args[-1]


def cmd_package(ctx, args):
    pkg = _package_arg(args, "package PKG")
    adb, serial = ctx.device()
    return pkgmod.package_info(adb, serial, ctx.state, pkg)


def cmd_app(ctx, args):
    if len(args) != 2 or args[0] not in actions.ACTIONS:
        raise BadArgs("app " + "|".join(actions.ACTIONS) + " PKG")
    pkg = _package_arg(args, "app ACTION PKG")
    adb, serial = ctx.device()
    payload = actions.ACTIONS[args[0]](adb, serial, pkg)
    payload["action"] = args[0]
    payload["package"] = pkg
    if args[0] != "uninstall":
        ctx.state.set_last_package(serial, pkg)
    return payload


def cmd_perms(ctx, args):
    if len(args) != 2 or args[0] not in ("grant", "revoke"):
        raise BadArgs("perms grant|revoke PKG")
    pkg = _package_arg(args, "perms grant|revoke PKG")
    adb, serial = ctx.device()
    payload = (actions.grant_all if args[0] == "grant" else actions.revoke_all)(adb, serial, pkg)
    payload["package"] = pkg
    ctx.state.set_last_package(serial, pkg)
    return payload


def cmd_deeplink(ctx, args):
    if len(args) not in (1, 2):
        raise BadArgs("deeplink URL [PKG]")
    url = args[0]
    pkg = args[1] if len(args) == 2 else None
    if pkg and not pkgmod.valid_package(pkg):
        raise BadArgs("deeplink URL [PKG]")
    if not actions.valid_url(url):
        raise BadArgs("Enter a URL with a scheme, such as https://example.com or myapp://open")
    adb, serial = ctx.device()
    payload = actions.deeplink(adb, serial, url, pkg)
    ctx.state.add_deeplink(url)
    payload["recent_deeplinks"] = ctx.state.recent_deeplinks
    return payload


def cmd_screenshot(ctx, args):
    adb, serial = ctx.device()
    return capture.screenshot(adb, serial, ctx.settings)


def cmd_toggles(ctx, args):
    adb, serial = ctx.device()
    return togmod.read_all(adb, serial)


def cmd_toggle(ctx, args):
    if len(args) not in (1, 2) or args[0] not in togmod.NAMES:
        raise BadArgs("toggle " + "|".join(togmod.NAMES) + " [on|off]")
    want = None
    if len(args) == 2:
        if args[1] not in ("on", "off"):
            raise BadArgs("toggle NAME [on|off]")
        want = args[1] == "on"
    adb, serial = ctx.device()
    return togmod.flip(adb, serial, args[0], want)


def cmd_help(ctx, args):
    return {"commands": [{"usage": u, "text": t} for u, t in HELP], "text": help_text()}


def help_text():
    return "omarchy-android-dev [--settings JSON] [--serial S] <command> [args]\n" + "\n".join(f"  {u:<70} {t}" for u, t in HELP)


COMMANDS = {
    "status": cmd_status,
    "devices": cmd_devices,
    "select": cmd_select,
    "packages": cmd_packages,
    "package": cmd_package,
    "app": cmd_app,
    "perms": cmd_perms,
    "deeplink": cmd_deeplink,
    "screenshot": cmd_screenshot,
    "toggles": cmd_toggles,
    "toggle": cmd_toggle,
    "help": cmd_help,
}


def _finish(ctx, command, payload, ok=True, error=None):
    try:
        ctx.state.save()
    except OSError as e:
        if error is None:
            error = {"code": "state_corrupt", "message": f"Could not write the state file: {e.strerror}"}
    if error is None and ctx.state.error:
        error = {"code": "state_corrupt", "message": ctx.state.error}
    elif error is None and ctx.state.problems:
        error = {"code": "state_corrupt", "message": ctx.state.problems[0]}
    doc = envelope(command, ok=ok, error=error, adb=ctx.adb_info(), **payload)
    if "selected" not in doc and ctx._devices is not None:
        doc["selected"] = ctx.selected()
    return doc


def _timeout_error(budget):
    return {"code": "timeout", "message": f"The Android Dev helper ran out of time ({budget:.0f} s)"}


def dispatch(argv, disarm):
    settings, serial, rest = _parse_global(list(argv))
    if not rest or rest[0] in ("-h", "--help"):
        raise BadArgs(help_text())
    command, args = rest[0], rest[1:]
    if command == "track":
        disarm()  # streams forever by design
        ctx = Context(settings, serial)
        if not ctx.adb:
            doc = envelope("track", ok=False, error=AdbError("no_adb", "No adb found. Set adbPath in the plugin settings, or install the android-tools package or the SDK platform-tools").to_dict(), event="error")
            emit(doc)
            return None
        try:
            devmod.track(ctx.adb, ctx.state)
        except AdbError as e:
            emit(envelope("track", ok=False, error=e.to_dict(), adb=ctx.adb_info(), event="error"))
        return None
    handler = COMMANDS.get(command)
    if handler is None:
        raise BadArgs(f"unknown command '{command}'\n{help_text()}")
    ctx = Context(settings, serial)
    try:
        payload = handler(ctx, args)
    except BadArgs:
        raise
    except AdbError as e:
        extra = dict(getattr(e, "payload", None) or {})
        if command in ("devices", "status") and ctx._devices is not None:
            extra["devices"] = ctx._devices
        if e.code == "no_adb" and command in ("devices", "status"):
            extra.setdefault("devices", [])
            extra["selected"] = None
        return _finish(ctx, command, extra, ok=False, error=e.to_dict())
    except Deadline as e:
        return _finish(ctx, command, {}, ok=False, error=_timeout_error(e.args[0]))
    return _finish(ctx, command, payload)


def emit(doc):
    line = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        pass


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    command = "?"
    disarm = _arm_deadline()
    doc = None
    try:
        skip = False
        for a in argv:
            if skip:
                skip = False
                continue
            if a in ("--settings", "--serial"):
                skip = True
                continue
            if a.startswith("--"):
                continue
            command = a
            break
        doc = dispatch(argv, disarm)
    except BadArgs as e:
        doc = envelope(command, ok=False, error={"code": "bad_args", "message": str(e)})
    except Deadline as e:
        doc = envelope(command, ok=False, error=_timeout_error(e.args[0]))
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 — the never-crash rule
        doc = envelope(command, ok=False, error={"code": "internal", "message": f"{type(e).__name__}: {e}"})
        if os.environ.get("OMARCHY_ANDROID_DEV_DEBUG"):
            import traceback
            traceback.print_exc()
    finally:
        disarm()
    if doc is not None:
        emit(doc)
    return 0
