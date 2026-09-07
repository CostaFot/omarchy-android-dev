"""The APK manager: the `.apk` files in a folder, and installing them one
at a time with `adb install -r -t PATH` (`-t` so a debug build marked
testOnly installs too; Windows used `-r` alone). Every path is one argv
entry; nothing here is quoted into a shell string.

A folder installed from is remembered in state.json (like the recent deep
links) and rides back on every `apk list` and on the answer to an install
that ran, so the page can offer it as a row; listing a folder remembers
nothing, or half a path typed past a real folder would land in the list."""

import os
import re

from . import fmt
from .adb import AdbError, PartialError

INSTALL_TIMEOUT = 120
_FAILURE = re.compile(r"Failure \[[^\]]*\]")


def apk_dir(settings, arg=None):
    """The folder to list, canonical: `abspath` after `~` so a trailing
    slash or a `..` cannot make `dir` differ from the `dir_of` the same
    folder is remembered under (the panel joins the two on that string)."""
    configured = str(arg if arg is not None else (settings.get("apkDir") or "~/Downloads")).strip() or "~/Downloads"
    return os.path.abspath(os.path.expanduser(configured))


def list_apks(directory):
    """{dir, dir_text, exists, apks[{path, path_text, name, size, size_text}], count, truncated}.
    Top-level `*.apk` files sorted by name; a missing folder is `exists: false`, not an error."""
    exists = os.path.isdir(directory)
    apks = []
    truncated = False
    if exists:
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            names = []
            exists = False
        for name in names:
            if not name.lower().endswith(".apk"):
                continue
            path = os.path.join(directory, name)
            try:
                if not os.path.isfile(path):
                    continue
                size = os.path.getsize(path)
            except OSError:
                continue
            apks.append({
                "path": path,
                "path_text": fmt.display_path(path),
                "name": fmt.clean(name),
                "size": size,
                "size_text": fmt.size_text(size),
            })
        if len(apks) > fmt.MAX_APKS:
            apks = apks[:fmt.MAX_APKS]
            truncated = True
    return {
        "dir": directory,
        "dir_text": fmt.display_path(directory),
        "exists": exists,
        "apks": apks,
        "count": len(apks),
        "truncated": truncated,
    }


def dir_of(path):
    """The folder an install came from, absolute (a relative path on the
    command line is resolved against the cwd, never remembered as is)."""
    return os.path.dirname(os.path.abspath(os.path.expanduser(str(path or ""))))


def recent_dirs(state):
    """The folders installed from, newest first: `[{path, path_text}]`."""
    return [{"path": d, "path_text": fmt.display_path(d)} for d in state.recent_apk_dirs]


def check_path(path):
    """An existing `.apk` file, `~` expanded; raises AdbError(bad_args)."""
    p = os.path.expanduser(str(path or "").strip())
    if not p:
        raise AdbError("bad_args", "apk install PATH")
    if not p.lower().endswith(".apk"):
        raise AdbError("bad_args", f"Not an .apk file: {fmt.display_path(p)}")
    if not os.path.isfile(p):
        raise AdbError("bad_args", f"No such file: {fmt.display_path(p)}")
    return p


def failure_text(e):
    """`Failure [INSTALL_FAILED_…]` out of adb's line, else the message."""
    for text in (e.stderr, e.message):
        m = _FAILURE.search(text or "")
        if m:
            return m.group(0)
    return fmt.clean(e.message)


def install(adb, serial, paths):
    """Sequential `adb install -r -t PATH`; one result per file. A single
    failing file is an error document with the result inside; several
    files answer `Installed n/m` and fail as a whole when any did."""
    results = []
    for path in paths:
        try:
            adb.run(["install", "-r", "-t", path], serial=serial, timeout=INSTALL_TIMEOUT)
            results.append({"path": path, "name": fmt.clean(os.path.basename(path)), "ok": True, "message": "Installed"})
        except AdbError as e:
            results.append({"path": path, "name": fmt.clean(os.path.basename(path)), "ok": False, "message": failure_text(e), "code": e.code})
    installed = sum(1 for r in results if r["ok"])
    payload = {"results": results, "installed": installed, "total": len(results)}
    if len(results) == 1:
        r = results[0]
        payload["path"] = r["path"]
        payload["name"] = r["name"]
        if r["ok"]:
            payload["notice"] = f"Installed: {r['name']}"
            return payload
        raise PartialError(payload, AdbError(r["code"], f"Install failed: {r['message']}"))
    payload["notice"] = f"Installed {installed}/{len(results)} APKs"
    if installed < len(results):
        first = next(r for r in results if not r["ok"])
        raise PartialError(payload, AdbError(first["code"], f"Installed {installed}/{len(results)} APKs; {first['name']}: {first['message']}"))
    return payload
