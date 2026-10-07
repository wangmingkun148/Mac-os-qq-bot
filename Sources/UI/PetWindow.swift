import SwiftUI
import AppKit
import Combine

/// The floating desktop pet: a borderless, transparent, always-on-top window that can be dragged anywhere.
final class PetController: NSObject {
    private var panel: NSPanel?
    private let app: AppModel
    let pet: PetModel
    private var subscriptions = Set<AnyCancellable>()
    private var drag: (mouse: NSPoint, origin: NSPoint)?
    private var shownScale = 0

    init(model: AppModel) {
        app = model
        pet = PetModel(app: model)
        super.init()
        pet.move = { [weak self] dx in self?.nudge(dx) ?? false }
        pet.room = { [weak self] in self?.room() ?? (left: 0, right: 0) }
        model.$pet.receive(on: DispatchQueue.main).sink { [weak self] settings in self?.apply(settings) }.store(in: &subscriptions)
    }

    private func apply(_ settings: PetSettings) {
        pet.settings = settings
        guard settings.enabled else { panel?.orderOut(nil); pet.stop(); return }
        if panel == nil { build() }
        if shownScale != settings.scale { resize(to: settings.scale) }
        panel?.orderFrontRegardless()
        pet.start()
    }

    // MARK: Window

    private func windowSize(_ scale: Int) -> NSSize {
        NSSize(width: max(CGFloat(PetArt.width * scale), 250), height: CGFloat(PetArt.height * scale) + 120)
    }

    private func build() {
        let size = windowSize(app.pet.scale)
        let panel = NSPanel(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless, .nonactivatingPanel],
                            backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        let menu: [(String, () -> Void)] = [
            ("打开实时状态小窗", { [weak self] in self?.app.control?.showLive() }),
            ("设置…", { [weak self] in self?.app.control?.showSettings() }),
            ("暂停 / 继续自动回复", { [weak self] in self?.app.control?.togglePaused() }),
            ("隐藏桌宠", { [weak self] in self?.app.control?.setPetEnabled(false) }),
        ]
        panel.contentView = NSHostingView(rootView: PetView(pet: pet, onDrag: { [weak self] began in if !began { self?.endDrag() } },
                                                            onDragMove: { [weak self] in self?.dragMoved() }, menu: menu))
        self.panel = panel
        shownScale = app.pet.scale
        panel.setFrameOrigin(restoredOrigin(size))
    }

    private func resize(to scale: Int) {
        guard let panel else { return }
        let old = panel.frame, size = windowSize(scale)
        panel.setFrame(NSRect(x: old.minX + (old.width - size.width) / 2, y: old.minY, width: size.width, height: size.height), display: true)
        shownScale = scale
    }

    private func restoredOrigin(_ size: NSSize) -> NSPoint {
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        if let saved = UserDefaults.standard.string(forKey: "QQBridgePetOrigin")?.split(separator: ",").compactMap({ Double($0) }), saved.count == 2 {
            let point = NSPoint(x: saved[0], y: saved[1])
            if NSScreen.screens.contains(where: { $0.visibleFrame.insetBy(dx: -size.width / 2, dy: -20).contains(point) }) { return point }
        }
        return NSPoint(x: screen.maxX - size.width - 30, y: screen.minY + 6)
    }

    // MARK: Dragging and walking

    private func dragMoved() {
        guard let panel else { return }
        let mouse = NSEvent.mouseLocation
        if drag == nil { drag = (mouse, panel.frame.origin); pet.userMoved() }
        guard let drag else { return }
        panel.setFrameOrigin(NSPoint(x: drag.origin.x + mouse.x - drag.mouse.x, y: drag.origin.y + mouse.y - drag.mouse.y))
    }
    private func endDrag() {
        drag = nil
        if let origin = panel?.frame.origin { UserDefaults.standard.set("\(origin.x),\(origin.y)", forKey: "QQBridgePetOrigin") }
        pet.userMoved()
    }

    /// (distance to the left screen edge, to the right edge) measured from the sprite itself, not the wider window.
    private func room() -> (left: CGFloat, right: CGFloat) {
        guard let panel, let screen = panel.screen ?? NSScreen.main else { return (0, 0) }
        let width = CGFloat(PetArt.width * app.pet.scale)
        let left = panel.frame.minX + (panel.frame.width - width) / 2
        return (left - screen.visibleFrame.minX, screen.visibleFrame.maxX - (left + width))
    }

    private func nudge(_ dx: CGFloat) -> Bool {
        guard let panel, drag == nil else { return false }
        let room = room()
        if dx < 0 && room.left < -dx || dx > 0 && room.right < dx { return false }
        panel.setFrameOrigin(NSPoint(x: panel.frame.minX + dx, y: panel.frame.minY))
        return true
    }
}
