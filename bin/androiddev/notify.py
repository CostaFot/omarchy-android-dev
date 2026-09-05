"""Desktop notifications and the Wayland clipboard, both optional.

`omarchy-notification-send` and `wl-copy` are run as argv arrays with a
short timeout; a failure never fails the command that asked for them.
OMARCHY_ANDROID_DEV_NOTIFY and OMARCHY_ANDROID_DEV_WL_COPY point tests at
recording scripts.
"""

import os
import shutil
import subprocess

from . import APP_NAME

NOTIFIER = "/usr/share/omarchy/bin/omarchy-notification-send"


def notifier_path():
    override = os.environ.get("OMARCHY_ANDROID_DEV_NOTIFY")
    if override:
        return override if os.access(override, os.X_OK) else None
    if os.access(NOTIFIER, os.X_OK):
        return NOTIFIER
    return shutil.which("omarchy-notification-send")


def wl_copy_path():
    override = os.environ.get("OMARCHY_ANDROID_DEV_WL_COPY")
    if override:
        return override if os.access(override, os.X_OK) else None
    return shutil.which("wl-copy")


def wl_paste_path():
    override = os.environ.get("OMARCHY_ANDROID_DEV_WL_PASTE")
    if override is not None:
        return override if override and os.access(override, os.X_OK) else None
    return shutil.which("wl-paste")


def _run(argv, stdin=None, timeout=5):
    """argv with a deadline; stdin is /dev/null unless a file is given, so a
    tool that reads its input can never wait on the shell's."""
    try:
        subprocess.run(argv, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def send(settings, headline, description="", image=None, urgency="low"):
    """True when a notification was handed to the notifier. `notify: false`
    in the settings silences everything."""
    if not settings.get("notify", True):
        return False
    path = notifier_path()
    if not path:
        return False
    argv = [path, "--app-name", APP_NAME, "-u", urgency]
    if image:
        argv += ["--image", image]
    argv.append(str(headline))
    if description:
        argv.append(str(description))
    return _run(argv)


def copy_file(path, mime="image/png"):
    """The file's bytes to the clipboard through wl-copy's stdin."""
    tool = wl_copy_path()
    if not tool:
        return False
    try:
        with open(path, "rb") as f:
            return _run([tool, "--type", mime], stdin=f)
    except OSError:
        return False
