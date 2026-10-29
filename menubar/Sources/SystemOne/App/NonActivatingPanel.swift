import AppKit

/// The window the panel lives in, verbatim from Menu-Bar-Chat but for comments.
///
/// Showing it must not take the user out of whatever app they were in: that
/// app is the one the run works in. That is achieved by three things and
/// nothing else:
///
/// 1. `.nonactivatingPanel` in the style mask — the panel can take keyboard
///    focus without the owning application being brought to the front.
/// 2. `canBecomeKey` overridden to `true`. A borderless window returns `false`
///    by default, which would leave the text field permanently unfocusable.
/// 3. `canBecomeMain` overridden to `false`, and `NSApp.activate` never called
///    anywhere in the app.
///
/// Verified empirically in Menu-Bar-Chat (its `_Log/03-window-and-build.md`): with this
/// configuration `NSWorkspace.shared.frontmostApplication` stays on the previous
/// app for the entire lifetime of the panel, while `panel.isKeyWindow` is true
/// and the SwiftUI field editor holds first responder.
final class NonActivatingPanel: NSPanel {

    /// Borderless windows refuse key status unless this is overridden.
    override var canBecomeKey: Bool { true }

    /// Never main. Becoming main is what greys the previous app permanently.
    override var canBecomeMain: Bool { false }

    init(contentRect: NSRect) {
        super.init(
            contentRect: contentRect,
            // `.borderless` has raw value 0, so this set is really just
            // `.nonactivatingPanel`; the absence of `.titled` is what makes the
            // window chromeless. Tested: this combination becomes key and draws
            // no title bar, so `.titled` + `.fullSizeContentView` is not needed.
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )

        level = .statusBar
        isOpaque = false
        backgroundColor = .clear
        // Off. Over a dark desktop the shadow renders as a black halo with a
        // visible rounded edge outside the panel, which reads as a second box.
        hasShadow = false
        isMovable = false
        isMovableByWindowBackground = false
        becomesKeyOnlyIfNeeded = false
        animationBehavior = .none

        // The panel is reused for the whole run of the app; `orderOut` must not
        // deallocate it.
        isReleasedWhenClosed = false
        isExcludedFromWindowsMenu = true
        titleVisibility = .hidden
        titlebarAppearsTransparent = true

        setFloating(false)
    }

    /// The panel must stay a non-hiding floating panel in both modes. This app
    /// is an accessory that never activates; `hidesOnDeactivate` or `.transient`
    /// therefore hide it the instant it is shown. Pinning only changes whether
    /// it follows Spaces.
    func setFloating(_ floating: Bool) {
        isFloatingPanel = true
        hidesOnDeactivate = false
        collectionBehavior = floating
            ? [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            : [.fullScreenAuxiliary]
    }
}
