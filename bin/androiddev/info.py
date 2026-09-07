"""The device at a glance: model, Android version, battery, network,
screen, memory, storage, the foreground activity and the uptime, read in
one `adb shell` and formatted here. Read-only; the page shows one row per
section and Enter copies its value.

The read is one fixed shell script (no device data in it), like the
toggles' and the tweaks': `key=value` lines for the one-word answers, then
`## name` sections for the multi-line dumps (`dumpsys battery`, the two
`/proc/meminfo` rows, `df -k /data`, `wm size` and `wm density`, the IPv4
addresses, the Wi-Fi status). The foreground activity is `mCurrentFocus`
first (as the package list reads it) and `topResumedActivity` when that
is null (an HONOR phone answers null while awake, seen 2026-09-08). The
Wi-Fi line is `cmd wifi status`'s `WifiInfo:` (API 30 and later) or
`dumpsys wifi`'s `mWifiInfo` before that, the same `key: value, ...`
format; the BSSID and the MAC in it are never emitted.
"""

import re

from . import fmt

SECTIONS = ("device", "android", "battery", "network", "screen", "memory", "storage", "foreground", "uptime")

LABELS = {
    "device": "Device", "android": "Android", "battery": "Battery", "network": "Network", "screen": "Screen",
    "memory": "Memory", "storage": "Storage", "foreground": "Foreground", "uptime": "Uptime",
}

READ_SCRIPT = (
    'echo model=$(getprop ro.product.model); echo manufacturer=$(getprop ro.product.manufacturer); '
    'echo brand=$(getprop ro.product.brand); echo device=$(getprop ro.product.device); '
    'echo name=$(settings get global device_name); echo abi=$(getprop ro.product.cpu.abi); '
    'echo api=$(getprop ro.build.version.sdk); echo release=$(getprop ro.build.version.release); '
    'echo patch=$(getprop ro.build.version.security_patch); echo build=$(getprop ro.build.display.id); '
    'echo type=$(getprop ro.build.type); '
    'echo brightness=$(settings get system screen_brightness); echo brightness_mode=$(settings get system screen_brightness_mode); '
    'echo uptime=$(cat /proc/uptime); '
    'echo screen=$(dumpsys display 2>/dev/null | grep -m1 mScreenState=); '
    'echo focus=$(dumpsys window 2>/dev/null | grep -m1 mCurrentFocus=); '
    'echo top=$(dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity=); '
    'echo "## battery"; dumpsys battery 2>&1; '
    'echo "## meminfo"; grep -E "^(MemTotal|MemAvailable):" /proc/meminfo; '
    'echo "## df"; df -k /data 2>&1; '
    'echo "## wm"; wm size 2>&1; wm density 2>&1; '
    'echo "## ip"; ip -o -4 addr show scope global 2>&1; '
    'echo "## wifi"; cmd wifi status 2>&1 | grep -m1 "^Wifi is"; cmd wifi status 2>&1 | grep -m1 "WifiInfo:"; '
    'dumpsys wifi 2>/dev/null | grep -m1 "^ *mWifiInfo"; '
    'echo "## end"'
)
READ_TIMEOUT = 20  # four dumpsys calls; 0.8 s over Wi-Fi on a phone, more on a cold emulator

BATTERY_STATUS = {2: "charging", 3: "discharging", 4: "not charging", 5: "full"}
BATTERY_HEALTH = {2: "good", 3: "overheated", 4: "dead", 5: "over voltage", 6: "failed", 7: "cold"}

_COMPONENT_RE = re.compile(r"\su0 (?P<pkg>[A-Za-z][A-Za-z0-9_.]*)/(?P<act>[A-Za-z0-9_.$]+)")
# The lookbehind keeps `BSSID:` from reading as `SSID:`.
_WIFI_FIELD_RE = re.compile(r"(?<![A-Za-z])(?P<key>SSID|RSSI|Link speed|Frequency): (?P<value>\"[^\"]*\"|[^,]*)")


def parse_read(text):
    """`key=value` lines into `raw[key]`, the lines of each `## name`
    section into `raw["#name"]` (a list)."""
    raw = {}
    section = None
    for line in fmt.lines(text):
        if line.startswith("## "):
            section = line[3:].strip()
            if section != "end":
                raw.setdefault("#" + section, [])
            else:
                section = None
            continue
        if section:
            raw["#" + section].append(line)
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip() and " " not in key.strip():
            raw[key.strip()] = fmt.clean(value.strip(), 512)
    return raw


def _int(text):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _float(text):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _word(raw, key):
    v = (raw.get(key) or "").strip()
    return "" if v in ("null", "unknown") else v


def _kv_section(lines):
    """`  key: value` lines (dumpsys battery) into a dict, keys lowercased."""
    out = {}
    for line in lines:
        key, sep, value = line.partition(":")
        if sep and " " not in key.strip():
            out[key.strip().lower()] = value.strip()
        elif sep:
            out[key.strip().lower()] = value.strip()
    return out


def _join(*parts):
    return " · ".join(p for p in parts if p)


def _gb(kib):
    return fmt.size_text(kib * 1024) if kib is not None else ""


def device_section(raw):
    model = fmt.humanize_model(_word(raw, "model")) or ""
    manufacturer = _word(raw, "manufacturer")
    if model and manufacturer and not model.lower().startswith(manufacturer.lower()):
        text = f"{manufacturer} {model}"
    else:
        text = model or manufacturer or "unknown"
    name = _word(raw, "name")
    codename = _word(raw, "device")
    abi = _word(raw, "abi")
    # The device_name setting is worth a mention when it is the user's own
    # (`HONOR Magic7 Pro`), not when it repeats the model (the emulator's).
    shown_name = name if name and name.lower() not in (text.lower(), model.lower(), _word(raw, "model").lower()) else ""
    return {
        "label": LABELS["device"], "text": fmt.clean(text), "copy": fmt.clean(model or text),
        "detail": fmt.clean(_join(LABELS["device"], shown_name, codename, abi)),
        "model": _word(raw, "model") or None, "manufacturer": manufacturer or None, "brand": _word(raw, "brand") or None,
        "codename": codename or None, "name": name or None, "abi": abi or None,
    }


def android_section(raw):
    api = _int(_word(raw, "api"))
    release = _word(raw, "release")
    patch = _word(raw, "patch")
    build = _word(raw, "build")
    build_type = _word(raw, "type")
    text = _join(f"Android {release}" if release else "", f"API {api}" if api else "") or "unknown"
    return {
        "label": LABELS["android"], "text": fmt.clean(text), "copy": fmt.clean(build or text),
        "detail": fmt.clean(_join(f"Security patch {patch}" if patch else "", build,
                                  f"{build_type} build" if build_type else "")) or LABELS["android"],
        "api": api, "release": release or None, "security_patch": patch or None, "build": build or None,
        "build_type": build_type or None,
    }


def battery_section(raw):
    kv = _kv_section(raw.get("#battery") or [])
    level = _int(kv.get("level"))
    scale = _int(kv.get("scale")) or 100
    if level is not None and scale and scale != 100:
        level = int(round(level * 100 / scale))
    status = _int(kv.get("status"))
    health = _int(kv.get("health"))
    temp = _int(kv.get("temperature"))
    voltage = _int(kv.get("voltage"))
    technology = kv.get("technology", "")
    sources = [name for key, name in (("usb powered", "over USB"), ("ac powered", "on AC"),
                                      ("wireless powered", "wirelessly"), ("dock powered", "on the dock"))
               if kv.get(key) == "true"]
    status_word = BATTERY_STATUS.get(status, "")
    if status_word in ("charging", "full") and sources:
        status_word = f"{status_word} {sources[0]}" if status_word == "charging" else f"{status_word}, {sources[0]}"
    text = _join(f"{level}%" if level is not None else "", status_word) or "unknown"
    detail = _join(LABELS["battery"], f"{temp / 10:.1f} °C" if temp is not None else "",
                   f"{voltage / 1000:.2f} V" if voltage else "", fmt.clean(technology, 32),
                   f"health {BATTERY_HEALTH[health]}" if health in BATTERY_HEALTH else "")
    return {
        "label": LABELS["battery"], "text": fmt.clean(text), "detail": fmt.clean(detail),
        "copy": f"{level}%" if level is not None else fmt.clean(text),
        "level": level, "status": status, "status_text": BATTERY_STATUS.get(status) or None,
        "health": health, "health_text": BATTERY_HEALTH.get(health) or None,
        "temperature": temp / 10 if temp is not None else None, "voltage": voltage,
        "technology": fmt.clean(technology, 32) or None, "sources": sources,
    }


def _addresses(lines):
    """`ip -o -4 addr show`: [(interface, ip/prefix)] in order."""
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and parts[2] == "inet":
            out.append((parts[1].rstrip(":"), parts[3]))
    return out


def _wifi_fields(lines):
    """The `SSID: "x", RSSI: -48, Link speed: 1080Mbps, Frequency: 5260MHz`
    fields off the first line that carries an SSID; the enabled/disabled
    word off `cmd wifi status`'s first line."""
    fields = {}
    state = None
    for line in lines:
        s = line.strip()
        if s.startswith("Wifi is enabled"):
            state = "enabled"
        elif s.startswith("Wifi is disabled"):
            state = "disabled"
        elif "SSID:" in s and not fields:
            for m in _WIFI_FIELD_RE.finditer(s):
                fields.setdefault(m.group("key"), m.group("value").strip())
    return state, fields


def network_section(raw):
    addresses = _addresses(raw.get("#ip") or [])
    tunnels = [i for i, _ in addresses if i.startswith(("tun", "wg", "ppp"))]
    usable = [(i, a) for i, a in addresses if i not in tunnels and i != "lo"]
    chosen = next(((i, a) for i, a in usable if i.startswith("wlan")), usable[0] if usable else None)
    interface, ip = (chosen[0], chosen[1].partition("/")[0]) if chosen else (None, None)
    state, fields = _wifi_fields(raw.get("#wifi") or [])
    ssid = fields.get("SSID", "").strip('"')
    if ssid in ("<unknown ssid>", "0x"):
        ssid = ""
    rssi = _int(fields.get("RSSI"))
    speed = _int((fields.get("Link speed") or "").replace("Mbps", ""))
    freq = _int((fields.get("Frequency") or "").replace("MHz", ""))
    if ip:
        text = _join(ip, fmt.clean(ssid, 64), f"{rssi} dBm" if rssi is not None else "")
    else:
        text = "No IPv4 address" + (" · Wi-Fi off" if state == "disabled" else "")
    detail = _join(LABELS["network"], interface or "", f"{speed} Mbps" if speed else "", f"{freq} MHz" if freq else "",
                   ("VPN " + ", ".join(tunnels)) if tunnels else "")
    return {
        "label": LABELS["network"], "text": fmt.clean(text), "detail": fmt.clean(detail), "copy": ip or fmt.clean(text),
        "ip": ip, "interface": interface, "ssid": fmt.clean(ssid, 64) or None, "rssi": rssi,
        "link_speed": speed, "frequency": freq, "wifi": state, "vpn_interfaces": tunnels,
        "addresses": [{"interface": i, "address": a} for i, a in addresses[:8]],
    }


def screen_section(raw):
    wm = {}
    for line in raw.get("#wm") or []:
        key, sep, value = line.partition(":")
        if sep:
            wm[key.strip().lower()] = value.strip()
    physical_size = wm.get("physical size") or None
    override_size = wm.get("override size") or None
    physical_density = _int(wm.get("physical density"))
    override_density = _int(wm.get("override density"))
    size = override_size or physical_size
    density = override_density if override_density is not None else physical_density
    state_word = (raw.get("screen") or "").partition("=")[2].strip().lower() or None
    brightness = _int(_word(raw, "brightness"))
    mode = _int(_word(raw, "brightness_mode"))
    overridden = bool(override_size) or override_density is not None
    text = _join(size or "", f"{density} dpi" if density else "", state_word or "", "overridden" if overridden else "") or "unknown"
    detail = _join(LABELS["screen"],
                   (f"brightness {brightness}" + (", automatic" if mode == 1 else ", manual" if mode == 0 else "")) if brightness is not None else "",
                   f"physical {physical_size}" if override_size else "",
                   f"physical {physical_density} dpi" if override_density is not None else "")
    return {
        "label": LABELS["screen"], "text": fmt.clean(text), "detail": fmt.clean(detail), "copy": fmt.clean(size or text),
        "size": size, "physical_size": physical_size, "override_size": override_size,
        "density": density, "physical_density": physical_density, "override_density": override_density,
        "state": state_word, "brightness": brightness, "brightness_mode": mode,
    }


def memory_section(raw):
    total = available = None
    for line in raw.get("#meminfo") or []:
        key, _, value = line.partition(":")
        n = _int(value.replace("kB", ""))
        if key.strip() == "MemTotal":
            total = n
        elif key.strip() == "MemAvailable":
            available = n
    if total and available is not None:
        text = f"{_gb(available)} free of {_gb(total)}"
        used = f"{int(round((total - available) * 100 / total))}% used"
    else:
        text, used = "unknown", ""
    return {
        "label": LABELS["memory"], "text": text, "detail": _join(LABELS["memory"], "MemAvailable of MemTotal", used),
        "copy": text, "total_kib": total, "available_kib": available,
    }


def storage_section(raw):
    total = used = available = None
    mount = None
    for line in reversed(raw.get("#df") or []):
        parts = line.split()
        if len(parts) >= 6 and _int(parts[1]) is not None and _int(parts[2]) is not None and _int(parts[3]) is not None:
            total, used, available, mount = _int(parts[1]), _int(parts[2]), _int(parts[3]), parts[-1]
            break
    if total:
        text = f"{_gb(available)} free of {_gb(total)}"
        pct = f"{int(round(used * 100 / total))}% used"
    else:
        text, pct = "unknown", ""
    return {
        "label": LABELS["storage"], "text": text, "detail": _join(LABELS["storage"], "/data", pct), "copy": text,
        "total_kib": total, "used_kib": used, "available_kib": available, "mount": fmt.clean(mount) if mount else None,
    }


def foreground_section(raw):
    pkg = activity = None
    for key in ("focus", "top"):
        m = _COMPONENT_RE.search(" " + (raw.get(key) or ""))
        if m:
            pkg, activity = m.group("pkg"), m.group("act")
            break
    if pkg:
        text = pkg
        detail = _join(LABELS["foreground"], fmt.activity_label(f"{pkg}/{activity}", pkg))
    else:
        text = "Nothing in the foreground"
        detail = _join(LABELS["foreground"], "the screen is off or locked" if (raw.get("screen") or "").upper().endswith(("OFF", "DOZE", "DOZE_SUSPEND")) else "")
    return {
        "label": LABELS["foreground"], "text": fmt.clean(text), "detail": fmt.clean(detail), "copy": fmt.clean(pkg or ""),
        "package": pkg, "activity": fmt.clean(activity) if activity else None,
        "component": f"{pkg}/{activity}" if pkg else None,
    }


def uptime_text(seconds):
    """`2 d 23 h`, `5 h 12 min`, `12 min`, `40 s`."""
    s = max(0, int(seconds))
    days, rest = divmod(s, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"


def uptime_section(raw):
    seconds = _float((raw.get("uptime") or "").split()[0] if raw.get("uptime") else None)
    text = uptime_text(seconds) if seconds is not None else "unknown"
    return {"label": LABELS["uptime"], "text": text, "detail": _join(LABELS["uptime"], "since the last boot"), "copy": text,
            "seconds": int(seconds) if seconds is not None else None}


_BUILDERS = {
    "device": device_section, "android": android_section, "battery": battery_section, "network": network_section,
    "screen": screen_section, "memory": memory_section, "storage": storage_section,
    "foreground": foreground_section, "uptime": uptime_section,
}


def sections(raw):
    return {name: _BUILDERS[name](raw) for name in SECTIONS}


def read_all(adb, serial):
    raw = parse_read(adb.shell(serial, READ_SCRIPT, timeout=READ_TIMEOUT).text)
    info = sections(raw)
    return {"info": info, "api": info["android"]["api"] or 0}
