import SwiftUI
import AppKit

private let sidebarNSColor = NSColor(name: nil) { appearance in
    NSColor(hex: appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? 0x1F1E1D : 0xF0EEE6)
}

// MARK: - Menu bar popover

final class PopoverController: NSObject {
    private let popover = NSPopover()

    init(model: AppModel) {
        super.init()
        let host = NSHostingController(rootView: PopoverView(model: model))
        host.sizingOptions = [.preferredContentSize]
        popover.contentViewController = host
        popover.behavior = .transient
        popover.animates = true
    }

    func toggle(from button: NSStatusBarButton) {
        if popover.isShown { popover.performClose(nil); return }
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
    }
    func close() { popover.performClose(nil) }
}

// MARK: - Live status panel

final class LivePanelController: NSObject, NSWindowDelegate {
    private var panel: NSPanel?
    private let model: AppModel
    init(model: AppModel) { self.model = model; super.init() }

    var isVisible: Bool { panel?.isVisible ?? false }

    func show(activate: Bool) {
        if panel == nil { build() }
        panel?.level = model.pinned ? .floating : .normal
        if activate { NSApp.activate(ignoringOtherApps: true); panel?.makeKeyAndOrderFront(nil) } else { panel?.orderFrontRegardless() }
    }
    func toggle() { isVisible ? panel?.orderOut(nil) : show(activate: true) }
    func setPinned(_ pinned: Bool) { panel?.level = pinned ? .floating : .normal }

    private func build() {
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 372, height: 560),
                            styleMask: [.titled, .closable, .resizable, .utilityWindow, .nonactivatingPanel],
                            backing: .buffered, defer: false)
        panel.title = "QQ 实时状态"
        panel.titlebarAppearsTransparent = true
        panel.backgroundColor = sidebarNSColor
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.contentView = NSHostingView(rootView: LiveView(model: model))
        panel.minSize = NSSize(width: 320, height: 300)
        panel.delegate = self
        if !panel.setFrameUsingName("QQBridgeLivePanel"), let screen = NSScreen.main {
            let area = screen.visibleFrame
            panel.setFrameTopLeftPoint(NSPoint(x: area.maxX - panel.frame.width - 16, y: area.maxY - 16))
        }
        panel.setFrameAutosaveName("QQBridgeLivePanel")
        self.panel = panel
    }
}

// MARK: - Settings

final class SettingsWindowController: NSObject, NSWindowDelegate {
    private var window: NSWindow?
    private let model: AppModel
    private let draft = ConfigDraft()
    init(model: AppModel) { self.model = model; super.init() }

    func show() {
        if window == nil { build() }
        if !draft.dirty { draft.load(model.control?.config ?? [:]) }
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }

    private func build() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 860, height: 640),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                              backing: .buffered, defer: false)
        window.title = "QQ 自动回复 · 设置"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: SettingsView(model: model, draft: draft))
        window.minSize = NSSize(width: 780, height: 560)
        window.setFrameAutosaveName("QQBridgeSettings")
        if !window.setFrameUsingName("QQBridgeSettings") { window.center() }
        window.delegate = self
        self.window = window
    }
}
