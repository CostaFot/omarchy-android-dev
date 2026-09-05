# TODO

Scaffolded 2026-09-05. Nothing is built; this is the list to come back to.

## First

- [ ] Read the Markets and Autoduck plugins again for the current `manifest.json`, `BarWidget.qml`, `Panel.qml` and helper conventions. Copy the shape, not the code.
- [ ] Decide the surface: bar icon that opens a panel (like Markets), or a `bindd` that opens the panel directly. Probably both.
- [ ] Helper in Python (like Markets' `bin/`) that wraps `adb` and returns JSON. QML never shells out to `adb` itself.
- [ ] Device list: `adb devices -l`, poll while the panel is open, handle zero and many devices.

## Commands to port from AdbExtension

| Windows extension | Omarchy |
|---|---|
| App Commands: Launch, Force Stop, Kill Process, Restart, Clear Data, Clear Data & Restart, Uninstall | [ ] package picker + action list |
| Grant / Revoke All Permissions | [ ] |
| Launch Deep Link | [ ] text field, `am start -a android.intent.action.VIEW -d <url>` |
| Take Screenshot | [ ] `exec-out screencap -p`, save to `~/Pictures/Screenshots`, notify like Omarchy's own screenshot does |
| Toggle Wi-Fi / Mobile Data / Airplane Mode | [ ] |
| Toggle Animations / Layout Bounds / Touch Coordinates | [ ] developer toggles, read current state so the row shows it |
| APK Manager | [ ] install from a file picker or a dropped path; probably last |

## Later

- [ ] Package search-as-you-type with the debounce Markets rejected. Package lists are long, so it makes sense here.
- [ ] Remember the last package per device.
- [ ] `omarchy-shell adb <verb>` CLI mirroring the panel, like Autoduck's.
- [ ] Marketplace submission (see Markets' `PUBLISHING.md`), preview image, entry on the site's projects page.
- [ ] Blog post. Working title: "It looks like you're trying to build an Omarchy plugin".

## Open questions

- Wireless `adb` pairing from the panel, or leave that to the terminal?
- Is `adb` on `PATH` assumed, or is there an Android SDK path setting?
