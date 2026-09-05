# Android Dev for Omarchy

The Android developer's side of a device, on the [Omarchy](https://omarchy.org) bar: pick a device, pick a package, clear its data, force-stop it, fire a deep link, flip the developer toggles, take a screenshot, start an emulator, follow logcat. No terminal, no Android Studio.

Started as a port of the Windows [ADB Extension for Command Palette](https://github.com/CostaFot/AdbExtension), the same way [Markets](https://github.com/CostaFot/omarchy-markets) was a port of the Markets extension, and grew into a device hub.

**Work in progress, feature complete.** In the bar: a droid glyph that lights up with a device and dims without one (and turns red with a dot while a recording runs), a notification when a device connects or disconnects, and a hub that shows the selected device with the pages hanging off it. The part that talks to `adb` also works from a terminal. What is left before 1.0 is polish.

## In the panel

- **Devices**: every attached device with its state; Enter selects the one the other pages talk to. With one device there is nothing to pick.
- **Apps**: the packages on the device, third-party by default (turn on *Show system apps* to see them all), with a filter box, the running and foreground ones on top and the package you last touched above them. Enter opens a package: its version and launcher activity, then Launch, Restart, Kill process, Clear app data, Clear data and restart, Force stop, Open deep link, Uninstall (asks first), Grant all permissions, Revoke all permissions. Each row names the adb command it runs.
- **Deep link**: type a URL or a deep link and press Enter; the recent ones are listed below and can be fired again. From a package's actions page the link is scoped to that package.
- **Toggles**: Animations, Show touches, Pointer location, Layout bounds, Airplane mode, Wi-Fi, Mobile data and Bluetooth, each with its current state read from the device; Enter flips it and the row repaints. Each row names the adb command behind it.
- **Capture**: Screenshot (saved to your Pictures folder, put on the clipboard, shown in a notification) and Start recording. A recording runs on the device (`screenrecord`, three minutes at most) while the row shows the elapsed time and the bar glyph a dot; Enter again stops it, and the mp4 is pulled into your Videos folder, removed from the device and announced. The folders follow Omarchy's own (`OMARCHY_SCREENSHOT_DIR`, `OMARCHY_SCREENRECORD_DIR`, else `~/Pictures` and `~/Videos`) and can be set in the plugin settings.
- **APKs**: a folder box, prefilled from the *APK folder* setting (`~/Downloads`), lists the `.apk` files in it as you type. Enter on one installs it (`adb install -r -t`, so a debug build marked testOnly installs too) and the row says Installed or quotes adb's `Failure [...]`. *Install all* runs them one after another.
- **Send text**: type a line and press Enter to have it typed into whatever field has focus on the device, or send the clipboard. Android's `input text` types one line of ASCII; anything else is refused with a plain message rather than typed wrong (a `%s` in the text becomes a space on the device, input's own escape).
- **Settings**: the adb binary, the screenshot, recording and APK folders, the extra scrcpy arguments, and the four switches (notifications, device notifications, confirm uninstall, show system apps) as a form; Save writes them to your `shell.json` and the plugin takes them at once, no restart. The hub's Settings row names the adb in use and how it was found.
- **Tools**: *Mirror with scrcpy* (once scrcpy is installed; the *Extra scrcpy arguments* setting is appended), *Logcat* for the package you last touched (`adb logcat --pid=…` in your default terminal; the app has to be running), and one row per emulator AVD showing Running or Stopped: Enter starts a stopped one and, after a confirm, stops a running one. What the Tools page launches is yours to close; the plugin never kills it.

Every action shows its result in the panel and sends a notification with the device's name. `j`/`k` or the arrows move, Enter runs, Escape or Backspace goes back, `r` reads again.

## Settings

Saved on the plugin's entry in `~/.config/omarchy/shell.json`, from the panel's Settings page or with `omarchy bar set costafot.android-dev KEY VALUE` (`--json` for a boolean; the plain word works too). Either way the plugin picks them up at once.

| Key | Default | What it does |
|---|---|---|
| `adbPath` | empty | The adb binary, or the folder holding it. Empty looks in `$ANDROID_HOME` or `$ANDROID_SDK_ROOT`, then `~/Android/Sdk/platform-tools`, then `PATH`. A path that holds no adb is reported on the hub, not silently replaced. |
| `screenshotDir` | empty | Where screenshots go. Empty uses `OMARCHY_SCREENSHOT_DIR`, else your Pictures folder. |
| `recordingDir` | empty | Where screen recordings go. Empty uses `OMARCHY_SCREENRECORD_DIR`, else your Videos folder. |
| `apkDir` | `~/Downloads` | Where the APKs page starts looking. |
| `scrcpyArgs` | empty | Appended to the scrcpy command line, split on whitespace (`--always-on-top --keyboard=uhid`). |
| `notify` | `true` | Desktop notifications for actions and captures. |
| `deviceNotifications` | `true` | A notification when a device connects, disconnects or needs authorising. |
| `confirmUninstall` | `true` | Ask before uninstalling an app. |
| `showSystemApps` | `false` | List every package on the Apps page, not only third-party ones. |

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
omarchy-shell costafot.android-dev page packages # open the panel on a page: hub, devices, packages, deeplink, toggles, capture, apks, text, tools, settings
omarchy-shell costafot.android-dev launch com.android.chrome   # forcestop and clear take a package too
omarchy-shell costafot.android-dev deeplink https://example.com
omarchy-shell costafot.android-dev flip touches  # animations, touches, pointer, layout, airplane, wifi, data, bluetooth
omarchy-shell costafot.android-dev record start  # stop pulls the mp4 into ~/Videos; toggle does either
omarchy-shell costafot.android-dev text "hello world"          # typed into the focused field; clipboard sends the clipboard
omarchy-shell costafot.android-dev scrcpy                      # mirror the selected device
omarchy-shell costafot.android-dev avd Medium_Phone            # start that emulator
omarchy-shell costafot.android-dev logcat com.android.chrome   # adb logcat --pid in a terminal; no package follows everything
```

Every verb returns at once; the result arrives as a notification and in the panel.

## Keybindings and the menu

Omarchy's bindings live in `~/.config/hypr/bindings.lua`. Two lines give the panel and a screenshot a key (`SUPER + ALT + A` and `SUPER + ALT + C` are free in the defaults; pick others if you use them):

```lua
o.bind("SUPER + ALT + A", "Android Dev panel", "omarchy-shell costafot.android-dev toggle")
o.bind("SUPER + ALT + C", "Android screenshot", "omarchy-shell costafot.android-dev screenshot")
```

The same two as classic Hyprland config lines, for a `bindings.conf`:

```
bindd = SUPER ALT, A, Android Dev panel, exec, omarchy-shell costafot.android-dev toggle
bindd = SUPER ALT, C, Android screenshot, exec, omarchy-shell costafot.android-dev screenshot
```

To put the panel on the Omarchy menu (`SUPER + SPACE`), add a row to `~/.config/omarchy/extensions/omarchy-menu.jsonc`; the second line puts a screenshot row under the Capture submenu:

```jsonc
"android": {"icon":"","label":"Android Dev","action":"omarchy-shell costafot.android-dev toggle","description":"Devices, apps, toggles, captures, APKs, emulators"},
"trigger.capture.android": {"icon":"","label":"Android screenshot","action":"omarchy-shell costafot.android-dev screenshot"},
```

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
bin/omarchy-android-dev apk list ~/Downloads | jq '.apks[].name'        # apk install PATH... installs them in turn
bin/omarchy-android-dev text send "hello world" | jq .notice            # text clipboard sends the clipboard
bin/omarchy-android-dev tools | jq '.avds[] | [.name, .detail]'         # tool scrcpy, tool avd NAME, tool avd-stop SERIAL, tool logcat [PKG]
```

Emulators show up by their AVD name, as in `Pixel 10 Pro Fold (emulator-5554)`.

## How it runs

The plugin never runs `adb` from the shell. A Python 3 helper with no dependencies does, as `/usr/bin/python3` with an argument list, `-s SERIAL` on every device command, a deadline and a size cap on every call. State lives in `~/.local/state/omarchy/costafot.android-dev/`, private to your user. Nothing leaves your machine: `adb` talks to its own server on `127.0.0.1` and to your device. scrcpy, the emulator and the logcat terminal are started detached, the way Omarchy's own launchers start apps, and are never signalled by the plugin; an emulator stops through `adb emu kill`. scrcpy is told to use the same `adb` as the plugin, so a second adb on PATH (the `scrcpy` package installs one) changes nothing.

## Uninstall

```bash
omarchy plugin remove costafot.android-dev
rm -rf ~/.local/state/omarchy/costafot.android-dev
```
