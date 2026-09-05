# omarchy-android-dev — agent notes

Before committing, re-read this file, the README and CHANGELOG against what actually changed and fix anything now stale. This file is the current-state reference: what the code does today and the rules for changing it safely. The session journal is the commit messages. Future work goes in `IDEAS.md`, never here.

The multi-session port plan (decisions, verified platform facts, architecture, helper contract, per-session scope with acceptance commands, invariants) lives in `~/.claude/plans/hey-so-i-made-unified-nautilus.md`. **Start every session by reading its Status line: the bold "Next" names the session to do.** The Windows original is `~/Work/AdbExtension` (C#); `~/Work/omarchy-markets` is the reference for the Quickshell side and for these conventions (its `Store.qml`, `Panel.qml`, `AGENTS.md`, `PUBLISHING.md`).

## What exists (scaffold, nothing built)

Renamed from omarchy-adb / `costafot.adb` to **omarchy-android-dev / `costafot.android-dev`** (display name Android Dev) on 2026-09-05 before anything was built; the checkout directory and GitHub repo may still say `omarchy-adb` until Costa does the plan's Step 0. `README.md`, `TODO.md`, `LICENSE` from the 2026-09-05 scaffold. `TODO.md` is superseded by the plan file; Session 1 folds it into this file's roadmap and `IDEAS.md` and deletes it.

## Roadmap (one session each; details in the plan file)

~~0 survey the marketplace's twelve Android plugins (patterns, gotchas, ideas; no code)~~ · 1 repo docs + Python core (terminal only) · 2 service, bar widget, hub · 3 devices, packages, actions, deep links · 4 toggles, screenshot, screen record · 5 APK manager, send text, tools · 6 settings page, IPC, keybinding docs · 7 release polish 1.0.0 · 8 publish (marketplace, projects page, blog draft)

Each session ends with tests green, `omarchy plugin validate` clean, `qmllint` clean, this file updated, a `CHANGELOG.md` entry with the `manifest.json` version bump, and the plan file's Status line appended. Commit only when Costa asks; never push, amend or add co-author trailers.
