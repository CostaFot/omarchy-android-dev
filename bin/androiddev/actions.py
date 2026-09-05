"""The per-package actions and deep links: one function per Windows command,
its toast text as the `notice`."""

import re

from . import fmt
from .adb import AdbError
from .packages import parse_package_dump, parse_resolve_activity

URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\s\x00-\x1f\x7f]+$")


def valid_url(url):
    return bool(url) and len(url) <= 2048 and URL_RE.match(url) is not None


def resolve_activity(adb, serial, pkg):
    """The launcher component, or None. `cmd package resolve-activity` as on
    Windows; when that answers nothing, `pm resolve-activity` as a second
    spelling some builds prefer."""
    for args in (("cmd", "package", "resolve-activity", "--brief", "-c", "android.intent.category.LAUNCHER", pkg),
                 ("pm", "resolve-activity", "--brief", "-c", "android.intent.category.LAUNCHER", pkg)):
        try:
            found = parse_resolve_activity(adb.shell(serial, *args, check=False).text, pkg)
        except AdbError:
            found = None
        if found:
            return found
    return None


def _start(adb, serial, activity):
    adb.shell(serial, "am", "start", "-n", activity)


def launch(adb, serial, pkg):
    activity = resolve_activity(adb, serial, pkg)
    if not activity:
        raise AdbError("adb_failed", f"Could not resolve launcher activity for {pkg}")
    try:
        _start(adb, serial, activity)
    except AdbError as e:
        raise AdbError(e.code, f"Failed to launch: {e.message}", e.stderr) from e
    return {"notice": f"Launched {pkg}", "activity": activity}


def force_stop(adb, serial, pkg):
    try:
        adb.shell(serial, "am", "force-stop", pkg)
    except AdbError as e:
        raise AdbError(e.code, f"Failed to force stop: {e.message}", e.stderr) from e
    return {"notice": f"Force stopped {pkg}"}


def kill(adb, serial, pkg):
    try:
        adb.shell(serial, "am", "kill", pkg)
    except AdbError as e:
        raise AdbError(e.code, f"Failed to kill process: {e.message}", e.stderr) from e
    return {"notice": f"Killed process: {pkg}"}


def restart(adb, serial, pkg):
    try:
        adb.shell(serial, "am", "force-stop", pkg)
    except AdbError as e:
        raise AdbError(e.code, f"Failed to stop app: {e.message}", e.stderr) from e
    activity = resolve_activity(adb, serial, pkg)
    if not activity:
        raise AdbError("adb_failed", f"App stopped, but could not resolve launcher activity for {pkg}")
    try:
        _start(adb, serial, activity)
    except AdbError as e:
        raise AdbError(e.code, f"App stopped, but failed to launch: {e.message}", e.stderr) from e
    return {"notice": f"Restarted {pkg}", "activity": activity}


def clear(adb, serial, pkg):
    try:
        adb.shell(serial, "pm", "clear", pkg)
    except AdbError as e:
        raise AdbError(e.code, f"Failed to clear data: {e.message}", e.stderr) from e
    return {"notice": f"Cleared data for {pkg}"}


def clear_restart(adb, serial, pkg):
    try:
        adb.shell(serial, "pm", "clear", pkg)
    except AdbError as e:
        raise AdbError(e.code, f"Failed to clear data: {e.message}", e.stderr) from e
    activity = resolve_activity(adb, serial, pkg)
    if not activity:
        raise AdbError("adb_failed", f"Data cleared, but could not resolve launcher activity for {pkg}")
    try:
        _start(adb, serial, activity)
    except AdbError as e:
        raise AdbError(e.code, f"Data cleared, but failed to launch: {e.message}", e.stderr) from e
    return {"notice": f"Cleared data and restarted {pkg}", "activity": activity}


def uninstall(adb, serial, pkg):
    """`adb uninstall PKG` (the host-side verb, whose Failure line lands on
    stdout with a non-zero exit; `shell pm uninstall` exits 0 on failure
    and Windows missed it)."""
    try:
        adb.run(["uninstall", pkg], serial=serial, timeout=60)
    except AdbError as e:
        raise AdbError(e.code, f"Failed to uninstall: {e.message}", e.stderr) from e
    return {"notice": f"Uninstalled {pkg}"}


def _runtime_permissions(adb, serial, pkg):
    dump = adb.shell(serial, "dumpsys", "package", pkg, cap=fmt.CAP_PACKAGES)
    info = parse_package_dump(dump.text, pkg)
    if not info["found"]:
        raise AdbError("adb_failed", f"No such package: {pkg}")
    return info["runtime_permissions"]


def grant_all(adb, serial, pkg):
    perms = _runtime_permissions(adb, serial, pkg)
    if not perms:
        return {"notice": "No runtime permissions found", "granted": 0, "total": 0, "failed": []}
    granted = 0
    failed = []
    for p in perms:
        try:
            adb.shell(serial, "pm", "grant", pkg, p["name"])
            granted += 1
        except AdbError as e:
            failed.append({"name": p["name"], "message": fmt.clean(e.message)})
    return {"notice": f"Granted {granted}/{len(perms)} permissions", "granted": granted, "total": len(perms), "failed": failed}


def revoke_all(adb, serial, pkg):
    perms = [p for p in _runtime_permissions(adb, serial, pkg) if p["granted"]]
    if not perms:
        return {"notice": "No granted runtime permissions found", "revoked": 0, "total": 0, "failed": []}
    revoked = 0
    failed = []
    for p in perms:
        try:
            adb.shell(serial, "pm", "revoke", pkg, p["name"])
            revoked += 1
        except AdbError as e:
            failed.append({"name": p["name"], "message": fmt.clean(e.message)})
    return {"notice": f"Revoked {revoked}/{len(perms)} permissions", "revoked": revoked, "total": len(perms), "failed": failed}


def deeplink(adb, serial, url, pkg=None):
    """`am start [-p PKG] -a android.intent.action.VIEW -d URL`; the URL is
    one argv entry, never quoted into a shell string."""
    if not valid_url(url):
        raise AdbError("bad_args", "Enter a URL with a scheme, such as https://example.com or myapp://open")
    args = ["am", "start"]
    if pkg:
        args += ["-p", pkg]
    args += ["-a", "android.intent.action.VIEW", "-d", url]
    try:
        adb.shell(serial, *args)
    except AdbError as e:
        verb = "open" if pkg else "launch"
        raise AdbError(e.code, f"Failed to {verb} deep link: {e.message}", e.stderr) from e
    return {"notice": (f"Opened: {url}" if pkg else f"Launched: {url}"), "url": url, "package": pkg}


ACTIONS = {
    "launch": launch,
    "restart": restart,
    "force-stop": force_stop,
    "kill": kill,
    "clear": clear,
    "clear-restart": clear_restart,
    "uninstall": uninstall,
}
