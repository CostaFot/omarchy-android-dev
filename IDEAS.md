# Ideas

Backlog, not commitments. Dead ideas stay here marked as such so they are not re-pitched. The 1.0 roadmap itself is in `AGENTS.md`; this is what comes after it, or what was left out on purpose.

## From the Windows wishlist and the scaffold's open questions

- **Wireless debugging** (`adb pair` with the code on stdin, `adb connect`, then `get-state` until `device`; `adb mdns services` or avahi `_adb-tls-connect._tcp` for discovery). Decided out of 1.0 on 2026-09-05: USB and emulators only. `adb connect` exits 0 on failure and success is the substring `connected to`; `pair` takes the code on stdin, never argv.
- **Non-ASCII text** for Send text: Android's `input text` is ASCII only. ADBKeyboard (a broadcast to `ADB_INPUT_TEXT` with base64) is the usual answer and needs an APK on the device; a `bad_args` with a plain message is what 1.0 does (0.5.0). A literal `%s` in the text becomes a space on the device (input's own escape); nobody has asked for a way around it.
- **Split APKs** (`.apks`, `.xapk`, `adb install-multiple`) in the APK manager. 1.0 installs single `.apk` files.
- **Recent APK folders** in the folder box (the plan's `recent_apk_dirs`): 0.5.0 prefills the `apkDir` setting and keeps the typed folder only while the page is on the stack. Would be one more list in `state.json`, like the recent deep links.
- **Logcat for a package that is not running**: 0.5.0 refuses (`pidof` finds nothing) and says to launch it first. Launching it and then following its pid, or `logcat` with a `--regex` on the package name as a fallback, would be friendlier.
- **scrcpy's window and the emulator's on Hyprland**: the Tools page launches both through `uwsm-app`; the float rules for the `Emulator` class and scrcpy's `--window-title "Android Dev"` are in the README since 1.0.0 (the emulator's without `center` since the check on 2026-09-05: it moves its windows to its own saved position after map). Done as far as the plugin goes; setting the rules itself would mean writing into `~/.config/hypr`, which it does not do.
- **Pull shared preferences** (`run-as PKG cat shared_prefs/*.xml`) for a debuggable package; a page under the package's actions.
- **Global per-action favorites** as on Windows (star "Launch" for every package). Dead, 2026-09-05: replaced by the last package per device and recent deep links.
- **Keep the panel open after an action** (`keepOpen` on Windows). Dead: the panel stays open by design.

## The 1.x slots (each is an `androiddev` module, a panel page and IPC verbs)

- **Forwarding**: `adb forward`/`reverse` list, add, remove. RN, Flutter and local-API work need it constantly; three adb calls.
- **Tweaks**: dark mode (`cmd uimode night yes|no`), font scale, density and size overrides (`wm density`, `wm size`), locale, demo mode for clean status bars. Reads current state like Toggles; pairs with Capture.
- **Device info**: model, API level, battery (`dumpsys battery` `level:`), IP, screen (`wm size`), memory (`/proc/meminfo`), disk (`dumpsys diskstats` `Data-Free:`), Wi-Fi SSID and RSSI (`dumpsys wifi`), brightness (`settings get|put system screen_brightness`), foreground activity. One batch; hub header material.
- **Wake and hardware keys**: `input keyevent KEYCODE_WAKEUP|BACK|HOME|APP_SWITCH|POWER|VOLUME_UP|VOLUME_DOWN` as a row group.
- **Reboot**: normal, recovery, bootloader; `adb root`; `adb tcpip`. A stepping stone to wireless and fastboot.
- **Files**: drop-to-push, pull to Downloads. The panel already handles paths for APKs.
- **Bug bundle**: screenshot plus filtered logcat plus `bugreport` zip, one Capture row.
- **Emulator console through `adb emu`** (no telnet, no auth token): battery level and charging (`emu power capacity`), GPS fix (`emu geo fix`), calls and SMS (`emu sms send`), network speed and latency (`emu network speed`), rotate, snapshots. One helper verb.
- **AVD management**: create, wipe, cold boot, snapshot load. Extends Tools.
- **Fastboot**: flash, unlock, boot image. Same USB device; the tracker already sees the mode change.
- **Dev loop**: watch a build output directory, install on change, launch, filtered logcat.
- **Fan-out**: run an action or an install on every attached device. Free once every call takes a serial.
- **Agent driver**: a documented stable CLI plus `uiautomator dump`, tap and type by resource id, so a coding agent can drive the app without a screenshot loop. The JSON helper is already the right shape.
- **Maestro**: a Flows page. Find `maestro` (PATH, `~/.maestro/bin`), report it in `status.tools` next to scrcpy; scan a settings-configured directory or the cwd's `.maestro/` for `*.yaml` flows, run one against the selected device (`maestro --device SERIAL test FLOW --format junit --output FILE`, parse the XML for pass/fail per flow and the failing step), the result as the notice and a notification, recent flows kept like recent deep links; `r` re-runs the last one. IPC `flow PATH` so a Hyprland keybinding runs the smoke flow of whatever is being worked on. Rows for `maestro studio` (a browser tab on `localhost:9999`, the device picker in the tool's own UI) and `maestro record FLOW` (an mp4 of the run, next to Capture). `maestro hierarchy` prints the view tree as JSON, a better UI dump for the agent driver than `uiautomator dump`. Fan-out is the obvious "fun" one: the same flow on every attached device at once, one notification per result. Caveats: a JVM app installed by its own script, so `tools.maestro` may be missing with everything else present; a run lasts minutes, longer than the 60 s helper budget, so it wants the tracker's shape (streaming, no alarm) or a detached run with the result read from the junit file; the first run installs `dev.mobile.maestro` and `dev.mobile.maestro.test` on the device, which then show up in the package list (hide them, or tag them); it forwards port 7001, so two runs on one serial collide; the terminal output is colored and chatty, only the junit file is worth parsing; failure screenshots land in `~/.maestro/tests/`, worth a `Show` row.
- **A full-screen `panel` kind** for a logcat or picker surface that outgrows the popup.

## Helper details worth revisiting

- **Leftover recordings on the device.** A shell restart (or `omarchy plugin disable`) mid-recording SIGKILLs the recorder; PDEATHSIG ends the adb client, screenrecord finishes the file, and `/sdcard/omarchy-android-dev-<stamp>.mp4` stays there with nobody to pull it (seen 2026-09-05, the documented limitation). `record` or `status` could list `/sdcard/omarchy-android-dev-*.mp4` and offer a `Pull the leftover recordings` row, or the next `record` could pull them first.
- **`record stop` from a terminal.** The plan had a `record.json` with the recorder's pid and a `stop` verb signalling it; dropped in 0.4.0 because the invariant says no PID files. A terminal recording ends with Ctrl-C, the service's with the signal to its own Process. A `--time-limit N` argument (screenrecord's own; `0` lifts the limit on API 34+) would be the terminal-friendly way if one is ever wanted.
- **Which display a screenshot or a recording targets** on a foldable: `screencap -d` / `screenrecord --display-id` with the ids from `dumpsys SurfaceFlinger --display-id`; see the foldables note below.

- The `page` IPC verb opens the panel on the first registered bar widget when none is open; `open`/`toggle` go through the shell and pick the focused monitor. With two monitors `page` can open on the other one.

- **Foldables act weirdly; come back to them.** Seen on the `Pixel_10_Pro_Fold` AVD (android-37.2-beta3) on 2026-09-05: the emulator window draws the skin misaligned (the inner display over the frame's edge, the hinge along the bottom, a strip of the desktop showing through), `screencap -p` warns about multiple displays and picks the first, and the AVD reports two displays while unfolded. Development moved to the `Medium_Phone` AVD that day. To look at later: which display a screenshot and a recording should target (`-d <id>` from `dumpsys SurfaceFlinger --display-id`), whether the posture (`device_state`) matters to any command, and whether the skin problem is the emulator's or the AVD's.
- **The emulator window on Hyprland.** Checked 2026-09-05 with the `Medium_Phone` AVD, the answers are in `AGENTS.md` (the emulator is XWayland with a detached toolbar window; a `float` rule alone is enough, `center` is a no-op for it, the toolbar follows the floated main window). Dead ends: no launch flag sizes the window or hides the toolbar (`-qt-hide-window` hides everything, `-no-window` is headless), and the launcher rewrites `QT_SCALE_FACTOR` to `none`, so the plugin cannot scale the UI for a HiDPI monitor; the user resizes the window. Still open: an *Extra emulator arguments* setting like `scrcpyArgs`, mostly for `-gpu host` (the log here says `Your GPU drivers may have a bug. Switching to software rendering` on an NVIDIA card and picks swangle), once `-gpu host` is known to work under XWayland with that driver.
- `screencap -p` on a device with several displays (the foldable emulator) prints a warning ahead of the PNG and picks the first display; `-d <id>` would let the user choose. 1.0 strips the warning and keeps the image.
- A second `ps -A` format: some vendor ROMs print `ps` without the `u0_a` user column, so nothing shows as Running. A `pidof`-based fallback per listed package would be many calls; `dumpsys activity processes` is one.
- `resolve-activity` on packages with several launcher activities returns one; a picker would need `cmd package query-activities`.

## Seen elsewhere, out of scope by name

- Screen preview thumbnail with tap and swipe (Omadroid), webcam and v4l2 (Omacam, Dori), AirPlay and iPhone (OmaGlass, Omarchy Phone), notification relay (Dori), HLS live stream (Omadroid removed it under review), scrcpy `--record` as the recording path (we record on-device with `screenrecord` and pull), a Ruby UI runtime (Omarchy Phone), Mac simulators (Simfarm), iOS through libimobiledevice. Android Dev is the developer's side of the device; the marketplace has five mirroring plugins and two webcam ones.
