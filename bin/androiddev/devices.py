"""Device list, labels, serial resolution and the track-devices stream."""

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

from . import fmt
from .adb import AdbError, classify, run_bounded

SERIAL_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


def valid_serial(serial):
    return bool(serial) and SERIAL_RE.match(serial) is not None


def kind_of(serial):
    s = str(serial or "")
    if s.startswith("emulator-") or s.startswith("localhost:"):
        return "emulator"
    if ":" in s:
        return "wifi"
    return "usb"


def parse_devices_l(text):
    """`adb devices -l` → [{serial, state, model, product, device, transport_id, kind}]."""
    out = []
    for line in fmt.lines(text):
        if line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = fmt.clean(parts[0])
        if not valid_serial(serial):
            continue
        state = fmt.clean(parts[1], 32)
        rest = parts[2:]
        if state == "no" and rest and rest[0].startswith("permissions"):
            state = "no permissions"
            rest = []
        info = {"serial": serial, "state": state, "model": "", "product": "", "device": "", "transport_id": "", "kind": kind_of(serial)}
        for token in rest:
            key, sep, value = token.partition(":")
            if sep and key in ("model", "product", "device", "transport_id"):
                info[key] = fmt.clean(value, 64)
        out.append(info)
    return fmt.cap_list(out, fmt.MAX_DEVICES)


def parse_avd_name(text):
    """`adb emu avd name` prints the AVD name, then `OK`."""
    for line in fmt.lines(text):
        s = line.strip()
        if s and s != "OK":
            return fmt.clean(s, 64)
    return None


def avd_name(adb, serial):
    try:
        result = adb.run(["emu", "avd", "name"], serial=serial, timeout=5, check=False)
    except AdbError:
        return None
    return parse_avd_name(result.text) if result.code == 0 else None


def list_devices(adb, with_labels=True):
    result = adb.run(["devices", "-l"], timeout=10)
    devices = parse_devices_l(result.text)
    for d in devices:
        avd = None
        if with_labels and d["kind"] == "emulator" and d["state"] == "device":
            avd = avd_name(adb, d["serial"])
        d["avd"] = avd
        d["label"] = fmt.device_label(d["serial"], d["model"], avd)
    return devices


def mark_selected(devices, selected):
    for d in devices:
        d["selected"] = d["serial"] == selected
    return devices


def resolve_serial(devices, explicit=None, remembered=None):
    """`--serial` wins; else the remembered one if attached; else the only
    attached device; else no_device / many_devices."""
    serials = [d["serial"] for d in devices]
    if explicit:
        if explicit in serials:
            return explicit
        raise AdbError("no_device", f"Device {explicit} is not attached")
    if remembered and remembered in serials:
        return remembered
    if len(serials) == 1:
        return serials[0]
    if not serials:
        raise AdbError("no_device", "No device attached")
    raise AdbError("many_devices", f"{len(serials)} devices attached; pick one")


def require_ready(devices, serial):
    """The state gate before a device command: `unauthorized` and `offline`
    become their own error codes with the hint the user needs."""
    for d in devices:
        if d["serial"] == serial:
            if d["state"] == "device":
                return d
            if d["state"] == "unauthorized":
                raise AdbError("unauthorized", f"{serial} has not authorised this computer; accept the USB debugging prompt on the device")
            if d["state"] == "offline":
                raise AdbError("offline", f"{serial} is offline; replug it or restart adb")
            raise AdbError("adb_failed", f"{serial} is in state '{d['state']}'")
    raise AdbError("no_device", f"Device {serial} is not attached")


# ---- track-devices ----------------------------------------------------------

def split_frames(buf):
    """(frames, rest): each frame is a 4-hex-digit length then that many
    bytes (`0015emulator-5554\\tdevice\\n`, `0000` for none)."""
    frames = []
    while len(buf) >= 4:
        try:
            n = int(bytes(buf[:4]).decode("ascii"), 16)
        except ValueError:
            raise AdbError("adb_failed", "track-devices sent an unreadable frame")
        if len(buf) < 4 + n:
            break
        frames.append(bytes(buf[4:4 + n]).decode("utf-8", errors="replace"))
        del buf[:4 + n]
    return frames, buf


def _emit(doc, out):
    doc.setdefault("schema_version", 1)
    doc.setdefault("generated_at", int(time.time()))
    line = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    try:
        out.write(line + "\n")
        out.flush()
    except (BrokenPipeError, OSError):
        raise SystemExit(0)


def track(adb, state, out=None):
    """Stream one `devices` event per frame of `adb track-devices`, with the
    details of one `devices -l` per frame. Never exits on its own except
    when adb goes away (one `error` event, exit 0). SIGTERM/SIGINT are
    forwarded to the child and end the run cleanly."""
    out = out or sys.stdout
    adb.ensure_server()
    proc = adb.popen(["track-devices"])
    stopping = {"flag": False}

    def on_signal(signum, frame):
        stopping["flag"] = True
        try:
            proc.terminate()
        except OSError:
            pass

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    err = {"data": bytearray(), "truncated": False}
    from .adb import _pump  # noqa: E402  (shared bounded reader)
    threading.Thread(target=_pump, args=(proc.stderr, fmt.CAP_STDERR, err, proc), daemon=True).start()

    buf = bytearray()
    previous = None
    fd = proc.stdout.fileno()
    try:
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buf += chunk
            if len(buf) > fmt.CAP_TRACK_FRAME:
                _emit({"event": "error", "error": AdbError("too_much_output", "track-devices sent more than 64 KiB without a frame boundary").to_dict()}, out)
                return 0
            try:
                frames, buf = split_frames(buf)
            except AdbError as e:
                _emit({"event": "error", "error": e.to_dict()}, out)
                return 0
            for _frame in frames:
                try:
                    devices = list_devices(adb)
                except AdbError as e:
                    _emit({"event": "error", "error": e.to_dict()}, out)
                    continue
                remembered = state.selected if state else None
                try:
                    selected = resolve_serial(devices, None, remembered)
                except AdbError:
                    selected = None
                mark_selected(devices, selected)
                now = {d["serial"] for d in devices}
                before = previous if previous is not None else set()
                _emit({
                    "event": "devices",
                    "devices": devices,
                    "selected": selected,
                    "added": sorted(now - before),
                    "removed": sorted(before - now),
                    "unauthorized": sorted(d["serial"] for d in devices if d["state"] == "unauthorized"),
                    "initial": previous is None,
                }, out)
                previous = now
    finally:
        # Whatever ended the loop (EOF, a cap, a signal, a closed stdout),
        # the adb child never outlives the helper.
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
    if not stopping["flag"]:
        stderr = fmt.clean(bytes(err["data"]).decode("utf-8", errors="replace").strip(), 512)
        from .adb import Result
        e = classify(Result(["adb", "track-devices"], proc.returncode if proc.returncode is not None else 1, b"", stderr))
        if e.code == "adb_failed":
            e = AdbError("adb_failed", stderr or f"adb track-devices exited with code {proc.returncode}", stderr=stderr)
        _emit({"event": "error", "error": e.to_dict()}, out)
    return 0
