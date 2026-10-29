import AppKit
import SwiftUI

/// The first box, from Menu-Bar-Chat's input bar: the goal, or the reply to a
/// question, and the switch between a dry run and driving the Mac.
struct InputBarView: View {

    @ObservedObject var model: RunModel
    @FocusState.Binding var isFieldFocused: Bool

    @State private var editingMonitor: Any?

    var body: some View {
        HStack(spacing: K.InputBar.elementGap) {
            HoverButton(
                systemName: model.drives ? "cursorarrow.click.2" : "eye",
                help: model.drives
                    ? "Drives the Mac: clicks and types. Click for a dry run instead."
                    : "Dry run: says what it would do, and does nothing. Click to let it drive the Mac.",
                isOn: model.drives,
                isEnabled: !model.isAsking
            ) {
                model.drives.toggle()
            }

            TextField(model.placeholder, text: $model.inputText)
                .textFieldStyle(.plain)
                .font(.system(size: K.InputBar.fontSize))
                .foregroundStyle(.primary)
                .focused($isFieldFocused)
                .onSubmit { model.submit() }
                .accessibilityLabel(model.placeholder)

            HoverButton(
                systemName: model.isAsking ? "arrowshape.turn.up.left" : "arrow.up",
                help: model.isAsking ? "Reply" : (model.drives ? "Start" : "Dry run"),
                isEnabled: model.canSubmit
            ) {
                model.submit()
            }
        }
        .padding(.horizontal, K.InputBar.horizontalPadding)
        .frame(width: K.Panel.width, height: K.InputBar.height)
        .onAppear(perform: installEditingMonitor)
        .onDisappear(perform: removeEditingMonitor)
    }

    /// Cut, copy, paste and select all, sent up the responder chain to the field
    /// editor. An SPM accessory app has no menu of its own to carry them;
    /// Menu-Bar-Chat ships this beside the Edit menu `AppDelegate` installs, and
    /// plain paste never worked there before the two.
    private func installEditingMonitor() {
        guard editingMonitor == nil else { return }
        editingMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask).subtracting(.capsLock)
            guard flags == .command, let key = event.charactersIgnoringModifiers?.lowercased() else { return event }
            let actions: [String: Selector] = [
                "x": #selector(NSText.cut(_:)),
                "c": #selector(NSText.copy(_:)),
                "v": #selector(NSText.paste(_:)),
                "a": #selector(NSText.selectAll(_:)),
            ]
            guard let action = actions[key] else { return event }
            return NSApp.sendAction(action, to: nil, from: nil) ? nil : event
        }
    }

    private func removeEditingMonitor() {
        if let editingMonitor { NSEvent.removeMonitor(editingMonitor) }
        editingMonitor = nil
    }
}
