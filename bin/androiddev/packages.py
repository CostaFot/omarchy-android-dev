"""The package list and one package's details.

Port of AdbHelper.GetInstalledPackages with the expensive part removed:
Windows parsed the whole `dumpsys package packages` dump for the DEBUGGABLE
flag; here `debuggable` comes from a targeted `dumpsys package PKG` the
first time a package is opened and is remembered in packages-<serial>.json,
so the list costs three cheap calls (`pm list packages [-3]`, `ps -A`,
`dumpsys window`) and never the full dump. A fourth, `dumpsys activity
processes`, only when `ps -A` names no app process at all (some vendor
ROMs print it without the user column).
"""

import re

from . import fmt
from .adb import AdbError

PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$|^[A-Za-z][A-Za-z0-9_]*$")
SECTIONS = ("Foreground", "Running", "Debuggable", "Other")


def valid_package(name):
    return bool(name) and len(name) <= fmt.MAX_FIELD and PACKAGE_RE.match(name) is not None


def parse_pm_list(text):
    names = []
    seen = set()
    for line in fmt.lines(text):
        s = line.strip()
        if not s.startswith("package:"):
            continue
        name = fmt.clean(s[len("package:"):])
        if valid_package(name) and name not in seen:
            seen.add(name)
            names.append(name)
    return fmt.cap_list(names, fmt.MAX_PACKAGES)


def parse_ps(text):
    """Package names with a process, from the `u0_a*` rows of `ps -A`. A
    sub-process (`com.foo:service`) counts for its package (Windows
    compared the raw name and missed those)."""
    running = set()
    for line in fmt.lines(text):
        s = line.strip()
        if not s.startswith("u0_a"):
            continue
        parts = s.split()
        if len(parts) < 9:
            continue
        name = parts[-1].split(":")[0]
        if valid_package(name):
            running.add(name)
    return running


_PROC_RE = re.compile(r"\b\d+:(?P<name>[A-Za-z0-9_.]+)(?::[^/\s]*)?/u0a\d+")


def parse_activity_processes(text):
    """Package names with a process, from `dumpsys activity processes`:
    the fallback when `ps -A` yields no `u0_a*` row (some vendor ROMs print
    ps without the user column). Every process there is written
    `PID:NAME/UID` (the ProcessRecords, the LRU list, the PID mappings), and
    `/u0aN` is user 0's app uid range, the range ps's `u0_a*` rows cover: so
    a system app with an app uid counts on both paths, `system/1000` and an
    isolated process (`/u0i4`) on neither, and a sub-process counts for its
    package as with ps. Verified against the emulator's own ps on 2026-09-07:
    the two sets were equal."""
    running = set()
    for m in _PROC_RE.finditer(str(text or "")):
        name = m.group("name")
        if valid_package(name):
            running.add(name)
    return running


_FOCUS_RE = re.compile(r"mCurrentFocus=Window\{[^}]*\s(?P<pkg>[A-Za-z0-9_.]+)(/[^\s}]*)?\}")
_TOP_RE = re.compile(r"topResumedActivity=ActivityRecord\{[^}]*\s(?P<pkg>[A-Za-z0-9_.]+)/")


def parse_foreground(text):
    for line in fmt.lines(text):
        m = _FOCUS_RE.search(line)
        if m and valid_package(m.group("pkg")):
            return m.group("pkg")
    return None


def parse_top_resumed(text):
    for line in fmt.lines(text):
        m = _TOP_RE.search(line)
        if m and valid_package(m.group("pkg")):
            return m.group("pkg")
    return None


def parse_resolve_activity(text, pkg):
    """The component (`pkg/activity`) from `cmd package resolve-activity
    --brief`: the last line that starts with the package."""
    found = None
    for line in fmt.lines(text):
        s = line.strip()
        if s.startswith(pkg + "/"):
            found = fmt.clean(s)
    return found


def parse_package_dump(text, pkg):
    """The first `Package [pkg]` section of `dumpsys package pkg`: version,
    the DEBUGGABLE flag, and the runtime permissions with their grant
    state (every `name: granted=…` line under `runtime permissions:`,
    whatever its prefix; Windows stopped at the first non-android. line)."""
    info = {"found": False, "version_name": None, "version_code": None, "debuggable": None, "runtime_permissions": []}
    header = f"Package [{pkg}]"
    in_section = False
    in_perms = False
    perms_indent = None
    for raw in str(text or "").replace("\r", "").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if not in_section:
            if stripped.startswith(header):
                in_section = True
                info["found"] = True
            continue
        if stripped.startswith("Package [") and not stripped.startswith(header):
            break
        if stripped.startswith(header) and in_perms:
            break  # the hidden system copy of the same package
        if stripped.startswith("Hidden system packages"):
            break
        indent = len(line) - len(line.lstrip())
        if in_perms:
            if indent <= perms_indent or not stripped:
                in_perms = False  # one block is enough; later ones are other users
            else:
                name, sep, rest = stripped.partition(":")
                if sep and "granted=" in rest:
                    granted = "granted=true" in rest
                    if len(info["runtime_permissions"]) < fmt.MAX_PERMISSIONS:
                        info["runtime_permissions"].append({"name": fmt.clean(name), "granted": granted})
                continue
        if stripped.startswith("runtime permissions:") and not info["runtime_permissions"]:
            in_perms = True
            perms_indent = indent
            continue
        if stripped.startswith("versionName="):
            info["version_name"] = fmt.clean(stripped[len("versionName="):], 64)
        elif stripped.startswith("versionCode="):
            info["version_code"] = fmt.clean(stripped[len("versionCode="):].split()[0], 32)
        elif (stripped.startswith("flags=[") or stripped.startswith("pkgFlags=[")) and info["debuggable"] is None:
            info["debuggable"] = "DEBUGGABLE" in stripped
    if info["found"] and info["debuggable"] is None:
        info["debuggable"] = False
    return info


def section_of(p):
    if p.get("foreground"):
        return "Foreground"
    if p.get("running"):
        return "Running"
    if p.get("debuggable"):
        return "Debuggable"
    return "Other"


def sort_packages(packages):
    """Foreground → Running → Debuggable → name, as on Windows."""
    return sorted(packages, key=lambda p: (not p.get("foreground"), not p.get("running"), not p.get("debuggable"), p["name"]))


def foreground_package(adb, serial):
    try:
        fg = parse_foreground(adb.shell(serial, "dumpsys", "window", cap=fmt.CAP_PACKAGES).text)
    except AdbError:
        fg = None
    if fg is None:
        try:
            fg = parse_top_resumed(adb.shell(serial, "dumpsys", "activity", "activities", cap=fmt.CAP_PACKAGES).text)
        except AdbError:
            fg = None
    return fg


def list_packages(adb, serial, state, settings):
    args = ["pm", "list", "packages"]
    if not settings.get("showSystemApps", False):
        args.append("-3")
    names = parse_pm_list(adb.shell(serial, *args, cap=fmt.CAP_PACKAGES).text)
    try:
        running = parse_ps(adb.shell(serial, "ps", "-A", cap=fmt.CAP_PACKAGES).text)
    except AdbError:
        running = set()
    if not running:
        # No app row at all: a ps without the user column (some vendor ROMs)
        # or a ps that failed. An Android with any app process has systemui
        # under u0_a, so an empty set is never the truth.
        try:
            running = parse_activity_processes(adb.shell(serial, "dumpsys", "activity", "processes", cap=fmt.CAP_PACKAGES).text)
        except AdbError:
            running = set()
    foreground = foreground_package(adb, serial)
    cache = state.package_cache(serial) if state else {}
    packages = []
    for name in names:
        known = cache.get(name, {})
        packages.append({
            "name": name,
            "running": name in running,
            "foreground": name == foreground,
            "debuggable": known.get("debuggable"),
        })
    packages = sort_packages(packages)
    for p in packages:
        p["section"] = section_of(p)
        p["detail"] = fmt.package_tags(p["running"], p["foreground"], p["debuggable"])
    if state:
        state.write_package_cache(serial, {p["name"]: {"debuggable": p["debuggable"]} for p in packages})
    return {"packages": packages, "foreground": foreground, "count": len(packages), "system_apps": bool(settings.get("showSystemApps", False))}


def package_info(adb, serial, state, pkg):
    dump = adb.shell(serial, "dumpsys", "package", pkg, cap=fmt.CAP_PACKAGES)
    info = parse_package_dump(dump.text, pkg)
    if not info["found"]:
        raise AdbError("adb_failed", f"No such package: {pkg}")
    try:
        launcher = parse_resolve_activity(adb.shell(serial, "cmd", "package", "resolve-activity", "--brief", "-c", "android.intent.category.LAUNCHER", pkg).text, pkg)
    except AdbError:
        launcher = None
    try:
        running = pkg in parse_ps(adb.shell(serial, "ps", "-A", cap=fmt.CAP_PACKAGES).text)
    except AdbError:
        running = None
    foreground = foreground_package(adb, serial) == pkg
    if state:
        cache = state.package_cache(serial)
        cache[pkg] = {"debuggable": info["debuggable"]}
        state.write_package_cache(serial, cache)
        state.set_last_package(serial, pkg)
    return {
        "name": pkg,
        "version_name": info["version_name"],
        "version_code": info["version_code"],
        "debuggable": info["debuggable"],
        "launcher_activity": launcher,
        "runtime_permissions": info["runtime_permissions"],
        "running": running,
        "foreground": foreground,
    }
