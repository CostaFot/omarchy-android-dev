pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui

// The Android Dev pages: the hub with the selected device and the pages
// hanging off it (Devices, Device info, Apps and a package's actions,
// Deep link, Toggles, Tweaks, Capture, APKs, Send text, Tools, Wireless and its two
// sub-pages, Settings). One component, shown by two hosts: the bar popup
// (Panel.qml, the kit's KeyboardPanel under the droid glyph) and the
// window (Window.qml, a FloatingWindow that Hyprland tiles or floats like
// any app). Pages live on a stack; Escape and Backspace walk back, and
// Escape on the hub asks the host to close (`closeRequested`). The data is
// the service's Store (one per shell), reached through `service`; this
// component never runs the helper for itself beyond asking the store (or
// the service, for actions that also notify) to.
//
// Page renderers build one flat `rows` array and a Repeater paints it.
// The filter / URL / folder / text field, the settings form and the
// confirm dialog live outside the Repeater: rows are rebuilt on every
// document. This component is the one writer of the plugin's settings
// (`persistSettings`, through the shell).
//
// The host sets `opened` (the popup's `opened`, the window's `visible`),
// `service`, `shell`, `hostWidget` (the bar widget whose shell.json entry
// holds the settings, when one is placed) and the colours, and answers
// `closeRequested`, `openRequested` (a page asked for while closed) and
// `switchRequested` (Tab: the popup switches bar panels, the window does
// nothing). `desiredHeight` and `focusTarget` are for the host's sizing
// and focus.
FocusScope {
  id: root

  readonly property string moduleName: "costafot.android-dev"
  property var service: null
  property var shell: null
  property var hostWidget: null
  property bool opened: false
  // The popup takes the page the service holds for the widget the shell
  // summoned (`page NAME` over IPC); the window is told its page directly.
  property bool takesServicePage: false
  // The popup shows the hub's Open as a window row; the window does not.
  property bool inPopup: false
  readonly property var store: service ? service.store : null

  signal closeRequested()
  signal openRequested()
  signal switchRequested(int direction)

  property color contentForeground: Color.foreground
  property string contentFontFamily: Style.font.family
  property color urgentForeground: Color.urgent
  readonly property color mutedForeground: Qt.darker(contentForeground, 1.4)
  // nf-fa-android, as an escape so no tool can strip it silently.
  readonly property string glyph: "\uf17b"
  readonly property var kindGlyphs: ({ emulator: "\uf108", usb: "\uf10b", wifi: "\uf1eb" })
  // The Wireless page's glyphs (nf-fa qrcode, key, link, times, shield), as escapes.
  readonly property var wirelessGlyphs: ({ qr: "\uf029", key: "\uf084", link: "\uf0c1", cancel: "\uf00d", vpn: "\uf132" })

  function refresh() {
    if (!store) return
    if (page === "packages") store.refreshPackages()
    else if (page === "actions") store.fetchPackage(current.pkg)
    else if (page === "toggles") store.refreshToggles()
    else if (page === "tweaks" || page === "fontpick" || page === "densitypick") store.refreshTweaks()
    else if (page === "info") store.refreshInfo()
    else if (page === "apks") { resetInstalls(); listApks() }
    else if (page === "tools") store.refreshTools()
    else if (page === "wireless" || (page === "paircode" && !current.addr)) store.refreshWireless()
    else store.refreshStatus()
  }

  // ---- Navigation ---------------------------------------------------------
  // Each entry: { page, ...args, cursor, query } where the cursor and the
  // field's text are saved on push and restored on pop.
  property var stack: [{ page: "hub" }]
  property var pendingStack: null
  readonly property var current: stack[stack.length - 1]
  readonly property string page: current.page
  readonly property bool isHub: stack.length === 1
  readonly property bool hasField: page === "packages" || page === "deeplink" || page === "apks" || page === "text" || page === "paircode"
  // The settings form replaces the row list while it shows.
  readonly property bool isSettingsForm: page === "settings"

  readonly property var pageTitles: ({
    hub: "Android Dev", devices: "Devices", info: "Device info", packages: "Apps", actions: "", deeplink: "Deep link", toggles: "Toggles",
    tweaks: "Tweaks", fontpick: "Font scale", densitypick: "Display scale",
    capture: "Capture", apks: "APKs", text: "Send text", tools: "Tools", wireless: "Wireless",
    paircode: "Pair with a code", settings: "Settings", avdboot: "", launchpick: ""
  })
  // Pages the IPC `page` verb may open straight onto.
  readonly property var ipcPages: ["hub", "devices", "info", "packages", "deeplink", "toggles", "tweaks", "capture", "apks", "text", "tools", "wireless", "settings"]

  function push(entry) {
    var top = Object.assign({}, current, { cursor: selectedIndex, query: filterField.text })
    stack = stack.slice(0, -1).concat([top, entry])
    enterPage(entry)
  }

  function pop() {
    if (confirmOpen) { cancelConfirm(); return }
    if (stack.length <= 1) { closeRequested(); return }
    var entry = stack[stack.length - 2]
    stack = stack.slice(0, -1)
    enterPage(entry)
  }

  function goHome() {
    stack = [{ page: "hub" }]
    enterPage(stack[0])
  }

  // IPC `page NAME`: open straight onto a page, with the hub under it.
  function stackFor(name) {
    var target = ipcPages.indexOf(name) !== -1 ? name : "hub"
    return target === "hub" ? [{ page: "hub" }] : [{ page: "hub" }, { page: target }]
  }

  function showPage(name) {
    var next = stackFor(name)
    if (opened) {
      stack = next
      enterPage(next[next.length - 1])
    } else {
      pendingStack = next
      openRequested()
    }
  }

  function enterPage(entry) {
    listScroll.contentY = 0
    // The APK page's field starts as the apkDir setting; the others empty.
    filterField.text = entry.query !== undefined ? entry.query : (entry.page === "apks" ? apkDirSetting() : "")
    cancelConfirm()
    if (store) {
      if (entry.page === "packages") store.refreshPackages()
      else if (entry.page === "actions" && entry.pkg) store.fetchPackage(entry.pkg)
      else if (entry.page === "toggles") store.refreshToggles()
      else if (entry.page === "tweaks") store.refreshTweaks()
      else if (entry.page === "info") store.refreshInfo()
      else if (entry.page === "apks") { resetInstalls(); listApks() }
      else if (entry.page === "tools") store.refreshTools()
      else if (entry.page === "wireless" || (entry.page === "paircode" && !entry.addr)) store.refreshWireless()
    }
    if (entry.page === "settings") loadPendingSettings()
    Qt.callLater(function() {
      var wanted = entry.cursor
      selectedIndex = (wanted !== undefined && root.isCursorRow(root.rows[wanted])) ? wanted : root.firstCursorIndex()
      root.focusForPage()
      root.ensureCursorVisible()
    })
  }

  function focusForPage() {
    if (hasField) filterField.forceActiveFocus()
    else keyCatcher.forceActiveFocus()
  }

  // ---- Rows ---------------------------------------------------------------
  // Row types: title header sep action note qr footer. Every string a row
  // shows is either a literal here or a field the helper already formatted;
  // the exceptions are the uninstall and stop questions and the "Pairing
  // with" note, literals around a name or an address.
  // The two running counters are read by the delegates, never by `rows`
  // (a row says `live: "countdown"` or `live: "elapsed"` and the delegate
  // appends the figure): before 1.4.1 the seconds were baked into the
  // model, so every tick rebuilt every row and re-read the QR PNG.
  readonly property int pairingLeft: service && service.pairing ? Math.max(0, service.pairingWindow - service.pairingSeconds) : 0
  readonly property string recordingElapsed: service && service.recording ? service.elapsedText(service.recordingSeconds) : ""

  readonly property var rows: {
    var out = []
    // Two pages are titled by what they act on: the actions page and the
    // launcher picker by the package, the boot picker by the AVD.
    if (!isHub) out.push({ type: "title", label: page === "actions" || page === "launchpick" ? (current.pkg || "")
                                                    : page === "avdboot" ? (current.avd || "") : (pageTitles[page] || page) })
    var body
    if (page === "hub") body = hubRows()
    else if (page === "devices") body = deviceRows()
    else if (page === "info") body = infoRows()
    else if (page === "packages") body = packageRows()
    else if (page === "actions") body = actionRows()
    else if (page === "deeplink") body = deeplinkRows()
    else if (page === "toggles") body = toggleRows()
    else if (page === "tweaks") body = tweakRows()
    else if (page === "fontpick") body = fontPickRows()
    else if (page === "densitypick") body = densityPickRows()
    else if (page === "capture") body = captureRows()
    else if (page === "apks") body = apkRows()
    else if (page === "text") body = textRows()
    else if (page === "tools") body = toolRows()
    else if (page === "wireless") body = wirelessRows()
    else if (page === "paircode") body = paircodeRows()
    else if (page === "avdboot") body = avdBootRows()
    else if (page === "launchpick") body = launchPickRows()
    else body = []  // the settings form paints itself
    for (var i = 0; i < body.length; i++) out.push(body[i])
    var s = root.store
    if (s && s.notice !== "") {
      out.push({ type: "sep" })
      out.push({ type: "note", label: s.notice, urgent: s.noticeUrgent })
    }
    out.push({ type: "footer", label: keyHint() })
    return out
  }

  // The hub's page rows.
  readonly property var pageRows: [
    { icon: "\uf05a", label: "Device info", detail: "Android version, battery, network, screen, memory, storage", page: "info" },
    { icon: "\uf00a", label: "Apps", detail: "Packages, their actions and deep links", page: "packages" },
    { icon: "\uf0c1", label: "Deep link", detail: "Open a URL on the device", page: "deeplink" },
    { icon: "\uf1de", label: "Toggles", detail: "Animations, touches, layout bounds, airplane, Wi-Fi, data, Bluetooth, demo mode", page: "toggles" },
    { icon: "\uf042", label: "Tweaks", detail: "Dark mode, font scale, display scale", page: "tweaks" },
    { icon: "\uf030", label: "Capture", detail: "Screenshot and screen recording", page: "capture" },
    { icon: "\uf1b2", label: "APKs", detail: "Install from a folder", page: "apks" },
    { icon: "\uf11c", label: "Send text", detail: "Type text or the clipboard on the device", page: "text" },
    { icon: "\uf0ad", label: "Tools", detail: "scrcpy, emulators, logcat", page: "tools" },
    { icon: kindGlyphs.wifi, label: "Wireless", detail: "Pair and connect over Wi-Fi, go cable-free", page: "wireless" },
    { icon: "\uf013", label: "Settings", detail: "", page: "settings" }
  ]

  function hubRows() {
    var s = root.store
    var out = []
    if (!s) {
      out.push({ type: "note", urgent: true, label: "The Android Dev service is not loaded",
                 detail: "Enable the plugin again or restart the shell." })
      return out
    }
    var svc = root.service
    var dev = s.selectedDevice
    if (!s.loaded) {
      out.push({ type: "action", icon: glyph, label: "Looking for adb…", detail: "", action: "refresh" })
    } else if (!s.hasAdb) {
      out.push({ type: "note", urgent: true, icon: "\uf071", label: "adb not found", detail: noAdbDetail() })
      out.push({ type: "action", icon: "\uf021", label: "Look again", detail: "Re-read adb and the devices", action: "refresh" })
    } else if (dev) {
      var detail = dev.detail || ""
      if (s.deviceCount > 1) detail += (detail !== "" ? " · " : "") + s.deviceCount + " attached"
      out.push({ type: "action", icon: glyph, label: dev.label, detail: detail, page: "devices",
                 urgent: dev.state !== "device" })
    } else {
      out.push({ type: "action", icon: glyph, label: "No device",
                 detail: s.deviceCount > 1 ? s.deviceCount + " attached, none selected" : "Connect a device or start an emulator",
                 page: "devices" })
    }
    if (svc && svc.recording)
      out.push({ type: "note", urgent: true, icon: "\uf03d", label: "Recording", live: "elapsed",
                 detail: "Stop it on the Capture page" })
    if (svc && svc.pairing)
      out.push({ type: "note", urgent: true, icon: wirelessGlyphs.qr, label: "Pairing", live: "countdown",
                 detail: "The QR code is on the Wireless page; cancel it there" })
    if (s.hasAdb && svc && svc.trackerError !== "" && svc.trackerErrorCode !== "no_adb")
      out.push({ type: "note", urgent: true, label: "Device tracking stopped", detail: svc.trackerError })
    if (s.lastError !== "" && s.lastErrorCode !== "no_adb" && s.notice === "")
      out.push({ type: "note", urgent: true, label: s.lastError })
    out.push({ type: "sep" })
    for (var i = 0; i < pageRows.length; i++) {
      var c = pageRows[i]
      out.push({ type: "action", icon: c.icon, label: c.label, detail: c.page === "settings" ? settingsDetail() : c.detail, page: c.page })
    }
    if (inPopup)
      out.push({ type: "action", icon: "\uf2d0", label: "Open as a window",
                 detail: "The same pages as a window; this popup closes", action: "openwindow" })
    return out
  }

  // The hub's Open as a window row (the popup alone): the popup closes
  // and the window opens on the hub through the shell's summon.
  function openAsWindowRow() {
    closeRequested()
    if (service && typeof service.openWindow === "function") service.openWindow("hub")
  }

  // The helper says why there is no adb (`No adb at ~/x. Fix the adbPath
  // setting…` or `No adb found. Set adbPath…`); the literal is for before
  // it has spoken.
  function noAdbDetail() {
    var s = root.store
    var svc = root.service
    if (s && s.lastErrorCode === "no_adb" && s.lastError !== "") return s.lastError
    if (svc && svc.trackerErrorCode === "no_adb" && svc.trackerError !== "") return svc.trackerError
    return "Set the adb path on the Settings page, or install the android-tools package or the SDK platform-tools."
  }

  // The hub's Settings row: which adb is in use, in the helper's words.
  function settingsDetail() {
    var s = root.store
    if (!s || !s.loaded) return "adb path, folders, notifications"
    if (!s.hasAdb) return "adb not found · set its path here"
    return s.adbText !== "" ? s.adbText : "adb path, folders, notifications"
  }

  // The picker: one row per attached device, the selected one marked.
  function deviceRows() {
    var s = root.store
    var out = []
    if (!s.hasAdb) {
      out.push({ type: "note", urgent: true, label: "adb not found", detail: noAdbDetail() })
    } else if (s.devices.length === 0) {
      out.push({ type: "note", label: "No device", detail: "Connect a device over USB or start an emulator; it shows up here on its own." })
    }
    for (var i = 0; i < s.devices.length; i++) {
      var d = s.devices[i]
      var selected = d.serial === s.selected
      out.push({ type: "action", icon: selected ? "\uf00c" : (kindGlyphs[d.kind] || glyph), label: d.label || d.serial,
                 detail: (d.detail || "") + (selected ? " · selected" : ""), action: "select", serial: d.serial,
                 urgent: d.state !== "device" })
    }
    out.push({ type: "sep" })
    out.push({ type: "action", icon: "\uf021", label: "Look again", detail: "Re-read adb and the devices", action: "refresh" })
    return out
  }

  // A device that can take commands, or the note saying why not.
  function deviceGate(out) {
    var s = root.store
    var dev = s.selectedDevice
    if (!s.hasAdb) {
      out.push({ type: "note", urgent: true, label: "adb not found", detail: noAdbDetail() })
      return false
    }
    if (!dev) {
      out.push({ type: "note", label: "No device",
                 detail: s.deviceCount > 1 ? "Pick one on the Devices page." : "Connect a device or start an emulator." })
      return false
    }
    if (dev.state !== "device") {
      out.push({ type: "note", urgent: true, label: dev.label, detail: dev.detail })
      return false
    }
    return true
  }

  readonly property string filterText: filterField.text
  readonly property string query: filterText.trim()

  function packageRow(p) {
    return { type: "action", icon: p.foreground ? "\uf06e" : (p.running ? "\uf04b" : "\uf1b2"), label: p.name,
             detail: p.detail || "", action: "package", pkg: p.name }
  }

  function packageRows() {
    var s = root.store
    var out = []
    if (!deviceGate(out)) return out
    var all = s.packages
    if (all.length === 0) {
      if (s.busy && s.runningCommand === "packages") out.push({ type: "note", label: "Listing packages…" })
      else if (s.packagesInfo && s.packagesInfo.system_apps) out.push({ type: "note", label: "No packages", detail: "Press r to list again." })
      else out.push({ type: "note", label: "No third-party packages on this device",
                      detail: "Turn on Show system apps on the Settings page to list every package." })
      return out
    }
    var f = query.toLowerCase()
    var shown = []
    for (var i = 0; i < all.length; i++)
      if (f === "" || String(all[i].name).toLowerCase().indexOf(f) !== -1) shown.push(all[i])
    if (shown.length === 0) {
      out.push({ type: "note", label: "No packages match" })
      return out
    }
    if (f === "" && s.lastPackage !== "") {
      for (var l = 0; l < shown.length; l++) {
        if (shown[l].name === s.lastPackage) {
          out.push({ type: "header", label: "Last used" })
          out.push(packageRow(shown[l]))
          break
        }
      }
    }
    var section = ""
    for (var k = 0; k < shown.length; k++) {
      if (shown[k].section !== section) {
        section = shown[k].section
        out.push({ type: "header", label: section })
      }
      out.push(packageRow(shown[k]))
    }
    return out
  }

  // The per-package actions, in the Windows order, each with its adb
  // command as the detail.
  readonly property var appActions: [
    { icon: "\uf04b", label: "Launch", detail: "am start -n <launcher activity>", act: "launch" },
    { icon: "\uf021", label: "Restart", detail: "am force-stop, then am start", act: "restart" },
    { icon: "\uf04d", label: "Kill process", detail: "am kill · only works while the app is in the background", act: "kill" },
    { icon: "\uf12d", label: "Clear app data", detail: "pm clear", act: "clear" },
    { icon: "\uf0e2", label: "Clear data and restart", detail: "pm clear, then am start", act: "clear-restart" },
    { icon: "\uf011", label: "Force stop", detail: "am force-stop", act: "force-stop" },
    { icon: "\uf0c1", label: "Open deep link", detail: "am start -a VIEW -d URL, in this package", act: "deeplink" },
    { icon: "\uf1f8", label: "Uninstall", detail: "adb uninstall", act: "uninstall" },
    { icon: "\uf00c", label: "Grant all permissions", detail: "pm grant, every runtime permission", act: "grant" },
    { icon: "\uf05e", label: "Revoke all permissions", detail: "pm revoke, every runtime permission", act: "revoke" }
  ]

  function actionRows() {
    var s = root.store
    var pkg = current.pkg || ""
    var out = []
    var info = s.packageDetails[pkg]
    if (info) {
      var tags = []
      if (info.foreground) tags.push("foreground")
      else if (info.running) tags.push("running")
      if (info.debuggable) tags.push("debuggable")
      out.push({ type: "note", label: info.version_name ? "Version " + info.version_name + (tags.length ? " · " + tags.join(" · ") : "") : tags.join(" · "),
                 detail: info.launcher_detail || info.launcher_activity || "No launcher activity" })
    } else if (s.busy && s.runningCommand === "package") {
      out.push({ type: "note", label: "Reading the package…" })
    }
    if (!deviceGate(out)) return out
    for (var i = 0; i < appActions.length; i++) {
      var a = appActions[i]
      out.push({ type: "action", icon: a.icon, label: a.label, detail: a.detail, action: "app", act: a.act, pkg: pkg })
      // A package with several launcher activities (a debug build with
      // LeakCanary's Leaks screen, say) gets the picker under Launch.
      if (a.act === "launch" && hasSeveralLaunchers(info))
        out.push({ type: "action", icon: "\uf0cb", label: "Launcher activity",
                   detail: info.launcher_picked ? "Launch starts your pick · Enter changes it" : "Launch starts the first · Enter picks another",
                   action: "app", act: "pick", pkg: pkg })
    }
    return out
  }

  function hasSeveralLaunchers(info) {
    return !!info && Array.isArray(info.launcher_activities) && info.launcher_activities.length > 1
  }

  // ---- Launcher picker ----------------------------------------------------
  // One row per launcher activity of the package (the helper's list, its
  // labels and which one Launch starts); Enter starts that one and the
  // helper remembers it for the package, so Launch goes straight to it
  // from then on.
  function launchPickRows() {
    var pkg = current.pkg || ""
    var info = root.store.packageDetails[pkg]
    var out = []
    if (!hasSeveralLaunchers(info)) {
      out.push({ type: "note", label: "One launcher activity", detail: "Launch starts it; nothing to pick here." })
      return out
    }
    out.push({ type: "note", label: info.launcher_text || "", detail: "Enter starts one and makes it what Launch starts" })
    for (var i = 0; i < info.launcher_activities.length; i++) {
      var a = info.launcher_activities[i]
      out.push({ type: "action", icon: a.chosen ? "\uf00c" : "\uf04b", label: a.label || a.component,
                 detail: a.chosen ? "am start -n · what Launch starts now" : "am start -n · Enter starts it and Launch keeps it",
                 action: "launchact", pkg: pkg, component: a.component })
    }
    return out
  }

  // ---- Boot picker ----------------------------------------------------------
  // A stopped AVD: quick boot (the emulator's default, the saved snapshot)
  // or a cold boot (-no-snapshot-load, the way out of a snapshot that
  // misbehaves). Enter starts it and goes back to Tools, which re-reads.
  function avdBootRows() {
    var name = current.avd || ""
    return [
      { type: "action", icon: "\uf04b", label: "Quick boot", detail: "emulator -avd <name> · resumes the saved snapshot", action: "avdstart", avd: name, cold: false },
      { type: "action", icon: "\uf2dc", label: "Cold boot", detail: "emulator -avd <name> -no-snapshot-load · starts fresh", action: "avdstart", avd: name, cold: true }
    ]
  }

  function deeplinkRows() {
    var s = root.store
    var pkg = current.pkg || ""
    var out = []
    if (pkg !== "") out.push({ type: "note", label: "Only this package", detail: pkg })
    if (!deviceGate(out)) return out
    if (query !== "") {
      out.push({ type: "action", icon: "\uf0c1", label: query, detail: "am start -a android.intent.action.VIEW -d …",
                 action: "deeplink", url: query, pkg: pkg })
    } else if (s.recentDeeplinks.length === 0) {
      out.push({ type: "note", label: "Type a URL or deep link, then Enter", detail: "https://example.com or myapp://home" })
    }
    if (s.recentDeeplinks.length > 0) {
      out.push({ type: "header", label: "Recent" })
      for (var i = 0; i < s.recentDeeplinks.length; i++) {
        var u = s.recentDeeplinks[i]
        out.push({ type: "action", icon: "\uf1da", label: u, detail: "", action: "deeplink", url: u, pkg: pkg })
      }
    }
    return out
  }

  // The nine developer toggles, in the Windows order plus Bluetooth and
  // SystemUI's demo mode; the
  // state word comes from the helper, the command text is a literal.
  readonly property var toggleOrder: ["animations", "touches", "pointer", "layout", "airplane", "wifi", "data", "bluetooth", "demo"]
  readonly property var toggleCommands: ({
    animations: "settings put global *_animation_scale 0|1",
    touches: "settings put system show_touches",
    pointer: "settings put system pointer_location",
    layout: "setprop debug.layout, then a poke at the activity service",
    airplane: "cmd connectivity airplane-mode (settings put + broadcast before API 30)",
    wifi: "svc wifi enable|disable",
    data: "svc data enable|disable",
    bluetooth: "svc bluetooth enable|disable",
    demo: "am broadcast systemui.demo enter|exit"
  })

  function toggleRows() {
    var s = root.store
    var out = []
    if (!deviceGate(out)) return out
    var t = s.toggles
    if (!t) {
      out.push({ type: "note", label: s.busy && s.runningCommand === "toggles" ? "Reading the toggles…" : "Press r to read the toggles" })
      return out
    }
    for (var i = 0; i < toggleOrder.length; i++) {
      var name = toggleOrder[i]
      var v = t[name]
      if (!v) continue
      // nf-fa-toggle_on / toggle_off / question, as escapes.
      var icon = v.on === true ? "\uf205" : v.on === false ? "\uf204" : "\uf128"
      out.push({ type: "action", icon: icon, label: v.label || name, detail: (v.text || "unknown") + " · " + toggleCommands[name],
                 action: "toggle", name: name })
    }
    return out
  }

  // ---- Device info ------------------------------------------------------------
  // One row per section of the helper's `info` document, in the helper's
  // order (`infoOrder` is pinned to `info.SECTIONS`): the value as the
  // label, the section's name and extras as the detail, both formatted by
  // the helper; Enter copies the value through the service.
  readonly property var infoOrder: ["device", "android", "battery", "network", "screen", "memory", "storage", "foreground", "uptime"]
  // nf-fa mobile, android, wifi, desktop, microchip, hdd_o, window_maximize, clock_o, as escapes.
  readonly property var infoGlyphs: ({ device: "\uf10b", android: "\uf17b", network: "\uf1eb", screen: "\uf108", memory: "\uf2db",
                                       storage: "\uf0a0", foreground: "\uf2d0", uptime: "\uf017" })

  // nf-fa battery_4 down to battery_0, by level.
  function batteryGlyph(level) {
    if (typeof level !== "number") return "\uf244"
    return level > 87 ? "\uf240" : level > 62 ? "\uf241" : level > 37 ? "\uf242" : level > 12 ? "\uf243" : "\uf244"
  }

  function infoRows() {
    var s = root.store
    var out = []
    if (!deviceGate(out)) return out
    var info = s.deviceInfo
    if (!info) {
      out.push({ type: "note", label: s.busy && s.runningCommand === "info" ? "Reading the device…" : "Press r to read the device" })
      return out
    }
    for (var i = 0; i < infoOrder.length; i++) {
      var name = infoOrder[i]
      var v = info[name]
      if (!v) continue
      var low = name === "battery" && typeof v.level === "number" && v.level <= 12
      out.push({ type: "action", icon: name === "battery" ? batteryGlyph(v.level) : infoGlyphs[name],
                 label: v.text || "unknown", detail: v.detail || v.label || name,
                 action: "copyinfo", value: v.copy || v.text || "", urgent: low })
    }
    return out
  }

  // ---- Tweaks ---------------------------------------------------------------
  // Dark mode, the font scale and the display density: the values and the
  // steps come from the helper, the command text is a literal. Enter flips
  // dark mode and opens a picker for the two scales; a `tweak` answer
  // carries all three, so the page repaints from it.
  readonly property var tweakCommands: ({
    dark: "cmd uimode night yes|no",
    font: "settings put system font_scale",
    density: "wm density"
  })

  function hasOverride(density) {
    return !!density && density.override !== null && density.override !== undefined
  }

  function tweakRows() {
    var s = root.store
    var out = []
    if (!deviceGate(out)) return out
    var t = s.tweaks
    if (!t) {
      out.push({ type: "note", label: s.busy && s.runningCommand === "tweaks" ? "Reading the tweaks…" : "Press r to read the tweaks" })
      return out
    }
    var dark = t.dark || {}
    var font = t.font || {}
    var density = t.density || {}
    // nf-fa-toggle_on / toggle_off / question, font, arrows-alt, as escapes.
    out.push({ type: "action", icon: dark.on === true ? "\uf205" : dark.on === false ? "\uf204" : "\uf128",
               label: dark.label || "Dark mode", detail: (dark.text || "unknown") + " · " + tweakCommands.dark,
               action: "tweak", name: "dark" })
    out.push({ type: "action", icon: "\uf031", label: font.label || "Font scale",
               detail: (font.text || "unknown") + " · " + tweakCommands.font, action: "fontpick" })
    out.push({ type: "action", icon: "\uf0b2", label: density.label || "Display scale",
               detail: (density.text || "unknown") + " · " + tweakCommands.density,
               urgent: hasOverride(density), action: "densitypick" })
    if (hasOverride(density))
      out.push({ type: "note", label: "A density override survives a reboot", detail: "Default in the picker puts the physical density back (wm density reset)" })
    return out
  }

  // ---- The two scale pickers ---------------------------------------------
  // One row per step the helper lists, a check on the current one; Enter
  // goes back to Tweaks and sets it, and the answer repaints the page.
  function fontPickRows() {
    var t = root.store.tweaks
    var font = t && t.font ? t.font : null
    var out = []
    if (!font || !Array.isArray(font.steps) || font.steps.length === 0) {
      out.push({ type: "note", label: "Press r to read the tweaks" })
      return out
    }
    out.push({ type: "note", label: "Android's own font size steps", detail: "Enter sets one; the apps on screen take it at once" })
    for (var i = 0; i < font.steps.length; i++) {
      var st = font.steps[i]
      out.push({ type: "action", icon: st.current ? "\uf00c" : "\uf031", label: st.text || "", detail: st.detail || "",
                 action: "fontset", value: st.text })
    }
    return out
  }

  function densityPickRows() {
    var t = root.store.tweaks
    var d = t && t.density ? t.density : null
    var out = []
    if (!d || !Array.isArray(d.steps) || d.steps.length === 0) {
      out.push({ type: "note", label: d && d.text === "unknown" ? "The device did not answer wm density" : "Press r to read the tweaks" })
      return out
    }
    out.push({ type: "note", label: "The Display size steps, from the physical density", detail: "Enter sets one; every app on screen restarts with it" })
    for (var i = 0; i < d.steps.length; i++) {
      var st = d.steps[i]
      // nf-fa-undo for the reset stop.
      out.push({ type: "action", icon: st.current ? "\uf00c" : st.reset ? "\uf0e2" : "\uf0b2", label: st.text || "", detail: st.detail || "",
                 action: "densityset", value: st.value, reset: st.reset === true })
    }
    out.push({ type: "note", label: "An override survives a reboot", detail: "Default puts the physical density back; a phone left on Largest stays that way" })
    return out
  }

  function captureRows() {
    var s = root.store
    var svc = root.service
    var out = []
    var st = s.status
    // The recording rows come before the device gate: a recording keeps
    // going (and needs its Stop row) whatever the tracker says meanwhile.
    if (svc && svc.recordingStopping) {
      out.push({ type: "note", icon: "\uf03d", label: "Saving the recording…", detail: "Pulling the mp4 from the device" })
    } else if (svc && svc.recording) {
      out.push({ type: "action", icon: "\uf04d", label: "Stop recording", urgent: true, live: "elapsed",
                 detail: "Enter stops and saves the mp4", action: "record" })
    } else if (svc && svc.recorderRunning) {
      out.push({ type: "note", icon: "\uf03d", label: "Starting the recording…" })
    }
    if (!deviceGate(out)) return out
    out.push({ type: "action", icon: "\uf030", label: "Screenshot",
               detail: "screencap -p · " + (st && st.screenshot_dir_text ? st.screenshot_dir_text : "the pictures folder") + " · copied to the clipboard",
               action: "screenshot" })
    if (svc && !svc.recorderRunning)
      out.push({ type: "action", icon: "\uf03d", label: "Start recording",
                 detail: "screenrecord on the device · " + (st && st.recording_dir_text ? st.recording_dir_text : "the videos folder") + " when stopped · 3 min limit",
                 action: "record" })
    return out
  }

  // ---- APKs ---------------------------------------------------------------
  // The folder field lists on the fly (debounced); Enter on a file installs
  // it, Install all runs the files one after another through the service,
  // each its own helper run with its own budget. Results live here, per
  // panel, until the folder changes or `r`. The folders installed from
  // before are rows at the foot, from the helper's state.
  property var apkResults: ({})
  property string apkInstalling: ""
  property var apkQueue: []
  property int apkBatchTotal: 0

  function apkDirSetting() {
    return store ? String(store.setting("apkDir", "~/Downloads") || "~/Downloads") : "~/Downloads"
  }

  function listApks() {
    if (store) store.listApks(query)
  }

  function resetInstalls() {
    apkResults = {}
    apkQueue = []
    apkBatchTotal = 0
  }

  property Timer apkListTimer: Timer {
    interval: 300
    repeat: false
    onTriggered: root.listApks()
  }

  onQueryChanged: {
    if (page === "apks") {
      resetInstalls()
      apkListTimer.restart()
    }
    // What was typed is the first row on these pages; Enter should take it
    // (seen 2026-09-05: the cursor stayed on Send clipboard while typing).
    if (page === "text" || page === "deeplink" || page === "paircode")
      Qt.callLater(function() { root.selectedIndex = root.firstCursorIndex() })
  }

  function installApks(paths) {
    if (apkInstalling !== "" || paths.length === 0) return
    apkResults = {}
    apkQueue = paths.slice()
    apkBatchTotal = paths.length
    installNext()
  }

  function installNext() {
    if (apkQueue.length === 0) {
      apkInstalling = ""
      if (apkBatchTotal > 1 && service && store && store.notifyEnabled) {
        var ok = 0
        for (var k in apkResults) if (apkResults[k].ok) ok++
        var dev = store.selectedDevice
        service.notify("Installed " + ok + "/" + apkBatchTotal + " APKs", dev ? dev.label : "")
      }
      return
    }
    var path = apkQueue[0]
    apkQueue = apkQueue.slice(1)
    apkInstalling = path
    var batch = apkBatchTotal > 1
    act(["apk", "install", path], function(doc) {
      var ok = doc && doc.ok !== false
      var message = ok ? "Installed" : (doc && doc.results && doc.results[0] && doc.results[0].message ? String(doc.results[0].message) : (store ? store.lastError : "Failed"))
      var next = Object.assign({}, root.apkResults)
      next[path] = { ok: ok, message: message }
      root.apkResults = next
      root.installNext()
    }, batch)
  }

  function apkRows() {
    var s = root.store
    var out = []
    if (!deviceGate(out)) return out
    var list = s.apkList
    var reading = s.busy && s.runningCommand === "apk" && apkInstalling === ""
    if (!list) {
      out.push({ type: "note", label: reading ? "Reading the folder…" : "Type a folder path", detail: "The .apk files in it are listed here." })
    } else if (!list.exists) {
      out.push({ type: "note", urgent: true, label: "Folder not found", detail: list.dir_text || "" })
    } else if (list.count === 0) {
      out.push({ type: "note", label: "No .apk files in this folder", detail: list.dir_text || "" })
    } else {
      var paths = []
      for (var p = 0; p < list.apks.length; p++) paths.push(list.apks[p].path)
      if (apkInstalling !== "" && apkBatchTotal > 1) {
        var done = 0
        for (var k in apkResults) done++
        out.push({ type: "note", icon: "\uf019", label: "Installing… (" + done + "/" + apkBatchTotal + ")", detail: list.dir_text || "" })
      } else if (list.count > 1) {
        out.push({ type: "action", icon: "\uf019", label: "Install all", detail: list.count + " APKs · adb install -r -t, one after another",
                   action: "installall", paths: paths })
      }
      for (var i = 0; i < list.apks.length; i++) {
        var a = list.apks[i]
        var r = apkResults[a.path]
        var icon = "\uf1b2", detail = a.size_text || "", urgent = false
        if (a.path === apkInstalling) { icon = "\uf017"; detail = "Installing…" }
        else if (r && r.ok) { icon = "\uf00c"; detail = "Installed" }
        else if (r) { icon = "\uf00d"; detail = r.message; urgent = true }
        out.push({ type: "action", icon: icon, label: a.name, detail: detail, action: "install", path: a.path, urgent: urgent })
      }
      if (list.truncated) out.push({ type: "note", label: "Only the first " + list.count + " files are listed" })
    }
    appendApkFolders(out, list ? String(list.dir || "") : "")
    return out
  }

  // The folders an APK was installed from, from the helper's state: a row
  // each at the foot, Enter puts one in the box. The folder on screen is
  // not among them, and none of them shows while an install runs (Enter
  // there would change the folder mid-install).
  function samePath(a, b) {
    return a.replace(/\/+$/, "") === b.replace(/\/+$/, "")
  }

  function appendApkFolders(out, currentDir) {
    if (apkInstalling !== "") return
    var recent = root.store ? root.store.recentApkDirs : []
    if (!recent || recent.length === 0) return
    var shown = 0
    for (var i = 0; i < recent.length; i++) {
      var d = recent[i]
      var text = d && d.path_text ? String(d.path_text) : ""
      if (!d || !d.path || text === "" || samePath(String(d.path), currentDir)) continue
      if (shown === 0) out.push({ type: "header", label: "Recent folders" })
      shown++
      out.push({ type: "action", icon: "\uf07b", label: text, detail: "Enter lists this folder", action: "apkdir", dir: text })
    }
  }

  // ---- Send text ----------------------------------------------------------
  function textRows() {
    var s = root.store
    var out = []
    if (!deviceGate(out)) return out
    if (query !== "") {
      out.push({ type: "action", icon: "\uf11c", label: filterText, detail: "input text · Enter types it into the focused field on the device",
                 action: "text", text: filterText })
    } else {
      out.push({ type: "note", label: "Type a line, then Enter", detail: "Android's input text types one line of ASCII into the focused field; %s in it becomes a space." })
    }
    out.push({ type: "action", icon: "\uf0ea", label: "Send clipboard", detail: "wl-paste, then input text", action: "clipboard" })
    return out
  }

  // ---- Tools --------------------------------------------------------------
  function toolRows() {
    var s = root.store
    var out = []
    var t = s.toolsInfo
    if (!t) {
      out.push({ type: "note", label: s.busy && s.runningCommand === "tools" ? "Reading the tools…" : "Press r to read the tools" })
      return out
    }
    var tools = t.tools || {}
    var dev = s.selectedDevice
    var ready = s.hasAdb && dev && dev.state === "device"
    var gate = []
    deviceGate(gate)
    if (ready) {
      // The transport is a literal keyed on the helper's `kind`: a Wi-Fi
      // entry mirrors over the network, with no cable in.
      var transport = dev.kind === "wifi" ? "over Wi-Fi · " : dev.kind === "usb" ? "over USB · " : ""
      if (tools.scrcpy && tools.scrcpy.found)
        out.push({ type: "action", icon: "\uf26c", label: "Mirror with scrcpy",
                   detail: transport + "scrcpy -s <serial> --window-title \"Android Dev\"" + (t.scrcpy_args ? " " + t.scrcpy_args : ""), action: "scrcpy" })
      else
        out.push({ type: "note", label: "scrcpy not installed", detail: "Install the scrcpy package to mirror the screen from here; this page looks again each time it opens." })
      if (tools.terminal && tools.terminal.found)
        // The one place a row label is built around a package name: "Logcat · " + the last package.
        out.push({ type: "action", icon: "\uf120", label: s.lastPackage !== "" ? "Logcat · " + s.lastPackage : "Logcat",
                   detail: s.lastPackage !== "" ? "adb logcat --pid=<its pid> in a terminal · it has to be running" : "adb logcat in a terminal",
                   action: "logcat", pkg: s.lastPackage })
      else
        out.push({ type: "note", label: "No terminal launcher", detail: "xdg-terminal-exec was not found; logcat opens in a terminal through it." })
    } else {
      for (var g = 0; g < gate.length; g++) out.push(gate[g])
    }
    out.push({ type: "header", label: "Emulators" })
    if (!tools.emulator || !tools.emulator.found) {
      out.push({ type: "note", label: "No emulator found", detail: "The SDK's emulator lives next to platform-tools; ~/Android/Sdk and PATH are searched too." })
    } else if (!t.avds || t.avds.length === 0) {
      out.push({ type: "note", label: "No AVDs", detail: "Create one in Android Studio's Device Manager." })
    } else {
      for (var i = 0; i < t.avds.length; i++) {
        var a = t.avds[i]
        out.push({ type: "action", icon: a.running ? "\uf04d" : "\uf04b", label: a.name,
                   detail: (a.detail || "") + (a.running ? " · Enter stops it" : " · Enter starts it, quick or cold"),
                   action: a.running ? "avdstop" : "avdboot", avd: a.name, serial: a.serial || "" })
      }
    }
    return out
  }

  // ---- Wireless -----------------------------------------------------------
  // Two ways onto Wi-Fi: a pairing QR code (a helper session the service
  // runs; the phone scans it from its Wireless debugging screen) and the
  // six-digit code from Pair device with pairing code (the address picked
  // off the network or typed, then the code, through the one field, the
  // code sent on stdin). A paired phone connects on its own; the ones seen
  // on the network are rows. Go wireless (adb tcpip) left the panel in
  // 1.4.0; the helper keeps `tcpip` and `usb` for the terminal. The lists
  // follow the tracker; the services come from the helper's `wireless`
  // document.
  function wirelessRows() {
    var s = root.store
    var svc = root.service
    var out = []
    if (!s.hasAdb) {
      out.push({ type: "note", urgent: true, label: "adb not found", detail: noAdbDetail() })
      return out
    }
    var w = s.wirelessInfo
    if (svc && svc.pairing) {
      out.push({ type: "qr", path: svc.pairingQr, label: "Scan it from Developer options › Wireless debugging › Pair device with QR code",
                 detail: "Only from that screen: a camera app reads it as Wi-Fi credentials", live: "countdown" })
      out.push({ type: "action", icon: wirelessGlyphs.cancel, label: "Cancel pairing", detail: "Esc only goes back; this ends the session", action: "pairstop", urgent: true })
    } else if (svc && svc.pairerRunning) {
      out.push({ type: "note", icon: wirelessGlyphs.qr, label: svc.pairingStopping ? "Cancelling…" : "Starting the pairing session…" })
    } else if (!w) {
      out.push({ type: "note", label: s.busy && s.runningCommand === "wireless" ? "Looking at the network…" : "Press r to look again" })
    } else {
      if (w.mdns && w.mdns.available && w.qrencode && w.qrencode.found)
        out.push({ type: "action", icon: wirelessGlyphs.qr, label: "Pair with a QR code",
                   detail: "The phone scans it · Wireless debugging › Pair device with QR code", action: "pairqr" })
      else if (!w.mdns || !w.mdns.available)
        out.push({ type: "note", label: w.mdns && w.mdns.supported === false ? "No QR pairing: adb has no mDNS"
                                     : w.mdns && w.mdns.text ? "No QR pairing: the mDNS check failed" : "No QR pairing: mDNS not checked",
                   detail: w.mdns && w.mdns.text ? w.mdns.text : "adb did not answer · press r to look again" })
      else
        out.push({ type: "note", label: "No QR pairing: qrencode not installed", detail: "Install the qrencode package (it is in Omarchy's base set), or pair with a code." })
      out.push({ type: "action", icon: wirelessGlyphs.key, label: "Pair with a code",
                 detail: "The six digits under Wireless debugging › Pair device with pairing code; the address is picked off the network", page: "paircode" })
    }
    out.push({ type: "header", label: "Wi-Fi devices" })
    var wifi = 0
    for (var i = 0; i < s.devices.length; i++) {
      var d = s.devices[i]
      if (d.kind !== "wifi") continue
      wifi++
      out.push({ type: "action", icon: kindGlyphs.wifi, label: d.label || d.serial, detail: (d.detail || "") + " · Enter disconnects",
                 action: "disconnect", addr: d.serial, urgent: d.state !== "device" })
    }
    if (wifi === 0) out.push({ type: "note", label: "None connected" })
    if (w && Array.isArray(w.services)) {
      var seen = false
      for (var k = 0; k < w.services.length; k++) {
        var sv = w.services[k]
        if (sv.kind !== "connect" || sv.attached) continue
        if (!seen) { out.push({ type: "header", label: "Seen on the network" }); seen = true }
        out.push({ type: "action", icon: kindGlyphs.wifi, label: sv.instance || sv.address, detail: (sv.detail || "") + " · Enter connects",
                   action: "connect", addr: sv.address })
      }
    }
    // A tunnel interface up on this machine (the helper read /sys/class/net):
    // the usual reason nothing on Wi-Fi ever answers is a VPN isolating the
    // LAN, so the page says one is up. Not urgent: a VPN that lets the LAN
    // through is fine. The label and the text are the helper's.
    if (w && w.vpn && w.vpn.up)
      out.push({ type: "note", icon: wirelessGlyphs.vpn, label: w.vpn.label || "A VPN is up", detail: w.vpn.text || "" })
    return out
  }

  // Step one takes the pairing address, step two the code; `current.addr`
  // tells them apart (the code step is its own stack entry, so Esc and
  // Backspace go back to the addresses with the typed one restored). While the phone's pairing dialog is open it advertises
  // the pairing address on mDNS (`_adb-tls-pairing._tcp`), so the addresses
  // seen are rows and typing one is the fallback; six digits typed there are
  // the code in the wrong box (seen 2026-09-07) and are refused. The code
  // never touches an argv: it goes to the helper's stdin and from there to
  // adb's.
  function paircodeRows() {
    var s = root.store
    var out = []
    if (!s.hasAdb) {
      out.push({ type: "note", urgent: true, label: "adb not found", detail: noAdbDetail() })
      return out
    }
    var addr = current.addr || ""
    if (addr === "") {
      var isCode = /^\d{6}$/.test(query)
      if (query !== "")
        out.push({ type: "action", icon: wirelessGlyphs.link, label: query,
                   detail: isCode ? "That is the code; the pairing address (ip:port) comes first" : "Use this as the pairing address, then type the code",
                   action: "pairaddr", addr: query, urgent: isCode })
      var w = s.wirelessInfo
      var seen = 0
      if (w && Array.isArray(w.services)) {
        for (var k = 0; k < w.services.length; k++) {
          var sv = w.services[k]
          if (sv.kind !== "pairing") continue
          seen++
          out.push({ type: "action", icon: wirelessGlyphs.key, label: sv.address,
                     detail: (sv.instance || "") + " · pairing address seen on the network · Enter uses it", action: "pairaddr", addr: sv.address })
        }
      }
      if (seen === 0 && query === "")
        out.push({ type: "note", label: !w && s.busy && s.runningCommand === "wireless" ? "Looking at the network…" : "No pairing address seen yet",
                   detail: "Open Wireless debugging › Pair device with pairing code on the phone and press r; or type its ip:port (not the one on the main screen), then Enter." })
      return out
    }
    // A literal around the address, like "Logcat · PKG".
    out.push({ type: "note", icon: wirelessGlyphs.key, label: "Pairing with " + addr, detail: "Now the six digits, then Enter" })
    if (query !== "")
      out.push({ type: "action", icon: wirelessGlyphs.key, label: query,
                 detail: /^\d{6}$/.test(query) ? "Enter sends the code to adb pair on stdin" : "Six digits", action: "paircode", addr: addr, code: query })
    return out
  }

  function keyHint() {
    if (page === "hub") return "j/k move · Enter opens · r refreshes · Esc closes"
    if (page === "devices") return "j/k move · Enter selects · r refreshes · Esc back"
    if (page === "info") return "j/k move · Enter copies the value · r reads again · Esc back"
    if (page === "packages") return "Type to filter · ↑/↓ move · Enter opens · r lists again · Esc back"
    if (page === "actions") return "j/k move · Enter runs it · Esc back"
    if (page === "deeplink") return "Type a URL, Enter launches · ↑/↓ recent · Esc back"
    if (page === "toggles") return "j/k move · Enter flips · r reads again · Esc back"
    if (page === "tweaks") return "j/k move · Enter flips or picks · r reads again · Esc back"
    if (page === "fontpick" || page === "densitypick") return "j/k move · Enter sets it · r reads again · Esc back"
    if (page === "capture") return "j/k move · Enter runs it · Esc back"
    if (page === "apks") return "Type a folder · Enter installs or opens · r lists again · Esc back"
    if (page === "text") return "Type a line, Enter sends it · ↑/↓ move · Esc back"
    if (page === "tools") return "j/k move · Enter runs it · r reads again · Esc back"
    if (page === "wireless") return "j/k move · Enter runs it · r looks again · Esc back"
    if (page === "paircode") return "Enter takes the address, then the code · r looks again · Esc back"
    if (page === "avdboot" || page === "launchpick") return "j/k move · Enter starts it · Esc back"
    if (page === "settings") return "j/k or Tab move · Enter edits or flips · Enter on Save · Esc cancels"
    return "Esc or Backspace back"
  }

  // ---- Settings -----------------------------------------------------------
  // The twelve settings live inline on the plugin's shell.json entry. The
  // form edits copies (the fields' text, `pending*` for the toggles) and
  // Save writes the keys that changed in one `updateEntryInline`, which
  // the shell patches into the running widget in place (no remount, the
  // panel stays open); the new entry reaches the service through the host
  // widget, so the store's next run and the restarted tracker carry it at
  // once. The manifest's defaults, repeated: QML cannot read manifest.json
  // cheaply (tests/test_manifest.py pins the copies together, with the
  // helper's and the store's key lists).
  readonly property var settingsDefaults: ({ adbPath: "", screenshotDir: "", recordingDir: "", apkDir: "~/Downloads", scrcpyArgs: "",
                                             mirrorScreenOff: false, mirrorKeys: true, notify: true, deviceNotifications: true, confirmUninstall: true,
                                             showSystemApps: false, openAsWindow: false })
  readonly property var settingsTextKeys: ["adbPath", "screenshotDir", "recordingDir", "apkDir", "scrcpyArgs"]
  readonly property var settingsBoolKeys: ["mirrorScreenOff", "mirrorKeys", "notify", "deviceNotifications", "confirmUninstall", "showSystemApps", "openAsWindow"]
  property bool pendingMirrorScreenOff: false
  property bool pendingMirrorKeys: true
  property bool pendingNotify: true
  property bool pendingDeviceNotifications: true
  property bool pendingConfirmUninstall: true
  property bool pendingShowSystemApps: false
  property bool pendingOpenAsWindow: false
  // The keyboard cursor over the form's controls, in `formControls` order.
  property int formCursor: 0
  // What a text field held when its editor took the keys, for Escape.
  property string fieldEditStart: ""

  function settingValue(key) { return store ? store.setting(key, settingsDefaults[key]) : settingsDefaults[key] }
  function settingText(key) {
    var v = settingValue(key)
    return v === null || v === undefined ? "" : String(v)
  }
  function settingFlag(key) { return store ? store.flag(key, settingsDefaults[key]) : settingsDefaults[key] }

  readonly property var formFields: [adbPathField, screenshotDirField, recordingDirField, apkDirField, scrcpyArgsField]
  readonly property var formToggles: [mirrorScreenOffToggle, mirrorKeysToggle, notifyToggle, deviceNotificationsToggle, confirmUninstallToggle, showSystemAppsToggle, openAsWindowToggle]
  readonly property var formControls: formFields.concat(formToggles).concat([saveButton, cancelButton])

  function pendingFlag(key) {
    return key === "mirrorScreenOff" ? pendingMirrorScreenOff : key === "mirrorKeys" ? pendingMirrorKeys : key === "notify" ? pendingNotify
      : key === "deviceNotifications" ? pendingDeviceNotifications
      : key === "confirmUninstall" ? pendingConfirmUninstall
      : key === "showSystemApps" ? pendingShowSystemApps : pendingOpenAsWindow
  }

  function setPendingFlag(key, value) {
    if (key === "mirrorScreenOff") pendingMirrorScreenOff = value
    else if (key === "mirrorKeys") pendingMirrorKeys = value
    else if (key === "notify") pendingNotify = value
    else if (key === "deviceNotifications") pendingDeviceNotifications = value
    else if (key === "confirmUninstall") pendingConfirmUninstall = value
    else if (key === "showSystemApps") pendingShowSystemApps = value
    else if (key === "openAsWindow") pendingOpenAsWindow = value
  }

  // The pending values start as what is saved, or the manifest's default.
  function loadPendingSettings() {
    for (var i = 0; i < settingsTextKeys.length; i++) formFields[i].text = settingText(settingsTextKeys[i])
    for (var k = 0; k < settingsBoolKeys.length; k++) setPendingFlag(settingsBoolKeys[k], settingFlag(settingsBoolKeys[k]))
    formCursor = 0
    settingsScroll.contentY = 0
  }

  // The clock panel's pattern: merge over the entry, apply locally first so
  // the service and the pages react now, then one atomic shell.json write.
  // `updateEntryInline` replaces the whole entry, hence the merge over the
  // bar widget's entry (the store's copy of it when this host has no
  // widget: the window). Returns whether anything was written (a widget
  // outside the bar layout cannot).
  function persistSettings(values) {
    var entry = { id: moduleName }
    var current = hostWidget && hostWidget.settings ? hostWidget.settings : (store && store.settings ? store.settings : ({}))
    for (var k in current) if (k !== "id") entry[k] = current[k]
    for (var key in values) entry[key] = values[key]
    if (hostWidget && "settings" in hostWidget) hostWidget.settings = entry
    if (shell && typeof shell.updateEntryInline === "function")
      return shell.updateEntryInline(moduleName, entry) === true
    return false
  }

  function saveSettings() {
    if (!isSettingsForm) return
    keyCatcher.forceActiveFocus()
    var changed = {}
    var any = false
    for (var i = 0; i < settingsTextKeys.length; i++) {
      var key = settingsTextKeys[i]
      var value = String(formFields[i].text).trim()
      if (value !== settingText(key).trim()) { changed[key] = value; any = true }
    }
    for (var b = 0; b < settingsBoolKeys.length; b++) {
      var bkey = settingsBoolKeys[b]
      var saved = settingValue(bkey)
      // Written as a boolean, also when it was stored as the word "false".
      var word = saved !== undefined && saved !== null && saved !== true && saved !== false
      if (pendingFlag(bkey) !== settingFlag(bkey) || word) { changed[bkey] = pendingFlag(bkey); any = true }
    }
    if (!any) { pop(); return }
    var written = persistSettings(changed)
    if (store) store.showNotice(written ? "Settings saved" : "Settings kept for this session only: the widget is not in the bar layout", !written)
    pop()
    // The adb path or a folder may have moved: the hub's rows follow.
    if (store) store.refreshStatus()
  }

  function moveFormCursor(delta) {
    var n = formControls.length
    formCursor = (formCursor + delta + n) % n
    ensureFormCursorVisible()
  }

  function ensureFormCursorVisible() {
    var item = formControls[formCursor]
    if (!item) return
    if (formFields.indexOf(item) === -1 && formToggles.indexOf(item) === -1) return   // the footer's buttons
    var top = item.mapToItem(settingsForm, 0, 0).y
    var bottom = top + item.height
    if (top < settingsScroll.contentY) settingsScroll.contentY = top
    else if (bottom > settingsScroll.contentY + settingsScroll.height)
      settingsScroll.contentY = Math.max(0, bottom - settingsScroll.height)
  }

  // h/l and the arrows flip a toggle; a text field is edited with Enter.
  function stepFormControl(dx) {
    var at = formToggles.indexOf(formControls[formCursor])
    if (at !== -1) setPendingFlag(settingsBoolKeys[at], !pendingFlag(settingsBoolKeys[at]))
  }

  // Enter and Space: a text field takes the keys, a toggle flips, the
  // buttons act.
  function activateFormControl() {
    var c = formControls[formCursor]
    var field = formFields.indexOf(c)
    var toggle = formToggles.indexOf(c)
    if (field !== -1) { c.input.forceActiveFocus(); c.input.cursorPosition = c.input.length }
    else if (toggle !== -1) setPendingFlag(settingsBoolKeys[toggle], !pendingFlag(settingsBoolKeys[toggle]))
    else if (c === saveButton) saveSettings()
    else if (c === cancelButton) pop()
  }

  // Keys that reach a text field while it has them: Enter keeps the text
  // and returns to the catcher, Escape puts the value from before back,
  // Tab and the arrows leave for the next control. Everything else edits.
  function formFieldKey(event, input) {
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      keyCatcher.forceActiveFocus()
      event.accepted = true
    } else if (event.key === Qt.Key_Escape) {
      input.text = fieldEditStart
      keyCatcher.forceActiveFocus()
      event.accepted = true
    } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab || event.key === Qt.Key_Down || event.key === Qt.Key_Up) {
      keyCatcher.forceActiveFocus()
      moveFormCursor(event.key === Qt.Key_Tab || event.key === Qt.Key_Down ? 1 : -1)
      event.accepted = true
    }
  }

  // True while a text field owns the keyboard; the catcher is blocked
  // then, and Backspace edits instead of popping the page.
  readonly property bool settingsKeysOwned: adbPathField.input.activeFocus || screenshotDirField.input.activeFocus
    || recordingDirField.input.activeFocus || apkDirField.input.activeFocus || scrcpyArgsField.input.activeFocus

  // A labelled text field for the form: the label, the field, a hint. The
  // field's `text` is the pending value; `input` is the kit TextField.
  component SettingField: Column {
    id: settingField
    required property int slot
    property string label: ""
    property string hint: ""
    property string placeholder: ""
    property alias text: settingInput.text
    readonly property alias input: settingInput
    spacing: Style.space(3)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: settingField.label
      color: root.contentForeground
      font.family: root.contentFontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      elide: Text.ElideRight
    }

    TextField {
      id: settingInput
      width: parent.width
      foreground: root.contentForeground
      font.family: root.contentFontFamily
      placeholderText: settingField.placeholder
      hasCursor: root.formCursor === settingField.slot
      onHoveredChanged: if (hovered) root.formCursor = settingField.slot
      onActiveFocusChanged: if (activeFocus) { root.formCursor = settingField.slot; root.fieldEditStart = text }
      Keys.onPressed: function(event) { root.formFieldKey(event, settingInput) }
    }

    Text {
      visible: settingField.hint !== ""
      width: parent.width
      textFormat: Text.PlainText
      text: settingField.hint
      color: root.mutedForeground
      font.family: root.contentFontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.Wrap
    }
  }

  // ---- Cursor -------------------------------------------------------------
  property int selectedIndex: -1

  // Hover moves the cursor only when the pointer itself moved: rows that
  // re-layout under a resting pointer (a tracker frame landing) get a
  // synthetic move and must not steal the cursor from the keyboard.
  property point lastPointer: Qt.point(-1, -1)

  function hoverRow(index, item, x, y) {
    var p = item.mapToItem(null, x, y)
    if (p.x === lastPointer.x && p.y === lastPointer.y) return
    lastPointer = p
    selectedIndex = index
  }

  function isCursorRow(row) {
    return row && row.type === "action"
  }

  function firstCursorIndex() {
    for (var i = 0; i < rows.length; i++) if (isCursorRow(rows[i])) return i
    return -1
  }

  onRowsChanged: {
    if (selectedIndex < 0 || selectedIndex >= rows.length || !isCursorRow(rows[selectedIndex]))
      selectedIndex = firstCursorIndex()
  }

  function moveCursor(dy) {
    var cursorRows = []
    for (var i = 0; i < rows.length; i++) if (isCursorRow(rows[i])) cursorRows.push(i)
    if (cursorRows.length === 0) return
    var pos = cursorRows.indexOf(selectedIndex)
    if (pos === -1) pos = dy > 0 ? -1 : 0
    pos = (pos + dy + cursorRows.length) % cursorRows.length
    selectedIndex = cursorRows[pos]
    ensureCursorVisible()
  }

  // Scroll the list so the cursor row is on screen (j/k past the fold).
  function ensureCursorVisible() {
    var item = rowRepeater.itemAt(selectedIndex)
    if (!item) return
    var top = item.y
    var bottom = item.y + item.height
    if (top < listScroll.contentY) listScroll.contentY = top
    else if (bottom > listScroll.contentY + listScroll.height)
      listScroll.contentY = Math.max(0, bottom - listScroll.height)
  }

  // ---- Actions ------------------------------------------------------------
  // Everything that touches the device goes through the service, which
  // runs the helper and turns the result into a notification as well.
  // `silent` reaches the service: a batch install passes it so the one
  // summary notification is the only one (before 1.0.0 it was dropped here
  // and Install all sent one per file plus the summary). `stdinText` is
  // what the helper reads on stdin (the pairing code).
  function act(args, onDone, silent, stdinText) {
    if (service && typeof service.act === "function") service.act(args, onDone, silent, stdinText)
    else if (store) store.run(args, onDone, stdinText)
  }

  // Pop until `name` is the page (or the hub is reached).
  function popTo(name) {
    while (stack.length > 1 && page !== name) {
      var entry = stack[stack.length - 2]
      stack = stack.slice(0, -1)
      if (page === name || stack.length === 1) enterPage(entry)
    }
  }

  function activate(row) {
    if (!row || confirmOpen) return
    if (row.type === "title") { pop(); return }
    if (row.type !== "action") return
    if (row.action === "refresh") refresh()
    else if (row.action === "copyinfo") { if (service && typeof service.copyText === "function") service.copyText(row.value) }
    else if (row.action === "pairqr") { if (service && typeof service.startPairing === "function") service.startPairing() }
    else if (row.action === "pairstop") { if (service && typeof service.stopPairing === "function") service.stopPairing() }
    else if (row.action === "pairaddr") {
      if (/^\d{6}$/.test(row.addr)) { if (store) store.showNotice("That is the code: the pairing address (ip:port) comes first", true); return }
      push({ page: "paircode", addr: row.addr })  // its own step: Esc goes back to the addresses
    }
    else if (row.action === "paircode") {
      if (!/^\d{6}$/.test(row.code)) { if (store) store.showNotice("The pairing code is six digits", true); return }
      filterField.text = ""
      act(["pair", "code", row.addr], function(doc) { if (doc && doc.ok !== false && root.page === "paircode") root.popTo("wireless") }, false, row.code + "\n")
    }
    else if (row.action === "connect") act(["connect", row.addr])
    else if (row.action === "disconnect") act(["disconnect", row.addr])
    else if (row.action === "select") { if (store) store.selectDevice(row.serial); pop() }
    else if (row.action === "package") push({ page: "actions", pkg: row.pkg })
    else if (row.action === "deeplink") act(["deeplink", row.url].concat(row.pkg ? [row.pkg] : []))
    else if (row.action === "app") runAppAction(row)
    else if (row.action === "toggle") act(["toggle", row.name])
    else if (row.action === "tweak") act(["tweak", row.name])
    else if (row.action === "fontpick") push({ page: "fontpick" })
    else if (row.action === "densitypick") push({ page: "densitypick" })
    else if (row.action === "fontset") { pop(); act(["tweak", "font", String(row.value)]) }
    else if (row.action === "densityset") { pop(); act(["tweak", "density", row.reset ? "reset" : String(row.value)]) }
    else if (row.action === "screenshot") act(["screenshot"])
    else if (row.action === "record") { if (service && typeof service.toggleRecording === "function") service.toggleRecording() }
    else if (row.action === "apkdir") filterField.text = row.dir  // the folder box; the list follows, debounced
    else if (row.action === "install") installApks([row.path])
    else if (row.action === "installall") installApks(row.paths)
    else if (row.action === "text") act(["text", "send", row.text])
    else if (row.action === "clipboard") act(["text", "clipboard"])
    else if (row.action === "scrcpy") act(["tool", "scrcpy"])
    else if (row.action === "logcat") act(["tool", "logcat"].concat(row.pkg ? [row.pkg] : []))
    else if (row.action === "avdboot") push({ page: "avdboot", avd: row.avd })
    else if (row.action === "avdstart") {
      // Back to Tools first (it re-reads on entry), then the launch; the
      // answer re-reads once more so the row follows the emulator.
      pop()
      act(["tool", "avd", row.avd].concat(row.cold ? ["cold"] : []), function() { if (root.page === "tools") root.store.refreshTools() })
    }
    else if (row.action === "launchact") {
      // Back to the package's page, then the launch with the activity named;
      // the answer re-reads the package so the note and the picker row show the pick.
      var picked = row.pkg
      pop()
      act(["app", "launch", row.pkg, row.component], function(doc) {
        if (doc && doc.ok !== false && root.page === "actions" && root.current.pkg === picked) root.store.fetchPackage(picked)
      })
    }
    else if (row.action === "avdstop") openConfirm(row)
    else if (row.action === "openwindow") openAsWindowRow()
    else if (row.page) push({ page: row.page })
  }

  function runAppAction(row) {
    var pkg = row.pkg
    if (row.act === "deeplink") { push({ page: "deeplink", pkg: pkg }); return }
    if (row.act === "pick") { push({ page: "launchpick", pkg: pkg }); return }
    if (row.act === "launch") {
      // Several launcher activities and none picked yet: the picker first;
      // once one is picked (or with one activity) Launch goes straight on.
      var info = store ? store.packageDetails[pkg] : null
      if (hasSeveralLaunchers(info) && !info.launcher_picked) { push({ page: "launchpick", pkg: pkg }); return }
    }
    if (row.act === "grant" || row.act === "revoke") { act(["perms", row.act, pkg]); return }
    if (row.act === "uninstall") {
      if (store && store.flag("confirmUninstall", true)) { openConfirm(row); return }
      uninstall(pkg)
      return
    }
    act(["app", row.act, pkg])
  }

  function uninstall(pkg) {
    act(["app", "uninstall", pkg], function(doc) {
      // Nothing to act on any more: back to the list, which re-reads.
      if (doc && doc.ok !== false && root.page === "actions" && root.current.pkg === pkg) root.pop()
    })
  }

  // ---- The confirm dialog -------------------------------------------------
  // Uninstall (the `confirmUninstall` setting) and stopping an emulator ask
  // first. The row that asked is kept; Cancel is preselected.
  property bool confirmOpen: false
  property var confirmRow: null
  readonly property string confirmMessage: !confirmRow ? ""
    : confirmRow.action === "avdstop" ? "Stop " + confirmRow.avd + "? The emulator shuts down; unsaved state may be lost."
    : "Uninstall " + (confirmRow.pkg || "") + "? This will remove the app and all its data from the device."
  readonly property string confirmText: confirmRow && confirmRow.action === "avdstop" ? "Stop" : "Uninstall"

  function openConfirm(row) {
    confirmRow = row
    confirmDialog.selectedIndex = 0
    confirmOpen = true
  }

  function cancelConfirm() {
    confirmOpen = false
    confirmRow = null
  }

  function acceptConfirm() {
    var row = confirmRow
    cancelConfirm()
    if (!row) return
    if (row.action === "avdstop") act(["tool", "avd-stop", row.serial], function() { if (root.page === "tools") root.store.refreshTools() })
    else if (row.pkg) uninstall(row.pkg)
  }

  // A folder's listing lands: the cursor goes to its first row and the list
  // scrolls to it. The rows under the old cursor are another folder's files,
  // and Enter installs.
  Connections {
    target: root.store
    function onApkListChanged() {
      if (!root.opened || root.page !== "apks") return
      root.selectedIndex = root.firstCursorIndex()
      Qt.callLater(function() { root.ensureCursorVisible() })  // after the Repeater has laid the rows out
    }
  }

  // The Running/Stopped state of the AVD rows follows the tracker: a stopped
  // emulator leaves the device list a few seconds after `emu kill` (it saves
  // its snapshot first), a started one joins it when it boots.
  Connections {
    target: root.store
    function onDevicesChanged() {
      if (!root.opened) return
      if (root.page === "tools") root.store.refreshTools()
      // A Wi-Fi entry joining or dropping repaints the lists and re-reads the services.
      else if (root.page === "wireless") wirelessRefresh.restart()
    }
  }

  // A pairing session ending (paired, cancelled, failed) re-reads the page.
  Connections {
    target: root.service
    function onPairingChanged() { if (root.opened && root.page === "wireless" && !root.service.pairing) wirelessRefresh.restart() }
  }

  // One read for a burst: a connect or a pairing answers with the device
  // list and the tracker frames it again right after, each a change. Before
  // 1.4.1 that was three or four `wireless` runs.
  Timer {
    id: wirelessRefresh
    interval: 300
    repeat: false
    onTriggered: if (root.opened && root.page === "wireless") root.store.refreshWireless()
  }

  onOpenedChanged: {
    if (opened) {
      if (store) store.refreshStatus()
      // A page asked for while closed: this host's own, else (the popup)
      // the one the service holds for whichever widget the shell summoned.
      var pending = pendingStack
      pendingStack = null
      if (!pending && takesServicePage && service && typeof service.takePendingPage === "function") {
        var page = service.takePendingPage()
        if (page) pending = stackFor(page)
      }
      if (pending) {
        stack = pending
        enterPage(stack[stack.length - 1])
      } else {
        goHome()
      }
    } else {
      cancelConfirm()
    }
  }

  // What the content wants to be tall, for a host that sizes itself to it
  // (the popup, under its cap); the window keeps its own size and the
  // lists scroll inside it.
  readonly property real desiredHeight: isSettingsForm ? settingsForm.implicitHeight + settingsFooter.implicitHeight + Style.space(20)
    : contentColumn.implicitHeight + (hasField ? filterField.height + Style.space(6) : 0)
  // Where the keys go once the host shows: the box on the pages that have
  // one, else the catcher.
  readonly property Item focusTarget: hasField ? filterField : keyCatcher

  // Unhandled keys from the catcher (it never accepts Backspace, and
  // nothing while blocked) land here: the dialog's keys, then Backspace.
  Item {
    id: pageArea
    anchors.fill: parent

    Keys.onPressed: function(event) {
      if (root.confirmOpen) {
        if (confirmDialog.handleKey(event)) event.accepted = true
        return
      }
      if (event.key === Qt.Key_Backspace && !filterField.activeFocus && !root.settingsKeysOwned) {
        root.pop()
        event.accepted = true
      }
    }

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      clip: true
      blocked: filterField.activeFocus || root.confirmOpen || root.settingsKeysOwned
      onMoveRequested: function(dx, dy) {
        if (root.isSettingsForm) {
          if (dy !== 0) root.moveFormCursor(dy)
          else if (dx !== 0) root.stepFormControl(dx)
        } else if (dy !== 0) root.moveCursor(dy)
      }
      onActivateRequested: {
        if (root.isSettingsForm) root.activateFormControl()
        else root.activate(root.rows[root.selectedIndex])
      }
      onCloseRequested: root.pop()
      // Tab walks the settings form; elsewhere it switches bar panels.
      onTabRequested: function(direction) {
        if (root.isSettingsForm) root.moveFormCursor(direction)
        else root.switchRequested(direction)
      }
      onTextKey: function(t) {
        if (root.isSettingsForm) return
        if (t === "r" || t === "R") root.refresh()
        else if (t === "/" && root.hasField) filterField.forceActiveFocus()
      }

      // The filter box (Apps) or the URL box (Deep link). Up/Down, Enter,
      // Escape and Tab are forwarded; everything else edits the text.
      TextField {
        id: filterField
        visible: root.hasField
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Style.space(8)
        anchors.rightMargin: Style.space(8)
        foreground: root.contentForeground
        font.family: root.contentFontFamily
        placeholderText: root.page === "deeplink" ? "URL or deep link, then Enter"
          : root.page === "apks" ? "Folder with .apk files"
          : root.page === "text" ? "Text to type on the device, then Enter"
          : root.page === "paircode" ? (root.current.addr ? "The six-digit pairing code, then Enter" : "Pairing address ip:port, or Enter on one seen")
          : "Filter packages"

        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Escape) {
            root.pop()
            event.accepted = true
          } else if (event.key === Qt.Key_Down) {
            root.moveCursor(1)
            event.accepted = true
          } else if (event.key === Qt.Key_Up) {
            root.moveCursor(-1)
            event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            root.activate(root.rows[root.selectedIndex])
            event.accepted = true
          } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
            keyCatcher.forceActiveFocus()
            event.accepted = true
          } else if (event.key === Qt.Key_Backspace && text === "") {
            root.pop()
            event.accepted = true
          }
        }
      }

      Flickable {
        id: listScroll
        visible: !root.isSettingsForm
        anchors.top: root.hasField ? filterField.bottom : parent.top
        anchors.topMargin: root.hasField ? Style.space(6) : 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        contentWidth: width
        contentHeight: contentColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: contentColumn
          width: listScroll.width
          spacing: Style.space(2)

          Repeater {
            id: rowRepeater
            model: root.rows

            delegate: Item {
              id: rowItem
              required property var modelData
              required property int index

              readonly property string kind: modelData.type
              // The running figure for a `live` row: a count, appended to a literal.
              readonly property string live: modelData.live === "countdown" ? root.pairingLeft + " s left"
                : modelData.live === "elapsed" ? root.recordingElapsed : ""
              readonly property bool isAction: kind === "action"
              readonly property bool isTitle: kind === "title"
              readonly property bool hasCursor: isAction && index === root.selectedIndex
              readonly property bool twoLine: isAction && !!modelData.detail
              readonly property color rowForeground: isAction && modelData.muted === true ? root.mutedForeground
                : isAction && modelData.urgent === true ? root.urgentForeground : root.contentForeground

              width: contentColumn.width
              height: kind === "sep" ? Style.space(11)
                : kind === "header" ? headerLabel.implicitHeight + Style.space(8)
                : kind === "title" ? Style.space(30)
                : kind === "note" ? noteColumn.implicitHeight + Style.space(12)
                : kind === "qr" ? qrColumn.implicitHeight + Style.space(16)
                : kind === "footer" ? footerLabel.implicitHeight + Style.space(8)
                : twoLine ? Style.space(44) : Style.space(32)

              PanelSeparator {
                visible: rowItem.kind === "sep"
                anchors.verticalCenter: parent.verticalCenter
                foreground: root.contentForeground
              }

              PanelSectionHeader {
                id: headerLabel
                visible: rowItem.kind === "header"
                text: rowItem.kind === "header" ? rowItem.modelData.label : ""
                foreground: root.contentForeground
                fontFamily: root.contentFontFamily
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Style.space(2)
              }

              // ‹ Page title, clicking it goes back.
              Item {
                visible: rowItem.isTitle
                anchors.fill: parent

                Row {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(8)

                  Text {
                    height: parent.height
                    textFormat: Text.PlainText
                    text: "‹"
                    color: root.mutedForeground
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.title
                    verticalAlignment: Text.AlignVCenter
                  }

                  Text {
                    width: parent.width - Style.space(20)
                    height: parent.height
                    textFormat: Text.PlainText
                    text: rowItem.isTitle ? rowItem.modelData.label : ""
                    color: root.contentForeground
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.title
                    font.bold: true
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideMiddle
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.pop()
                }
              }

              Column {
                id: noteColumn
                visible: rowItem.kind === "note"
                width: parent.width - Style.space(16)
                x: Style.space(8)
                spacing: Style.space(3)
                anchors.verticalCenter: parent.verticalCenter

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: (rowItem.modelData.icon ? rowItem.modelData.icon + "  " : "") + (rowItem.modelData.label || "") + (rowItem.live ? " · " + rowItem.live : "")
                  color: rowItem.modelData.urgent ? root.urgentForeground : root.contentForeground
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.body
                  wrapMode: Text.Wrap
                }

                Text {
                  visible: !!rowItem.modelData.detail
                  width: parent.width
                  textFormat: Text.PlainText
                  text: rowItem.modelData.detail || ""
                  color: root.mutedForeground
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.Wrap
                }
              }

              // The pairing code: the PNG the helper wrote (0600, in the
              // state dir, gone when the session ends) on a white card, the
              // instruction under it. Re-read every time (`cache: false`):
              // the path repeats across sessions of one helper pid. Loaded
              // off the UI thread, once per session: the row is static and
              // the countdown is bound below, not in the model.
              Column {
                id: qrColumn
                visible: rowItem.kind === "qr"
                width: parent.width - Style.space(16)
                x: Style.space(8)
                spacing: Style.space(6)
                anchors.verticalCenter: parent.verticalCenter

                Rectangle {
                  width: Style.space(200)
                  height: width
                  radius: Style.cornerRadius
                  color: "white"
                  anchors.horizontalCenter: parent.horizontalCenter

                  Image {
                    anchors.fill: parent
                    anchors.margins: Style.space(6)
                    source: rowItem.kind === "qr" && rowItem.modelData.path ? Util.fileUrl(String(rowItem.modelData.path)) : ""
                    cache: false
                    asynchronous: true
                    smooth: false
                    fillMode: Image.PreserveAspectFit
                  }
                }

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: rowItem.kind === "qr" ? (rowItem.modelData.label || "") : ""
                  color: root.contentForeground
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.body
                  wrapMode: Text.Wrap
                  horizontalAlignment: Text.AlignHCenter
                }

                Text {
                  visible: rowItem.kind === "qr" && !!rowItem.modelData.detail
                  width: parent.width
                  textFormat: Text.PlainText
                  text: rowItem.kind === "qr" ? (rowItem.modelData.detail || "") + (rowItem.live ? " · " + rowItem.live : "") : ""
                  color: root.urgentForeground
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.Wrap
                  horizontalAlignment: Text.AlignHCenter
                }
              }

              Text {
                id: footerLabel
                visible: rowItem.kind === "footer"
                width: parent.width - Style.space(16)
                x: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: rowItem.kind === "footer" ? rowItem.modelData.label : ""
                color: root.mutedForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }

              CursorSurface {
                visible: rowItem.isAction
                anchors.fill: parent
                hasCursor: rowItem.hasCursor
                foreground: root.contentForeground
                accent: Color.accent

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  onPositionChanged: function(mouse) { root.hoverRow(rowItem.index, rowItem, mouse.x, mouse.y) }
                  onClicked: root.activate(rowItem.modelData)
                }

                //  Label                                      detail below
                Row {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  spacing: Style.space(10)

                  Text {
                    width: Style.space(18)
                    height: parent.height
                    textFormat: Text.PlainText
                    text: rowItem.isAction ? (rowItem.modelData.icon || "") : ""
                    color: rowItem.rowForeground
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.body
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                  }

                  Column {
                    width: parent.width - Style.space(18) - parent.spacing
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(1)

                    Text {
                      width: parent.width
                      textFormat: Text.PlainText
                      text: rowItem.isAction ? (rowItem.modelData.label || "") : ""
                      color: rowItem.rowForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.body
                      elide: Text.ElideMiddle
                    }

                    Text {
                      visible: rowItem.twoLine
                      width: parent.width
                      textFormat: Text.PlainText
                      text: (rowItem.live ? rowItem.live + " · " : "") + (rowItem.modelData.detail || "")
                      color: root.mutedForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    // The settings page. Outside the row Repeater: a tracker frame
    // landing rebuilds `rows` and must not reset a half-edited field.
    // The kit's controls paint themselves; the keyboard cursor
    // (`formCursor`) is ours, driven from the key catcher.
    Flickable {
      id: settingsScroll
      visible: root.isSettingsForm
      anchors.top: parent.top
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: settingsFooter.top
      anchors.leftMargin: Style.space(8)
      anchors.rightMargin: Style.space(8)
      contentWidth: width
      contentHeight: settingsForm.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      interactive: contentHeight > height

      Column {
        id: settingsForm
        width: settingsScroll.width
        spacing: Style.space(8)

        // ‹ Settings, clicking it backs out, like the list titles.
        Item {
          width: parent.width
          height: Style.space(30)

          Row {
            anchors.fill: parent
            spacing: Style.space(8)

            Text {
              height: parent.height
              textFormat: Text.PlainText
              text: "‹"
              color: root.mutedForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.title
              verticalAlignment: Text.AlignVCenter
            }

            Text {
              height: parent.height
              textFormat: Text.PlainText
              text: "Settings"
              color: root.contentForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              verticalAlignment: Text.AlignVCenter
            }
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.pop()
          }
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: "Saved on the plugin's entry in shell.json and applied at once. Empty means the default."
          color: root.mutedForeground
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.Wrap
        }

        SettingField {
          id: adbPathField
          slot: 0
          width: parent.width
          label: "adb binary"
          placeholder: "auto-detect"
          hint: root.store && root.store.hasAdb ? "In use: " + root.store.adbText
            : "Empty looks in $ANDROID_HOME or $ANDROID_SDK_ROOT, then ~/Android/Sdk/platform-tools, then PATH. A folder means the adb inside it."
        }

        SettingField {
          id: screenshotDirField
          slot: 1
          width: parent.width
          label: "Screenshot folder"
          placeholder: "Omarchy's screenshot folder"
          hint: "Empty uses OMARCHY_SCREENSHOT_DIR, else your Pictures folder."
        }

        SettingField {
          id: recordingDirField
          slot: 2
          width: parent.width
          label: "Recording folder"
          placeholder: "Omarchy's screen recording folder"
          hint: "Empty uses OMARCHY_SCREENRECORD_DIR, else your Videos folder."
        }

        SettingField {
          id: apkDirField
          slot: 3
          width: parent.width
          label: "APK folder"
          placeholder: "~/Downloads"
          hint: "Where the APKs page starts looking for .apk files."
        }

        SettingField {
          id: scrcpyArgsField
          slot: 4
          width: parent.width
          label: "Extra scrcpy arguments"
          placeholder: "none"
          hint: "Appended to the scrcpy command line, split on whitespace: --always-on-top --keyboard=uhid"
        }

        Toggle {
          id: mirrorScreenOffToggle
          width: parent.width
          label: "Mirror with the screen off"
          description: "scrcpy turns the device's screen off and keeps it awake while it mirrors (--turn-screen-off --stay-awake); the screen comes back when scrcpy closes."
          checked: root.pendingMirrorScreenOff
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          activeFocusOnTab: false
          hasCursor: root.formCursor === 5
          onHovered: function(on) { if (on) root.formCursor = 5 }
          onClicked: { root.formCursor = 5; root.pendingMirrorScreenOff = !root.pendingMirrorScreenOff }
        }

        Toggle {
          id: mirrorKeysToggle
          width: parent.width
          label: "Keys beside the mirror"
          description: "A strip of the phone's keys (Back, Home, Recents, the volume, Power, Screenshot, Record) next to the scrcpy window, following it around."
          checked: root.pendingMirrorKeys
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          activeFocusOnTab: false
          hasCursor: root.formCursor === 6
          onHovered: function(on) { if (on) root.formCursor = 6 }
          onClicked: { root.formCursor = 6; root.pendingMirrorKeys = !root.pendingMirrorKeys }
        }

        Toggle {
          id: notifyToggle
          width: parent.width
          label: "Notifications"
          description: "Desktop notifications for actions and captures."
          checked: root.pendingNotify
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          activeFocusOnTab: false
          hasCursor: root.formCursor === 7
          onHovered: function(on) { if (on) root.formCursor = 7 }
          onClicked: { root.formCursor = 7; root.pendingNotify = !root.pendingNotify }
        }

        Toggle {
          id: deviceNotificationsToggle
          width: parent.width
          label: "Device notifications"
          description: "Notify when a device connects, disconnects or needs authorising."
          checked: root.pendingDeviceNotifications
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          activeFocusOnTab: false
          hasCursor: root.formCursor === 8
          onHovered: function(on) { if (on) root.formCursor = 8 }
          onClicked: { root.formCursor = 8; root.pendingDeviceNotifications = !root.pendingDeviceNotifications }
        }

        Toggle {
          id: confirmUninstallToggle
          width: parent.width
          label: "Confirm uninstall"
          description: "Ask before uninstalling an app."
          checked: root.pendingConfirmUninstall
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          activeFocusOnTab: false
          hasCursor: root.formCursor === 9
          onHovered: function(on) { if (on) root.formCursor = 9 }
          onClicked: { root.formCursor = 9; root.pendingConfirmUninstall = !root.pendingConfirmUninstall }
        }

        Toggle {
          id: showSystemAppsToggle
          width: parent.width
          label: "Show system apps"
          description: "List every package on the Apps page, not only third-party ones."
          checked: root.pendingShowSystemApps
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          activeFocusOnTab: false
          hasCursor: root.formCursor === 10
          onHovered: function(on) { if (on) root.formCursor = 10 }
          onClicked: { root.formCursor = 10; root.pendingShowSystemApps = !root.pendingShowSystemApps }
        }

        Toggle {
          id: openAsWindowToggle
          width: parent.width
          label: "Open as a window"
          description: "The bar glyph's left click and the open, toggle and page verbs open the window instead of the popup; right click opens the popup then."
          checked: root.pendingOpenAsWindow
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          activeFocusOnTab: false
          hasCursor: root.formCursor === 11
          onHovered: function(on) { if (on) root.formCursor = 11 }
          onClicked: { root.formCursor = 11; root.pendingOpenAsWindow = !root.pendingOpenAsWindow }
        }
      }
    }

    // Save, Cancel and the key hint stay put under the scrolling form,
    // so a long form never hides the buttons.
    Column {
      id: settingsFooter
      visible: root.isSettingsForm
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.leftMargin: Style.space(8)
      anchors.rightMargin: Style.space(8)
      spacing: Style.space(8)

      PanelSeparator {
        width: parent.width
        foreground: root.contentForeground
      }

      Row {
        spacing: Style.space(8)

        Button {
          id: saveButton
          text: "Save"
          bordered: true
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
          hasCursor: root.formCursor === 12
          onHovered: function(on) { if (on) root.formCursor = 12 }
          onClicked: root.saveSettings()
        }

        Button {
          id: cancelButton
          text: "Cancel"
          foreground: root.mutedForeground
          fontFamily: root.contentFontFamily
          hasCursor: root.formCursor === 13
          onHovered: function(on) { if (on) root.formCursor = 13 }
          onClicked: root.pop()
        }
      }

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: root.keyHint()
        color: root.mutedForeground
        font.family: root.contentFontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.Wrap
      }
    }

    // Uninstall and Stop emulator ask first. Keys reach the dialog
    // through pageArea while the catcher is blocked.
    ConfirmDialog {
      id: confirmDialog
      anchors.fill: parent
      z: 10
      opened: root.confirmOpen
      message: root.confirmMessage
      confirmText: root.confirmText
      foreground: root.contentForeground
      fontFamily: root.contentFontFamily
      onCanceled: root.cancelConfirm()
      onConfirmed: root.acceptConfirm()
    }
  }
}
