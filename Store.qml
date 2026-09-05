pragma ComponentBehavior: Bound
import QtQuick
import Quickshell.Io

// The data side of the plugin: runs bin/omarchy-android-dev, one process at
// a time, and holds what the last documents said (adb, devices, the
// selected serial, packages, toggles, the APK folder, the tools, the
// wireless page, the status page). Nothing here draws
// and nothing here runs adb: the helper does every adb call with a serial,
// a deadline and a byte cap, and formats every string. This object parses
// one JSON line per run and keeps it.
//
// Owned by Service.qml (one per shell, not per monitor); the bar widget
// and the panel read it through the service. The recorder's final
// document also lands in handle(), from the service.
QtObject {
  id: store

  // Injected by the service: the plugin's directory and the bar widget's
  // inline shell.json entry (the service has no settings of its own).
  property var settings: ({})
  property string pluginDir: ""

  // ---- Settings -----------------------------------------------------------
  function setting(key, fallback) {
    var v = settings ? settings[key] : undefined
    return v === undefined || v === null ? fallback : v
  }

  // The scalars the helper understands (cli.SETTING_DEFAULTS). Keys it does
  // not know are ignored on its side, so this list can lead the helper.
  readonly property var helperSettingKeys: ["adbPath", "screenshotDir", "recordingDir", "apkDir", "scrcpyArgs",
                                            "mirrorScreenOff", "notify", "deviceNotifications", "confirmUninstall", "showSystemApps"]

  // Serialised once so a re-injection of identical settings (every remount
  // does one) changes nothing downstream.
  readonly property string settingsJson: {
    var out = {}
    for (var i = 0; i < helperSettingKeys.length; i++) {
      var k = helperSettingKeys[i]
      var v = settings ? settings[k] : undefined
      if (v !== undefined && v !== null) out[k] = v
    }
    return JSON.stringify(out)
  }

  // A boolean setting. `omarchy bar set ID KEY false` without --json
  // stores the string "false", so the words count as well as the JSON
  // booleans; anything unreadable is the fallback.
  function flag(key, fallback) {
    var v = setting(key, fallback)
    if (v === true || v === false) return v
    var t = String(v).trim().toLowerCase()
    if (t === "true" || t === "1" || t === "yes" || t === "on") return true
    if (t === "false" || t === "0" || t === "no" || t === "off" || t === "") return false
    return fallback
  }

  readonly property bool notifyEnabled: flag("notify", true)
  readonly property bool deviceNotifications: flag("deviceNotifications", true)

  // ---- What the helper said ----------------------------------------------
  // Each section is replaced by the newest document that carries it and
  // never blanked by a failure: an error sets `lastError`, the lists stay.
  // The envelope's `adb`: path and source, plus the helper's display line
  // (`~/Android/Sdk/platform-tools/adb · found in ~/Android/Sdk`) for the
  // hub's Settings row.
  property var adbInfo: ({ path: null, source: null, text: null })
  property var status: null
  property var devices: []
  property string selected: ""
  property var packages: []
  property var packagesInfo: null
  // name → the last `package PKG` document (version, launcher activity,
  // runtime permissions), filled when the actions page for it opens.
  property var packageDetails: ({})
  // Per selected device, the package last acted on; and the deep links
  // fired from this machine, newest first (10 kept by the helper).
  property string lastPackage: ""
  property var recentDeeplinks: []
  property var toggles: null
  // The last `apk list` document (dir, exists, apks[]) and the last `tools`
  // one (what is installed, the AVDs with Running or Stopped).
  property var apkList: null
  property var toolsInfo: null
  // The last `wireless` document (mDNS yes or no, the services on the
  // network, the Wi-Fi and plugged devices).
  property var wirelessInfo: null
  property string lastError: ""
  property string lastErrorCode: ""
  // True once any document has landed (the first `status` after load).
  property bool loaded: false

  readonly property bool hasAdb: adbInfo && adbInfo.path ? true : false
  readonly property string adbPath: adbInfo && adbInfo.path ? String(adbInfo.path) : ""
  readonly property string adbSource: adbInfo && adbInfo.source ? String(adbInfo.source) : ""
  readonly property string adbText: adbInfo && adbInfo.text ? String(adbInfo.text) : ""
  readonly property int deviceCount: devices.length
  readonly property var selectedDevice: {
    for (var i = 0; i < devices.length; i++) if (devices[i].serial === selected) return devices[i]
    return null
  }
  readonly property var tools: status && status.tools ? status.tools : ({})
  function toolFound(name) {
    var t = tools[name]
    return t && t.found === true
  }

  // The one-line human result of the last action (the helper's `notice`),
  // shown by the panel for a few seconds.
  property string notice: ""
  property bool noticeUrgent: false

  function showNotice(text, urgent) {
    notice = String(text || "")
    noticeUrgent = urgent === true
    if (notice !== "") noticeTimer.restart()
  }

  property Timer noticeTimer: Timer {
    interval: 3000
    repeat: false
    onTriggered: store.notice = ""
  }

  // ---- Commands -----------------------------------------------------------
  function refreshStatus() { run(["status"], null) }
  function refreshDevices() { run(["devices"], null) }
  function selectDevice(serial) { run(["select", String(serial)], null) }
  function screenshot() { run(["screenshot"], null) }
  function refreshPackages() { run(["packages"], null) }
  function fetchPackage(pkg) { run(["package", String(pkg)], null) }
  function refreshToggles() { run(["toggles"], null) }
  function listApks(dir) { run(dir ? ["apk", "list", String(dir)] : ["apk", "list"], null) }
  function refreshTools() { run(["tools"], null) }
  function refreshWireless() { run(["wireless"], null) }

  // The toggles were read from one device; another selection makes them
  // stale until the page reads again.
  onSelectedChanged: toggles = null

  // The command of the run in flight ("" between runs), so a page can say
  // "Listing packages…" for its own run and not for someone else's.
  readonly property string runningCommand: currentRun && currentRun.args ? String(currentRun.args[0]) : ""

  // A frame from the service's tracker (`track`): the device list and the
  // selection it resolved, replacing ours. Not a helper run, so no queue.
  function applyTrackerEvent(ev) {
    if (!ev || !Array.isArray(ev.devices)) return
    devices = ev.devices
    selected = ev.selected ? String(ev.selected) : ""
    loaded = true
  }

  // ---- Running the helper -------------------------------------------------
  // One process at a time; requests made while one runs wait in
  // `pendingRuns`, in order. A read (`isRead`: status, devices, packages, a
  // package, toggles, an APK listing, tools, wireless) replaces any read
  // already waiting, since the later one answers for both; an action
  // (anything that changes the device, or carries stdin: the pairing code)
  // is never dropped. Before 1.3.2 one request waited and the last one won,
  // so a `pair code` queued behind the page's own read was replaced by an
  // `r` pressed meanwhile, without a word. Past `maxPending` waiting
  // requests the newcomer is refused with a notice; a run that hits its
  // budget drops the queue behind it (the helper is stuck, every waiting
  // request would be too). Both the exit code and the collected stdout have
  // to arrive before a run is finalised, in either order, hence the two
  // flags. `runGen` numbers the runs: every timer
  // carries the generation it was armed for and does nothing when a later
  // run has started, so a stale timer can never kill or finalise the wrong
  // run.
  property bool collectorDone: true
  property bool processDone: true
  readonly property bool busy: !collectorDone || !processDone
  property string capturedText: ""
  property int exitCode: 0
  property bool sawExit: false
  property bool tripwireFired: false
  property bool timedOut: false
  property var pendingRuns: []
  readonly property int maxPending: 8
  readonly property var readCommands: ["status", "devices", "packages", "package", "toggles", "tools", "wireless"]
  property var currentRun: null
  property int runGen: 0

  // The helper's whole-process budget in seconds
  // (OMARCHY_ANDROID_DEV_TOTAL_BUDGET): its own alarm answers a `timeout`
  // document at this point, and this store sends SIGTERM `killGraceMs`
  // later, then SIGKILL, for a helper stuck where Python's signal handler
  // cannot run (a blocking C call). Until then every later request queues
  // behind the stuck one, and goes with it when the budget is hit.
  readonly property int helperBudgetSeconds: 60
  readonly property int killGraceMs: 10000

  // What the next run gets on its stdin (a pairing code: never on argv,
  // where `ps` would show it), written once the process has started and
  // blanked right after.
  property string pendingStdin: ""

  // Runs one helper command. `onDone(doc)` gets the parsed document (or null
  // when the output was unusable) after its sections have been merged.
  // `stdinText` goes to the helper's stdin (`pair code` reads the six
  // digits there).
  function run(args, onDone, stdinText) {
    var job = { args: args, onDone: onDone, stdin: typeof stdinText === "string" ? stdinText : "", read: isRead(args) }
    if (busy) { enqueue(job); return }
    runGen += 1
    var gen = runGen
    job.gen = gen
    currentRun = job
    collectorDone = false
    processDone = false
    capturedText = ""
    sawExit = false
    tripwireFired = false
    timedOut = false
    exitCode = 0
    // Through sh, never direct: handing Quickshell a binary that cannot
    // start can take the whole shell down before a QML signal fires. sh
    // always starts; a failed exec is sh exiting 126/127. The interpreter is
    // the absolute system one, never `python3` off PATH.
    proc.command = ["/bin/sh", "-c", 'exec "$0" "$@"', "/usr/bin/python3",
                    pluginDir + "/bin/omarchy-android-dev", "--settings", settingsJson].concat(args)
    // The helper arms its own alarm from this; keep the two in step.
    proc.environment = { OMARCHY_ANDROID_DEV_TOTAL_BUDGET: String(helperBudgetSeconds) }
    pendingStdin = job.stdin
    proc.stdinEnabled = pendingStdin !== ""
    proc.running = true
    exitFallback.gen = gen
    killTimer.gen = gen
    killFallback.gen = gen
    killTimer.restart()
  }

  // A read answers a page; the latest one waiting is enough.
  function isRead(args) {
    var head = args && args.length ? String(args[0]) : ""
    if (head === "apk") return args.length > 1 && String(args[1]) === "list"
    return readCommands.indexOf(head) >= 0
  }

  function enqueue(job) {
    var waiting = job.read ? pendingRuns.filter(function(j) { return !j.read }) : pendingRuns.slice()
    if (waiting.length >= maxPending) {
      showNotice("Busy: " + waiting.length + " requests are waiting; try again in a moment", true)
      return
    }
    waiting.push(job)
    pendingRuns = waiting
  }

  function runNext() {
    if (busy || pendingRuns.length === 0) return
    var next = pendingRuns[0]
    pendingRuns = pendingRuns.slice(1)
    run(next.args, next.onDone, next.stdin)
  }

  function maybeFinalize() {
    if (!collectorDone || !processDone) return
    exitFallback.stop()
    killTimer.stop()
    killFallback.stop()
    finalizeRun()
  }

  // The budget is up and the helper has not answered for itself: SIGTERM,
  // and SIGKILL if it is still there after `killFallback`. The exit lands
  // through the usual signals and finalizeRun reports the timeout.
  function killHelper(sig) {
    if (!proc.running) return
    timedOut = true
    proc.signal(sig)
  }

  function fail(code, message) {
    lastErrorCode = String(code || "internal")
    lastError = String(message || "")
  }

  function finalizeRun() {
    var job = currentRun
    currentRun = null
    pendingStdin = ""
    var text = capturedText.trim()
    var doc = null
    if (timedOut) {
      var dropped = pendingRuns.length
      pendingRuns = []
      fail("timeout", "The Android Dev helper did not answer within " + (helperBudgetSeconds + killGraceMs / 1000) + " s and was stopped"
           + (dropped > 0 ? "; " + dropped + " waiting request" + (dropped === 1 ? "" : "s") + " dropped" : ""))
    } else if (text === "") {
      if (tripwireFired) {
        // Already explained.
      } else if (!sawExit || exitCode === 126 || exitCode === 127) {
        fail("internal", "/usr/bin/python3 could not start (exit " + exitCode + ")")
      } else {
        fail("internal", "The Android Dev helper produced no output (exit " + exitCode + ")")
      }
    } else {
      doc = handle(text)
    }
    if (job && typeof job.onDone === "function") job.onDone(doc)
    if (pendingRuns.length > 0) Qt.callLater(function() { store.runNext() })
  }

  // Merges one document. "Has data" and "has error" are independent: a
  // `state_corrupt` note rides with a good answer, and a `status` with no
  // adb still names the tools it found.
  function handle(text) {
    var d
    try {
      d = JSON.parse(text)
    } catch (e) {
      fail("internal", "The Android Dev helper returned unparseable output" + (exitCode !== 0 ? " (exit " + exitCode + ")" : ""))
      return null
    }
    if (!d || d.schema_version !== 1) {
      fail("internal", "The Android Dev helper returned an unexpected document (not schema_version 1)")
      return null
    }
    if (d.adb && typeof d.adb === "object") adbInfo = { path: d.adb.path || null, source: d.adb.source || null, text: d.adb.text || null }
    if (d.command === "status") status = d
    if (Array.isArray(d.devices)) {
      devices = d.devices
      selected = d.selected ? String(d.selected) : ""
    } else if (d.selected !== undefined && d.selected !== null) {
      selected = String(d.selected)
    }
    if (Array.isArray(d.packages)) {
      packages = d.packages
      packagesInfo = { foreground: d.foreground || "", count: d.count || 0,
                       system_apps: d.system_apps === true, last_package: d.last_package || "" }
    }
    if (d.toggles && typeof d.toggles === "object") toggles = d.toggles
    if (d.command === "apk" && Array.isArray(d.apks)) apkList = d
    if (d.command === "tools" && Array.isArray(d.avds)) toolsInfo = d
    if (d.command === "wireless" && d.mdns && typeof d.mdns === "object") wirelessInfo = d
    if (Array.isArray(d.recent_deeplinks)) recentDeeplinks = d.recent_deeplinks
    if (d.last_package !== undefined) lastPackage = d.last_package ? String(d.last_package) : ""
    if (d.command === "package" && d.ok !== false && d.name) {
      var details = Object.assign({}, packageDetails)
      details[String(d.name)] = d
      packageDetails = details
    }
    if (d.command === "app" && d.action === "uninstall" && d.ok !== false && d.package) {
      // Gone from the device; drop it here too until the next list.
      packages = packages.filter(function(p) { return p.name !== d.package })
      if (lastPackage === d.package) lastPackage = ""
    }
    loaded = true
    if (d.error && d.error.message) {
      fail(String(d.error.code || "internal"), String(d.error.message))
    } else {
      lastError = ""
      lastErrorCode = ""
    }
    if (d.notice) showNotice(String(d.notice), d.ok === false)
    else if (d.error && d.error.message && d.ok === false) showNotice(String(d.error.message), true)
    return d
  }

  property Process proc: Process {
    // The pairing code goes over stdin, never argv (the kit's network
    // panel does the same with a Wi-Fi secret); stdin is closed right
    // after so the helper sees the end of it.
    onStarted: {
      if (store.pendingStdin !== "") {
        write(store.pendingStdin)
        store.pendingStdin = ""
        stdinEnabled = false
      }
    }
    // A command that cannot start emits neither `started` nor `exited`;
    // `running` dropping back to false is the only signal.
    onRunningChanged: {
      if (running) return
      store.processDone = true
      exitFallback.restart()
      store.maybeFinalize()
    }
    onExited: function(code) {
      store.sawExit = true
      store.exitCode = code
      store.processDone = true
      exitFallback.restart()
      store.maybeFinalize()
    }
    stdout: StdioCollector {
      waitForEnd: true
      // A tripwire in UTF-16 units, not a byte cap (the helper enforces the
      // real caps on what it reads and lists). It refuses to retain an
      // answer that could not have come from a healthy run.
      readonly property int maxChars: 1024 * 1024
      onStreamFinished: {
        if (text.length > maxChars) {
          store.tripwireFired = true
          store.capturedText = ""
          store.fail("too_much_output", "The Android Dev helper returned more than " + (maxChars / 1024) + "K characters; refusing it")
        } else {
          store.capturedText = text
        }
        store.collectorDone = true
        store.maybeFinalize()
      }
    }
  }

  // The collector's end can land after the exit (or never, for a run that
  // could not start); this closes the run either way.
  property Timer exitFallback: Timer {
    id: exitFallback
    property int gen: 0
    interval: 300
    repeat: false
    onTriggered: {
      if (gen !== store.runGen) return
      store.collectorDone = true
      store.maybeFinalize()
    }
  }

  property Timer killTimer: Timer {
    id: killTimer
    property int gen: 0
    interval: store.helperBudgetSeconds * 1000 + store.killGraceMs
    repeat: false
    onTriggered: {
      if (gen !== store.runGen) return
      store.killHelper(15)  // SIGTERM
      killFallback.restart()
    }
  }

  property Timer killFallback: Timer {
    id: killFallback
    property int gen: 0
    interval: 5000
    repeat: false
    onTriggered: {
      if (gen !== store.runGen) return
      store.killHelper(9)  // SIGKILL
    }
  }
}
