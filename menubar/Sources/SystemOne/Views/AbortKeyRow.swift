import AppKit
import SwiftUI

/// The settings row for the abort key. Click the field, hold a combination,
/// and it becomes the abort key once every key is let go.
struct AbortKeyRow: View {

    /// False once the panel starts closing; recording stops with it, or the
    /// field would keep swallowing keys the next time the panel opens.
    var isLive = true

    @State private var key = AbortKey.current
    @State private var isRecording = false
    @State private var held: NSEvent.ModifierFlags = []
    @State private var pending: AbortKey?
    @State private var hint: String?
    @State private var monitor: Any?

    var body: some View {
        VStack(alignment: .leading, spacing: K.Settings.rowGap) {
            HStack(spacing: K.InputBar.elementGap) {
                Text("Abort key")
                    .font(.system(size: K.RunBox.bodyFontSize, weight: .medium))
                    .foregroundStyle(.primary)
                Spacer(minLength: 0)
                if key != .fallback {
                    PillButton(title: "Reset") {
                        stopRecording()
                        save(.fallback)
                    }
                }
            }

            Button(action: toggleRecording) {
                Text(fieldText)
                    .font(.system(size: K.RunBox.bodyFontSize))
                    .foregroundStyle(.primary)
                    .opacity(isRecording && pending == nil && held.isEmpty ? K.Settings.captionOpacity : 1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, K.Settings.fieldPaddingH)
                    .padding(.vertical, K.Settings.fieldPaddingV)
                    .background {
                        RoundedRectangle(cornerRadius: K.Settings.fieldCornerRadius, style: .continuous)
                            .fill(Color.primary.opacity(K.Settings.fieldFillOpacity * (isRecording ? 2 : 1)))
                    }
                    .overlay {
                        if isRecording {
                            RoundedRectangle(cornerRadius: K.Settings.fieldCornerRadius, style: .continuous)
                                .strokeBorder(Color.accentColor.opacity(0.6), lineWidth: 1)
                        }
                    }
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Abort key, \(key.display)")

            Text(hint ?? "Stops a run from any app, as Stop does. For an F key on a Mac keyboard, hold fn too")
                .font(.system(size: K.Settings.captionSize))
                .foregroundStyle(hint == nil ? Color.secondary : Color.red)
                .opacity(hint == nil ? K.Settings.captionOpacity : K.RunBox.errorOpacity)
                .fixedSize(horizontal: false, vertical: true)
        }
        .onDisappear(perform: stopRecording)
        .onChange(of: isLive) { _, live in
            if !live { stopRecording() }
        }
    }

    private var fieldText: String {
        guard isRecording else { return key.display }
        if let pending { return pending.display }
        let mods = AbortKey.symbols(held)
        return mods.isEmpty ? "Press a combination…" : mods
    }

    // MARK: - Recording

    private func toggleRecording() {
        isRecording ? stopRecording() : startRecording()
    }

    private func startRecording() {
        stopRecording()
        isRecording = true
        hint = nil
        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp, .flagsChanged, .systemDefined]) { event in
            MainActor.assumeIsolated { handle(event) }
            return nil  // swallowed: the combination is being recorded, not typed
        }
    }

    private func stopRecording() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        isRecording = false
        held = []
        pending = nil
    }

    private func handle(_ event: NSEvent) {
        let mods = event.modifierFlags.intersection(AbortKey.modifierMask)
        switch event.type {
        case .keyDown:
            guard !event.isARepeat else { return }
            held.formUnion(mods)
            pending = AbortKey(keyCode: event.keyCode, modifiers: held, keyName: AbortKey.name(of: event))
        case .keyUp:
            break
        case .systemDefined:
            // The top row without fn: brightness, volume, media. These are not
            // key presses, so a hotkey cannot be made of them.
            guard event.subtype.rawValue == 8 else { return }
            hint = "That's a media key. Hold fn with it to use the F key"
            return
        case .flagsChanged:
            if pending == nil { held = mods } else { held.formUnion(mods) }
        default:
            return
        }
        // Let go of the modifiers, or of a bare key: the combination is done.
        // Key-ups alone cannot say so, since AppKit sends none while ⌘ is held.
        guard event.type != .keyDown, mods.isEmpty, let recorded = pending else { return }
        finish(recorded)
    }

    private func finish(_ recorded: AbortKey) {
        if recorded.flags.isEmpty, recorded.keyCode == 53 {  // Escape alone: cancel
            stopRecording()
            return
        }
        guard recorded.isFunctionKey || !recorded.flags.intersection([.command, .option, .control]).isEmpty else {
            // A bare key would fire whenever the run types it; an F key it never types.
            hint = "Use an F key, or hold ⌘, ⌥ or ⌃ with the key"
            pending = nil
            held = []
            return
        }
        stopRecording()
        save(recorded)
    }

    private func save(_ new: AbortKey) {
        AbortKey.current = new
        key = new
        hint = nil
    }
}
