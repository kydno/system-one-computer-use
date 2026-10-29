import AppKit

/// The menu bar item, from Menu-Bar-Chat. A left click toggles the panel, or,
/// while a run has the screen, shows its progress and a Stop; a right click (or
/// control-click) shows the app's menu.
@MainActor
final class StatusItemController: NSObject {

    /// Left click, when `menuForClick` has no menu to show instead. Handed the
    /// button so the panel can anchor itself under it.
    var onToggle: ((NSStatusBarButton) -> Void)?

    /// Asked on every left click: a menu to show in place of the panel. While a
    /// run has the screen the panel must stay off it, so the click shows this.
    var menuForClick: (() -> NSMenu?)?

    /// The right-click menu, built fresh each time so it shows current state.
    var contextMenu: (() -> NSMenu)?

    /// Fired just before either menu appears, so the panel can get out of the way.
    var onWillShowMenu: (() -> Void)?

    private let statusItem: NSStatusItem

    var button: NSStatusBarButton? { statusItem.button }

    override init() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        // Set before the button is configured so the saved position applies on this launch.
        statusItem.autosaveName = K.StatusItem.autosaveName
        super.init()

        guard let button = statusItem.button else { return }
        button.image = Self.symbol(K.StatusItem.idleSymbol)
        button.imagePosition = .imageLeading
        button.toolTip = K.StatusItem.accessibilityName
        button.target = self
        button.action = #selector(buttonClicked(_:))
        // Both buttons must reach `buttonClicked`, or right-click does nothing.
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])
    }

    /// The icon while a run has the screen, with the step it is on beside it.
    func showRun(running: Bool, step: Int) {
        guard let button else { return }
        button.image = Self.symbol(running ? K.StatusItem.runningSymbol : K.StatusItem.idleSymbol)
        button.title = running && step > 0 ? " \(step)" : ""
    }

    // MARK: - Click routing

    @objc private func buttonClicked(_ sender: NSStatusBarButton) {
        let event = NSApp.currentEvent
        let isRightClick = event?.type == .rightMouseUp || event?.modifierFlags.contains(.control) == true

        if isRightClick, let menu = contextMenu?() {
            show(menu, from: sender)
        } else if let menu = menuForClick?() {
            show(menu, from: sender)
        } else {
            onToggle?(sender)
        }
    }

    private func show(_ menu: NSMenu, from button: NSStatusBarButton) {
        onWillShowMenu?()
        // `popUp(positioning:at:in:)` rather than assigning `statusItem.menu`,
        // because an assigned menu makes AppKit swallow the left click too.
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height + 4), in: button)
    }

    // MARK: - Icon

    /// A template image, so macOS tints it for the menu bar's appearance.
    private static func symbol(_ name: String) -> NSImage? {
        guard let symbol = NSImage(systemSymbolName: name, accessibilityDescription: K.StatusItem.accessibilityName) else {
            return nil
        }
        let configured = symbol.withSymbolConfiguration(
            NSImage.SymbolConfiguration(pointSize: K.StatusItem.symbolSize, weight: .regular)
        ) ?? symbol
        configured.isTemplate = true
        return configured
    }
}

/// A menu item that runs a closure, so the composition root can build menus
/// out of the model without a target object per item.
final class ClosureMenuItem: NSMenuItem {

    private let handler: () -> Void

    init(_ title: String, state: NSControl.StateValue = .off, handler: @escaping () -> Void) {
        self.handler = handler
        super.init(title: title, action: #selector(fire), keyEquivalent: "")
        self.target = self
        self.state = state
    }

    required init(coder: NSCoder) {
        fatalError("not used from a nib")
    }

    @objc private func fire() { handler() }
}
