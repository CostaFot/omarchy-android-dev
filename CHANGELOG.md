# Changelog

## 1.12.1

The pointer for people who set the plugin up through a coding agent (board issue COS-117).

- README: a *From a coding agent* section at the end. It says `AGENTS.md` ships with the plugin and what it covers (the settings and their `omarchy bar set` form, the IPC verbs, the helper's commands and their JSON, the popup and window routing, the constraints), that an agent working in the plugin's folder reads it on its own and how to hand it the path from anywhere else, and that `help` and `status` let it check its own work. The one-line pointer under the install command now points at that section.
- `AGENTS.md` opens with a paragraph for a reader who is not the next session's agent, naming the two sections a configuring agent needs.

## 1.12.0

The Device info page (board issue COS-85).

- Added: a **Device info** page, first on the hub: the device at a glance, read from it in one call. The model and the device's name, the Android version with its API level, security patch and build, the battery with its level, whether and how it is charging, its temperature and health, the IPv4 address with the Wi-Fi network, signal and link speed (and the tunnel interface when a VPN is up on the phone), the screen size, density, state and brightness, the memory and storage free, the activity in the foreground and the uptime. Enter on a row copies its value to the clipboard: the IP address for an `adb connect`, the build for a bug report. `page info` and `window info` open it.
- Added: the helper's `info`: the same nine sections as JSON, the raw values beside the formatted text.
- Tests: 264.

## 1.11.0

The keys beside the mirror (board issue COS-86).

- Added: a strip of the phone's keys drawn along the scrcpy window's right edge while a mirror is up, following it as it is dragged, resized, tiled or moved, and going with it when its workspace is switched away or the window closes: Back, Home, Recents, Volume up, Volume down, Power, then Screenshot and Record (red while a recording runs). scrcpy has the keys as Mod shortcuts and shows nothing on screen; the strip never takes keyboard focus, so typing into the mirror keeps working with it there. The keys go to the selected device (the one *Mirror with scrcpy* started for). The *Keys beside the mirror* setting (`mirrorKeys`, on) turns it off.
- Added: the helper's `key NAME` (`input keyevent` by name: `back home recents power volup voldown wake sleep`) and the IPC verb `key NAME` for a keybinding; `status` carries `mirror` (whether a mirror window is up, where it is, where the strip sits).
- Tests: 253.

## 1.10.0

The Tweaks page (board issue COS-84).

- Added: a **Tweaks** page on the hub, under Toggles, for the display settings flipped while checking a UI: *Dark mode* (`cmd uimode night yes|no`, Enter flips it), *Font scale* (`settings put system font_scale`) and *Display scale* (`wm density`), each with its current value read from the device in one call. Enter on either scale opens a picker with Android's own steps (the font size stops 0.85 to 2.0; the Display size stops as ratios of the physical density, Small to Largest, made even as Settings does), a check on the current one; Enter sets it and goes back. The Default stop of the display picker is `wm density reset`, because an override survives a reboot and leaves a phone looking odd until it is put back; the page says so under the row while one is set.
- Added: the helper's `tweaks` (the three with their steps) and `tweak dark [on|off]`, `tweak font [SCALE|next]`, `tweak density [DPI|reset|next]` (`next` steps through the stops, wrapping), and the IPC verbs `dark on|off|toggle`, `fontscale SCALE|next` and `density DPI|reset|next`, so a keybinding can flip dark mode or step the font size while looking at the app. `page tweaks` and `window tweaks` open the page.
- Tests: 246.

## 1.9.0

Two small choice pages (board issues COS-91 and COS-105).

- Added: a stopped emulator's row on the Tools page now asks how to start it: *Quick boot* (the emulator's default, the saved snapshot) or *Cold boot* (`emulator -avd NAME -no-snapshot-load`, the way out of a snapshot that misbehaves). Enter starts it and goes back to Tools; Escape goes back without starting anything. The helper takes `tool avd NAME cold`, and `omarchy-shell costafot.android-dev avdcold NAME` is the cold boot's verb (`avd NAME` stays the quick one).
- Added: a package with several launcher activities (a debug build with LeakCanary's Leaks screen in the launcher, an app with several entry points) no longer launches whichever one `resolve-activity` ranks first. The `package PKG` document lists them all (`launcher_activities`, one query scoped to the package; `resolve-activity` stays as the fallback for a shell without it), the actions note names the count, and Launch opens a picker the first time: one row per activity, Enter starts that one and the helper remembers it for the package (`state.json`'s `launch_activities`, fifty kept), so the next Launch, Restart and Clear data and restart go straight to it. A *Launcher activity* row under Launch changes the pick. `app launch|restart|clear-restart PKG ACTIVITY` names one from the terminal; the IPC `launch PKG` follows the pick.
- Tests: 234.

## 1.8.0

The window from the bar and the hub (board issue COS-113).

- Added: the *Open as a window* setting (`openAsWindow`, off by default), on the Settings page and through `omarchy bar set`. With it on, the bar glyph's left click and the `open`, `close`, `toggle` and `page` verbs open the window instead of the popup, so one keybinding serves whichever you prefer. Right click on the glyph opens the other surface (the window with the setting off, the popup with it on), so neither is ever out of reach; middle click keeps re-reading adb. The `window` verb stays explicit either way, and `status.settings` shows the value.
- Added: a hub row, *Open as a window*, at the foot of the popup's page list: Enter closes the popup and opens the window on the hub. The window does not show it.
- Tests: 224.

## 1.7.0

The panel as its own window (board issue COS-97).

- Added: the same pages open as a normal window. `omarchy-shell costafot.android-dev window` takes `open`, `close`, `toggle` or a page name (`window toggles` opens it on that page, or moves an open one there), and the shell's generic `omarchy-shell shell summon costafot.android-dev '{"page":"toggles"}'` does the same. It is a Wayland toplevel (class `org.quickshell`, title `Android Dev`) that Hyprland tiles or floats like any app, resizable, with ordinary keyboard focus: the same keys as the popup, Escape on the hub closes it (so does the window's close button), and Tab does nothing there (in the popup it switches bar panels). It does not replace the bar popup, which stays the one-key panel, and the bar widget stays the tracker's host and the settings' home. The README has a keybinding line and a window rule that floats it phone-sized, to sit beside the mirror.
- Changed: the pages live once. `Panel.qml` is the popup wrapper alone (the kit's Panel and KeyboardPanel around the content, sized to the page under the old cap), `Pages.qml` is the content both hosts show (the page stack, the rows, the boxes, the settings form, the confirm dialog, the keys) and `Window.qml` is the window. The manifest gains the `panel` kind with `Window.qml` as its entry point, and the shell keeps the window loaded (`keepLoaded`), hidden until asked for.
- Changed: with a `panel` kind the shell's own summon and hide route to the window, so the popup verbs (`open`, `close`, `toggle`, `page`) now call the bar's summon directly, the same function the shell used to call for them; they still pick the widget on the focused monitor.
- `status` carries `window: {opened, page, size}` (`size` is the window's own width and height and the content's, so a rule's `size` can be checked); `opened` and `page` stay the popup's.
- Tests: 223.

## 1.6.1

Two small fixes (board issues COS-102 and COS-104).

- Fixed: `omarchy-shell costafot.android-dev page NAME` with the panel closed opened it on the first bar widget the service knew of, which on a two-monitor bar could be the other screen's; `open` and `toggle` went through the shell and picked the focused monitor. `page` now goes the same way: the page waits in the service and the widget the shell summons takes it as it opens.
- Fixed: an Apps page with nothing marked Running or Foreground on a device whose `ps -A` prints no user column (some vendor ROMs do; neither phone here). When ps names no app process at all, the helper reads `dumpsys activity processes` once and takes the running packages from its process list, the same user-0 app-uid range ps's `u0_a` rows cover, so the two paths tag the same packages (checked against the emulator's own ps: equal sets). A ps that fails outright falls back the same way. On every other device nothing changes: no extra call.
- Tests: 220.

## 1.6.0

The folders you install from, kept (board issue COS-80).

- Added: the folders an APK has been installed from are rows at the foot of the APKs page, newest first, ten of them kept. Enter on one puts it in the folder box and the listing follows. Until now the box was prefilled with the *APK folder* setting and a folder typed over it lived only as long as the page stayed on the stack, so a second APK out of a build directory meant typing the whole path again. They sit in `state.json` beside the recent deep links and ride on `apk list`, on `status` and on the answer to an install as `recent_apk_dirs[{path, path_text}]`.
- A folder is remembered when an install has run from it, never when it is listed: the page lists as you type, and a listing that remembered would fill the section with every folder a path was typed past. An APK adb refused remembers its folder too, since a failed install says nothing about where the file came from; a refused path or no device remembers nothing. The folder on screen is not offered back, and no folder row shows while an install runs.
- Fixed: `display_path` turned any path merely sharing the home prefix into a `~` one (`/home/x-backup/apks` → `~-backup/apks`), which never expanded back. It has always been display-only; a folder row hands it back as the folder to list, so the separator is required now.
- Tests: 216.

## 1.5.0

The Wireless page and a VPN in the way (board issue COS-77).

- Added: the Wireless page says when a VPN interface is up on this machine (`A VPN is up: nordlynx`, a note at the foot of the page, not urgent) and what to do if nothing on Wi-Fi ever answers: let LAN traffic through (NordVPN: LAN Discovery) or disconnect it while pairing. A VPN that isolates the LAN was the whole of a lost afternoon on 2026-09-05: every packet to the phone dropped and the helper saw only timeouts. The helper reads `/sys/class/net` for a tunnel interface that is up (wireguard, tun, tailscale, ppp) and spawns nothing; the `wireless` document carries it as `vpn`.
- Added: a connect that times out or fails to reach the phone, a pairing that cannot start its client, and a QR session nobody scanned name the VPN in their error when one is up (`… · a VPN is up (nordlynx); if it isolates the LAN, nothing here reaches the phone`). A wrong pairing code gets no hint: the phone was reached.
- Changed: the entry adb makes for a phone it connected to on its own is labelled by its mDNS instance, `PTP-N49 (adb-AQCK025731000692-WBgDVa)`, instead of the whole service name with `._adb-tls-connect._tcp.` on the end, which filled the hub's row. The serial is unchanged (it is what `-s` and `disconnect` take) and the instance is what *Seen on the network* lists the phone under; the Disconnected notice shows the instance too.
- Tests: 204. `OMARCHY_ANDROID_DEV_NET_DIR` points the suite at a fake `/sys/class/net`, so the developer's own VPN colours no test.

## 1.4.1

The smaller findings of the 1.2.0 review (board issue COS-98).

- Fixed: the QR page rebuilt every row once a second and re-read the code's PNG with it, 120 times a session; the same for the hub's *Recording* and *Pairing* notes and the Capture page's *Stop recording* row. The counters are bound in the rows now and the model stays still; the PNG is loaded off the UI thread, once.
- Fixed: a `record stop` sent while the helper was still listing devices was dropped and the recording went on (the shell starts the helper with SIGINT ignored; the handlers went in only when screenrecord did). They are armed first now, as `pair qr`'s have been since 1.3.1; a stop that lands before screenrecord starts ends the run quietly.
- Fixed: the code step of *Pair with a code* is its own page. Escape or Backspace go back to the addresses with the typed one restored, instead of dropping the whole page and the address with it.
- Fixed: the QR session's `paired` line went out before the state was saved and carried no device list, so the tracker's next frame could move the selection back for a moment; it is written like `pair code`'s answer now, the state first and the fresh list riding along, and a state file that cannot be written is reported instead of swallowed.
- Fixed: `--serial X usb Y` reported the state's selection instead of X; the commands no longer rewrite the `--serial` flag.
- Fixed: a `pair code` typed at a terminal waited a full minute for the digits under the helper's 60 s budget, so nobody typing answered *ran out of time*; the wait is cut to fit the budget and the answer is *no code*.
- Fixed: a connect or a pairing re-read the Wireless page three or four times in a row (its own answer, then every tracker frame); one read after the burst.
- Changed: an address is at most 255 characters (the host 249), inside the 256-character field rule.
- Internal: the recorder and the pairer in `Service.qml` are one `StreamSession` component instantiated twice; they had started to drift.
- Not done, on purpose: `mdns check` and `mdns services` stay two calls in a row on every paint. Running them together would call `mdns services` against an adb that just said it has no mDNS or just failed, which 1.3.3 rules out, and a cache would need a state field keyed on the binary for a few tens of milliseconds.
- Tests: 200.

## 1.4.0

- Changed: *Go wireless* and *Back to USB* have left the Wireless page, and the `tcpip` and `usb` verbs the IPC surface. Pairing by QR code or by code covers what they did: a paired phone connects on its own whenever its Wireless debugging is on, with no cable-first step, no `adb tcpip` that a reboot undoes and no dead `ip:port` entry to clean up after. The *Plugged phones* section went with them. The helper keeps `tcpip` and `usb` for the terminal, unchanged.
- Changed: the *Pair with a code* page no longer asks for the address first. While the phone's *Pair device with pairing code* dialog is open it announces the pairing address on the network, and the page lists each one it sees as a row: Enter takes it, and only the six digits are typed. The page reads the network on entry and on `r` again (the ordered queue of 1.3.2 keeps a pairing code behind that read, which is what had stopped it). Typing the address stays as the fallback, and six digits typed there are refused with a word: on 2026-09-07 the code went into the address box, the panel took it as the address and the second step had nothing left to send.
- Checked live on 2026-09-07: pairing by QR code again, adb connecting on its own after a reconnect, and pairing by code from the panel with a second phone (an OPPO Find X5), the code on stdin end to end. That closes the live pass.
- README: two ways instead of three, the pair-by-code paragraph, the IPC example, the FAQ; `wireless.png` retaken.
- Tests: 197.

## 1.3.3

- Fixed: *Back to USB* left the phone's old Wi-Fi entry in the picker as *Wi-Fi · offline*, in the urgent colour, for minutes: adb keeps retrying an address it was told to connect to. The helper disconnects the dead entry now: the one named, or, when the plugged entry is named, the ones on the phone's Wi-Fi address; an mDNS-named entry (a paired phone adb found on its own) is left for adb to find again. A dropped entry that was the selection moves to the phone on the cable. The `usb` answer lists them as `disconnected`.
- Fixed: *Go wireless* on a network that drops packets could answer the bare *ran out of time* instead of naming the address the phone now listens on. Every connect try takes its full ten seconds there and the retries were checked only after a try, so one started late ran past the helper's budget. A retry is made only while a whole try still fits in what is left of the budget (the first is always made), and the answer is the specific error with the address.
- Fixed: an adb whose server had just died (after `adb kill-server`, say) was reported as having no mDNS, and the Wireless page told the user to change the adb path. Only adb's own *not supported* answer means that; anything else is adb's line as an error with the page's lists still filled, and the panel's note says the check failed rather than that adb has no mDNS. The page's error path no longer runs two more calls against the adb that just failed (up to ten seconds) before its error shows. The `wireless` document's `mdns` gains `supported`: true, false, or null when the check could not be made.
- Checked live on 2026-09-06 with the desktop's VPN letting the LAN through: Go wireless connected to the HONOR phone in under two seconds and Back to USB put it back; Costa paired it by QR code from the panel and adb connected to it on its own (the mDNS-named entry, without a trailing dot here, a form the plugin already took). The phone runs a VPN of its own and answers on its Wi-Fi address regardless. Two things worth knowing: the phone's Wireless debugging switch can read on while its server is not running (nothing on mDNS then; toggle it off and on), and a phone asleep filters multicast, so it answers no mDNS query until it is woken.
- Tests: 196.

## 1.3.2

- Fixed: the *Cancel pairing* row said Escape cancels too. Escape goes back a page everywhere and left the session running: the QR code stayed on disk for up to two minutes and a phone that scanned it meanwhile was paired unwatched. The row says so now, and the hub shows *Pairing · N s left* while a session runs, pointing at the Wireless page, like it does for a recording.
- Fixed: *Back to USB* on the plugged entry itself (and `usb ""` over IPC with the USB phone selected) cleared the selection, and the hub said *No device* with the phone still on the cable. Only a Wi-Fi entry's selection moves, to the one USB phone left.
- Fixed: a pairing code could be dropped without a word. The store held one waiting request and the last one won, so a `pair code` queued behind the Wireless page's own read was replaced by an `r`, a middle click on the glyph or a `page wireless` over IPC: no notice, the phone's dialog timed out. Requests now wait in order: a read (status, devices, packages, a package, toggles, an APK listing, tools, wireless) replaces any read already waiting, an action never is; past eight waiting requests the newcomer is refused with a notice, and a run that hits its budget drops the queue behind it and says how many. The Pair with a code page no longer reads the network on entry or on `r`; it shows nothing from it.
- Fixed: after a pairing, the first new Wi-Fi entry on any host was selected, so a second known phone whose Wireless debugging came on during the wait could be picked and named in the notice. The wait is for an entry on the pairing host (an `ip:port` serial by its host, an mDNS-named one by the host its connect service advertises), and the poll asks for no emulator labels. The QR session lists no devices before the scan; its cancel handlers are armed before the mDNS check, its first adb call.
- README: the state directory no longer lists the recent Wi-Fi addresses, gone since 1.3.0; `wireless-qr.png` retaken with the new Cancel row.
- Tests: 189.

## 1.3.1

- Fixed: a phone adb connected to on its own after pairing was listed as plugged in. adb names that entry after the phone's mDNS service (`adb-<serialno>-<6 chars>._adb-tls-connect._tcp.`, no colon), and the plugin read the kind off the colon alone: the pairing notice named the address instead of the phone, nothing was selected, the Wireless page put the phone under *Plugged phones* with a Go wireless row and offered to connect to it again under *Seen on the network*, and the Tools row said over USB. The name is a Wi-Fi entry now; its service counts as attached; a pairing finds it by the host its service advertises; Disconnect takes the name (from the row and over IPC).
- Fixed: cancelling a QR pairing session in its first moments did nothing. The cancel handlers went in after the adb server check and the device list, and the helper starts with SIGINT ignored, so a `pair stop` while it was still listing devices was dropped and the session ran its two minutes. The handlers are armed first now.
- Tests: 187.

## 1.3.0

- **Wireless**: the *Connect to an address* page is gone, and with it the recent addresses in `state.json` (an old file's list is ignored). A paired phone connects on its own whenever its Wireless debugging is on, and one that is on the network but not attached shows under *Seen on the network* with Enter connecting to it, so typing an address was a third way to do what the other two already do. Pairing is by QR code or by code. The helper's `connect ADDR` stays for the terminal and for Go wireless; the IPC verb `connect` is removed (`disconnect`, `tcpip` and `usb` stay). The `connect`, `tcpip` and `wireless` documents no longer carry `recent_addresses`. 183 tests.

## 1.2.0

- **Wireless**: a new hub page, four ways onto Wi-Fi debugging. *Pair with a QR code*: the panel shows a code, the phone scans it from Developer options › Wireless debugging › Pair device with QR code, the helper waits up to two minutes for the phone's pairing service to appear on mDNS (`adb mdns services`), pairs with the password on `adb pair`'s stdin, and adb connects on its own from then on whenever the phone's Wireless debugging is on. *Pair with a code*: the address and six digits from Pair device with pairing code, in two steps through the one box; the code travels on stdin to the helper and on to adb, never on an argument list. *Connect to an address*: `adb connect`, which exits 0 on failure and is judged by its text, then `get-state` until the device is ready; the last ten addresses are kept. *Go wireless* for a plugged phone: `adb tcpip 5555`, the phone's Wi-Fi address from `ip route`, connect, the Wi-Fi entry selected, so the cable can come out; each Wi-Fi entry has Disconnect and *Back to USB* (`adb usb`), and the connect services seen on the network are rows too. The QR payload is a Wi-Fi-credential string by format (`WIFI:T:ADB;S:…;P:…;;`), so the page says to scan it from that screen only: a camera app would try to join a network that does not exist. With an adb that has no mDNS (the `android-tools` one) the QR row becomes a note and the other three paths stay; without `qrencode` (in Omarchy's base set) likewise. No new setting.
- Helper: `wireless`, `pair qr` (streaming, like `record`: a `pairing` event naming the PNG, then `paired` or an error; SIGINT or SIGTERM cancel it quietly and remove the PNG), `pair code ADDR`, `connect ADDR`, `disconnect ADDR`, `tcpip [USBSERIAL]`, `usb [SERIAL]`. `Adb.run` takes `stdin=` and `pdeathsig=`; `status.tools` and `tools` gain `qrencode`; `state.json` gains `recent_addresses`; the pairing PNG is a 0600 file in the state dir, removed when the session ends and swept by the next one. A bracketed IPv6 address is refused with a message (the device list could not show one). The bare `recent_addresses`, the devices and the selection ride in every answer, so the panel updates ahead of the tracker's next frame.
- IPC: `pair start|stop|toggle`, `connect ADDR`, `disconnect ADDR`, `tcpip SERIAL`, `usb SERIAL` (`""` for the selected device), `page wireless`; `status` adds `pairing`.
- Tools: the *Mirror with scrcpy* row says *over Wi-Fi* or *over USB* for the selected device. Mirroring itself is unchanged: a Wi-Fi entry mirrors like any other (`scrcpy -s host:port`).
- Tests: 185 (37 new), among them the QR session as a subprocess (the PNG's mode and bytes, the payload on qrencode's stdin and not its argv, the code on `adb pair`'s stdin, SIGINT/SIGTERM/SIGKILL cleanup, no mDNS, no qrencode, nobody scanning), pairing by code (`["pair", ADDR, "<stdin>123456"]` and the code in no argv), connect classification on exit 0, Go wireless's argv order and selection, and a `pair code` started with a silent stdin answering `bad_args` within seconds instead of hanging.
- Checked live on an HONOR phone over USB (Android 16): `wireless` sees mDNS through the SDK adb and reports the `android-tools` one has none; the QR session in the panel (the code on a white card with the countdown, Cancel, `pair stop` over IPC; the PNG gone after); `tcpip` switched the phone's adbd to port 5555 and `usb` put it back. The connect itself could not be verified on this desk: the desktop's VPN (LAN Discovery off) drops all LAN traffic to the phone, ping included, so pairing and connecting are verified against the fake adb only until that is lifted.

## 1.1.0

- **Demo mode**: a ninth row on the Toggles page (IPC `flip demo`, helper `toggle demo`) for SystemUI's demo mode, the clean status bar store screenshots are taken with: the clock at 12:00, a full battery and full signal, no notification icons. On, the helper opens the `sysui_demo_allowed` gate and sends the seven demo broadcasts; off, it sends `exit` and closes the gate. The state reads on from either `sysui_tuner_demo_on` (AOSP mirrors the shown state there) or the gate, because a vendor SystemUI may never write the first; an HONOR phone on Android 16 keeps it at 0, and honours only part of the demo (battery and notification icons, not the clock or the signal bars).
- **Mirror with the screen off**: a new setting (`mirrorScreenOff`, off by default; a switch on the Settings page under the scrcpy arguments, or `omarchy bar set costafot.android-dev mirrorScreenOff true`). With it on, *Mirror with scrcpy* runs `scrcpy --turn-screen-off --stay-awake`: the phone's own screen goes dark while the mirror runs, it stays awake while plugged in, and scrcpy turns the screen back on when it closes. The flags go ahead of `scrcpyArgs`, so your own arguments win; the Tools row's detail shows what will be appended, and `tools` reports `screen_off`. Checked live on a phone over USB (Android 16): the argv carried both flags, the phone's stay-on setting read 7 while the mirror ran and 0 after it closed, and scrcpy logged `Device display turned off`.
- README: the emulator's window rule is `float` alone and the text says what happens (the emulator is an X11 window with a detached toolbar; tiled, it pads the tile grey with the toolbar loose over it; floated, it takes its phone shape with the toolbar attached and reopens where it was last dragged, so `center` does nothing for it; scrcpy keeps `center`). A FAQ entry says why the window looks wrong without the rule and why it comes out small on a scaled monitor. Verified live with rules added through `hyprctl eval`.

## 1.0.0

- **Release.** The README has a preview and a screenshot per page, the FAQ (adb off PATH, an unauthorised device, two devices, no wireless pairing, ASCII-only text, vendor ROMs that block input injection, a recording cut by a shell restart, what differs from the Windows extension), Hyprland window rules that float the emulator and scrcpy, and the update line. `preview.png` and `assets/screenshots/` are captured from the panel on the Medium_Phone emulator.
- Fixed: *Install all* sent one notification per file on top of the batch summary. The panel's `act` wrapper dropped the `silent` flag on its way to the service; it now passes it through, and a batch of three sends exactly one `Installed 3/3 APKs`.
- Tests: `tests/test_tree.py` pins the tree invariants a marketplace reviewer reads for: every QML `Text` is `Text.PlainText`, the helper spawns children in three named modules only and never through a shell, QML never runs adb, nothing is killed by name, no shared temp dir, and no file in the tree names a privilege-escalation, package-manager, service-manager or clone-and-run command. 144 offline tests.
- Checked live before tagging: no adb anywhere (the hub's note and the helper's `no_adb`), the adb server killed under the tracker (an `adb_failed` note for five seconds, then the tracker back with the device), a second emulator selected and then killed (the selection falls back to the one device left; connected and disconnected notifications carry the AVD name), a corrupt `state.json` (set aside as `.bak`, reported once, clean on the next run), the bar on the left (the glyph and the panel follow), a package uninstalled behind the open actions page.

## 0.6.0

- **Settings**: the last hub row is a page. A form with the adb binary, the screenshot, recording and APK folders and the extra scrcpy arguments as text fields, and Notifications, Device notifications, Confirm uninstall and Show system apps as toggles; `j`/`k`, Tab and the arrows walk it, Enter edits a field or flips a toggle, Enter on Save writes the keys that changed in one atomic shell.json update and the running plugin takes them at once (the tracker restarts with the new adb path, the next helper run carries the new folders), no shell restart. The hub's Settings row names the adb in use and how it was found (`~/Android/Sdk/platform-tools/adb · found in ~/Android/Sdk`). `page settings` over IPC opens it.
- An `adbPath` setting that names no adb is now reported (`No adb at ~/x. Fix the adbPath setting, or clear it to look in the SDK and on PATH again`) on the hub, the Devices page and every device page, instead of being silently replaced by the SDK's or PATH's adb. Clearing the setting brings auto-detection back, live.
- IPC: `status` adds the settings in force, the page the open panel shows and the recording state; `help` lists every verb, the settings keys and the `omarchy bar set` form.
- scrcpy is launched with `ADB` set to the adb the plugin resolved (the SDK's platform-tools by default), so it talks to the same binary and server as everything else. The `scrcpy` package pulls in `android-tools` and its own `/usr/bin/adb`, which scrcpy would otherwise pick off PATH; a client of another protocol version restarts the adb server under the device tracker. Checked live: the Mirror row appeared on the Tools page without a restart once scrcpy was installed, the window opened in its own scope, and its adb child was the SDK one.
- README: Hyprland keybindings (`o.bind` lines for the panel and a screenshot), an `omarchy-menu` extension row, the settings table.
- Helper: `adb.path_text`, `adb.source_text` and `adb.text` in every envelope. Tests: `tests/test_manifest.py` pins the manifest's defaults and schema to the helper's, the store's key list, the Settings page's defaults and form, and the IPC help's page list. 134 offline tests.

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
