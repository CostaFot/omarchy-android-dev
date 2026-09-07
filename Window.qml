pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

// The Android Dev pages as their own window: a FloatingWindow, a Wayland
// toplevel that Hyprland tiles or floats like any app, resizable, with a
// title a window rule can match, and ordinary keyboard focus. The shell's
// panel loader creates it once (`keepLoaded`) and hands it `shell`,
// `manifest` and the plugin's `service`; `shell summon costafot.android-dev
// '{"page":"toggles"}'` (or the plugin's `window` verb) calls `open` with
// the payload, `shell hide` calls `close`, and a window the user closes
// (Escape on the hub, the close button) tells the shell so its open-panel
// map stays right (the dev gallery's pattern). It does not replace the bar
// popup, which stays the one-key panel; the bar widget stays the
// tracker's host and the settings' home.
Item {
  id: root

  // Injected by the shell's panel loader.
  property var shell: null
  property var manifest: null
  property string omarchyPath: ""
  property var service: null

  readonly property string pluginId: "costafot.android-dev"
  readonly property bool opened: window.visible
  // The window's own idea of its size, for `status` (a rule or a drag
  // resizes it; the content follows the surface).
  readonly property var windowSize: ({ width: window.width, height: window.height, content_width: pages.width, content_height: pages.height })
  // The page on screen, for the service's `status`.
  readonly property string page: pages.page
  property bool closingFromHost: false

  // The loader injects the service it finds at load; a service created
  // later (the plugin enabled at runtime) is looked up again on open.
  function resolveService() {
    if (!service && shell && typeof shell.serviceFor === "function") service = shell.serviceFor(pluginId)
  }

  // The payload may name a page: {"page": "packages"}. Unknown names open
  // the hub. Open already: the page moves and the keys come back here.
  function open(payloadJson) {
    resolveService()
    var page = ""
    if (payloadJson) {
      try {
        var parsed = JSON.parse(String(payloadJson))
        if (parsed && typeof parsed.page === "string") page = parsed.page
      } catch (e) { /* no page */ }
    }
    closingFromHost = false
    if (page !== "") pages.showPage(page)
    window.visible = true
    Qt.callLater(function() { if (window.visible) pages.focusForPage() })
  }

  // Host-initiated (`shell hide`): the shell already knows.
  function close() {
    closingFromHost = true
    window.visible = false
    closingFromHost = false
  }

  function showPage(name) { pages.showPage(String(name)) }

  // User-initiated (Escape on the hub, the window's close button): through
  // the shell, so `toggle` works on the next call.
  function requestClose() {
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
    else window.visible = false
  }

  // ---- Registration with the service ---------------------------------------
  property var registeredWith: null

  function register() {
    if (registeredWith === service) return
    if (registeredWith && typeof registeredWith.unregisterWindow === "function") registeredWith.unregisterWindow(root)
    registeredWith = service
    if (service && typeof service.registerWindow === "function") service.registerWindow(root)
  }

  onServiceChanged: register()
  onShellChanged: resolveService()
  Component.onDestruction: {
    if (registeredWith && typeof registeredWith.unregisterWindow === "function") registeredWith.unregisterWindow(root)
    registeredWith = null
  }

  FloatingWindow {
    id: window
    title: "Android Dev"
    color: Color.background
    implicitWidth: Style.space(420)
    implicitHeight: Style.space(760)
    minimumSize: Qt.size(Style.space(320), Style.space(420))
    visible: false

    onVisibleChanged: {
      if (!visible && !root.closingFromHost) root.requestClose()
    }

    Pages {
      id: pages
      anchors.fill: parent
      anchors.margins: Style.spacing.popupPadding
      service: root.service
      shell: root.shell
      hostWidget: root.service ? root.service.host : null
      opened: window.visible
      onCloseRequested: root.requestClose()
      onOpenRequested: window.visible = true
    }
  }
}
