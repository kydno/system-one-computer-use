import Foundation

/// The checkout this app runs `clicker` from.
///
/// `Scripts/build.sh` writes the path of the checkout it was run in into the
/// bundle's Info.plist, so a build finds its own project with no setup. A
/// `projectRoot` default overrides it, for an app moved away from its source:
///
///     defaults write com.kydno.SystemOne projectRoot ~/code/system-one-computer-use
enum Project {

    static var root: URL? {
        let configured = UserDefaults.standard.string(forKey: K.Run.projectRootDefaultsKey)
            ?? Bundle.main.object(forInfoDictionaryKey: K.Run.projectRootInfoKey) as? String
        guard let path = configured, !path.isEmpty else { return nil }
        return URL(fileURLWithPath: (path as NSString).expandingTildeInPath, isDirectory: true)
    }

    /// The entry point `uv sync` installs, or why there is none, in words for the panel.
    static func clicker() -> Result<(executable: URL, root: URL), ProjectError> {
        guard let root else { return .failure(.noRoot) }
        let executable = root.appendingPathComponent(K.Run.clickerPath)
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            return .failure(.notInstalled(root))
        }
        return .success((executable, root))
    }

    /// A run folder as `clicker` names it: relative to the checkout unless `--out` made it absolute.
    static func folder(_ path: String, in root: URL) -> URL {
        path.hasPrefix("/") ? URL(fileURLWithPath: path, isDirectory: true) : root.appendingPathComponent(path, isDirectory: true)
    }
}

enum ProjectError: Error, Equatable {
    case noRoot
    case notInstalled(URL)

    var message: String {
        switch self {
        case .noRoot:
            return "This build does not know where System One Computer Use is checked out. "
                + "Build it with menubar/Scripts/build.sh, or run "
                + "`defaults write com.kydno.SystemOne projectRoot <checkout>`."
        case .notInstalled(let root):
            return "No clicker in \(root.path). Run `uv sync` there, then try again."
        }
    }
}
