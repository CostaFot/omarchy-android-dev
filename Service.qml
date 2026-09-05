pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io

// Android Dev service: headless, loaded once per shell while the plugin is
// enabled (`keepLoaded`). Owns the Store (the helper queue and the last
// documents), the device tracker (one `omarchy-android-dev track` process,
// restarted with backoff), the screen recorder (one `record` process while
// a recording runs), the pairer (one `pair qr` process while a pairing
// code is up), the device notifications and the plugin's IPC target. Bar widgets register themselves as hosts; the first one lends
// its settings (the shell injects settings only into bar widgets) and the
// panel verbs route through the shell's own summon/hide, which picks the
// widget on the focused monitor.
Item {
  id: root

  // Injected by the shell.
  property var shell: null
  property var manifest: null
  property string omarchyPath: ""

  readonly property string pluginId: "costafot.android-dev"
  readonly property string appName: "Android Dev"
  // nf-fa-android, written as an escape so no tool can strip it silently.
  readonly property string glyph: "\uf17b"
  readonly property string version: manifest && manifest.version ? String(manifest.version) : ""

  readonly property string pluginDir: {
    var dir = Qt.resolvedUrl(".").toString()
    return dir.replace(/^file:\/\//, "").replace(/\/$/, "")
  }

  // ---- Hosts ---------------------------------------------------------------
  // The bar widgets (one per monitor). Settings come from the first one;
  // with none placed the helper runs on its defaults.
  property var hosts: []
  readonly property var host: hosts.length > 0 ? hosts[0] : null
  readonly property var hostSettings: host && host.settings ? host.settings : ({})

  function registerHost(widget) {
    if (!widget || hosts.indexOf(widget) !== -1) return
    hosts = hosts.concat([widget])
  }

  function unregisterHost(widget) {
    var next = []
    for (var i = 0; i < hosts.length; i++) if (hosts[i] !== widget) next.push(hosts[i])
    hosts = next
  }

  readonly property Store store: Store {
    pluginDir: root.pluginDir
    settings: root.hostSettings
  }

  // ---- The tracker ---------------------------------------------------------
  // `track` streams one JSON line per adb track-devices frame and exits
  // only when adb is missing or goes away (one `error` line first). Every
  // exit that was not asked for restarts it after a backoff (5 s doubling
  // to 60 s, reset by the next good frame); a settings change restarts it
  // at once because adbPath may have moved.
  property bool stopping: false
  property bool trackerRestartPending: false
  property int trackerBackoffMs: 5000
  readonly property int trackerBackoffMaxMs: 60000
  property string trackerErrorCode: ""
  property string trackerError: ""
  readonly property bool tracking: tracker.running
  // serial → label from the last frame, so a removed device can be named.
  property var knownLabels: ({})
  // Serials that were in state `device` on the last frame: "connected"
  // means becoming ready, not appearing. An emulator appears as `offline`
  // with no model and becomes ready a minute later with its AVD name; a
  // phone appears ready, or `unauthorized` and then ready once accepted.
  property var knownReady: ({})
  // Unauthorised serials already notified, so one prompt gives one toast.
  property var reportedUnauthorized: ({})

  function trackerCommand() {
    return ["/bin/sh", "-c", 'exec "$0" "$@"', "/usr/bin/python3",
            pluginDir + "/bin/omarchy-android-dev", "--settings", store.settingsJson, "track"]
  }

  function startTracker() {
    if (stopping || tracker.running) return
    tracker.command = trackerCommand()
    tracker.running = true
  }

  // SIGTERM: the helper forwards it to adb and exits 0; nothing is left.
  function stopTracker() {
    restartTimer.stop()
    if (tracker.running) tracker.signal(15)
  }

  function restartTracker() {
    if (stopping) return
    if (tracker.running) {
      trackerRestartPending = true
      tracker.signal(15)
    } else {
      restartTimer.stop()
      startTracker()
    }
  }

  function applyTrackerLine(line) {
    var text = String(line || "").trim()
    if (text === "") return
    // The helper caps everything it prints (32 devices, 256-character
    // fields); a longer line did not come from a healthy run.
    if (text.length > 65536) {
      trackerErrorCode = "too_much_output"
      trackerError = "The device tracker printed a line longer than 64K characters; ignoring it"
      return
    }
    var ev
    try {
      ev = JSON.parse(text)
    } catch (e) {
      return
    }
    if (!ev || typeof ev !== "object") return
    if (ev.event === "devices" && Array.isArray(ev.devices)) {
      trackerErrorCode = ""
      trackerError = ""
      trackerBackoffMs = 5000
      store.applyTrackerEvent(ev)
      notifyDevices(ev)
      // A device on its way out passes through `offline`, where its label
      // falls back to the model; keep the label from when it was ready.
      var labels = {}
      for (var i = 0; i < ev.devices.length; i++) {
        var d = ev.devices[i]
        labels[d.serial] = d.state === "device" || !knownLabels[d.serial] ? (d.label || d.serial) : knownLabels[d.serial]
      }
      knownLabels = labels
      // adb was missing when the store last looked and is back now.
      if (!store.hasAdb && !store.busy) store.refreshStatus()
    } else if (ev.event === "error" && ev.error) {
      trackerErrorCode = String(ev.error.code || "internal")
      trackerError = String(ev.error.message || "The device tracker stopped")
      if (trackerErrorCode === "no_adb") store.adbInfo = { path: null, source: null, text: null }
    }
  }

  function labelIn(devices, serial) {
    for (var i = 0; i < devices.length; i++)
      if (devices[i].serial === serial && devices[i].state === "device") return devices[i].label || serial
    return knownLabels[serial] || serial
  }

  function notifyDevices(ev) {
    var wanted = !ev.initial && store.notifyEnabled && store.deviceNotifications
    var unauthorized = Array.isArray(ev.unauthorized) ? ev.unauthorized : []
    var seen = {}
    for (var u = 0; u < unauthorized.length; u++) seen[unauthorized[u]] = true
    var ready = {}
    for (var d = 0; d < ev.devices.length; d++) if (ev.devices[d].state === "device") ready[ev.devices[d].serial] = true
    if (wanted) {
      for (var serial in ready)
        if (!knownReady[serial]) notify("Android device connected", labelIn(ev.devices, serial))
      var removed = Array.isArray(ev.removed) ? ev.removed : []
      for (var r = 0; r < removed.length; r++)
        notify("Android device disconnected", labelIn(ev.devices, removed[r]))
      for (var n = 0; n < unauthorized.length; n++)
        if (!reportedUnauthorized[unauthorized[n]])
          notify("Android device needs authorising", "Accept the USB debugging prompt on " + labelIn(ev.devices, unauthorized[n]))
    }
    knownReady = ready
    reportedUnauthorized = seen
  }

  // ---- The recorder --------------------------------------------------------
  // `record` runs screenrecord on the device and streams a `recording`
  // event once it is going, then one final document (`recorded`, or an
  // `error`) when it ends: on SIGINT from here (`recorder.signal(2)`, what
  // Ctrl-C does in a terminal) or on screenrecord's own 3 minute limit.
  // The helper pulls the mp4, removes the device copy and sends the
  // notification itself; the final document goes through the store like
  // any other, so the panel shows the notice. One recording per shell.
  property bool recording: false
  property bool recordingStopping: false
  property double recordingStartedAt: 0
  property int recordingSeconds: 0
  property string recordingDevicePath: ""
  readonly property bool recorderRunning: recorder.running

  function recorderCommand() {
    return ["/bin/sh", "-c", 'exec "$0" "$@"', "/usr/bin/python3",
            pluginDir + "/bin/omarchy-android-dev", "--settings", store.settingsJson, "record"]
  }

  function startRecording() {
    if (recorder.running) return "already recording"
    recording = false
    recordingStopping = false
    recordingSeconds = 0
    recordingDevicePath = ""
    recorder.command = recorderCommand()
    recorder.running = true
    return "requested"
  }

  function stopRecording() {
    if (!recorder.running) return "not recording"
    recordingStopping = true
    recorder.signal(2)  // SIGINT: the helper ends adb, pulls the file and answers
    return "stopping"
  }

  function toggleRecording() { return recorder.running ? stopRecording() : startRecording() }

  function elapsedText(seconds) {
    var s = Math.max(0, Math.floor(Number(seconds) || 0))
    var r = s % 60
    return Math.floor(s / 60) + ":" + (r < 10 ? "0" : "") + r
  }

  function applyRecorderLine(line) {
    var text = String(line || "").trim()
    if (text === "" || text.length > 65536) return
    var ev
    try {
      ev = JSON.parse(text)
    } catch (e) {
      return
    }
    if (!ev || typeof ev !== "object") return
    if (ev.event === "recording") {
      recording = true
      recordingStartedAt = Date.now()
      recordingSeconds = 0
      recordingDevicePath = String(ev.device_path || "")
      return
    }
    // The final document (`recorded` or `error`): merged like any other,
    // so the notice and lastError are the panel's; the helper sent its
    // own notification for a saved file, a failure gets one here.
    recording = false
    var doc = store.handle(text)
    if (doc && doc.ok === false && store.notifyEnabled) {
      var dev = store.selectedDevice
      notify(store.lastError !== "" ? store.lastError : "The recording failed", dev ? dev.label : "")
    }
  }

  Process {
    id: recorder
    stdout: SplitParser {
      onRead: function(line) { root.applyRecorderLine(line) }
    }
    onRunningChanged: {
      if (running) return
      // The final line may still be on its way; decide after a moment.
      recorderExitFallback.restart()
    }
  }

  Timer {
    id: recorderExitFallback
    interval: 300
    repeat: false
    onTriggered: {
      if (root.recording) {
        // Ended without a final document: could not start, or was killed.
        root.recording = false
        root.store.showNotice("The recording ended without an answer", true)
      }
      root.recordingStopping = false
      root.recordingDevicePath = ""
    }
  }

  Timer {
    interval: 1000
    repeat: true
    running: root.recording
    onTriggered: root.recordingSeconds = Math.floor((Date.now() - root.recordingStartedAt) / 1000)
  }

  // ---- The pairer ----------------------------------------------------------
  // `pair qr` writes a pairing code as a PNG, streams one `pairing` event
  // naming it, then waits (two minutes at most) for the phone to scan it
  // from its Wireless debugging screen and pairs; the final document
  // (`paired`, or an `error`) goes through the store like any other. A
  // cancel (`pairer.signal(2)`, what Ctrl-C does) removes the PNG and
  // prints nothing, so "Pairing cancelled" is said here. One session per shell.
  property bool pairing: false
  property bool pairingStopping: false
  property string pairingQr: ""
  property string pairingName: ""
  property int pairingWindow: 120
  property double pairingStartedAt: 0
  property int pairingSeconds: 0
  readonly property bool pairerRunning: pairer.running

  function pairerCommand() {
    return ["/bin/sh", "-c", 'exec "$0" "$@"', "/usr/bin/python3",
            pluginDir + "/bin/omarchy-android-dev", "--settings", store.settingsJson, "pair", "qr"]
  }

  function startPairing() {
    if (pairer.running) return "already pairing"
    pairing = false
    pairingStopping = false
    pairingQr = ""
    pairingName = ""
    pairingSeconds = 0
    pairer.command = pairerCommand()
    pairer.running = true
    return "requested"
  }

  function stopPairing() {
    if (!pairer.running) return "not pairing"
    pairingStopping = true
    pairer.signal(2)  // SIGINT: the helper removes the PNG and exits quietly
    return "stopping"
  }

  function togglePairing() { return pairer.running ? stopPairing() : startPairing() }

  function applyPairerLine(line) {
    var text = String(line || "").trim()
    if (text === "" || text.length > 65536) return
    var ev
    try {
      ev = JSON.parse(text)
    } catch (e) {
      return
    }
    if (!ev || typeof ev !== "object") return
    if (ev.event === "pairing") {
      pairingQr = String(ev.qr_path || "")
      pairingName = String(ev.name || "")
      pairingWindow = Number(ev.seconds) > 0 ? Number(ev.seconds) : 120
      pairingStartedAt = Date.now()
      pairingSeconds = 0
      pairing = true
      return
    }
    // The final document (`paired` or `error`): merged like any other, so
    // the notice, the new device list and lastError are the panel's.
    pairing = false
    pairingQr = ""
    var doc = store.handle(text)
    if (!store.notifyEnabled) return
    if (doc && doc.ok !== false && doc.notice) notify(String(doc.notice), String(doc.address || ""))
    else if (store.lastError !== "") notify(store.lastError, "")
  }

  Process {
    id: pairer
    stdout: SplitParser {
      onRead: function(line) { root.applyPairerLine(line) }
    }
    onRunningChanged: {
      if (running) return
      pairerExitFallback.restart()
    }
  }

  Timer {
    id: pairerExitFallback
    interval: 300
    repeat: false
    onTriggered: {
      if (root.pairing) {
        // Ended without a final document: cancelled (nothing is printed
        // then, by design), could not start, or was killed.
        root.pairing = false
        root.store.showNotice(root.pairingStopping ? "Pairing cancelled" : "The pairing session ended without an answer", !root.pairingStopping)
      }
      root.pairingStopping = false
      root.pairingQr = ""
      root.pairingName = ""
    }
  }

  Timer {
    interval: 1000
    repeat: true
    running: root.pairing
    onTriggered: root.pairingSeconds = Math.floor((Date.now() - root.pairingStartedAt) / 1000)
  }

  // omarchy-notification-send as argv, fire and forget. Device labels are
  // one argument each, never a shell string.
  function notify(headline, body) {
    var bin = omarchyPath !== "" ? omarchyPath + "/bin/omarchy-notification-send" : "omarchy-notification-send"
    Quickshell.execDetached([bin, "--app-name", appName, "-g", glyph, String(headline), String(body || "")])
  }

  Process {
    id: tracker
    stdout: SplitParser {
      onRead: function(line) { root.applyTrackerLine(line) }
    }
    // A command that cannot start emits no `exited`; `running` dropping
    // back to false is the one signal every exit shares.
    onRunningChanged: {
      if (running || root.stopping) return
      if (root.trackerRestartPending) {
        root.trackerRestartPending = false
        Qt.callLater(root.startTracker)
        return
      }
      restartTimer.interval = root.trackerBackoffMs
      root.trackerBackoffMs = Math.min(root.trackerBackoffMs * 2, root.trackerBackoffMaxMs)
      restartTimer.restart()
    }
  }

  Timer {
    id: restartTimer
    repeat: false
    onTriggered: root.startTracker()
  }

  Connections {
    target: root.store
    function onSettingsJsonChanged() { root.restartTracker() }
  }

  // Deferred so the first bar widget can register (and lend its settings)
  // before the first helper run; the tracker and that run start together,
  // which is the case the helper's server lock exists for.
  Component.onCompleted: Qt.callLater(function() {
    root.store.refreshStatus()
    root.startTracker()
  })

  // Disabling the plugin destroys this item: the tracker (and through it
  // adb track-devices), the recorder and any helper still running go with
  // it. A recording in flight is asked to stop, but the shell kills the
  // process right after, so the mp4 stays on the device (documented).
  Component.onDestruction: {
    stopping = true
    stopTracker()
    if (recorder.running) recorder.signal(2)
    if (pairer.running) pairer.signal(2)
    if (store.proc.running) store.proc.signal(15)
  }

  // ---- Actions ---------------------------------------------------------------
  // One path for the panel and the IPC verbs: run the helper, then tell the
  // user how it went. The panel shows the store's notice on its own; the
  // notification is for the terminal and for the panel being closed. The
  // helper's own notification (screenshots) is not doubled.
  // `silent` skips the notification (the APK page's Install all sends one
  // summary instead of one per file). `stdinText` reaches the helper's
  // stdin (the pairing code).
  function act(args, onDone, silent, stdinText) {
    store.run(args, function(doc) {
      if (args[0] !== "screenshot" && store.notifyEnabled && silent !== true) {
        var dev = store.selectedDevice
        if (doc && doc.ok !== false && doc.notice) notify(String(doc.notice), dev ? dev.label : "")
        else if (store.lastError !== "") notify(store.lastError, dev ? dev.label : "")
      }
      if (typeof onDone === "function") onDone(doc)
    }, stdinText)
    return "requested"
  }

  readonly property var toggleNames: ["animations", "touches", "pointer", "layout", "airplane", "wifi", "data", "bluetooth", "demo"]

  // A package name as the IPC verbs accept it; the helper checks again.
  function validPackage(pkg) {
    var p = String(pkg || "").trim()
    return p !== "" && p.length <= 256 && /^[A-Za-z0-9_.]+$/.test(p) ? p : ""
  }

  function validSerial(serial) {
    var s = String(serial || "").trim()
    return s !== "" && s.length <= 128 && /^[A-Za-z0-9._:\-]+$/.test(s) ? s : ""
  }

  // `host` or `host:port` as `adb connect` takes it (IPv4 or a name; the
  // helper refuses IPv6 and says so).
  function validAddress(address) {
    var a = String(address || "").trim()
    return a !== "" && a.length <= 260 && /^[A-Za-z0-9][A-Za-z0-9.-]*(:\d{1,5})?$/.test(a) ? a : ""
  }

  // One line of printable ASCII, 500 characters at most: what `input text`
  // types. The helper checks again and says why when it refuses.
  function validText(text) {
    var t = String(text || "")
    return t !== "" && t.length <= 500 && /^[\x20-\x7e]+$/.test(t)
  }

  function validAvd(name) {
    var n = String(name || "").trim()
    return /^[A-Za-z0-9._-]{1,64}$/.test(n) ? n : ""
  }

  // ---- Panel routing ---------------------------------------------------------
  // The shell's summon/hide pick the widget on the focused monitor; with
  // no bar widget placed there is nothing to open.
  readonly property bool opened: {
    for (var i = 0; i < hosts.length; i++) if (hosts[i].opened === true) return true
    return false
  }

  function openPanel() {
    if (hosts.length === 0) return "no bar widget placed"
    if (shell && typeof shell.summon === "function") return shell.summon(pluginId, "") ? "opened" : "no bar widget placed"
    host.open()
    return "opened"
  }

  function closePanel() {
    if (hosts.length === 0) return "no bar widget placed"
    if (shell && typeof shell.hide === "function") { shell.hide(pluginId); return "closed" }
    host.close()
    return "closed"
  }

  function togglePanel() { return opened ? closePanel() : openPanel() }

  function showPage(name) {
    if (hosts.length === 0) return "no bar widget placed"
    var target = host
    for (var i = 0; i < hosts.length; i++) if (hosts[i].opened === true) { target = hosts[i]; break }
    if (typeof target.showPage !== "function") return "no panel"
    target.showPage(String(name))
    return "opened"
  }

  // The page the open panel shows (the first host's when none is open).
  readonly property string panelPage: {
    var target = null
    for (var i = 0; i < hosts.length; i++) if (hosts[i].opened === true) { target = hosts[i]; break }
    if (!target) target = host
    return target && target.page !== undefined ? String(target.page) : ""
  }

  function statusJson() {
    var s = store
    var dev = s.selectedDevice
    var settings = {}
    try { settings = JSON.parse(s.settingsJson) } catch (e) { settings = {} }
    return JSON.stringify({
      version: version,
      plugin_dir: pluginDir,
      adb: s.adbInfo,
      settings: settings,
      devices: s.devices.length,
      selected: s.selected,
      selected_label: dev ? dev.label : "",
      tracker: { running: tracking, error_code: trackerErrorCode, error: trackerError, backoff_ms: trackerBackoffMs },
      busy: s.busy,
      error_code: s.lastErrorCode,
      error: s.lastError,
      recording: { active: recording, stopping: recordingStopping, seconds: recordingSeconds, device_path: recordingDevicePath },
      pairing: { active: pairing, stopping: pairingStopping, seconds: pairingSeconds, window: pairingWindow, qr_path: pairingQr, name: pairingName },
      hosts: hosts.length,
      opened: opened,
      page: opened ? panelPage : ""
    })
  }

  readonly property var helpLines: [
    "omarchy-shell costafot.android-dev <verb> [args]",
    "  help                 this list",
    "  open | close | toggle  the panel (show/hide are aliases)",
    "  page NAME            open the panel on a page: hub devices packages deeplink toggles capture apks text tools wireless settings",
    "  status               one JSON line: adb, settings, devices, tracker, recording, pairing, the open page, errors",
    "  devices              one JSON line: the attached devices",
    "  select SERIAL        make SERIAL the selected device",
    "  launch PKG           start PKG's launcher activity on the selected device",
    "  forcestop PKG        am force-stop PKG",
    "  clear PKG            pm clear PKG",
    "  deeplink URL         am start -a VIEW -d URL",
    "  screenshot           screenshot of the selected device: file, clipboard, notification",
    "  record start|stop|toggle  screen recording of the selected device; stop pulls the mp4 to the videos folder",
    "  flip NAME            flip a developer toggle: animations touches pointer layout airplane wifi data bluetooth demo",
    "  text TEXT            type TEXT on the selected device (input text: one line of ASCII)",
    "  clipboard            type the clipboard (wl-paste) on the selected device",
    "  scrcpy               mirror the selected device with scrcpy",
    "  avd NAME             start that emulator (refused while it runs)",
    "  logcat [PKG]         adb logcat in a terminal, following PKG's process when given",
    "  pair start|stop|toggle  a pairing QR code in the panel; the phone scans it from Wireless debugging",
    "  disconnect ADDR      adb disconnect host[:port], or the mDNS name of a phone adb connected to on its own",
    "  tcpip SERIAL         go wireless: adb tcpip 5555 on that plugged phone, connect to its Wi-Fi address, select it (\"\" for the selected device)",
    "  usb SERIAL           back to USB (adb usb) for that entry; the Wi-Fi one drops (\"\" for the selected device)",
    "  refresh              re-read adb and the device list",
    "Action verbs return at once; the result arrives as a notification and in the panel.",
    "Settings: the panel's Settings page, or `omarchy bar set costafot.android-dev KEY VALUE` (adbPath screenshotDir",
    "recordingDir apkDir scrcpyArgs mirrorScreenOff notify deviceNotifications confirmUninstall showSystemApps); both apply at once."
  ]

  //   omarchy-shell costafot.android-dev help
  //   omarchy-shell costafot.android-dev toggle
  //   omarchy-shell costafot.android-dev status | jq
  //   omarchy-shell costafot.android-dev screenshot
  // Every verb returns within omarchy-shell's 2 s budget: the helper runs
  // afterwards, its notice becomes a notification (the helper sends its
  // own for captures) and the panel shows it.
  IpcHandler {
    target: "costafot.android-dev"
    function help(): string { return root.helpLines.join("\n") }
    function open(): string { return root.openPanel() }
    function show(): string { return root.openPanel() }
    function close(): string { return root.closePanel() }
    function hide(): string { return root.closePanel() }
    function toggle(): string { return root.togglePanel() }
    function page(name: string): string { return root.showPage(name) }
    function status(): string { return root.statusJson() }
    function devices(): string { return JSON.stringify({ devices: root.store.devices, selected: root.store.selected }) }
    function select(serial: string): string {
      var s = root.validSerial(serial)
      if (s === "") return "select needs a device serial"
      root.store.selectDevice(s)
      return "requested"
    }
    function launch(pkg: string): string {
      var p = root.validPackage(pkg)
      return p === "" ? "launch needs a package name" : root.act(["app", "launch", p])
    }
    function forcestop(pkg: string): string {
      var p = root.validPackage(pkg)
      return p === "" ? "forcestop needs a package name" : root.act(["app", "force-stop", p])
    }
    function clear(pkg: string): string {
      var p = root.validPackage(pkg)
      return p === "" ? "clear needs a package name" : root.act(["app", "clear", p])
    }
    function deeplink(url: string): string {
      var u = String(url || "").trim()
      if (u === "" || u.length > 2048 || /[\s\x00-\x1f\x7f]/.test(u)) return "deeplink needs a URL with a scheme, such as https://example.com"
      return root.act(["deeplink", u])
    }
    function screenshot(): string { root.store.screenshot(); return "requested" }
    // `toggle` is the panel verb (the kit's convention), so the developer
    // toggles flip with `flip`.
    function flip(name: string): string {
      var n = String(name || "").trim().toLowerCase()
      if (root.toggleNames.indexOf(n) === -1) return "flip takes one of: " + root.toggleNames.join(" ")
      return root.act(["toggle", n])
    }
    function record(mode: string): string {
      var m = String(mode || "").trim().toLowerCase()
      if (m === "start") return root.startRecording()
      if (m === "stop") return root.stopRecording()
      if (m === "" || m === "toggle") return root.toggleRecording()
      return "record takes start, stop or toggle"
    }
    function text(text: string): string {
      var t = String(text || "")
      if (!root.validText(t)) return "text needs one line of printable ASCII, 500 characters at most"
      return root.act(["text", "send", t])
    }
    function clipboard(): string { return root.act(["text", "clipboard"]) }
    function scrcpy(): string { return root.act(["tool", "scrcpy"]) }
    function avd(name: string): string {
      var n = root.validAvd(name)
      return n === "" ? "avd needs an AVD name" : root.act(["tool", "avd", n])
    }
    function logcat(pkg: string): string {
      var p = String(pkg || "").trim()
      if (p === "") return root.act(["tool", "logcat"])
      var v = root.validPackage(p)
      return v === "" ? "logcat takes a package name, or nothing for the whole log" : root.act(["tool", "logcat", v])
    }
    function pair(mode: string): string {
      var m = String(mode || "").trim().toLowerCase()
      if (m === "start") return root.startPairing()
      if (m === "stop") return root.stopPairing()
      if (m === "" || m === "toggle") return root.togglePairing()
      return "pair takes start, stop or toggle"
    }
    function disconnect(address: string): string {
      // An address, or the mDNS name adb gave an auto-connected phone (the serial alphabet; the helper checks the shape).
      var a = root.validAddress(address) || root.validSerial(address)
      return a === "" ? "disconnect needs an address as ip:port, or a Wi-Fi entry's serial" : root.act(["disconnect", a])
    }
    function tcpip(serial: string): string {
      var s = String(serial || "").trim()
      if (s === "") return root.act(["tcpip"])
      var v = root.validSerial(s)
      return v === "" ? "tcpip takes a USB serial, or nothing for the selected device" : root.act(["tcpip", v])
    }
    function usb(serial: string): string {
      var s = String(serial || "").trim()
      if (s === "") return root.act(["usb"])
      var v = root.validSerial(s)
      return v === "" ? "usb takes a serial, or nothing for the selected device" : root.act(["usb", v])
    }
    function refresh(): string { root.store.refreshStatus(); return "requested" }
  }
}
