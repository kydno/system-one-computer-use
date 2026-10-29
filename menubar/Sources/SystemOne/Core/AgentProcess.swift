import Foundation

/// One `clicker --events` run, as a child of this app.
///
/// Being the child of an app is what makes the panel work for computer use:
/// the panel never activates the app, so the app you were in stays frontmost
/// and the run works in it. Run from a terminal, the terminal is frontmost
/// instead, and `clicker` has to bring the work back to the front first.
///
/// It also means macOS asks for Accessibility and Screen Recording on behalf
/// of this app, not of a terminal; the README says where to grant them.
///
/// Not actor-isolated: the pipes are read on FileHandle's own queue. Every
/// callback is delivered on the main queue, in the order the run wrote it,
/// and the exit is delivered after the last event.
final class AgentProcess: @unchecked Sendable {

    /// Each event, on the main actor.
    var onEvent: (@MainActor (AgentEvent) -> Void)?
    /// Once, after the last event: the exit status and what the run wrote to stderr, last lines last.
    var onExit: (@MainActor (Int32, String) -> Void)?

    private let process = Process()
    private let input = Pipe()
    private let output = Pipe()
    private let errors = Pipe()

    /// Only touched from `output`'s readability handler, which FileHandle never
    /// runs twice at once.
    private var pending = Data()
    private let errorLock = NSLock()
    private var errorText = Data()

    init(executable: URL, arguments: [String], directory: URL) {
        process.executableURL = executable
        process.arguments = arguments
        // `clicker` reads ./.env and writes ./runs/ from where it starts.
        process.currentDirectoryURL = directory
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = K.Run.path
        environment["PYTHONUNBUFFERED"] = "1"
        process.environment = environment
        process.standardInput = input
        process.standardOutput = output
        process.standardError = errors
    }

    var isRunning: Bool { process.isRunning }

    func start() throws {
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            self?.read(handle.availableData)
        }
        errors.fileHandleForReading.readabilityHandler = { [weak self] handle in
            self?.readErrors(handle.availableData)
        }
        try process.run()
    }

    /// One line to the run's stdin: the reply to the question it is waiting on.
    func send(_ line: String) {
        let flat = line.replacingOccurrences(of: "\n", with: " ")
        // `write(contentsOf:)` throws on a closed pipe where `write(_:)` would
        // raise an Objective-C exception; SIGPIPE is ignored at launch.
        try? input.fileHandleForWriting.write(contentsOf: Data((flat + "\n").utf8))
    }

    /// Stop the run the way Ctrl-C stops it in a terminal, so it still writes
    /// run.json and says it was aborted. Terminated if it has not gone in
    /// `K.Run.stopGrace` seconds.
    func stop() {
        guard process.isRunning else { return }
        process.interrupt()
        DispatchQueue.global().asyncAfter(deadline: .now() + K.Run.stopGrace) { [weak self] in
            guard let self, self.process.isRunning else { return }
            self.process.terminate()
        }
    }

    // MARK: - Reading

    private func read(_ data: Data) {
        guard !data.isEmpty else {
            finish()
            return
        }
        pending.append(data)
        while let newline = pending.firstIndex(of: UInt8(ascii: "\n")) {
            let line = String(decoding: pending[pending.startIndex..<newline], as: UTF8.self)
            pending.removeSubrange(pending.startIndex...newline)
            deliver(AgentEvent(line: line))
        }
    }

    private func readErrors(_ data: Data) {
        guard !data.isEmpty else {
            errors.fileHandleForReading.readabilityHandler = nil
            return
        }
        errorLock.withLock { errorText.append(data) }
    }

    /// stdout is closed, so the run is ending. Wait for it here, off the main
    /// queue, so the exit is reported after every event and with all of stderr.
    private func finish() {
        output.fileHandleForReading.readabilityHandler = nil
        if !pending.isEmpty {
            deliver(AgentEvent(line: String(decoding: pending, as: UTF8.self)))
            pending.removeAll()
        }
        process.waitUntilExit()
        errors.fileHandleForReading.readabilityHandler = nil
        let rest = errors.fileHandleForReading.readDataToEndOfFile()
        let stderr = errorLock.withLock { () -> String in
            errorText.append(rest)
            return String(decoding: errorText, as: UTF8.self)
        }
        let status = process.terminationStatus
        DispatchQueue.main.async { [weak self] in
            MainActor.assumeIsolated { self?.onExit?(status, stderr) }
        }
    }

    private func deliver(_ event: AgentEvent) {
        DispatchQueue.main.async { [weak self] in
            MainActor.assumeIsolated { self?.onEvent?(event) }
        }
    }
}
