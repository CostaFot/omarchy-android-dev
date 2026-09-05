# Ideas

Backlog, not commitments. Dead ideas stay here marked as such so they are not re-pitched. The 1.0 roadmap itself is in `AGENTS.md`; this is what comes after it, or what was left out on purpose.

## From the Windows wishlist and the scaffold's open questions

- **Wireless debugging** (`adb pair` with the code on stdin, `adb connect`, then `get-state` until `device`; `adb mdns services` or avahi `_adb-tls-connect._tcp` for discovery). Decided out of 1.0 on 2026-09-05: USB and emulators only. `adb connect` exits 0 on failure and success is the substring `connected to`; `pair` takes the code on stdin, never argv.
- **Non-ASCII text** for Send text: Android's `input text` is ASCII only. ADBKeyboard (a broadcast to `ADB_INPUT_TEXT` with base64) is the usual answer and needs an APK on the device; a `bad_args` with a plain message is what 1.0 does.
- **Split APKs** (`.apks`, `.xapk`, `adb install-multiple`) in the APK manager. 1.0 installs single `.apk` files.
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
- **A full-screen `panel` kind** for a logcat or picker surface that outgrows the popup.

## Helper details worth revisiting

- The `page` IPC verb opens the panel on the first registered bar widget when none is open; `open`/`toggle` go through the shell and pick the focused monitor. With two monitors `page` can open on the other one.

- `screencap -p` on a device with several displays (the foldable emulator) prints a warning ahead of the PNG and picks the first display; `-d <id>` from `dumpsys SurfaceFlinger --display-id` would let the user choose. 1.0 strips the warning and keeps the image.
- A second `ps -A` format: some vendor ROMs print `ps` without the `u0_a` user column, so nothing shows as Running. A `pidof`-based fallback per listed package would be many calls; `dumpsys activity processes` is one.
- `resolve-activity` on packages with several launcher activities returns one; a picker would need `cmd package query-activities`.

## Seen elsewhere, out of scope by name

- Screen preview thumbnail with tap and swipe (Omadroid), webcam and v4l2 (Omacam, Dori), AirPlay and iPhone (OmaGlass, Omarchy Phone), notification relay (Dori), HLS live stream (Omadroid removed it under review), scrcpy `--record` as the recording path (we record on-device with `screenrecord` and pull), a Ruby UI runtime (Omarchy Phone), Mac simulators (Simfarm), iOS through libimobiledevice. Android Dev is the developer's side of the device; the marketplace has five mirroring plugins and two webcam ones.
