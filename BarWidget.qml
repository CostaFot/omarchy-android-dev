pragma ComponentBehavior: Bound
import QtQuick
import qs.Ui

// Bar widget for Android Dev: the droid glyph, the device count when more
// than one is attached, dimmed with none; red while the selected device
// waits for authorisation or is offline, and with a dot while a screen
// recording runs. Click opens the hub (Panel.qml),
// middle click re-reads adb and the devices. The data lives in the service
// (one per shell); this widget registers with it as a host so the service
// can read its settings and open its panel.
BarWidget {
  id: root
  moduleName: "costafot.android-dev"

  readonly property var svc: bar && bar.shell ? bar.shell.serviceFor("costafot.android-dev") : null
  readonly property var store: svc ? svc.store : null
  // nf-fa-android, as an escape so no tool can strip it silently.
  readonly property string glyph: "\uf17b"

  // Untyped on purpose: naming the type would collide with qs.Ui's Panel base.
  readonly property var devPanel: panelLoader.item

  // ---- Panel shape contract for shell.summon/hide/toggle routing ---------
  readonly property bool opened: devPanel ? devPanel.opened === true : false
  function open() { if (devPanel) devPanel.open() }
  function close() { if (devPanel) devPanel.close() }
  function togglePanel() { if (devPanel) devPanel.toggle() }
  readonly property bool popoutSwitchClosing: devPanel ? devPanel.popoutSwitchClosing === true : false
  function closeForPopoutSwitch() { if (devPanel) devPanel.closeForPopoutSwitch() }
  function showPage(name) { if (devPanel) devPanel.showPage(name) }
  // The page the panel shows, for the service's `status`.
  readonly property string page: devPanel && devPanel.page !== undefined ? String(devPanel.page) : ""
  function refresh() { if (store) store.refreshStatus() }

  function injectPanel() {
    var target = devPanel
    if (!target) return
    target.bar = root.bar
    target.settings = root.settings
    target.anchorItem = button
    target.hostWidget = root
    target.service = root.svc
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  // ---- Registration with the service --------------------------------------
  property var registeredWith: null

  function register() {
    if (registeredWith === svc) return
    if (registeredWith) registeredWith.unregisterHost(root)
    registeredWith = svc
    if (svc) svc.registerHost(root)
  }

  onSvcChanged: {
    register()
    injectPanel()
  }
  Component.onCompleted: register()
  Component.onDestruction: {
    if (registeredWith) registeredWith.unregisterHost(root)
    registeredWith = null
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  // ---- What the glyph says -------------------------------------------------
  readonly property int deviceCount: store ? store.deviceCount : 0
  readonly property var device: store ? store.selectedDevice : null
  readonly property bool loaded: store ? store.loaded : false
  readonly property bool hasAdb: store ? store.hasAdb : false
  readonly property bool attention: device ? device.state !== "device" : false
  readonly property bool recording: svc ? svc.recording === true : false
  readonly property int recordingSeconds: svc ? svc.recordingSeconds : 0

  // A plain black circle (U+25CF, not a Nerd Font glyph) marks a recording.
  readonly property string labelText: glyph + (recording ? " \u25cf" : "") + (deviceCount > 1 ? " " + deviceCount : "")

  readonly property string tooltip: {
    if (!store) return ""
    if (!loaded) return "Android Dev"
    if (!hasAdb) return "Android Dev: adb not found"
    if (!device) return deviceCount > 0 ? deviceCount + " devices, none selected" : "No device"
    var t = device.label
    if (device.state !== "device") t += " (" + (device.state === "unauthorized" ? "needs authorising" : device.state) + ")"
    if (deviceCount > 1) t += ", " + deviceCount + " attached"
    if (recording) t += ", recording " + svc.elapsedText(recordingSeconds)
    return t
  }

  visible: svc !== null
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.labelText
    active: root.attention || root.recording
    dimmed: root.deviceCount === 0
    tooltipText: root.tooltip

    onPressed: function(b) {
      if (b === Qt.MiddleButton) root.refresh()
      else root.togglePanel()
    }
  }
}
