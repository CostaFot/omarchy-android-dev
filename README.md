# Android Dev for Omarchy

The Android developer's side of a device, on the [Omarchy](https://omarchy.org) bar: pick a device, pick a package, clear its data, force-stop it, fire a deep link, flip the developer toggles, take a screenshot, start an emulator, follow logcat. No terminal, no Android Studio.

Started as a port of the Windows [ADB Extension for Command Palette](https://github.com/CostaFot/AdbExtension), the same way [Markets](https://github.com/CostaFot/omarchy-markets) was a port of the Markets extension, and grew into a device hub.

**Work in progress.** In the bar: a droid glyph that lights up with a device and dims without one (and turns red with a dot while a recording runs), a notification when a device connects or disconnects, and a hub that shows the selected device. The pages hang off it one release at a time; the part that talks to `adb` is complete and works from a terminal.

## In the panel

- **Devices**: every attached device with its state; Enter selects the one the other pages talk to. With one device there is nothing to pick.
- **Apps**: the packages on the device, third-party by default (turn on *Show system apps* to see them all), with a filter box, the running and foreground ones on top and the package you last touched above them. Enter opens a package: its version and launcher activity, then Launch, Restart, Kill process, Clear app data, Clear data and restart, Force stop, Open deep link, Uninstall (asks first), Grant all permissions, Revoke all permissions. Each row names the adb command it runs.
- **Deep link**: type a URL or a deep link and press Enter; the recent ones are listed below and can be fired again. From a package's actions page the link is scoped to that package.
- **Toggles**: Animations, Show touches, Pointer location, Layout bounds, Airplane mode, Wi-Fi, Mobile data and Bluetooth, each with its current state read from the device; Enter flips it and the row repaints. Each row names the adb command behind it.
- **Capture**: Screenshot (saved to your Pictures folder, put on the clipboard, shown in a notification) and Start recording. A recording runs on the device (`screenrecord`, three minutes at most) while the row shows the elapsed time and the bar glyph a dot; Enter again stops it, and the mp4 is pulled into your Videos folder, removed from the device and announced. The folders follow Omarchy's own (`OMARCHY_SCREENSHOT_DIR`, `OMARCHY_SCREENRECORD_DIR`, else `~/Pictures` and `~/Videos`) and can be set in the plugin settings.

Every action shows its result in the panel and sends a notification with the device's name. `j`/`k` or the arrows move, Enter runs, Escape or Backspace goes back, `r` reads again.

## Requirements

`adb`, from the `android-tools` package or the SDK platform-tools. It does not need to be on `PATH`: the plugin looks in `$ANDROID_HOME`, `$ANDROID_SDK_ROOT` and `~/Android/Sdk` too, and a settings key can point at it.

A device over USB, or an emulator. Wireless debugging is not supported.

## Install

```bash
omarchy plugin add https://github.com/CostaFot/omarchy-android-dev --enable
```

## From the shell

```bash
omarchy-shell costafot.android-dev help          # the verbs
omarchy-shell costafot.android-dev toggle        # the hub
omarchy-shell costafot.android-dev status | jq   # adb, devices, the tracker
omarchy-shell costafot.android-dev screenshot    # saved, on the clipboard, with a notification
omarchy-shell costafot.android-dev select emulator-5554
omarchy-shell costafot.android-dev page packages # open the panel on a page: hub, devices, packages, deeplink, toggles, capture
omarchy-shell costafot.android-dev launch com.android.chrome   # forcestop and clear take a package too
omarchy-shell costafot.android-dev deeplink https://example.com
omarchy-shell costafot.android-dev flip touches  # animations, touches, pointer, layout, airplane, wifi, data, bluetooth
omarchy-shell costafot.android-dev record start  # stop pulls the mp4 into ~/Videos; toggle does either
```

Bind any of them to a key in Hyprland the way you would any command.

## From a terminal

Every command answers with one line of JSON. Errors ride inside it; the exit code is always 0.

```bash
bin/omarchy-android-dev status | jq '{adb, selected, tools}'
bin/omarchy-android-dev devices | jq '.devices[] | [.serial, .state, .label]'
bin/omarchy-android-dev packages | jq '.packages[] | [.name, .section, .detail]'
bin/omarchy-android-dev package com.android.chrome | jq '{launcher_activity, runtime_permissions}'
bin/omarchy-android-dev app launch com.android.chrome | jq .notice       # restart, force-stop, kill, clear, clear-restart, uninstall
bin/omarchy-android-dev perms grant com.android.chrome | jq .notice      # or revoke
bin/omarchy-android-dev deeplink https://example.com | jq .notice
bin/omarchy-android-dev toggles | jq '.toggles | map_values(.text)'
bin/omarchy-android-dev toggle touches | jq .notice                     # animations, touches, pointer, layout, airplane, wifi, data, bluetooth
bin/omarchy-android-dev screenshot | jq .path                           # saved, on the clipboard, with a notification
bin/omarchy-android-dev record                                          # records until Ctrl-C, then prints the mp4's path
bin/omarchy-android-dev select emulator-5554 | jq .notice               # with more than one device attached; --serial S does it per call
```

Emulators show up by their AVD name, as in `Pixel 10 Pro Fold (emulator-5554)`.

## How it runs

The plugin never runs `adb` from the shell. A Python 3 helper with no dependencies does, as `/usr/bin/python3` with an argument list, `-s SERIAL` on every device command, a deadline and a size cap on every call. State lives in `~/.local/state/omarchy/costafot.android-dev/`, private to your user. Nothing leaves your machine: `adb` talks to its own server on `127.0.0.1` and to your device.

## Uninstall

```bash
omarchy plugin remove costafot.android-dev
rm -rf ~/.local/state/omarchy/costafot.android-dev
```
