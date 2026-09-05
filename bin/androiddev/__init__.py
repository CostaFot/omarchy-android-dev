"""androiddev — the adb core of the Android Dev plugin for Omarchy.

Pure Python 3 standard library. The QML side never runs adb or touches
state files; it runs `bin/omarchy-android-dev <command>` and renders the
one-line JSON document that comes back. See cli.py for the contract.
"""

import json
import os

PLUGIN_ID = "costafot.android-dev"
APP_NAME = "Android Dev"


def plugin_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def plugin_version():
    """The manifest's version is the single source of truth."""
    try:
        with open(os.path.join(plugin_root(), "manifest.json"), "r", encoding="utf-8") as f:
            return str(json.load(f).get("version", "dev"))
    except (OSError, ValueError):
        return "dev"
