"""Wireless debugging: pairing a phone, connecting to it, going cable-free.

Four ways onto Wi-Fi, all of them adb's own:

- `pair qr` (streaming): a pairing code as a PNG (qrencode, in Omarchy's
  base set), then wait for the phone to scan it from Developer options ›
  Wireless debugging › Pair device with QR code. The phone advertises
  `_adb-tls-pairing._tcp` under the name in the code; `adb mdns services`
  shows it; `adb pair ip:port` with the password on stdin finishes it, and
  adb then connects on its own (the paired GUID goes into its known_hosts,
  and its server auto-connects to that phone whenever the phone's
  `_adb-tls-connect` service is on the network).
- `pair code ADDR`: the address and the six digits the phone shows under
  Pair device with pairing code; the code arrives on this helper's stdin
  and goes to `adb pair`'s stdin, never on an argv.
- `connect ADDR`: `adb connect`, which exits 0 on failure (success is the
  text `connected to`), then `get-state` until the device is ready. The
  panel's network rows and `tcpip` use it; there is no page for typing one.
- `tcpip [USBSERIAL]`: the pre-Android-11 way and the cable-free one:
  `adb tcpip 5555` over USB, the phone's Wi-Fi address from `ip route`,
  connect, select the Wi-Fi entry. `usb` puts adbd back on USB.

The QR payload (`WIFI:T:ADB;S:<name>;P:<password>;;`) is a Wi-Fi
credential string by format: a camera app that reads it will try to join
a network that does not exist, which is why the page says where to scan
it from. The password lives in the PNG (0600, in the private state dir,
removed when the session ends) and on adb's stdin, nowhere else.
"""

import os
import re
import secrets
import select
import signal
import sys
import time

from . import devices as devmod, fmt, tools as toolsmod
from .adb import AdbError, die_with_parent, run_bounded
from .capture import PNG_MAGIC

PAIRING_SERVICE = "_adb-tls-pairing._tcp"
CONNECT_SERVICE = "_adb-tls-connect._tcp"
DEFAULT_PORT = 5555
CONNECT_TIMEOUT = 10      # adb's own TCP timeout is minutes
PAIR_TIMEOUT = 30
STATE_WAIT = 3.0          # get-state polling after a connect
STATE_POLL = 0.3
TCPIP_SETTLE = 1.5        # adbd restarts after `tcpip`; dori's pause
TCPIP_WINDOW = 20.0       # connect retries after `tcpip`
NEW_DEVICE_WAIT = 8.0     # a paired phone shows up in `devices -l` within this
MDNS_POLL = 1.0
PAIR_WINDOW = 120         # seconds the code stays up
CODE_WAIT = 5.0           # how long `pair code` waits for the code on a pipe

CODE_RE = re.compile(r"^\d{6}$")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_GUID_RE = re.compile(r"\[guid=([^\]]+)\]")
_INET_RE = re.compile(r"\binet (\d{1,3}(?:\.\d{1,3}){3})/")


class Cancelled(BaseException):
    """SIGINT or SIGTERM during a `pair qr` session: clean up, print
    nothing, exit 0 (what `track` does)."""


# ---- addresses -----------------------------------------------------------------

def valid_address(text):
    """`host:port` normalised (`:5555` added when there is no port), or None.
    IPv4 or a host name; a bracketed IPv6 address is refused (the device
    list cannot show one: `devices.SERIAL_RE` has no `[`)."""
    s = str(text or "").strip()
    if not s or len(s) > 260 or "[" in s or s.count(":") > 1:
        return None
    host, sep, port = s.partition(":")
    if not sep:
        port = str(DEFAULT_PORT)
    if not HOST_RE.match(host) or not port.isdigit() or not 1 <= int(port) <= 65535:
        return None
    if host.replace(".", "").isdigit():
        octets = host.split(".")
        if len(octets) != 4 or any(not o or int(o) > 255 for o in octets):
            return None
    return f"{host}:{int(port)}"


def check_address(text):
    """valid_address, or AdbError(bad_args) saying why."""
    addr = valid_address(text)
    if addr:
        return addr
    s = str(text or "").strip()
    if "[" in s or s.count(":") > 1:
        raise AdbError("bad_args", "IPv6 addresses are not accepted; use the IPv4 address Wireless debugging shows")
    raise AdbError("bad_args", "Enter an address as ip:port (5555 is used when there is no port)")


def check_target(text):
    """What `disconnect` takes: an address (normalised), or the mDNS-named
    serial adb gave a phone it connected to on its own (as is)."""
    s = str(text or "").strip()
    if devmod.valid_serial(s) and devmod.mdns_instance(s):
        return s
    return check_address(s)


def valid_code(text):
    s = str(text or "").strip()
    return s if CODE_RE.match(s) else None


# ---- mDNS ------------------------------------------------------------------------

def parse_mdns_services(text):
    """`adb mdns services`: a header, then `instance<TAB>service<TAB>ip:port`
    per line. Only the two wireless-debugging services are kept."""
    out = []
    for line in fmt.lines(text):
        if line.startswith("List of discovered"):
            continue
        parts = [p.strip() for p in line.split("\t")] if "\t" in line else line.split()
        parts = [p for p in parts if p]
        if len(parts) < 3:
            continue
        service = fmt.clean(parts[1], 64).rstrip(".")
        if service.startswith("_adb-tls-pairing"):
            kind = "pairing"
        elif service.startswith("_adb-tls-connect"):
            kind = "connect"
        else:
            continue
        address = valid_address(parts[-1])
        if not address:
            continue
        host, _, port = address.rpartition(":")
        out.append({
            "instance": fmt.clean(parts[0], 128),
            "service": service,
            "host": host,
            "port": int(port),
            "address": address,
            "kind": kind,
            "detail": fmt.service_detail(kind, address),
        })
    return fmt.cap_list(out, fmt.MAX_MDNS_SERVICES)


def mdns_available(adb):
    """(True, `mdns daemon version …`) or (False, why). Arch's android-tools
    adb answers `mdns is not supported by this version of adb`."""
    try:
        result = adb.run(["mdns", "check"], timeout=5, check=False)
    except AdbError as e:
        return False, e.message
    text = " ".join(result.lines()).strip()
    low = (text + " " + result.stderr).lower()
    if result.code == 0 and text and "not supported" not in low:
        return True, fmt.clean(text)
    return False, fmt.MDNS_MISSING_TEXT


def services(adb, pdeathsig=False):
    try:
        result = adb.run(["mdns", "services"], timeout=5, check=False, pdeathsig=pdeathsig)
    except AdbError:
        return []
    if result.code != 0:
        return []
    return parse_mdns_services(result.text)


# ---- connect / disconnect ---------------------------------------------------------

_CONNECT_FAILED = ("failed to connect", "cannot connect", "unable to connect", "no route", "refused")


def classify_connect(result):
    """(ok, text). `adb connect` exits 0 either way; `connected to ` (also
    `already connected to `) is success, everything else the reason."""
    text = " ".join(result.lines()).strip() or result.stderr
    low = text.lower()
    if "connected to " in low and not any(w in low for w in _CONNECT_FAILED):
        return True, fmt.clean(text)
    return False, fmt.clean(text or f"adb connect exited with code {result.code}", 512)


def wait_ready(adb, serial, budget=STATE_WAIT):
    """`adb -s SERIAL get-state` until it says `device`; the last state word
    seen (`offline`, `unauthorized`, `` for none) when the budget runs out."""
    deadline = time.monotonic() + budget
    last = ""
    while True:
        try:
            result = adb.run(["get-state"], serial=serial, timeout=5, check=False)
            words = result.lines()
            last = fmt.clean(words[0].strip(), 32) if words else fmt.clean(result.stderr, 64)
        except AdbError as e:
            last = fmt.clean(e.message, 64)
        if last == "device" or time.monotonic() >= deadline:
            return last
        time.sleep(STATE_POLL)


def connect(adb, address):
    result = adb.run(["connect", address], timeout=CONNECT_TIMEOUT, check=False)
    ok, text = classify_connect(result)
    if not ok:
        raise AdbError("adb_failed", f"adb connect: {text}", result.stderr)
    ready = wait_ready(adb, address)
    if ready != "device":
        if "unauthorized" in ready:
            raise AdbError("unauthorized", f"Connected to {address}, but the phone has not authorised this computer: accept the prompt on it")
        raise AdbError("offline", f"Connected to {address}, but it is {ready or 'not ready'}: unlock the phone, or toggle Wireless debugging off and on")
    return {"notice": fmt.connected_notice(address), "address": address, "state": ready}


def disconnect(adb, address):
    result = adb.run(["disconnect", address], timeout=CONNECT_TIMEOUT, check=False)
    text = " ".join(result.lines()).strip() or result.stderr
    if result.code != 0 and "no such device" not in text.lower():
        raise AdbError("adb_failed", f"adb disconnect: {fmt.clean(text)}", result.stderr)
    return {"notice": fmt.disconnected_notice(address), "address": address}


# ---- pairing -------------------------------------------------------------------------

def read_code(stream=None, wait=CODE_WAIT):
    """The six digits from this helper's stdin (one line). A pipe that
    stays silent for `wait` seconds is "no code" rather than a hang; a
    terminal gets a prompt and a minute."""
    stream = stream if stream is not None else getattr(sys.stdin, "buffer", None)
    if stream is None:
        raise AdbError("bad_args", "No pairing code on stdin")
    tty = False
    try:
        tty = os.isatty(stream.fileno())
    except (OSError, ValueError, AttributeError):
        tty = False
    if tty:
        sys.stderr.write("Enter the 6-digit pairing code: ")
        sys.stderr.flush()
    try:
        ready, _, _ = select.select([stream], [], [], 60 if tty else wait)
    except (OSError, ValueError):
        ready = [stream]
    raw = b""
    if ready:
        try:
            raw = stream.readline(64)
        except OSError:
            raw = b""
    code = raw.decode("utf-8", errors="replace").strip()
    if not code:
        raise AdbError("bad_args", "No pairing code on stdin: pipe the six digits in, as in printf '123456\\n' | … pair code ADDR")
    if not CODE_RE.match(code):
        raise AdbError("bad_args", "The pairing code is six digits")
    return code


def classify_pair(result):
    """(ok, text, guid). `Successfully paired to HOST [guid=…]` is the one
    good answer; `Failed: Wrong password or connection was dropped.` gets a
    plainer sentence."""
    text = " ".join(result.lines()).strip()
    low = (text + " " + result.stderr).lower()
    if "successfully paired" in low:
        m = _GUID_RE.search(text)
        return True, fmt.clean(text), (fmt.clean(m.group(1), 128) if m else None)
    if "wrong password" in low:
        return False, "Pairing failed: wrong code, or the phone closed the dialog", None
    return False, fmt.clean(text or result.stderr or f"adb pair exited with code {result.code}", 512), None


def _piped(data):
    """A pipe holding `data`, write end closed: what a child reads as stdin.
    Small enough (a code, a QR payload) that the write never blocks."""
    r, w = os.pipe()
    try:
        os.write(w, data)
    finally:
        os.close(w)
    return r


def pair(adb, address, code, pdeathsig=False):
    """`adb pair ADDRESS` with the code on its stdin."""
    fd = _piped((code + "\n").encode("ascii"))
    try:
        result = adb.run(["pair", address], timeout=PAIR_TIMEOUT, check=False, stdin=fd, pdeathsig=pdeathsig)
    finally:
        os.close(fd)
    ok, text, guid = classify_pair(result)
    if not ok:
        raise AdbError("adb_failed", text, result.stderr)
    return {"address": address, "guid": guid, "pair_text": text}


def wifi_device_on(adb, host, budget=NEW_DEVICE_WAIT):
    """The ready Wi-Fi entry on `host`, polled from `devices -l` for up to
    `budget` seconds: a phone paired again while connected is there at
    once, a fresh one shows up as adb connects to it on its own. An
    `ip:port` serial carries its host; an mDNS-named one is on the host its
    connect service advertises (one `mdns services` call per poll, made
    only when such an entry is ready). Never an entry on another host:
    before 1.3.2 the first new Wi-Fi entry anywhere was taken, so a second
    known phone whose Wireless debugging came on during the wait could be
    selected and named. None when nothing on that host is ready in time.
    No labels are asked for: a Wi-Fi entry's label is its model, and the
    poll must not cost one `emu avd name` per running emulator."""
    deadline = time.monotonic() + budget
    while True:
        try:
            devices = devmod.list_devices(adb, with_labels=False)
        except AdbError:
            devices = []
        named = None
        for d in devices:
            if d["kind"] != "wifi" or d["state"] != "device":
                continue
            instance = devmod.mdns_instance(d["serial"])
            if instance is None:
                if d["serial"].rpartition(":")[0] == host:
                    return d
                continue
            if named is None:
                named = {s["instance"]: s["host"] for s in services(adb) if s["kind"] == "connect"}
            if named.get(instance) == host:
                return d
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def finish_pairing(adb, state, address):
    """After a good `adb pair`: adb connects on its own; wait for the Wi-Fi
    entry on that host, select it, and say who was paired."""
    host = address.rpartition(":")[0]
    dev = wifi_device_on(adb, host)
    if dev:
        state.select(dev["serial"])
    return {
        "serial": dev["serial"] if dev else None,
        "label": dev["label"] if dev else None,
        "notice": fmt.paired_notice(dev["label"] if dev else host),
    }


# ---- the QR session -----------------------------------------------------------------

def make_pairing_secret():
    return f"omarchy-android-dev-{secrets.token_hex(2)}", f"{secrets.randbelow(10 ** 8):08d}"


def qr_payload(name, password):
    return f"WIFI:T:ADB;S:{name};P:{password};;"


def pair_window():
    try:
        return max(2, int(float(os.environ.get("OMARCHY_ANDROID_DEV_PAIR_SECONDS") or PAIR_WINDOW)))
    except ValueError:
        return PAIR_WINDOW


def write_qr_png(payload, path):
    """qrencode reads the payload from stdin (never argv) and prints the PNG;
    the helper writes it as a new 0600 file."""
    qrencode = toolsmod.qrencode_path()
    if not qrencode:
        raise AdbError("no_tool", "qrencode is not installed (it is in Omarchy's base set); pair with a code instead")
    fd = _piped(payload.encode("utf-8"))
    try:
        result = run_bounded([qrencode, "-o", "-", "-t", "PNG", "-s", "6", "-m", "2", "-l", "M"], timeout=10, cap=fmt.CAP_QR_PNG, stdin=fd)
    except AdbError as e:
        raise AdbError("no_tool", f"qrencode failed: {e.message}", e.stderr) from e
    finally:
        os.close(fd)
    if result.code != 0 or not result.stdout.startswith(PNG_MAGIC):
        raise AdbError("no_tool", "qrencode did not produce a PNG" + (f": {result.stderr}" if result.stderr else ""), result.stderr)
    try:
        out = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o600)
        with os.fdopen(out, "wb") as f:
            f.write(result.stdout)
    except OSError as e:
        raise AdbError("internal", f"Cannot write {path}: {e.strerror}") from e


def arm_cancel():
    """The QR session's cancel: SIGINT or SIGTERM raise `Cancelled`, and this
    helper dies with its parent. `dispatch` calls it before the adb server
    check and the mDNS check, not just `pair_qr`: the shell starts the
    helper with SIGINT ignored, so until a handler is in place a `pair
    stop` in the first moments was simply dropped and the session went on
    (found in the 1.2.0 review). Idempotent."""
    die_with_parent()  # a killed shell must not leave this helper behind

    def on_signal(signum, frame):
        raise Cancelled()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def pair_qr(adb, state, emit):
    """Stream: the `pairing` event with the PNG, then the `paired` document
    (or raises AdbError). SIGINT/SIGTERM cancel: the PNG goes, nothing is
    printed (Cancelled is caught here and None returned; one raised before
    the `try` below reaches `dispatch`, which swallows it the same way)."""
    arm_cancel()  # dispatch armed it already; a direct caller gets it here
    state.sweep_pairing_files()
    available, why = mdns_available(adb)
    if not available:
        raise AdbError("adb_failed", why)
    path = state.pairing_png_path()
    if not path:
        raise AdbError("state_corrupt", state.error or "The state directory is not usable")
    name, password = make_pairing_secret()
    window = pair_window()
    try:
        write_qr_png(qr_payload(name, password), path)
        started = time.time()
        emit({
            "event": "pairing",
            "qr_path": path,
            "qr_path_text": fmt.display_path(path),
            "name": name,
            "seconds": window,
            "started_at": int(started),
            "expires_at": int(started + window),
        })
        deadline = time.monotonic() + window
        while True:
            for s in services(adb, pdeathsig=True):
                if s["kind"] == "pairing" and s["instance"] == name:
                    payload = pair(adb, s["address"], password, pdeathsig=True)
                    payload.update(finish_pairing(adb, state, s["address"]))
                    payload["event"] = "paired"
                    return payload
            if time.monotonic() >= deadline:
                raise AdbError("timeout", f"Nobody scanned the code within {fmt.window_text(window)}")
            time.sleep(MDNS_POLL)
    except Cancelled:
        return None
    finally:
        _unlink(path)


# ---- cable-free ------------------------------------------------------------------------

def parse_ip_route(text):
    """The `src` address of the wlan route (`default via … dev wlan0 … src 192.168.1.5`)."""
    fallback = None
    for line in fmt.lines(text):
        parts = line.split()
        if "src" not in parts or "dev" not in parts:
            continue
        dev = parts[parts.index("dev") + 1] if parts.index("dev") + 1 < len(parts) else ""
        src = parts[parts.index("src") + 1] if parts.index("src") + 1 < len(parts) else ""
        if not dev.startswith("wlan") or not valid_address(src):
            continue
        if parts[0] == "default":
            return src
        fallback = fallback or src
    return fallback


def parse_inet_addr(text):
    """`inet 192.168.1.5/24 …` from `ip -f inet addr show wlan0`."""
    m = _INET_RE.search(str(text or ""))
    return m.group(1) if m else None


def device_ip(adb, serial):
    ip = None
    try:
        ip = parse_ip_route(adb.shell(serial, "ip", "route", timeout=10, check=False).text)
    except AdbError:
        ip = None
    if not ip:
        try:
            ip = parse_inet_addr(adb.shell(serial, "ip", "-f", "inet", "addr", "show", "wlan0", timeout=10, check=False).text)
        except AdbError:
            ip = None
    return ip


def go_wireless(adb, serial, state, label=None, port=DEFAULT_PORT):
    """`adb tcpip PORT` on the plugged phone, connect to its Wi-Fi address,
    select that entry. Lasts until the phone reboots."""
    ip = device_ip(adb, serial)
    if not ip:
        raise AdbError("adb_failed", f"{label or serial} has no Wi-Fi address: put the phone on the same Wi-Fi network first")
    address = f"{ip}:{port}"
    result = adb.run(["tcpip", str(port)], serial=serial, timeout=10, check=False)
    if result.code != 0 or "error" in result.stderr.lower():
        raise AdbError("adb_failed", f"adb tcpip {port} failed: {fmt.clean(result.stderr or result.text.strip())}", result.stderr)
    time.sleep(TCPIP_SETTLE)
    deadline = time.monotonic() + TCPIP_WINDOW
    while True:
        try:
            payload = connect(adb, address)
            break
        except AdbError as e:
            if e.code == "unauthorized" or time.monotonic() >= deadline:
                raise AdbError(e.code, f"The phone listens on {address}, but: {e.message}", e.stderr) from e
            time.sleep(1.0)
    state.select(address)
    payload.update({"notice": fmt.go_wireless_notice(address), "address": address, "usb_serial": serial, "selected": address})
    return payload


def back_to_usb(adb, target, devices, state):
    """`adb -s SERIAL usb` on `target` (a device entry): adbd listens on USB
    again and the Wi-Fi entry drops. When that Wi-Fi entry was the
    selection it moves to the one USB phone left, or clears. Naming the
    plugged entry itself leaves the selection alone: the phone is still on
    the cable (before 1.3.2 `usb ""` with the USB phone selected cleared it
    and the hub said No device)."""
    serial = target["serial"]
    result = adb.run(["usb"], serial=serial, timeout=10, check=False)
    if result.code != 0 or "error" in result.stderr.lower():
        raise AdbError("adb_failed", f"adb usb failed: {fmt.clean(result.stderr or result.text.strip())}", result.stderr)
    payload = {"notice": fmt.usb_notice(target.get("label") or serial), "serial": serial}
    if target["kind"] == "wifi" and state.selected == serial:
        usb = [d["serial"] for d in devices if d["kind"] == "usb"]
        fallback = usb[0] if len(usb) == 1 else None
        state.select(fallback)
        payload["selected"] = fallback
    return payload


# ---- the page's document -----------------------------------------------------------------

def describe(adb, state, devices):
    """The `wireless` payload: mDNS yes or no, the services on the network,
    the Wi-Fi and the plugged devices, qrencode."""
    if adb is not None:
        available, text = mdns_available(adb)
    else:
        available, text = False, None
    found = services(adb) if (adb is not None and available) else []
    serials = {d["serial"] for d in devices}
    instances = {devmod.mdns_instance(d["serial"]) for d in devices} - {None}
    for s in found:
        # By `ip:port`, or by the instance name adb gave an auto-connected phone.
        s["attached"] = s["address"] in serials or s["instance"] in instances
    return {
        "mdns": {"available": available, "text": text},
        "services": found,
        "wifi_devices": [d for d in devices if d["kind"] == "wifi"],
        "usb_devices": [d for d in devices if d["kind"] == "usb"],
        "qrencode": toolsmod.tool(toolsmod.qrencode_path()),
        "port": DEFAULT_PORT,
        "pair_seconds": pair_window(),
    }
