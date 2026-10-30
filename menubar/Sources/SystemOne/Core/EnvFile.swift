import Foundation

/// The checkout's `.env`, which `clicker` reads on every run. The settings box
/// writes keys here rather than to the Keychain, so the terminal and the menu
/// bar app share one set of keys.
///
/// Read the way `config.load_dotenv` reads it: `KEY=VALUE` lines, `#` comments
/// skipped, surrounding quotes stripped. Writes keep every other line as it was.
enum EnvFile {

    static var url: URL? { Project.root?.appendingPathComponent(".env") }

    /// Every uncommented `KEY=VALUE` pair; the first line for a key wins, as it does in Python.
    static func values() -> [String: String] {
        guard let url, let text = try? String(contentsOf: url, encoding: .utf8) else { return [:] }
        var result: [String: String] = [:]
        for raw in text.components(separatedBy: .newlines) {
            guard let (key, value) = parse(raw), result[key] == nil else { continue }
            result[key] = value
        }
        return result
    }

    static func value(_ key: String) -> String? {
        guard let value = values()[key], !value.isEmpty else { return nil }
        return value
    }

    /// Set one key, or clear it with an empty value. Replaces the key's line,
    /// else uncomments the `# KEY=` line `.env.example` ships, else appends.
    /// A missing `.env` starts from `.env.example`, as the README's `cp` does.
    static func set(_ key: String, to value: String) throws {
        guard let url else { throw ProjectError.noRoot }
        var lines = try existingLines(at: url)
        let line = "\(key)=\(value)"

        if let index = lines.firstIndex(where: { parse($0)?.key == key }) {
            lines[index] = line
        } else if let index = lines.firstIndex(where: { isCommented(key, $0) }) {
            lines[index] = line
        } else {
            if lines.last == "" { lines.removeLast() }
            lines.append(line)
            lines.append("")
        }

        try lines.joined(separator: "\n").write(to: url, atomically: true, encoding: .utf8)
        // Keys in it: readable by you alone.
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    private static func existingLines(at url: URL) throws -> [String] {
        if let text = try? String(contentsOf: url, encoding: .utf8) {
            return text.components(separatedBy: "\n")
        }
        let example = url.deletingLastPathComponent().appendingPathComponent(".env.example")
        if let text = try? String(contentsOf: example, encoding: .utf8) {
            return text.components(separatedBy: "\n")
        }
        return []
    }

    private static func parse(_ raw: String) -> (key: String, value: String)? {
        let line = raw.trimmingCharacters(in: .whitespaces)
        guard !line.isEmpty, !line.hasPrefix("#"), let equals = line.firstIndex(of: "=") else { return nil }
        let key = line[..<equals].trimmingCharacters(in: .whitespaces)
        let value = line[line.index(after: equals)...]
            .trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "'\""))
        return (key, value)
    }

    private static func isCommented(_ key: String, _ raw: String) -> Bool {
        let line = raw.trimmingCharacters(in: .whitespaces)
        guard line.hasPrefix("#") else { return false }
        let rest = line.dropFirst().trimmingCharacters(in: .whitespaces)
        return rest.hasPrefix("\(key)=")
    }
}

/// One line of the settings box: a variable `clicker` reads from `.env`.
struct EnvSetting: Identifiable {
    let key: String
    let title: String
    let caption: String
    /// Keys are masked as you type and shown only by their last characters.
    let isSecret: Bool

    var id: String { key }

    /// The decision keys: `clicker` stops before its first capture without one of them.
    /// The box offers OpenRouter's alone; a TypeSafe key already in `.env` still counts.
    static let decisionKeys = ["OPENROUTER_API_KEY", "TYPESAFE_API_KEY"]

    static let all: [EnvSetting] = [
        EnvSetting(
            key: "OPENROUTER_API_KEY",
            title: "OpenRouter",
            caption: "Runs all inference",
            isSecret: true
        ),
        EnvSetting(
            key: "CLICKER_EMAIL",
            title: "Email",
            caption: "Lets it type the address into fields",
            isSecret: false
        ),
    ]
}

/// The decision models OpenRouter serves that `clicker` is set up for
/// (`docs/decision-models.md`), as the settings box's picker offers them.
struct DecisionModel: Identifiable, Equatable {
    let id: String
    let title: String

    static let key = "CLICKER_DECISION_MODEL"

    static let all: [DecisionModel] = [
        DecisionModel(id: "~typesafe/jev-latest", title: "Jev latest"),
        DecisionModel(id: "inception/mercury-decide", title: "Mercury Decide"),
        DecisionModel(id: "openai/gpt-6-luna-decisions", title: "OpenAI"),
    ]

    /// What `.env` names, or Jev when it names none, as `clicker` falls back.
    static var current: DecisionModel {
        let named = EnvFile.value(key)
        return all.first { $0.id == named } ?? all[0]
    }
}
