# Changelog

## 0.1.0

- The Python core, terminal only: `bin/omarchy-android-dev` finds adb (the `adbPath` setting, `$ANDROID_HOME`/`$ANDROID_SDK_ROOT`, `~/Android/Sdk`, then PATH), lists and tracks devices, lists packages and one package's details, runs the seven per-package actions and the two permission sweeps, fires deep links, reads and flips the eight developer toggles, and takes a screenshot to the pictures folder, the clipboard and a notification. Every answer is one JSON line, exit 0, errors inside.
- Every adb call is an argv array with `-s SERIAL`, a deadline and a byte cap at the reader; a child that outruns the cap is killed and reported as `too_much_output`, never parsed. `adb start-server` runs once per helper run under a lock file, so two clients starting together at login cannot both fork a server. The cold-start banner is skipped. Emulators are labelled by their AVD name (`Pixel 10 Pro Fold (emulator-5554)`).
- State in `~/.local/state/omarchy/costafot.android-dev/`: a 0700 directory checked on every run, files read through `O_NOFOLLOW` descriptors with a size cap, written as exclusive 0600 temp files, fsync, rename. A symlinked or unreadable file is set aside and reported once as `state_corrupt`.
- A foldable emulator's `screencap -p` prints a multiple-displays warning ahead of the PNG; the helper finds the signature and keeps the image.
- Repo docs: `AGENTS.md`, `IDEAS.md` (the Windows wishlist, the open questions and the 1.x slots), this file; `TODO.md` folded into them and removed. `manifest.json` with both kinds and stub entry points so `omarchy plugin validate` passes; the QML arrives in 0.2.0.
- 86 offline tests against a fake adb; no device, no real adb, no network.
