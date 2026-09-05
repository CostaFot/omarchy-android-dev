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

from . import PLUGIN_ID, actions, adb as adbmod, apk as apkmod, capture, devices as devmod, fmt, packages as pkgmod, plugin_version, text as textmod, toggles as togmod, tools as toolsmod, wireless as wlmod
from .adb import Adb, AdbError, PartialError
from .state import State

SCHEMA_VERSION = 1

SETTING_DEFAULTS = {
    "adbPath": "",
    "screenshotDir": "",
    "recordingDir": "",
    "apkDir": "~/Downloads",
    "scrcpyArgs": "",
    "mirrorScreenOff": False,
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
    ("record", "screenrecord on the device until Ctrl-C (or its 3 min limit), then pull to the videos dir"),
    ("toggles", "the nine developer toggles with their state"),
    ("toggle NAME [on|off]", "flip (or set) animations, touches, pointer, layout, airplane, wifi, data, bluetooth, demo"),
    ("apk list [DIR]", "the .apk files in DIR (default: the apkDir setting)"),
    ("apk install PATH...", "adb install -r -t, one file after another"),
    ("text send TEXT", "type TEXT on the device (input text; one line of ASCII)"),
    ("text clipboard", "type the clipboard (wl-paste) on the device"),
    ("tools", "scrcpy, emulator and terminal found or not; the AVDs with Running or Stopped"),
    ("tool scrcpy", "mirror the selected device (scrcpy -s SERIAL --window-title, --turn-screen-off --stay-awake with mirrorScreenOff, plus scrcpyArgs)"),
    ("tool avd NAME", "start that AVD (refused while it runs)"),
    ("tool avd-stop SERIAL", "stop a running emulator (adb emu kill)"),
    ("tool logcat [PKG]", "adb logcat in a terminal, following PKG's process when given"),
    ("wireless", "mDNS yes or no, the pairing and connect services on the network, the Wi-Fi and plugged devices"),
    ("pair qr", "streaming: a pairing QR code as a PNG, then wait for the phone to scan it and pair (Ctrl-C cancels)"),
    ("pair code ADDR", "pair with the address and six-digit code from Pair device with pairing code; the code is read from stdin, never argv"),
    ("connect ADDR", "adb connect host[:port] (5555 without a port), then wait until the device is ready"),
    ("disconnect ADDR", "adb disconnect host[:port]"),
    ("tcpip [USBSERIAL]", "go wireless: adb tcpip 5555 on the plugged phone, connect to its Wi-Fi address and select that entry"),
    ("usb [SERIAL]", "back to USB: adb usb; the Wi-Fi entry drops"),
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
        return self.adb.describe() if self.adb else {"path": None, "source": None, "path_text": None, "source_text": None, "text": None}

    def no_adb(self):
        return AdbError("no_adb", adbmod.missing_text(self.settings))

    def require_adb(self):
        if not self.adb:
            raise self.no_adb()
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

def cmd_status(ctx, args):
    adb = ctx.adb
    payload = {
        "version": plugin_version(),
        "python": sys.version.split()[0],
        "state_dir": ctx.state.dir,
        "state_dir_text": fmt.display_path(ctx.state.dir) if ctx.state.dir else None,
        "tools": toolsmod.find_all(adb.path if adb else None),
        "apk_dir": apkmod.apk_dir(ctx.settings),
        "apk_dir_text": fmt.display_path(apkmod.apk_dir(ctx.settings)),
        "screenshot_dir": capture.screenshot_dir(ctx.settings),
        "screenshot_dir_text": fmt.display_path(capture.screenshot_dir(ctx.settings)),
        "recording_dir": capture.recording_dir(ctx.settings),
        "recording_dir_text": fmt.display_path(capture.recording_dir(ctx.settings)),
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


def cmd_record(ctx, args, emit_doc):
    """Streaming like `track`: the `recording` event, then the final
    document, every one a full envelope."""
    if args:
        raise BadArgs("record")
    adb, serial = ctx.device()
    label = next((d["label"] for d in ctx.devices() if d["serial"] == serial), serial)

    def send(payload):
        emit_doc(envelope("record", ok=True, adb=ctx.adb_info(), selected=serial, **payload))

    send(capture.record(adb, serial, ctx.settings, send, device_label=label))


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


def cmd_apk(ctx, args):
    usage = "apk list [DIR] | apk install PATH..."
    if not args:
        raise BadArgs(usage)
    if args[0] == "list":
        if len(args) > 2:
            raise BadArgs(usage)
        return apkmod.list_apks(apkmod.apk_dir(ctx.settings, args[1] if len(args) == 2 else None))
    if args[0] == "install":
        if len(args) < 2:
            raise BadArgs(usage)
        paths = [apkmod.check_path(p) for p in args[1:]]
        adb, serial = ctx.device()
        return apkmod.install(adb, serial, paths)
    raise BadArgs(usage)


def cmd_text(ctx, args):
    usage = "text send TEXT | text clipboard"
    if len(args) == 2 and args[0] == "send":
        text, source = args[1], "text"
    elif args == ["clipboard"]:
        text, source = textmod.clipboard_text(), "clipboard"
    else:
        raise BadArgs(usage)
    textmod.check(text)
    adb, serial = ctx.device()
    return textmod.send(adb, serial, text, source)


def _device_label(ctx, serial):
    return next((d["label"] for d in (ctx._devices or []) if d["serial"] == serial), serial)


def cmd_tools(ctx, args):
    """What is installed and the AVDs. Works without adb (nothing is
    Running then, and `no_adb` rides in the envelope)."""
    if args:
        raise BadArgs("tools")
    adb_path = ctx.adb.path if ctx.adb else None
    try:
        devices = ctx.devices()
    except AdbError as e:
        raise PartialError(toolsmod.describe(adb_path, ctx.settings, []), e) from e
    return toolsmod.describe(adb_path, ctx.settings, devices)


def cmd_tool(ctx, args):
    usage = "tool scrcpy | tool avd NAME | tool avd-stop SERIAL | tool logcat [PKG]"
    if not args:
        raise BadArgs(usage)
    sub = args[0]
    if sub == "scrcpy":
        if len(args) != 1:
            raise BadArgs(usage)
        adb, serial = ctx.device()
        return toolsmod.scrcpy(serial, ctx.settings, _device_label(ctx, serial), adb.path)
    if sub == "avd":
        if len(args) != 2 or not toolsmod.AVD_RE.match(args[1]):
            raise BadArgs("tool avd NAME")
        emulator = toolsmod.emulator_path(ctx.adb.path if ctx.adb else None)
        avds = toolsmod.list_avds(emulator)
        try:
            running = toolsmod.running_avds(ctx.devices())
        except AdbError:
            running = {}
        return toolsmod.avd_start(emulator, args[1], avds, running)
    if sub == "avd-stop":
        if len(args) != 2 or not devmod.valid_serial(args[1]):
            raise BadArgs("tool avd-stop SERIAL")
        adb = ctx.require_adb()
        devices = ctx.devices()
        target = next((d for d in devices if d["serial"] == args[1]), None)
        if target is None:
            raise AdbError("no_device", f"Device {args[1]} is not attached")
        if target["kind"] != "emulator":
            raise AdbError("bad_args", f"{args[1]} is not an emulator")
        return toolsmod.avd_stop(adb, args[1], target["label"])
    if sub == "logcat":
        if len(args) > 2:
            raise BadArgs("tool logcat [PKG]")
        pkg = args[1] if len(args) == 2 else None
        if pkg is not None and not pkgmod.valid_package(pkg):
            raise BadArgs("tool logcat [PKG]")
        adb, serial = ctx.device()
        payload = toolsmod.logcat(adb, serial, pkg, _device_label(ctx, serial))
        if pkg:
            ctx.state.set_last_package(serial, pkg)
        return payload
    raise BadArgs(usage)


def cmd_wireless(ctx, args):
    """The Wireless page's document. Works without adb (`no_adb` rides
    along, the lists empty)."""
    if args:
        raise BadArgs("wireless")
    try:
        devices = ctx.devices()
    except AdbError as e:
        raise PartialError(wlmod.describe(ctx.adb if ctx.adb and e.code != "no_adb" else None, ctx.state, []), e) from e
    return wlmod.describe(ctx.adb, ctx.state, devices)


def _with_devices(ctx, payload, selected=None):
    """The fresh device list rides in the answer (the store replaces its
    own from it, ahead of the tracker's next frame)."""
    if selected:
        ctx.explicit_serial = selected
    payload["devices"] = ctx.devices(refresh=True)
    return payload


def cmd_pair(ctx, args):
    """`pair code ADDR`; `pair qr` is the streaming command dispatch() takes."""
    if len(args) != 2 or args[0] != "code":
        raise BadArgs("pair qr | pair code ADDR   (the six digits on stdin)")
    address = wlmod.check_address(args[1])
    code = wlmod.read_code()
    adb = ctx.require_adb()
    before = {d["serial"] for d in ctx.devices()}
    payload = wlmod.pair(adb, address, code)
    payload.update(wlmod.finish_pairing(adb, ctx.state, before, address))
    return _with_devices(ctx, payload, payload.get("serial"))


def cmd_connect(ctx, args):
    if len(args) != 1:
        raise BadArgs("connect ADDR")
    address = wlmod.check_address(args[0])
    adb = ctx.require_adb()
    payload = wlmod.connect(adb, address)
    return _with_devices(ctx, payload)


def cmd_disconnect(ctx, args):
    if len(args) != 1:
        raise BadArgs("disconnect ADDR")
    address = wlmod.check_address(args[0])
    adb = ctx.require_adb()
    payload = wlmod.disconnect(adb, address)
    return _with_devices(ctx, payload)


def _named_or_selected(ctx, args, usage):
    """The serial on the command line, else the resolved one; the device must be ready."""
    if len(args) > 1 or (args and not devmod.valid_serial(args[0])):
        raise BadArgs(usage)
    if args:
        ctx.explicit_serial = args[0]
    adb, serial = ctx.device()
    target = next(d for d in ctx.devices() if d["serial"] == serial)
    return adb, target


def cmd_tcpip(ctx, args):
    adb, target = _named_or_selected(ctx, args, "tcpip [USBSERIAL]")
    if target["kind"] != "usb":
        raise AdbError("bad_args", "Go wireless needs the phone on the cable: pick the USB entry")
    payload = wlmod.go_wireless(adb, target["serial"], ctx.state, target["label"])
    return _with_devices(ctx, payload, payload["selected"])


def cmd_usb(ctx, args):
    adb, target = _named_or_selected(ctx, args, "usb [SERIAL]")
    if target["kind"] == "emulator":
        raise AdbError("bad_args", f"{target['serial']} is an emulator")
    payload = wlmod.back_to_usb(adb, target["serial"], ctx.devices(), ctx.state, target["label"])
    ctx.explicit_serial = None
    payload["devices"] = ctx.devices(refresh=True)
    return payload


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
    "apk": cmd_apk,
    "text": cmd_text,
    "tools": cmd_tools,
    "tool": cmd_tool,
    "wireless": cmd_wireless,
    "pair": cmd_pair,
    "connect": cmd_connect,
    "disconnect": cmd_disconnect,
    "tcpip": cmd_tcpip,
    "usb": cmd_usb,
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
            doc = envelope("track", ok=False, error=ctx.no_adb().to_dict(), adb=ctx.adb_info(), event="error")
            emit(doc)
            return None
        try:
            devmod.track(ctx.adb, ctx.state)
        except AdbError as e:
            emit(envelope("track", ok=False, error=e.to_dict(), adb=ctx.adb_info(), event="error"))
        return None
    if command == "record":
        disarm()  # runs until the recording ends, minutes at most
        ctx = Context(settings, serial)
        try:
            cmd_record(ctx, args, emit)
        except AdbError as e:
            emit(envelope("record", ok=False, error=e.to_dict(), adb=ctx.adb_info(), event="error"))
        return None
    if command == "pair" and args == ["qr"]:
        disarm()  # waits for the phone to scan, two minutes at most
        ctx = Context(settings, serial)
        try:
            adb = ctx.require_adb()
            devices = ctx.devices()
            result = wlmod.pair_qr(adb, ctx.state, lambda p: emit(envelope("pair", ok=True, adb=ctx.adb_info(), selected=ctx.selected(), **p)), devices)
            if result is not None:
                emit(envelope("pair", ok=True, adb=ctx.adb_info(), selected=result.get("serial") or ctx.selected(), **result))
                ctx.state.save()
        except AdbError as e:
            emit(envelope("pair", ok=False, error=e.to_dict(), adb=ctx.adb_info(), event="error"))
        except wlmod.Cancelled:
            pass
        except OSError:
            pass  # the state file could not be written; the pairing itself is done
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
