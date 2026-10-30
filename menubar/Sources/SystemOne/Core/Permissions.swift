import AppKit
import ApplicationServices
import CoreGraphics
import CoreServices

/// The grants a run needs. `clicker` runs as this app's child, so macOS
/// files them under System One: asking from here is asking for the run.
enum Permissions {

    struct Status: Equatable {
        var accessibility: Bool
        var screenRecording: Bool
    }

    static var status: Status {
        Status(accessibility: AXIsProcessTrusted(), screenRecording: CGPreflightScreenCaptureAccess())
    }

    /// Ask for every grant still missing. macOS shows each prompt once; a grant
    /// already asked for and still off opens its page in System Settings instead.
    @MainActor
    static func prompt() {
        if !AXIsProcessTrusted() {
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            AXIsProcessTrustedWithOptions(options)
        }

        if !CGPreflightScreenCaptureAccess() {
            let defaults = UserDefaults.standard
            if defaults.bool(forKey: K.Permissions.askedScreenKey) {
                NSWorkspace.shared.open(K.Permissions.screenRecordingPane)
            } else {
                defaults.set(true, forKey: K.Permissions.askedScreenKey)
                CGRequestScreenCaptureAccess()
            }
        }

        askAutomation()
    }

    /// Automation: the run asks System Events for the frontmost app, and the
    /// browser for its page. The question blocks until answered, so off the main thread.
    private static func askAutomation() {
        if let events = URL(string: "file://" + K.Permissions.systemEventsPath) {
            let configuration = NSWorkspace.OpenConfiguration()
            configuration.activates = false
            configuration.addsToRecentItems = false
            NSWorkspace.shared.openApplication(at: events, configuration: configuration) { _, _ in
                DispatchQueue.global(qos: .userInitiated).async {
                    for bundleID in K.Permissions.automationTargets {
                        automate(bundleID)
                    }
                }
            }
        }
    }

    /// A target that is not running answers `procNotFound` and asks nothing.
    @discardableResult
    private static func automate(_ bundleID: String) -> OSStatus {
        var target = AEAddressDesc()
        let bytes = Array(bundleID.utf8)
        guard AECreateDesc(typeApplicationBundleID, bytes, bytes.count, &target) == noErr else { return OSStatus(paramErr) }
        defer { AEDisposeDesc(&target) }
        return AEDeterminePermissionToAutomateTarget(&target, typeWildCard, typeWildCard, true)
    }
}
