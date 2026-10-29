import AppKit
import SwiftUI

/// Wires the status item to the panel. Knows nothing about `Views/` or
/// `State/`: the root view and the menus are injected by the composition root,
/// `Bootstrap.swift`, as in Menu-Bar-Chat.
///
/// Not generic, because `NSApplicationDelegate` is an `@objc` protocol and
/// members of a generic class cannot be `@objc`; the content is type-erased.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {

    // MARK: - Hooks for the composition root

    var onPanelOpen: (() -> Void)?
    /// Fires at the *start* of the close, `K.Motion.panelClose` before the window leaves the screen.
    var onPanelClose: (() -> Void)?
    /// A menu in place of the panel for a left click, or nil for the panel.
    var menuForClick: (() -> NSMenu?)?
    var contextMenu: (() -> NSMenu)?
    var onTerminate: (() -> Void)?

    // MARK: - State

    private let makeContent: () -> AnyView
    private var statusItemController: StatusItemController?

    private(set) lazy var panelController = PanelController<AnyView> { [makeContent] in
        makeContent()
    }

    init<Content: View>(@ViewBuilder content: @escaping () -> Content) {
        self.makeContent = { AnyView(content()) }
        super.init()
    }

    // MARK: - Lifecycle

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Alongside `LSUIElement`: no Dock tile, no app menu, never activated.
        NSApp.setActivationPolicy(.accessory)
        // A reply written to a run that has just died must fail, not kill the app.
        signal(SIGPIPE, SIG_IGN)
        installEditMenu()

        panelController.onOpen = { [weak self] in self?.onPanelOpen?() }
        panelController.onClose = { [weak self] in self?.onPanelClose?() }

        let status = StatusItemController()
        status.onToggle = { [weak self] button in
            self?.panelController.toggle(anchoredTo: button)
        }
        status.menuForClick = { [weak self] in self?.menuForClick?() }
        status.contextMenu = { [weak self] in self?.contextMenu?() ?? NSMenu() }
        status.onWillShowMenu = { [weak self] in
            self?.panelController.close()
        }
        statusItemController = status
    }

    func applicationWillTerminate(_ notification: Notification) {
        onTerminate?()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    // MARK: - Panel API for the composition root

    func openPanel() {
        guard let button = statusItemController?.button else { return }
        if !panelController.isOpen {
            panelController.open(anchoredTo: button)
        }
    }

    func closePanel() {
        panelController.close()
    }

    func updateContentHeight(_ height: CGFloat) {
        panelController.updateContentHeight(height)
    }

    func showRun(running: Bool, step: Int) {
        statusItemController?.showRun(running: running, step: step)
    }

    /// The menu bar is hidden (`LSUIElement`), but AppKit still routes Cmd-V and
    /// friends through `NSApp.mainMenu`. An SPM app has no MainMenu.xib, so
    /// without this those keys do nothing in the field.
    private func installEditMenu() {
        let mainMenu = NSMenu()

        let appItem = NSMenuItem()
        mainMenu.addItem(appItem)
        let appMenu = NSMenu()
        appItem.submenu = appMenu
        appMenu.addItem(withTitle: "Quit System One", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        let editItem = NSMenuItem()
        mainMenu.addItem(editItem)
        let editMenu = NSMenu(title: "Edit")
        editItem.submenu = editMenu
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")

        NSApp.mainMenu = mainMenu
    }
}
