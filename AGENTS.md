# omarchy-android-dev — agent notes

Before committing, re-read this file, the README and CHANGELOG against what actually changed and fix anything now stale. This file is the current-state reference: what the code does today and the rules for changing it safely. The session journal is the commit messages. Future work goes in `IDEAS.md`, never here.

The multi-session plan (decisions, verified platform facts, architecture, helper contract, per-session scope with acceptance commands, invariants, the marketplace survey) lives in `~/.claude/plans/hey-so-i-made-unified-nautilus.md`. **Start every session by reading its Status line: the bold "Next" names the session to do.** The Windows original is `~/Work/AdbExtension` (C#); `~/Work/omarchy-markets` is the reference for the Quickshell side and for these conventions (its `Store.qml`, `Panel.qml`, `AGENTS.md`, `PUBLISHING.md`); the twelve surveyed plugins are read-only clones under `~/Work/omarchy-android-dev-survey/`.

## What exists (0.1.0: the Python core, terminal only)

The helper that everything else will call: it finds adb, lists and tracks devices, lists packages, runs the per-package actions, reads and flips the developer toggles, fires deep links and takes screenshots, from the terminal. No QML yet beyond two stubs that keep `omarchy plugin validate` green.

```
manifest.json                schemaVersion 1, id costafot.android-dev, kinds service + bar-widget, keepLoaded, defaults + schema for the eight settings
Service.qml / BarWidget.qml  stubs (QtObject {} / Item {}) until 0.2.0
bin/omarchy-android-dev      entry: fixes sys.path, calls androiddev.cli.main
bin/androiddev/__init__.py   PLUGIN_ID, APP_NAME, plugin_version() from the manifest
bin/androiddev/cli.py        argv → one JSON line, exit 0, always; --settings/--serial; Context (state, adb, devices, serial rule); the whole-process alarm
bin/androiddev/adb.py        resolve() order, Adb.run() = argv + -s SERIAL + deadline + bounded reader, error classification, ensure_server() under flock
bin/androiddev/devices.py    devices -l parser, AVD labels, resolve_serial(), require_ready(), the track-devices stream
bin/androiddev/packages.py   pm list / ps -A / dumpsys window parsers, package_info() from one dumpsys package PKG, the sort and sections
bin/androiddev/actions.py    launch restart force-stop kill clear clear-restart uninstall, grant/revoke all, deeplink; the Windows toast texts as `notice`
bin/androiddev/toggles.py    one batched read script, flip() with the Windows commands
bin/androiddev/capture.py    screenshot: exec-out screencap -p → pictures dir → wl-copy → notification
bin/androiddev/state.py      the private state dir, O_NOFOLLOW reads, exclusive-temp + fsync + rename writes, State (selected, last package, recent deep links, package cache)
bin/androiddev/notify.py     omarchy-notification-send and wl-copy as argv, optional, never fatal
bin/androiddev/fmt.py        every cap and every display string
tests/                       fakeadb.py + fixtures/ (captured from the Pixel_10_Pro_Fold emulator, API 37) + test_*.py
```

## The helper contract

```
/usr/bin/python3 bin/omarchy-android-dev [--settings '<json>'] [--serial S] <command> [args]
```

`--settings` carries the plugin's shell.json scalars (`adbPath screenshotDir apkDir scrcpyArgs notify deviceNotifications confirmUninstall showSystemApps`); unknown keys are ignored, defaults are in `cli.SETTING_DEFAULTS` and must match `manifest.json`. `--serial` wins over the remembered device.

Envelope on every document: `schema_version:1, command, ok, error, generated_at, adb:{path, source}`, then the payload; device commands add `selected`. `error` is `{code, message, stderr?}` with codes `no_adb no_device many_devices unauthorized offline adb_failed bad_args timeout too_much_output state_corrupt internal`. **A document can carry `ok:true` and an error at the same time** (`state_corrupt` rides with a good answer); consumers treat "has data" and "has error" independently. `notice` is the one-line human result the panel shows and a notification carries.

| Command | Payload |
|---|---|
| `status` | `version python state_dir state_dir_text tools:{scrcpy emulator terminal wl_copy}:{found path} adb_version devices selected`; with no adb: `error.code no_adb`, the rest still filled |
| `devices` | `devices[] {serial state model product device transport_id kind avd label selected}`, `selected`; `kind` is `emulator` (`emulator-*`, `localhost:*`), `wifi` (a `:` in the serial) or `usb`; `label` is the AVD name from `emu avd name` for a running emulator, else the model with `_` → space, then ` (SERIAL)` |
| `select SERIAL` | writes `state.selected`; `devices selected notice` |
| `track` | streaming: `{"event":"devices", devices, selected, added[], removed[], unauthorized[], initial}` per frame of `adb track-devices` (details from one `devices -l` per frame); `{"event":"error", error}` once when adb is missing or goes away, then exit 0; SIGTERM/SIGINT end it and the adb child with it |
| `packages` | `packages[] {name running foreground debuggable section}` sorted Foreground → Running → Debuggable → name; `foreground count system_apps last_package`; `debuggable` is `null` until that package has been opened once |
| `package PKG` | `name version_name version_code debuggable launcher_activity runtime_permissions[{name granted}] running foreground`; remembers `last_package` per serial and the debuggable flag for the next list |
| `app ACTION PKG` | `notice action package`, `activity` for the launches; ACTION ∈ `launch restart force-stop kill clear clear-restart uninstall` |
| `perms grant\|revoke PKG` | `notice granted\|revoked total failed[]`; every `name: granted=…` line under the first `runtime permissions:` block, whatever its prefix |
| `deeplink URL [PKG]` | `notice url package recent_deeplinks[]` (10 kept); the URL must have a scheme and no whitespace or control characters |
| `screenshot` | `notice path path_text size size_text copied notified warning` |
| `toggles` | `toggles:{animations touches pointer layout airplane wifi data bluetooth}:{on text label}`, `api`; `on` is `null` and `text` `unknown` when the device answers nothing readable |
| `toggle NAME [on\|off]` | `notice toggle on toggles api` (the fresh states after the flip) |
| `help` | `commands[{usage text}] text` |

Serial rule (`devices.resolve_serial`): `--serial` wins; else `state.selected` if that device is still attached; else the only attached device; else `many_devices`/`no_device`. Then `require_ready`: a device in state `unauthorized` or `offline` is its own error code with the hint the user needs, before any device command runs.

adb resolution (`adb.resolve`): `OMARCHY_ANDROID_DEV_PATH` overrides everything (tests; a non-executable value means "no adb"); else the `adbPath` setting (a file, or a directory containing `adb`); else `$ANDROID_HOME`/`$ANDROID_SDK_ROOT` `platform-tools/adb`; else `~/Android/Sdk/platform-tools/adb`; else PATH. `status` reports which as `adb.source` (`override setting env home path`).

Environment: `OMARCHY_ANDROID_DEV_STATE_DIR` (tests), `OMARCHY_ANDROID_DEV_DEBUG=1` (argv, exit codes and byte counts on stderr; nothing on stdout), `OMARCHY_ANDROID_DEV_TOTAL_BUDGET` (whole-run alarm, 60 s, 0 disables; `track` disarms it), `OMARCHY_ANDROID_DEV_NOTIFY` / `OMARCHY_ANDROID_DEV_WL_COPY` (recording scripts in tests), `OMARCHY_SCREENSHOT_DIR` (Omarchy's own), `ANDROID_ADB_SERVER_PORT` / `ANDROID_ADB_SERVER_ADDRESS` (adb's own; the tests set the port to a closed one).

## Hard-won constraints — do not re-litigate without re-testing

- **Never crash.** `cli.main` catches `BaseException`; a traceback on stdout would be parsed as garbage by QML and blank the bar. Errors ride inside the JSON. Verified: `bin/omarchy-android-dev bogus; echo $?` → 0.
- **Every adb call goes through `Adb.run`**: absolute binary, argv list, `-s SERIAL` on every device command, `timeout=` (10 s default, 60 s for uninstall, 30 s for screencap, none for `track`), `cap=` (256 KiB default, 1 MiB for `pm list`/`dumpsys`, 20 MiB for screencap). The reader threads stop at the cap and kill the child; `too_much_output` is an error, never a parse. Package names, URLs and paths are single argv entries; the Windows `\"…\"` quoting must not be copied. The one shell script in the tree (`toggles.READ_SCRIPT`) is a fixed string with no device data in it.
- **The failure rule is wider than Windows'**: exit code ≠ 0, or `error:` on stderr, or a stdout line starting `Failure`, `Error:` or `Failed`. `pm clear` on an unknown package prints `Failed` with exit 0; `adb uninstall` prints `Failure [DELETE_FAILED_INTERNAL_ERROR]` with exit 1; both are caught (`shell pm uninstall` exits 0 on failure, which is why `uninstall` uses the host verb).
- **`ensure_server()` runs once per helper run**, under `flock` on `<state dir>/adb-server.lock` (non-blocking loop, 10 s ceiling). Under the lock: a stamp written by another holder within 10 s means skip; a connect to adb's server port that succeeds means skip; otherwise `adb start-server`, then write the stamp. Dori PR #4 is the crash this prevents (two clients at login, one aborts on the busy socket). `test_two_helpers_at_once_start_the_server_once` runs two helpers against a fake that sleeps in `start-server`.
- **Cold-start banner.** The first adb call after boot prints `* daemon not running; starting now at tcp:5037` / `* daemon started successfully` on stdout ahead of its result; `fmt.lines()` drops every line starting with `*`. Fixture `devices_l_coldstart.txt`.
- **`screencap -p` on the foldable emulator prints `[Warning] Multiple displays were found…` ahead of the PNG** (seen 2026-09-05, API 37). `capture.split_png` looks for the signature within the first 4 KiB, keeps the image and returns the text as `warning`. Anything without a signature is `adb_failed` and no file is written.
- **The foreground package** comes from `dumpsys window` `mCurrentFocus=Window{… u0 PKG/ACTIVITY}` (still there on API 37) with `dumpsys activity activities` `topResumedActivity=` as the fallback. `ps -A` rows are matched on the `u0_a*` user and the last column with any `:subprocess` suffix removed, so a package with only a service process counts as Running (Windows compared the raw name and missed those).
- **`dumpsys package PKG` prints the package twice** for an updated system app (the installed copy under `Packages:`, then the stub under `Hidden system packages:`); `parse_package_dump` reads the first section only and stops at the second header. Runtime permissions are the first `runtime permissions:` block (user 0), ended by a dedent.
- **Emulator labels** cost one `adb -s SERIAL emu avd name` per running emulator per `devices` call (5 s timeout, `OK` line skipped). A phone's label is its model with `_` → space. `devices -l` states include `no permissions (…)` with spaces; the parser handles it.
- **Toggles are read in one `adb shell`** (`toggles.READ_SCRIPT`: `api=`, `layout=`, then `namespace:key=value` lines). Animations are on unless `window_animation_scale` is `0`; a `null` setting is "never set" (off for touches/pointer/layout/airplane, unknown for wifi/data/bluetooth). Airplane mode uses `cmd connectivity airplane-mode enable|disable` on API ≥ 30 and `settings put` + the broadcast before that. Layout bounds needs `service call activity 1599295570` after `setprop debug.layout`. Every flip re-reads and returns all eight.
- **State files** (`state.py`): the dir is verified on every run (not a symlink, a directory, owned by us, no group/other bits; a failing dir means no state is read or written and `state_corrupt` rides in the envelope); reads open `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`, `fstat` a regular file under 64 KiB and read through the descriptor; a symlink (`ELOOP`), an oversized or an unparsable file is renamed to `<name>.bak.<ts>` (rename never follows the link) and reported once; writes are `mkstemp` in the same dir (0600, `O_EXCL`), `fsync`, `os.replace`. No `/tmp` anywhere. `packages-<serial>.json` uses `state.file_token()` for the serial (`:` → `_`).
- **The whole run has a budget** (`OMARCHY_ANDROID_DEV_TOTAL_BUDGET`, 60 s): `cli.main` arms `SIGALRM`, the handler raises `cli.Deadline` (a `BaseException`), `dispatch` answers `error.code timeout`; `track` disarms it. Python runs the handler between bytecodes, so a `proc.wait()` is interrupted but a stuck C call is not: that is what the store's kill timer will be for in 0.2.0.
- **Notifications and the clipboard are optional.** `notify.send` and `notify.copy_file` run `omarchy-notification-send` / `wl-copy` as argv with a 5 s timeout and return False on any failure; the screenshot is already on disk. `notify:false` in the settings silences notifications; nothing else is affected.
- **Nothing is killed by name.** The only children signalled are the ones `Adb.run` and `track` hold; no `pkill`, no `pgrep`, no PID files.
- **No string in the tree names a privilege-escalation, package-manager, service-manager or clone-and-run command** (the seven tokens are in the plan file's invariant 17; the marketplace baseline flags each as a capability and a maintainer then has to rule on it). Say "install the `android-tools` package or the SDK platform-tools" without a command. This sentence is worded the way it is for the same reason.
- Formatting is Python's job (`fmt.py`: labels, `on`/`off`, sizes, paths with `~`); QML will render strings and never build one from device data. Every field is cut at 256 characters with `\r`, ANSI sequences and control characters removed; lists are capped (devices 32, packages 4000, permissions 512, AVDs 64, APKs 200, recent deep links 10).
- The manifest's `version` is the single source of truth (`androiddev.plugin_version()`); bump it with the CHANGELOG in the same commit. The manifest `defaults` must equal `cli.SETTING_DEFAULTS` (a test pins that from 0.6.0).

## Testing

```bash
python3 -m unittest discover -s tests -v            # 86 offline tests, ~10 s; no device, no real adb, no network
python3 -W error::ResourceWarning -m unittest discover -s tests   # the pipes are closed too
omarchy plugin validate /home/costa/Work/omarchy-android-dev
mkdir -p /tmp/qmlimports && ln -sfn /usr/share/omarchy/shell /tmp/qmlimports/qs
/usr/lib/qt6/bin/qmllint -I /tmp/qmlimports *.qml | grep -v 'on type "QObject"'   # qmllint is not on PATH
```

`tests/_paths.py` gives every test a temp state dir, the fake adb (`OMARCHY_ANDROID_DEV_PATH=tests/fakeadb.py`), a rule script (`OMARCHY_ANDROID_DEV_FAKE_SCRIPT`), an argv log (`OMARCHY_ANDROID_DEV_FAKE_LOG`, one JSON list per call), a recorder for the notifier and wl-copy, and `ANDROID_ADB_SERVER_PORT=9` so `ensure_server()` never sees the real server. Rules are `{"match": "substring of the argv", "stdout" | "stdout_file" (a fixture) | "stdout_hex" | "bytes": N, "stderr", "code", "sleep", "sleep_after"}`; `add_rules()` prepends so the last rule added wins. Fixtures were captured from the Pixel_10_Pro_Fold emulator (API 37) on 2026-09-05 and trimmed; `pm_list_3.txt` adds two composed names so the sort is testable, `devices_l_coldstart.txt` carries the banner.

Live, against the emulator (`~/Android/Sdk/emulator/emulator -avd Pixel_10_Pro_Fold &`):

```bash
export OMARCHY_ANDROID_DEV_STATE_DIR=$(mktemp -d)   # keep the real state dir clean while trying things
bin/omarchy-android-dev status | jq '{adb, adb_version, selected, tools}'
bin/omarchy-android-dev devices | jq '.devices[] | [.serial,.state,.label]'
bin/omarchy-android-dev packages | jq '.packages[] | [.name,.section]'
bin/omarchy-android-dev package com.android.chrome | jq '{launcher_activity, n: (.runtime_permissions|length)}'
bin/omarchy-android-dev app launch com.android.chrome | jq .notice
bin/omarchy-android-dev toggles | jq '.toggles.animations'
bin/omarchy-android-dev toggle touches | jq .notice; bin/omarchy-android-dev toggle touches | jq .notice
bin/omarchy-android-dev screenshot | jq '{path, copied, notified, warning}'
bin/omarchy-android-dev deeplink https://example.com | jq .notice
OMARCHY_ANDROID_DEV_PATH=/nonexistent bin/omarchy-android-dev devices | jq '.error.code'; echo $?   # "no_adb", 0
timeout 3 bin/omarchy-android-dev track | head -1 | jq '.devices|length'
OMARCHY_ANDROID_DEV_DEBUG=1 bin/omarchy-android-dev packages >/dev/null   # argv log on stderr
bin/omarchy-android-dev bogus; echo $?                                    # JSON with ok:false, exit 0
```

`perms grant` and `perms revoke` change the device: on 2026-09-05 a live `perms grant com.android.chrome` granted all thirteen and the extra ten were revoked by hand afterwards. Prefer a throwaway package for live tries.

## Dev loop

Terminal only until 0.2.0. Edit, run the suite, try the command against the emulator. The QML loop (symlink into `~/.config/omarchy/plugins`, `rescanPlugins`, `omarchy restart shell` after every QML edit, `journalctl -t omarchy-shell -f`) is in the plan file and lands here with Session 2.

## Roadmap (one session each; details in the plan file)

~~0 survey the marketplace's twelve Android plugins~~ · ~~1 repo docs + Python core (terminal only)~~ (done, 0.1.0) · 2 service, bar widget, hub · 3 devices, packages, actions, deep links (the `deeplink` command already exists; the pages remain) · 4 toggles, screenshot, screen record · 5 APK manager, send text, tools · 6 settings page, IPC, keybinding docs · 7 release polish 1.0.0 · 8 publish (marketplace, projects page, blog draft)

Each session ends with tests green, `omarchy plugin validate` clean, `qmllint` clean, this file updated, a `CHANGELOG.md` entry with the `manifest.json` version bump, and the plan file's Status line appended. Commit only when Costa asks; never push, amend or add co-author trailers.
