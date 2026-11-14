import AppKit
import Carbon.HIToolbox

/// The key combination that stops a run from anywhere, as Stop does. Kept in
/// the app's defaults rather than `.env`: only the app listens for it.
struct AbortKey: Codable, Equatable {
    /// The virtual key code, as `NSEvent.keyCode` reports it.
    let keyCode: UInt16
    /// `NSEvent.ModifierFlags` raw value: command, option, control and shift only.
    let modifiers: UInt
    /// How the settings row shows it, such as "⌥⌘.".
    let display: String

    static let fallback = AbortKey(
        keyCode: UInt16(kVK_ANSI_Period),
        modifiers: NSEvent.ModifierFlags([.option, .command]).rawValue,
        display: "⌥⌘."
    )

    static var current: AbortKey {
        get {
            guard let data = UserDefaults.standard.data(forKey: K.AbortKey.defaultsKey),
                  let key = try? JSONDecoder().decode(AbortKey.self, from: data) else { return fallback }
            return key
        }
        set {
            guard let data = try? JSONEncoder().encode(newValue) else { return }
            UserDefaults.standard.set(data, forKey: K.AbortKey.defaultsKey)
        }
    }

    /// The modifiers a combination may hold.
    static let modifierMask: NSEvent.ModifierFlags = [.command, .option, .control, .shift]

    var flags: NSEvent.ModifierFlags { NSEvent.ModifierFlags(rawValue: modifiers) }

    /// The modifiers as Carbon's hotkey call takes them.
    var carbonModifiers: UInt32 {
        var result: UInt32 = 0
        if flags.contains(.command) { result |= UInt32(cmdKey) }
        if flags.contains(.option) { result |= UInt32(optionKey) }
        if flags.contains(.control) { result |= UInt32(controlKey) }
        if flags.contains(.shift) { result |= UInt32(shiftKey) }
        return result
    }

    /// One combination from a recorded key and the modifiers held with it.
    init(keyCode: UInt16, modifiers: NSEvent.ModifierFlags, keyName: String) {
        let flags = modifiers.intersection(Self.modifierMask)
        self.keyCode = keyCode
        self.modifiers = flags.rawValue
        self.display = Self.symbols(flags) + keyName
    }

    private init(keyCode: UInt16, modifiers: UInt, display: String) {
        self.keyCode = keyCode
        self.modifiers = modifiers
        self.display = display
    }

    /// In the order macOS menus show them.
    static func symbols(_ flags: NSEvent.ModifierFlags) -> String {
        var text = ""
        if flags.contains(.control) { text += "⌃" }
        if flags.contains(.option) { text += "⌥" }
        if flags.contains(.shift) { text += "⇧" }
        if flags.contains(.command) { text += "⌘" }
        return text
    }

    /// F1 to F20: the run never types them, so one may stand alone.
    static let functionKeys: Set<Int> = [
        kVK_F1, kVK_F2, kVK_F3, kVK_F4, kVK_F5, kVK_F6, kVK_F7, kVK_F8, kVK_F9, kVK_F10,
        kVK_F11, kVK_F12, kVK_F13, kVK_F14, kVK_F15, kVK_F16, kVK_F17, kVK_F18, kVK_F19, kVK_F20,
    ]

    var isFunctionKey: Bool { Self.functionKeys.contains(Int(keyCode)) }

    /// A key's name for the row: its symbol for the keys that have one, else what it types.
    static func name(of event: NSEvent) -> String {
        let named: [Int: String] = [
            kVK_Escape: "⎋", kVK_Return: "↩", kVK_Tab: "⇥", kVK_Space: "Space",
            kVK_Delete: "⌫", kVK_ForwardDelete: "⌦", kVK_LeftArrow: "←", kVK_RightArrow: "→",
            kVK_UpArrow: "↑", kVK_DownArrow: "↓", kVK_Home: "↖", kVK_End: "↘",
            kVK_PageUp: "⇞", kVK_PageDown: "⇟",
            kVK_F1: "F1", kVK_F2: "F2", kVK_F3: "F3", kVK_F4: "F4", kVK_F5: "F5", kVK_F6: "F6",
            kVK_F7: "F7", kVK_F8: "F8", kVK_F9: "F9", kVK_F10: "F10", kVK_F11: "F11", kVK_F12: "F12",
            kVK_F13: "F13", kVK_F14: "F14", kVK_F15: "F15", kVK_F16: "F16", kVK_F17: "F17",
            kVK_F18: "F18", kVK_F19: "F19", kVK_F20: "F20",
        ]
        if let name = named[Int(event.keyCode)] { return name }
        let typed = event.charactersIgnoringModifiers?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return typed.isEmpty ? "Key \(event.keyCode)" : typed.uppercased()
    }
}

/// The abort key, held system-wide while a run goes. A Carbon hotkey, because it
/// needs no Accessibility permission and fires whichever app is in front.
@MainActor
final class AbortHotKey {

    private var ref: EventHotKeyRef?
    private var handlerRef: EventHandlerRef?
    private static var onPress: (() -> Void)?

    /// Listens for `key` until `unregister`; `action` runs on each press.
    func register(_ key: AbortKey, action: @escaping () -> Void) {
        unregister()
        Self.onPress = action
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
            DispatchQueue.main.async {
                MainActor.assumeIsolated { AbortHotKey.onPress?() }
            }
            return noErr
        }, 1, &spec, nil, &handlerRef)
        let id = EventHotKeyID(signature: OSType(0x5331_4142), id: 1)  // "S1AB"
        RegisterEventHotKey(UInt32(key.keyCode), key.carbonModifiers, id, GetApplicationEventTarget(), 0, &ref)
    }

    func unregister() {
        if let ref { UnregisterEventHotKey(ref) }
        if let handlerRef { RemoveEventHandler(handlerRef) }
        ref = nil
        handlerRef = nil
        Self.onPress = nil
    }
}
