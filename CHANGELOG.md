# Changelog

## 0.5.0

- **APKs**: a folder box prefilled from the `apkDir` setting lists the `.apk` files in it as you type; Enter on one installs it (`adb install -r -t`, so a debug build marked testOnly installs too) and the row says Installed or quotes adb's `Failure [...]`; **Install all** runs the files one after another, each its own helper run, with one summary notification.
- **Send text**: type a line and press Enter to have it typed into the focused field on the device (`input text`, spaces as `%s`, the rest quoted for the device shell), or send the clipboard through `wl-paste`. Non-ASCII, line breaks and more than 500 characters are refused with a plain message rather than typed wrong. IPC `text TEXT` and `clipboard`.
- **Tools**: Mirror with scrcpy (`scrcpy -s SERIAL --window-title "Android Dev"` plus the `scrcpyArgs` setting; the row appears once scrcpy is installed, no restart needed), Logcat for the last package (`adb logcat --pid=…` in the default terminal through `xdg-terminal-exec`, the way Omarchy opens one), and one row per AVD showing Running or Stopped: Enter starts a stopped one (`emulator -avd NAME`, refused while it runs) and stops a running one (`adb emu kill`) behind the same confirm dialog as Uninstall. Everything launched here is detached and, with `uwsm-app` present, given its own scope outside the shell's, so a shell restart cannot take it down; the plugin never signals it. The AVD rows follow the device tracker, so Running turns into Stopped once the emulator is really gone. IPC `scrcpy`, `avd NAME`, `logcat [PKG]`; `page` accepts `apks text tools`.
- Helper: `apk list [DIR]`, `apk install PATH...`, `text send TEXT`, `text clipboard`, `tools`, `tool scrcpy|avd NAME|avd-stop SERIAL|logcat [PKG]`; `status.tools` gains `wl_paste` and `status` names the APK folder; a new error code `no_tool` for a missing scrcpy, emulator, terminal or wl-paste. A helper run that hits its whole-process budget now kills the adb call in flight instead of leaving it to finish unseen.
- 126 offline tests, with fake scrcpy, emulator, terminal and wl-paste scripts next to the fake adb.

## 0.4.0

- **Toggles**: the eight developer toggles (Animations, Show touches, Pointer location, Layout bounds, Airplane mode, Wi-Fi, Mobile data, Bluetooth) as rows with their state read from the device in one call; Enter flips one and every row repaints from the answer. Airplane mode goes through `cmd connectivity` on API 30 and up. IPC `flip NAME` (`toggle` is the panel verb).
- **Capture**: Screenshot from the panel, and screen recording: `screenrecord` runs on the device while the row counts the seconds and the bar glyph turns red with a dot; stopping pulls the mp4 into the videos folder (`OMARCHY_SCREENRECORD_DIR`, else `~/Videos`, or the new `recordingDir` setting), removes the device copy and notifies. IPC `record start|stop|toggle`; `page` accepts `toggles` and `capture`. The hub shows the running recording.
- Helper: `record` streams a `recording` event and the final document; it ends on Ctrl-C, SIGTERM or screenrecord's own 3 minute limit, waits for the device file to stop growing, then pulls. `status` names the screenshot and recording folders. A `recordingDir` setting joins the eight; a test pins the manifest defaults and schema to the helper's.
- Fixed before release: the shell starts its processes with SIGINT ignored and the adb child inherited it, so the first `record stop` did nothing; the helper now installs its handlers before spawning adb, resets SIGINT in every long-lived child and stops the adb client with SIGTERM.
- 98 offline tests, the recorder among them (SIGINT, SIGTERM and SIGKILL against a fake screenrecord that sleeps; a screenrecord that fails at once).

## 0.3.0

- The first pages: **Devices** (the picker: every attached device with its state, Enter selects), **Apps** (the package list with a filter box, the Foreground, Running, Debuggable and Other sections, the last package used on that device on top, `r` lists again), the **actions** page for a package (the version and launcher activity, then Launch, Restart, Kill process, Clear app data, Clear data and restart, Force stop, Open deep link, Uninstall behind a confirm dialog, Grant and Revoke all permissions, each with its adb command as the second line) and **Deep link** (a URL box, the recent links, optionally scoped to one package). The hub's device row opens the picker; the Apps and Deep link rows are live.
- Every action runs through the service, so the result is both the notice row in the panel and a notification with the device's label. An error is an urgent notice and a notification too.
- IPC: `launch PKG`, `forcestop PKG`, `clear PKG`, `deeplink URL`; `page` accepts `hub devices packages deeplink`.
- Helper: `packages[].detail` (`foreground · debuggable`, `running`, …, the Windows subtitle), `status` carries `last_package` for the selected device and `recent_deeplinks`, so the panel can show both before anything runs.
- Boolean settings set as words (`omarchy bar set costafot.android-dev showSystemApps false` without `--json` stores `"false"`) are read as booleans by the helper and the store; before, the word was truthy and system apps stayed listed.
- 90 offline tests.

## 0.2.0

- First QML: the plugin is in the bar. `Service.qml` (loaded once per shell while the plugin is enabled) owns the Store, the device tracker and the IPC target; `BarWidget.qml` shows the droid glyph with the device count, dimmed with no device, red while the selected one waits for authorisation, and opens the hub; `Panel.qml` is the hub: the selected device with its state, the pages to come as muted rows, `j`/`k`, Enter, `r`, Escape.
- `Store.qml` runs the helper the way Markets does (one process at a time, last command wins, `/bin/sh -c exec` in front of `/usr/bin/python3`, a 1 MiB tripwire, the 60 s budget passed as `OMARCHY_ANDROID_DEV_TOTAL_BUDGET`, SIGTERM then SIGKILL after it) plus a run generation, so a timer armed for a killed run can never touch the next one.
- The tracker is one `omarchy-android-dev track` process with a `SplitParser`; it restarts with a 5 s to 60 s backoff and at once when the settings change. Each frame replaces the device list; a device connecting, disconnecting or waiting for authorisation sends a notification (`deviceNotifications`, `notify`).
- IPC target `costafot.android-dev`: `help open close show hide toggle page status devices select screenshot refresh`. Action verbs return at once; the helper's own notification carries the result.
- Helper: `devices[].detail` (`Emulator · ready`, `USB · needs authorising: accept the prompt on the device`) so the hub renders a string Python built; the tracker re-reads the state file every frame so a `select` from another run is seen; the helper and the tracker's adb child ask the kernel for SIGTERM when their parent dies (`PR_SET_PDEATHSIG`), because the shell ends an unwanted helper with SIGKILL and an `adb track-devices` was left behind without it.
- 88 offline tests.

## 0.1.0

- The Python core, terminal only: `bin/omarchy-android-dev` finds adb (the `adbPath` setting, `$ANDROID_HOME`/`$ANDROID_SDK_ROOT`, `~/Android/Sdk`, then PATH), lists and tracks devices, lists packages and one package's details, runs the seven per-package actions and the two permission sweeps, fires deep links, reads and flips the eight developer toggles, and takes a screenshot to the pictures folder, the clipboard and a notification. Every answer is one JSON line, exit 0, errors inside.
- Every adb call is an argv array with `-s SERIAL`, a deadline and a byte cap at the reader; a child that outruns the cap is killed and reported as `too_much_output`, never parsed. `adb start-server` runs once per helper run under a lock file, so two clients starting together at login cannot both fork a server. The cold-start banner is skipped. Emulators are labelled by their AVD name (`Pixel 10 Pro Fold (emulator-5554)`).
- State in `~/.local/state/omarchy/costafot.android-dev/`: a 0700 directory checked on every run, files read through `O_NOFOLLOW` descriptors with a size cap, written as exclusive 0600 temp files, fsync, rename. A symlinked or unreadable file is set aside and reported once as `state_corrupt`.
- A foldable emulator's `screencap -p` prints a multiple-displays warning ahead of the PNG; the helper finds the signature and keeps the image.
- Repo docs: `AGENTS.md`, `IDEAS.md` (the Windows wishlist, the open questions and the 1.x slots), this file; `TODO.md` folded into them and removed. `manifest.json` with both kinds and stub entry points so `omarchy plugin validate` passes; the QML arrives in 0.2.0.
- 86 offline tests against a fake adb; no device, no real adb, no network.
