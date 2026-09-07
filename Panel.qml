pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui

// The bar popup for Android Dev: the kit's Panel and KeyboardPanel around
// the pages (Pages.qml), anchored under the droid glyph, sized to the
// page under a cap. The service owns the plugin's IPC target, so
// `manageIpc` is off here. The bar tracks the widget mounted in its slot
// (BarWidget.qml), so the popout coordinator and panel switching identify
// us by that widget (`barIdentity`). The window (Window.qml) shows the
// same pages as a toplevel.
Panel {
  id: root
  moduleName: "costafot.android-dev"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
  readonly property var barIdentity: hostWidget || root
  // The page on screen, for the service's `status`.
  readonly property string page: pages.page

  function showPage(name) { pages.showPage(name) }
  function refresh() { pages.refresh() }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: pages.focusTarget
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(pages.desiredHeight, Style.space(760))

    Pages {
      id: pages
      anchors.fill: parent
      service: root.service
      shell: root.bar ? root.bar.shell : null
      hostWidget: root.hostWidget
      opened: root.opened
      takesServicePage: true
      inPopup: true
      contentForeground: root.bar ? root.bar.foreground : Color.foreground
      contentFontFamily: root.bar ? root.bar.fontFamily : Style.font.family
      urgentForeground: root.bar ? root.bar.urgent : Color.urgent
      onCloseRequested: root.close()
      onOpenRequested: root.open()
      onSwitchRequested: function(direction) { root.switchPanel(direction) }
    }
  }
}
