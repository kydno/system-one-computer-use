import Foundation

/// What a run may do without asking, as `clicker` reads it from
/// `CLICKER_PERMISSIONS` or `--permissions`. Kept in `.env`, not the app's
/// defaults, so a run from the terminal follows the same setting.
///
/// Not to be confused with `Permissions`, the macOS grants this app needs.
enum RunPermission: String, CaseIterable, Identifiable {
    case full
    case ask
    case look

    static let key = "CLICKER_PERMISSIONS"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .full: "Act freely"
        case .ask: "Ask first"
        case .look: "Look only"
        }
    }

    var caption: String {
        switch self {
        case .full: "Takes every action it picks"
        case .ask: "Asks before sending, buying or posting"
        case .look: "Reads only, never changes anything"
        }
    }

    /// What `.env` names, or full when it names none, as `clicker` falls back.
    static var current: RunPermission {
        let named = EnvFile.value(key)?.trimmingCharacters(in: .whitespaces).lowercased() ?? ""
        return RunPermission(rawValue: named) ?? .full
    }
}
