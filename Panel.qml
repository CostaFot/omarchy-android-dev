pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui

// Popup for the Android Dev bar widget: the hub is the selected device with
// the pages hanging off it. Pages live on a stack; Escape and Backspace
// walk back, Escape on the hub closes. The data is the service's Store
// (one per shell), reached through `service`; this panel never runs the
// helper for itself beyond asking the store to.
//
// Page renderers build one flat `rows` array and a Repeater paints it. The
// service owns the plugin's IPC target, so `manageIpc` is off here.
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

  function refresh() { if (store) store.refreshStatus() }

  // ---- Navigation ---------------------------------------------------------
  // Each entry: { page, ...args, cursor } where the cursor is saved on push
  // and restored on pop.
  property var stack: [{ page: "hub" }]
  property var pendingStack: null
  readonly property var current: stack[stack.length - 1]
  readonly property string page: current.page
  readonly property bool isHub: stack.length === 1

  readonly property var pageTitles: ({
    hub: "Android Dev", devices: "Devices", packages: "Apps", deeplink: "Deep link", toggles: "Toggles",
    capture: "Capture", apks: "APKs", text: "Send text", tools: "Tools", settings: "Settings"
  })

  function push(entry) {
    var top = Object.assign({}, current, { cursor: selectedIndex })
    stack = stack.slice(0, -1).concat([top, entry])
    enterPage(entry)
  }

  function pop() {
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
    var target = pageTitles[name] !== undefined ? name : "hub"
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
    Qt.callLater(function() {
      var wanted = entry.cursor
      selectedIndex = (wanted !== undefined && root.isCursorRow(root.rows[wanted])) ? wanted : root.firstCursorIndex()
      keyCatcher.forceActiveFocus()
      root.ensureCursorVisible()
    })
  }

  // ---- Rows ---------------------------------------------------------------
  // Row types: title header sep action note footer. Every string a row
  // shows is either a literal here or a field the helper already formatted.
  readonly property var rows: {
    var out = []
    if (!isHub) out.push({ type: "title", label: pageTitles[page] || page })
    var body = page === "hub" ? hubRows() : soonRows()
    for (var i = 0; i < body.length; i++) out.push(body[i])
    var s = root.store
    if (s && s.notice !== "") {
      out.push({ type: "sep" })
      out.push({ type: "note", label: s.notice, urgent: s.noticeUrgent })
    }
    out.push({ type: "footer", label: keyHint() })
    return out
  }

  // The pages to come, in the order they arrive.
  readonly property var comingRows: [
    { icon: "\uf00a", label: "Apps", detail: "Packages, their actions and deep links", page: "packages", version: "0.3.0" },
    { icon: "\uf0c1", label: "Deep link", detail: "Open a URL on the device", page: "deeplink", version: "0.3.0" },
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
      out.push({ type: "action", icon: glyph, label: dev.label, detail: detail, action: "refresh",
                 urgent: dev.state !== "device" })
    } else {
      out.push({ type: "action", icon: glyph, label: "No device",
                 detail: s.deviceCount > 1 ? s.deviceCount + " attached, none selected" : "Connect a device or start an emulator",
                 action: "refresh" })
    }
    if (s.hasAdb && svc && svc.trackerError !== "" && svc.trackerErrorCode !== "no_adb")
      out.push({ type: "note", urgent: true, label: "Device tracking stopped", detail: svc.trackerError })
    if (s.lastError !== "" && s.lastErrorCode !== "no_adb" && s.notice === "")
      out.push({ type: "note", urgent: true, label: s.lastError })
    out.push({ type: "sep" })
    for (var i = 0; i < comingRows.length; i++) {
      var c = comingRows[i]
      out.push({ type: "action", icon: c.icon, label: c.label, detail: c.version + " · " + c.detail, page: c.page, muted: true })
    }
    return out
  }

  function soonRows() {
    for (var i = 0; i < comingRows.length; i++)
      if (comingRows[i].page === page)
        return [{ type: "note", label: comingRows[i].detail, detail: "Coming in version " + comingRows[i].version + "." }]
    return [{ type: "note", label: "Coming in a later version." }]
  }

  function keyHint() {
    if (page === "hub") return "j/k move · Enter opens · r refreshes · Esc closes"
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

  function activate(row) {
    if (!row) return
    if (row.type === "action") {
      if (row.action === "refresh") refresh()
      else if (row.page) push({ page: row.page })
    } else if (row.type === "title") {
      pop()
    }
  }

  onOpenedChanged: {
    if (opened) {
      refresh()
      if (pendingStack) {
        stack = pendingStack
        pendingStack = null
        enterPage(stack[stack.length - 1])
      } else {
        goHome()
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight, Style.space(760))

    // Unhandled keys from the catcher (it never accepts Backspace) land here.
    Item {
      id: pageArea
      anchors.fill: parent

      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Backspace) {
          root.pop()
          event.accepted = true
        }
      }

      PanelKeyCatcher {
        id: keyCatcher
        anchors.fill: parent
        clip: true
        onMoveRequested: function(dx, dy) { if (dy !== 0) root.moveCursor(dy) }
        onActivateRequested: root.activate(root.rows[root.selectedIndex])
        onCloseRequested: root.pop()
        onTabRequested: function(direction) { root.switchPanel(direction) }
        onTextKey: function(t) {
          if (t === "r" || t === "R") root.refresh()
        }

        Flickable {
          id: listScroll
          anchors.fill: parent
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
                      text: rowItem.isTitle ? rowItem.modelData.label : ""
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
                        elide: Text.ElideRight
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
    }
  }
}
