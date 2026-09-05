pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui

// Popup for the Android Dev bar widget: the hub is the selected device with
// the pages hanging off it. Pages live on a stack; Escape and Backspace
// walk back, Escape on the hub closes. The data is the service's Store
// (one per shell), reached through `service`; this panel never runs the
// helper for itself beyond asking the store (or the service, for actions
// that also notify) to.
//
// Page renderers build one flat `rows` array and a Repeater paints it.
// The filter / URL field and the uninstall dialog live outside the
// Repeater: rows are rebuilt on every document. The service owns the
// plugin's IPC target, so `manageIpc` is off here.
Panel {
  id: root
  moduleName: "costafot.android-dev"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
  readonly property var store: service ? service.store : null
  // The bar tracks the widget mounted in its slot (BarWidget.qml), so the
  // popout coordinator and panel switching must identify us by that widget.
  readonly property var barIdentity: hostWidget || root

  readonly property color contentForeground: bar ? bar.foreground : Color.foreground
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color mutedForeground: Qt.darker(contentForeground, 1.4)
  readonly property color urgentForeground: bar ? bar.urgent : Color.urgent
  // nf-fa-android, as an escape so no tool can strip it silently.
  readonly property string glyph: "\uf17b"
  readonly property var kindGlyphs: ({ emulator: "\uf108", usb: "\uf10b", wifi: "\uf1eb" })

  function refresh() {
    if (!store) return
    if (page === "packages") store.refreshPackages()
    else if (page === "actions") store.fetchPackage(current.pkg)
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
  readonly property bool hasField: page === "packages" || page === "deeplink"

  readonly property var pageTitles: ({
    hub: "Android Dev", devices: "Devices", packages: "Apps", actions: "", deeplink: "Deep link", toggles: "Toggles",
    capture: "Capture", apks: "APKs", text: "Send text", tools: "Tools", settings: "Settings"
  })
  // Pages the IPC `page` verb may open straight onto.
  readonly property var ipcPages: ["hub", "devices", "packages", "deeplink"]

  function push(entry) {
    var top = Object.assign({}, current, { cursor: selectedIndex, query: filterField.text })
    stack = stack.slice(0, -1).concat([top, entry])
    enterPage(entry)
  }

  function pop() {
    if (confirmOpen) { cancelConfirm(); return }
    if (stack.length <= 1) { root.close(); return }
    var entry = stack[stack.length - 2]
    stack = stack.slice(0, -1)
    enterPage(entry)
  }

  function goHome() {
    stack = [{ page: "hub" }]
    enterPage(stack[0])
  }

  // IPC `page NAME`: open straight onto a page, with the hub under it.
  function showPage(name) {
    var target = ipcPages.indexOf(name) !== -1 ? name : "hub"
    var next = target === "hub" ? [{ page: "hub" }] : [{ page: "hub" }, { page: target }]
    if (opened) {
      stack = next
      enterPage(next[next.length - 1])
    } else {
      pendingStack = next
      root.open()
    }
  }

  function enterPage(entry) {
    listScroll.contentY = 0
    filterField.text = entry.query || ""
    cancelConfirm()
    if (store) {
      if (entry.page === "packages") store.refreshPackages()
      else if (entry.page === "actions" && entry.pkg) store.fetchPackage(entry.pkg)
    }
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
  // Row types: title header sep action note footer. Every string a row
  // shows is either a literal here or a field the helper already formatted;
  // the one exception is the uninstall question, a literal around a name.
  readonly property var rows: {
    var out = []
    if (!isHub) out.push({ type: "title", label: page === "actions" ? (current.pkg || "") : (pageTitles[page] || page) })
    var body
    if (page === "hub") body = hubRows()
    else if (page === "devices") body = deviceRows()
    else if (page === "packages") body = packageRows()
    else if (page === "actions") body = actionRows()
    else if (page === "deeplink") body = deeplinkRows()
    else body = soonRows()
    for (var i = 0; i < body.length; i++) out.push(body[i])
    var s = root.store
    if (s && s.notice !== "") {
      out.push({ type: "sep" })
      out.push({ type: "note", label: s.notice, urgent: s.noticeUrgent })
    }
    out.push({ type: "footer", label: keyHint() })
    return out
  }

  // The hub's page rows, in the order they arrive. `version` marks a page
  // that is not here yet.
  readonly property var pageRows: [
    { icon: "\uf00a", label: "Apps", detail: "Packages, their actions and deep links", page: "packages" },
    { icon: "\uf0c1", label: "Deep link", detail: "Open a URL on the device", page: "deeplink" },
    { icon: "\uf1de", label: "Toggles", detail: "Animations, touches, layout bounds, airplane, Wi-Fi, data, Bluetooth", page: "toggles", version: "0.4.0" },
    { icon: "\uf030", label: "Capture", detail: "Screenshot and screen recording", page: "capture", version: "0.4.0" },
    { icon: "\uf1b2", label: "APKs", detail: "Install from a folder", page: "apks", version: "0.5.0" },
    { icon: "\uf11c", label: "Send text", detail: "Type text or the clipboard on the device", page: "text", version: "0.5.0" },
    { icon: "\uf0ad", label: "Tools", detail: "scrcpy, emulators, logcat", page: "tools", version: "0.5.0" },
    { icon: "\uf013", label: "Settings", detail: "adb path, folders, notifications", page: "settings", version: "0.6.0" }
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
      out.push({ type: "note", urgent: true, icon: "\uf071", label: "adb not found",
                 detail: "Set the adb path in the plugin settings, or install the android-tools package or the SDK platform-tools." })
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
    if (s.hasAdb && svc && svc.trackerError !== "" && svc.trackerErrorCode !== "no_adb")
      out.push({ type: "note", urgent: true, label: "Device tracking stopped", detail: svc.trackerError })
    if (s.lastError !== "" && s.lastErrorCode !== "no_adb" && s.notice === "")
      out.push({ type: "note", urgent: true, label: s.lastError })
    out.push({ type: "sep" })
    for (var i = 0; i < pageRows.length; i++) {
      var c = pageRows[i]
      if (c.version) out.push({ type: "action", icon: c.icon, label: c.label, detail: c.version + " · " + c.detail, page: c.page, muted: true })
      else out.push({ type: "action", icon: c.icon, label: c.label, detail: c.detail, page: c.page })
    }
    return out
  }

  // The picker: one row per attached device, the selected one marked.
  function deviceRows() {
    var s = root.store
    var out = []
    if (!s.hasAdb) {
      out.push({ type: "note", urgent: true, label: "adb not found", detail: "Set the adb path in the plugin settings." })
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
      out.push({ type: "note", urgent: true, label: "adb not found", detail: "Set the adb path in the plugin settings." })
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
                      detail: "Turn on Show system apps in the plugin settings to list every package." })
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
                 detail: info.launcher_activity || "No launcher activity" })
    } else if (s.busy && s.runningCommand === "package") {
      out.push({ type: "note", label: "Reading the package…" })
    }
    if (!deviceGate(out)) return out
    for (var i = 0; i < appActions.length; i++) {
      var a = appActions[i]
      out.push({ type: "action", icon: a.icon, label: a.label, detail: a.detail, action: "app", act: a.act, pkg: pkg })
    }
    return out
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

  function soonRows() {
    for (var i = 0; i < pageRows.length; i++)
      if (pageRows[i].page === page)
        return [{ type: "note", label: pageRows[i].detail, detail: "Coming in version " + pageRows[i].version + "." }]
    return [{ type: "note", label: "Coming in a later version." }]
  }

  function keyHint() {
    if (page === "hub") return "j/k move · Enter opens · r refreshes · Esc closes"
    if (page === "devices") return "j/k move · Enter selects · r refreshes · Esc back"
    if (page === "packages") return "Type to filter · ↑/↓ move · Enter opens · r lists again · Esc back"
    if (page === "actions") return "j/k move · Enter runs it · Esc back"
    if (page === "deeplink") return "Type a URL, Enter launches · ↑/↓ recent · Esc back"
    return "Esc or Backspace back"
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
  function act(args, onDone) {
    if (service && typeof service.act === "function") service.act(args, onDone)
    else if (store) store.run(args, onDone)
  }

  function activate(row) {
    if (!row || confirmOpen) return
    if (row.type === "title") { pop(); return }
    if (row.type !== "action") return
    if (row.action === "refresh") refresh()
    else if (row.action === "select") { if (store) store.selectDevice(row.serial); pop() }
    else if (row.action === "package") push({ page: "actions", pkg: row.pkg })
    else if (row.action === "deeplink") act(["deeplink", row.url].concat(row.pkg ? [row.pkg] : []))
    else if (row.action === "app") runAppAction(row)
    else if (row.page) push({ page: row.page })
  }

  function runAppAction(row) {
    var pkg = row.pkg
    if (row.act === "deeplink") { push({ page: "deeplink", pkg: pkg }); return }
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

  // ---- The uninstall dialog -----------------------------------------------
  property bool confirmOpen: false
  property string confirmPkg: ""

  function openConfirm(row) {
    confirmPkg = row.pkg
    confirmDialog.selectedIndex = 0
    confirmOpen = true
  }

  function cancelConfirm() {
    confirmOpen = false
    confirmPkg = ""
  }

  function acceptConfirm() {
    var pkg = confirmPkg
    cancelConfirm()
    if (pkg !== "") uninstall(pkg)
  }

  onOpenedChanged: {
    if (opened) {
      if (store) store.refreshStatus()
      if (pendingStack) {
        stack = pendingStack
        pendingStack = null
        enterPage(stack[stack.length - 1])
      } else {
        goHome()
      }
    } else {
      cancelConfirm()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: root.hasField ? filterField : keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(
      contentColumn.implicitHeight + (root.hasField ? filterField.height + Style.space(6) : 0), Style.space(760))

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
        if (event.key === Qt.Key_Backspace && !filterField.activeFocus) {
          root.pop()
          event.accepted = true
        }
      }

      PanelKeyCatcher {
        id: keyCatcher
        anchors.fill: parent
        clip: true
        blocked: filterField.activeFocus || root.confirmOpen
        onMoveRequested: function(dx, dy) { if (dy !== 0) root.moveCursor(dy) }
        onActivateRequested: root.activate(root.rows[root.selectedIndex])
        onCloseRequested: root.pop()
        onTabRequested: function(direction) { root.switchPanel(direction) }
        onTextKey: function(t) {
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
          placeholderText: root.page === "deeplink" ? "URL or deep link, then Enter" : "Filter packages"

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
                    text: (rowItem.modelData.icon ? rowItem.modelData.icon + "  " : "") + (rowItem.modelData.label || "")
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
                        text: rowItem.modelData.detail || ""
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

      // Uninstall asks first (the `confirmUninstall` setting). Keys reach
      // it through pageArea while the catcher is blocked.
      ConfirmDialog {
        id: confirmDialog
        anchors.fill: parent
        z: 10
        opened: root.confirmOpen
        message: "Uninstall " + root.confirmPkg + "? This will remove the app and all its data from the device."
        confirmText: "Uninstall"
        foreground: root.contentForeground
        fontFamily: root.contentFontFamily
        onCanceled: root.cancelConfirm()
        onConfirmed: root.acceptConfirm()
      }
    }
  }
}
