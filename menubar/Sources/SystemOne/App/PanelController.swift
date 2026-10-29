import AppKit
import SwiftUI

/// Owns the one `NonActivatingPanel`, positions it under the status item,
/// resizes it as the SwiftUI content grows, and decides when it closes.
///
/// Menu-Bar-Chat's `PanelController` without its resize and move handles,
/// backdrop sampling, file drops and appearance settings. What it keeps is the
/// property this app depends on: showing the panel does not move the user out
/// of the app they were in, because `NSApp.activate` is never called. Do not add
/// it "just to be safe"; the run works in whichever app is in front.
@MainActor
final class PanelController<Content: View> {

    // MARK: - Contract surface

    private(set) var isOpen = false

    /// Fired synchronously once the panel is key and on screen.
    var onOpen: (() -> Void)?

    /// Fired synchronously at the *start* of `close()`, `K.Motion.panelClose`
    /// seconds before the window leaves the screen, so the content can animate out.
    var onClose: (() -> Void)?

    /// While true, neither an outside click nor a lost key status closes the
    /// panel; Escape and the menu bar icon still do. Set while the run waits on
    /// a question, so a stray click cannot decline it.
    var isPinned = false {
        didSet { panel?.setFloating(isPinned) }
    }

    // MARK: - Private state

    private let makeContent: () -> Content
    private var panel: NonActivatingPanel?
    private weak var anchorButton: NSStatusBarButton?

    private var globalMouseMonitor: Any?
    private var escapeMonitor: Any?
    private var resignKeyObserver: NSObjectProtocol?
    private var resignActiveObserver: NSObjectProtocol?

    private var pendingOrderOut: DispatchWorkItem?
    private var ignoreDismissUntil: Date?

    /// Height of the *visible* content, excluding `K.Panel.windowPadding`.
    private var contentHeight: CGFloat = K.InputBar.height

    private static var escapeKeyCode: UInt16 { 53 }

    init(content: @escaping () -> Content) {
        self.makeContent = content
    }

    // MARK: - Open / close

    func toggle(anchoredTo button: NSStatusBarButton) {
        if isOpen && panel?.isVisible == true {
            close()
        } else {
            open(anchoredTo: button)
        }
    }

    func open(anchoredTo button: NSStatusBarButton) {
        // A reopen during the exit animation reuses the same window.
        pendingOrderOut?.cancel()
        pendingOrderOut = nil

        anchorButton = button
        let panel = ensurePanel()
        applyFrame(to: panel, anchoredTo: button)

        isOpen = true
        ignoreDismissUntil = Date().addingTimeInterval(K.Panel.dismissGrace)

        // The only show call in the app. Never `NSApp.activate`.
        panel.makeKeyAndOrderFront(nil)
        installMonitors()
        onOpen?()
    }

    /// Starts the close: `onClose` fires now, so the content animates out, and
    /// the window orders out `K.Motion.panelClose` later unless reopened first.
    func close() {
        guard isOpen else { return }
        isOpen = false
        removeMonitors()
        onClose?()

        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.pendingOrderOut = nil
            guard !self.isOpen else { return }
            self.panel?.orderOut(nil)
        }
        pendingOrderOut = work
        DispatchQueue.main.asyncAfter(deadline: .now() + K.Motion.panelClose, execute: work)
    }

    // MARK: - Sizing

    /// Resizes the window keeping its **top** edge fixed, so the panel grows
    /// downward as the run box appears and fills.
    func updateContentHeight(_ height: CGFloat) {
        let clamped = max(height, K.InputBar.height)
        guard abs(clamped - contentHeight) > 0.5 else { return }
        contentHeight = clamped
        guard let panel else { return }
        let pad = K.Panel.windowPadding
        var frame = panel.frame
        let top = frame.maxY
        frame.size.height = contentHeight + pad * 2
        frame.origin.y = top - frame.size.height
        panel.setFrame(frame, display: true, animate: false)
    }

    // MARK: - Panel construction

    private func ensurePanel() -> NonActivatingPanel {
        if let panel { return panel }

        let pad = K.Panel.windowPadding
        let size = NSSize(width: K.Panel.width + pad * 2, height: contentHeight + pad * 2)
        let panel = NonActivatingPanel(contentRect: NSRect(origin: .zero, size: size))

        let hosting = NSHostingView(rootView: makeContent())
        hosting.autoresizingMask = [.width, .height]
        hosting.frame = NSRect(origin: .zero, size: size)
        panel.contentView = hosting
        panel.initialFirstResponder = hosting
        panel.setFloating(isPinned)
        self.panel = panel

        resignKeyObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.didResignKeyNotification,
            object: panel,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.handleResignKey() }
        }

        resignActiveObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didResignActiveNotification,
            object: NSApp,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.handleDismissal() }
        }

        return panel
    }

    // MARK: - Positioning

    private func applyFrame(to panel: NonActivatingPanel, anchoredTo button: NSStatusBarButton) {
        let pad = K.Panel.windowPadding
        let width = K.Panel.width
        let windowSize = NSSize(width: width + pad * 2, height: contentHeight + pad * 2)
        let buttonRect = screenRect(of: button)

        // macOS parks a status item it cannot fit in the menu bar far off to
        // the left, with `isVisible` still true. Centring on that would pin the
        // panel to the wrong end of the menu bar, so fall back to the right.
        let isAnchorOnScreen = NSScreen.screens.contains { $0.frame.intersects(buttonRect) }
        let screen = (isAnchorOnScreen ? NSScreen.screens.first { $0.frame.intersects(buttonRect) } : nil)
            ?? button.window?.screen
            ?? NSScreen.main

        guard let screen else {
            panel.setFrame(NSRect(origin: .zero, size: windowSize), display: false)
            return
        }

        // Bottom-left origin, and `visibleFrame` already excludes the menu bar.
        let contentTop = screen.visibleFrame.maxY - K.Panel.topInsetBelowMenuBar
        var contentLeft = isAnchorOnScreen
            ? buttonRect.midX - width / 2
            : screen.frame.maxX - K.Panel.screenEdgeClamp - width
        let minLeft = screen.frame.minX + K.Panel.screenEdgeClamp
        let maxLeft = screen.frame.maxX - K.Panel.screenEdgeClamp - width
        contentLeft = maxLeft >= minLeft ? min(max(contentLeft, minLeft), maxLeft) : minLeft

        let origin = NSPoint(x: contentLeft - pad, y: contentTop - contentHeight - pad)
        panel.setFrame(NSRect(origin: origin, size: windowSize), display: false)
    }

    private func screenRect(of button: NSStatusBarButton) -> NSRect {
        guard let window = button.window else { return .zero }
        return window.convertToScreen(button.convert(button.bounds, to: nil))
    }

    // MARK: - Monitors

    private func installMonitors() {
        removeMonitors()

        // Mouse up, and global: clicks in other apps. Global mouse monitors need
        // no Accessibility permission; global key monitors would, which is why
        // Escape is a local monitor.
        globalMouseMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseUp, .rightMouseUp]) { [weak self] _ in
            MainActor.assumeIsolated { self?.handleOutsideMouseUp() }
        }

        escapeMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            MainActor.assumeIsolated { () -> NSEvent? in
                guard let self, self.isOpen, event.keyCode == Self.escapeKeyCode else { return event }
                self.close()
                return nil  // swallowed, so no beep
            }
        }
    }

    private func removeMonitors() {
        if let globalMouseMonitor { NSEvent.removeMonitor(globalMouseMonitor) }
        if let escapeMonitor { NSEvent.removeMonitor(escapeMonitor) }
        globalMouseMonitor = nil
        escapeMonitor = nil
    }

    private func handleOutsideMouseUp() {
        guard isOpen, !isPinned else { return }
        if let ignoreDismissUntil, Date() < ignoreDismissUntil { return }
        let location = NSEvent.mouseLocation
        if let panel, panel.frame.insetBy(dx: K.Panel.windowPadding, dy: K.Panel.windowPadding).contains(location) { return }
        // A release on our own status item is the toggle, not an outside click.
        if let anchorButton, screenRect(of: anchorButton).contains(location) { return }
        close()
    }

    private func handleResignKey() {
        // Defer one turn: at notification time the new key window is not set yet.
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            // Another window of ours took key, such as a menu: not the user leaving.
            if NSApp.windows.contains(where: { $0.isKeyWindow && $0 !== self.panel }) { return }
            self.handleDismissal()
        }
    }

    private func handleDismissal() {
        guard isOpen, !isPinned else { return }
        if let ignoreDismissUntil, Date() < ignoreDismissUntil { return }
        close()
    }
}
