pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Ui

// The keys beside the mirror: a strip of the phone's hardware keys drawn
// along the scrcpy window's right edge while one is up, following it as
// it moves (scrcpy has the keys as Mod shortcuts and shows nothing on
// screen). One layer-shell window on the top layer, owned by the service
// like the shell's OSD card, keyboard focus off so a click never takes
// the keys away from the mirror. The mirror is the Hyprland toplevel
// with the title `tool scrcpy` gives it and scrcpy's app id (the plugin's
// own window shares the title, hence the id); its position and size come
// from Hyprland's client object, which Quickshell refreshes on request:
// Hyprland sends no event for a floating window being dragged, so the
// strip polls the refresh while a mirror exists, fast while the mirror
// is the active window (a drag needs it focused) and slowly otherwise
// (a tile moved by another window opening). Every key is one helper run
// (`key NAME`, silent: the mirror shows the result); Screenshot and Record
// are the plugin's own.
Item {
  id: root

  // The service (Service.qml): the store, the recorder, `pressKey`.
  property var service: null
  // The `mirrorKeys` setting; off, no strip and no polling.
  property bool keysEnabled: true

  readonly property string mirrorTitle: "Android Dev"
  readonly property string mirrorAppId: "scrcpy"

  // The scrcpy toplevel (a HyprlandToplevel) and the fields of its last
  // client object the strip needs, copied so an unchanged refresh moves
  // nothing.
  property var mirror: null
  property var ipc: ({})

  readonly property var keyRows: [
    { key: "back", glyph: "\uf060", label: "Back" },
    { key: "home", glyph: "\uf015", label: "Home" },
    { key: "recents", glyph: "\uf24d", label: "Recents" },
    { key: "sep" },
    { key: "volup", glyph: "\uf028", label: "Volume up" },
    { key: "voldown", glyph: "\uf027", label: "Volume down" },
    { key: "power", glyph: "\uf011", label: "Power" },
    { key: "sep" },
    { key: "screenshot", glyph: "\uf030", label: "Screenshot" },
    { key: "record", glyph: "\uf03d", label: "Record" }
  ]

  function isMirror(t) {
    if (!t || String(t.title || "") !== mirrorTitle) return false
    var wl = t.wayland
    if (wl && String(wl.appId || "") !== "") return String(wl.appId) === mirrorAppId
    var o = t.lastIpcObject
    return !!o && String(o["class"] || "") === mirrorAppId
  }

  // The mirror among the toplevels: the active one when several are up
  // (two devices mirrored), else the first.
  function rescan() {
    var found = null
    if (keysEnabled) {
      var list = Hyprland.toplevels.values
      for (var i = 0; i < list.length; i++) {
        var t = list[i]
        if (!isMirror(t)) continue
        if (found === null || t.activated === true) found = t
      }
    }
    if (found !== mirror) {
      mirror = found
      // A window just mapped has no client object yet; ask for one.
      if (found) Hyprland.refreshToplevels()
    }
    takeIpc()
  }

  function takeIpc() {
    var o = mirror ? mirror.lastIpcObject : null
    var next = {}
    // `at` and `size` arrive as list wrappers, not JS arrays: read by index.
    var at = o ? o.at : null, size = o ? o.size : null
    if (at && size && at.length === 2 && size.length === 2 && isFinite(Number(at[0])) && isFinite(Number(size[0]))) {
      next = { at: [Number(at[0]), Number(at[1])], size: [Number(size[0]), Number(size[1])],
               fullscreen: Number(o.fullscreen) || 0, hidden: o.hidden === true, mapped: o.mapped !== false,
               workspace: o.workspace && o.workspace.id !== undefined ? Number(o.workspace.id) : -1 }
    }
    if (JSON.stringify(next) !== JSON.stringify(ipc)) ipc = next
  }

  onKeysEnabledChanged: rescan()
  Component.onCompleted: rescan()

  Connections {
    target: Hyprland.toplevels
    function onValuesChanged() { root.rescan() }
  }

  Connections {
    target: Hyprland
    function onActiveToplevelChanged() { root.rescan() }
    // A title set after the map, a workspace or monitor change, a window
    // floated or tiled: the list is the same and the mirror may not be.
    function onRawEvent(ev) {
      var name = String(ev.name)
      if (name === "windowtitlev2" || name === "movewindowv2" || name === "changefloatingmode" || name === "fullscreen"
          || name === "workspace" || name === "focusedmon" || name === "openwindow" || name === "closewindow") root.rescan()
    }
  }

  Connections {
    target: root.mirror
    function onLastIpcObjectChanged() { root.takeIpc() }
    function onTitleChanged() { root.rescan() }
    function onWaylandHandleChanged() { root.rescan() }
  }

  // Hyprland says nothing when a window is dragged or resized: ask.
  Timer {
    running: root.keysEnabled && root.mirror !== null
    interval: root.mirror && root.mirror.activated === true ? 100 : 700
    repeat: true
    onTriggered: Hyprland.refreshToplevels()
  }

  readonly property var monitor: mirror ? mirror.monitor : null
  readonly property var screen: {
    if (!monitor) return null
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++) if (screens[i].name === monitor.name) return screens[i]
    return null
  }

  // The monitor in layout (logical) pixels: Hyprland's `at` and `size`
  // are in that space; the monitor's width and height are physical.
  readonly property int monitorX: monitor ? monitor.x : 0
  readonly property int monitorY: monitor ? monitor.y : 0
  readonly property int monitorWidth: {
    if (!monitor) return 0
    var o = monitor.lastIpcObject || {}
    var rotated = (Number(o.transform) || 0) % 2 === 1
    var w = Number(o.width) || monitor.width, h = Number(o.height) || monitor.height
    return Math.round((rotated ? h : w) / (monitor.scale || 1))
  }
  readonly property int monitorHeight: {
    if (!monitor) return 0
    var o = monitor.lastIpcObject || {}
    var rotated = (Number(o.transform) || 0) % 2 === 1
    var w = Number(o.width) || monitor.width, h = Number(o.height) || monitor.height
    return Math.round((rotated ? w : h) / (monitor.scale || 1))
  }

  // Shown while the mirror is on screen: mapped, not hidden, on its
  // monitor's active workspace, and neither maximised nor fullscreen
  // (no edge to sit beside then).
  readonly property bool shown: {
    if (!keysEnabled || !mirror || !ipc.at || !screen) return false
    if (!ipc.mapped || ipc.hidden || ipc.fullscreen > 0) return false
    var ws = mirror.workspace
    if (ws && ws.active === false) return false
    return true
  }

  readonly property int keySize: Style.space(30)
  readonly property int keyGap: Style.space(3)
  readonly property int sepHeight: Style.space(9)
  readonly property int pad: Style.space(5)
  readonly property int edgeGap: Style.space(6)
  readonly property int contentHeight: {
    var h = 0
    for (var i = 0; i < keyRows.length; i++) h += (keyRows[i].key === "sep" ? sepHeight : keySize) + (i > 0 ? keyGap : 0)
    return h
  }
  readonly property int stripWidth: card.borderLeft + pad + keySize + pad + card.borderRight
  readonly property int stripHeight: card.borderTop + pad + contentHeight + pad + card.borderBottom

  // Along the right edge, top-aligned; the left edge when the right one
  // runs off the monitor; never past the monitor's bottom.
  readonly property int stripX: {
    if (!ipc.at) return 0
    var x = ipc.at[0] + ipc.size[0] + edgeGap
    if (x + stripWidth > monitorX + monitorWidth) x = ipc.at[0] - edgeGap - stripWidth
    return Math.max(monitorX, x)
  }
  readonly property int stripY: {
    if (!ipc.at) return 0
    var y = ipc.at[1]
    if (y + stripHeight > monitorY + monitorHeight) y = monitorY + monitorHeight - stripHeight
    return Math.max(monitorY, y)
  }

  function press(key) {
    if (!service) return
    if (key === "screenshot") { service.store.screenshot(); return }
    if (key === "record") { service.toggleRecording(); return }
    service.pressKey(key)
  }

  function statusObject() {
    return {
      present: mirror !== null,
      shown: shown,
      at: ipc.at ? ipc.at : null,
      size: ipc.size ? ipc.size : null,
      monitor: monitor ? monitor.name : null,
      strip: shown ? { x: stripX, y: stripY, width: stripWidth, height: stripHeight } : null
    }
  }

  PanelWindow {
    id: panel
    visible: root.shown
    screen: root.screen
    anchors { top: true; left: true }
    margins { left: root.stripX - root.monitorX; top: root.stripY - root.monitorY }
    implicitWidth: root.stripWidth
    implicitHeight: root.stripHeight
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    WlrLayershell.namespace: "android-dev-keys"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    BorderSurface {
      id: card
      anchors.fill: parent
      color: Util.alpha(Color.popups.background, 0.97)
      borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(2)))
      radius: Style.cornerRadius

      Column {
        x: card.borderLeft + root.pad
        y: card.borderTop + root.pad
        spacing: root.keyGap

        Repeater {
          model: root.keyRows
          delegate: Item {
            id: row
            required property var modelData
            readonly property bool isSep: modelData.key === "sep"
            readonly property bool recordKey: modelData.key === "record"
            readonly property bool lit: recordKey && root.service && root.service.recording === true
            width: root.keySize
            height: isSep ? root.sepHeight : root.keySize

            Rectangle {
              visible: row.isSep
              anchors.centerIn: parent
              width: parent.width - Style.space(6)
              height: Math.max(1, Style.space(1))
              color: Util.alpha(Color.popups.text, 0.25)
            }

            Rectangle {
              visible: !row.isSep
              anchors.fill: parent
              radius: Style.space(6)
              color: area.pressed ? Util.alpha(Color.accent, 0.35) : area.containsMouse ? Util.alpha(Color.popups.text, 0.14) : "transparent"
            }

            Text {
              visible: !row.isSep
              anchors.centerIn: parent
              textFormat: Text.PlainText
              text: row.isSep ? "" : String(row.modelData.glyph)
              font.family: Style.font.family
              font.pixelSize: Style.font.title
              color: row.lit ? Color.urgent : Color.popups.text
            }

            MouseArea {
              id: area
              visible: !row.isSep
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.press(String(row.modelData.key))
            }
          }
        }
      }
    }
  }
}
