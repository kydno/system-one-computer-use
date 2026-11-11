import AppKit
import Combine
import Foundation

/// Where a run stands, as the panel and the status item show it.
enum RunPhase: Equatable {
    /// Nothing has run yet.
    case idle
    /// `clicker` has the screen. The panel stays off it: anything on screen is
    /// something the run would read, and a key panel would take its keystrokes.
    /// Locked, it stays as a passive strip instead, which neither happens to.
    case running
    /// The writer asked the user something, and the run waits for the reply.
    case asking(String)
    /// The run is over; its answer, or why it ended, is on show.
    case finished
}

/// One run as the box shows it. A finished run stays on show above the next
/// one until Clear, and is told to the runs after it, so a goal such as
/// "search for it" can lean on the one before.
struct RunRecord: Identifiable, Equatable {
    let id = UUID()
    var goal: String?
    var actions: [String] = []
    var answer: String?
    var achieved: Bool?
    var outcome: String?
    var errorText: String?
    var runFolder: URL?
    var seconds: Double?
    var cost: Double?

    /// What `--earlier-tasks` carries for this run; nil for one that never began.
    var earlierTask: [String: Any]? {
        guard let goal, runFolder != nil else { return nil }
        var task: [String: Any] = ["goal": goal]
        if let answer { task["answer"] = answer }
        if let achieved { task["achieved"] = achieved }
        if let outcome { task["outcome"] = outcome }
        return task
    }
}

/// The only interface between the views and the run, as `PanelModel` is in
/// Menu-Bar-Chat. Views read it and call its methods; the composition root
/// wires its hooks to the window layer.
@MainActor
final class RunModel: ObservableObject {

    // MARK: - What the views show

    @Published var inputText = ""
    @Published private(set) var phase: RunPhase = .idle
    @Published private(set) var goal: String?
    /// The step the run is on, from 1.
    @Published private(set) var step = 0
    /// What the run did, oldest first, as the runner words it.
    @Published private(set) var actions: [String] = []
    /// The latest word from the run that is not an action: what a dry run
    /// would have done, or the focus the writer sent the classifier back with.
    @Published private(set) var note: String?
    /// What kind of word `note` is, for its label.
    @Published private(set) var noteTitle = ""
    @Published private(set) var answer: String?
    @Published private(set) var achieved: Bool?
    /// How the run ended, in words, when there is no answer to say it.
    @Published private(set) var outcome: String?
    @Published private(set) var errorText: String?
    @Published private(set) var runFolder: URL?
    @Published private(set) var seconds: Double?
    /// What the run cost in USD, as its replies reported it; nil when none did.
    @Published private(set) var cost: Double?
    /// The runs before this one since the last Clear, oldest first.
    @Published private(set) var past: [RunRecord] = []

    /// The lock: an outside click leaves the panel open, and a run shows its
    /// status in one row instead of the panel leaving the screen.
    @Published var isPinned: Bool {
        didSet {
            UserDefaults.standard.set(isPinned, forKey: K.Run.pinnedDefaultsKey)
            if isRunning, !isPinned { requestClose?() }
        }
    }

    /// Bumped on every open so the view can replay its entrance and refocus the
    /// field; the hosting view is reused, so `.onAppear` fires only once.
    @Published private(set) var openToken = 0
    @Published private(set) var isClosing = false

    /// The gear: the settings box shows in place of the run box.
    @Published private(set) var isShowingSettings = false

    // MARK: - Hooks, set by the composition root

    var requestOpen: (() -> Void)?
    var requestClose: (() -> Void)?
    var onContentHeightChange: ((CGFloat) -> Void)?

    // MARK: - State

    private var process: AgentProcess?
    private var root: URL?
    private var logTail: [String] = []
    private var ended = false

    init() {
        isPinned = UserDefaults.standard.bool(forKey: K.Run.pinnedDefaultsKey)
    }

    var isRunning: Bool { phase == .running }

    /// The panel is one row of status while a locked run has the screen.
    var showsRunStrip: Bool { isRunning && isPinned }

    var isAsking: Bool {
        if case .asking = phase { return true }
        return false
    }

    var question: String? {
        if case .asking(let text) = phase { return text }
        return nil
    }

    var canSubmit: Bool {
        isAsking || (!isRunning && !inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    var hasRunContent: Bool { phase != .idle || errorText != nil || !past.isEmpty }

    /// The run on show below the earlier ones, as a record; nil before the first.
    var current: RunRecord? {
        guard phase != .idle || errorText != nil else { return nil }
        return RunRecord(
            goal: goal, actions: actions, answer: answer, achieved: achieved, outcome: outcome,
            errorText: errorText, runFolder: runFolder, seconds: seconds, cost: cost
        )
    }

    /// What every run in the box has cost together, since the last Clear: the earlier ones and
    /// this one, which alone is the whole of it for the first. Nil while no run reported a cost.
    var sessionCost: Double? {
        let costs = (past.map(\.cost) + [current?.cost]).compactMap { $0 }
        return costs.isEmpty ? nil : costs.reduce(0, +)
    }

    /// The clear button: the box can go once no run is live.
    var canClear: Bool { hasRunContent && !isRunning && !isAsking }

    var placeholder: String { isAsking ? K.InputBar.replyPlaceholder : K.InputBar.goalPlaceholder }

    /// One line for the status item's menu and the strip while the run has the screen.
    var progressLine: String {
        let doing = actions.last ?? note ?? "Reading the screen"
        return step > 0 ? "Step \(step) · \(doing)" : doing
    }

    // MARK: - Panel lifecycle

    func panelDidOpen() {
        isClosing = false
        // With no decision key a run would stop before it starts, so the first
        // thing to show is where to put one.
        if phase == .idle, !hasDecisionKey { isShowingSettings = true }
        openToken &+= 1
    }

    /// Closing the panel on a question declines it, as an empty reply does in
    /// the terminal: the run ends with the answer it has.
    func panelWillClose() {
        isClosing = true
        if isAsking { reply("") }
    }

    func reportContentHeight(_ height: CGFloat) {
        onContentHeightChange?(height)
    }

    // MARK: - Settings

    var hasDecisionKey: Bool {
        EnvSetting.decisionKeys.contains { EnvFile.value($0) != nil }
    }

    func toggleSettings() {
        isShowingSettings ? closeSettings() : openSettings()
    }

    func openSettings() {
        guard !isAsking else { return }
        isShowingSettings = true
    }

    func closeSettings() {
        isShowingSettings = false
    }

    // MARK: - Actions

    /// Enter in the field: a reply while the run asks, otherwise a new goal.
    func submit() {
        if isAsking {
            reply(inputText)
        } else if canSubmit {
            start(inputText.trimmingCharacters(in: .whitespacesAndNewlines))
        }
    }

    func start(_ newGoal: String) {
        guard !isRunning, !isAsking else { return }
        isShowingSettings = false
        if phase == .finished, let finished = current { past.append(finished) }
        switch Project.clicker() {
        case .failure(let error):
            reset(goal: newGoal)
            errorText = error.message
            phase = .finished
        case .success(let found):
            reset(goal: newGoal)
            inputText = ""
            phase = .running
            root = found.root
            // No step limit: Stop, `done`, low confidence or a stall ends the run.
            var arguments = ["--events", "--act", "--steps", String(K.Run.unlimitedSteps)]
            let earlier = past.compactMap(\.earlierTask).suffix(K.Run.earlierTasks)
            if !earlier.isEmpty,
               let data = try? JSONSerialization.data(withJSONObject: Array(earlier)),
               let json = String(data: data, encoding: .utf8) {
                arguments += ["--earlier-tasks", json]
            }
            arguments += ["--", newGoal]
            let run = AgentProcess(executable: found.executable, arguments: arguments, directory: found.root)
            run.onEvent = { [weak self] event in self?.handle(event) }
            run.onExit = { [weak self] status, stderr in self?.exited(status, stderr) }
            process = run
            // Off the screen before the run's first capture: the run reads
            // whatever is showing, and works in whichever app is in front.
            // Locked, the panel shrinks to its passive strip instead.
            if !isPinned { requestClose?() }
            DispatchQueue.main.asyncAfter(deadline: .now() + K.Motion.panelClose + K.Run.screenSettle) { [weak self] in
                MainActor.assumeIsolated { self?.launch(run) }
            }
        }
    }

    /// Answer the run's question. The panel leaves the screen first, since the
    /// run goes back to reading it as soon as it has the reply.
    func reply(_ text: String) {
        guard isAsking, let process else { return }
        phase = .running
        inputText = ""
        if !isPinned { requestClose?() }
        DispatchQueue.main.asyncAfter(deadline: .now() + K.Motion.panelClose + K.Run.screenSettle) {
            process.send(text)
        }
    }

    /// As Ctrl-C in the terminal: the run stops where it is and says so.
    func stop() {
        process?.stop()
    }

    /// The clear button: every run's box goes, the next goal starts a new thread
    /// with no earlier tasks, and the panel is back to just the input bar. What
    /// is typed in the field stays.
    func clear() {
        guard canClear else { return }
        past = []
        reset(goal: nil)
        phase = .idle
    }

    /// The latest run's folder, or `folder` when an earlier run's box asks.
    func openRunFolder(_ folder: URL? = nil) {
        guard let folder = folder ?? runFolder else { return }
        NSWorkspace.shared.open(folder)
    }

    // MARK: - The run

    private func launch(_ run: AgentProcess) {
        guard process === run else { return }
        do {
            try run.start()
        } catch {
            process = nil
            errorText = "Could not start clicker: \(error.localizedDescription)"
            phase = .finished
            requestOpen?()
        }
    }

    private func handle(_ event: AgentEvent) {
        switch event {
        case .log(let line):
            guard !line.trimmingCharacters(in: .whitespaces).isEmpty else { return }
            logTail.append(line)
            if logTail.count > K.Run.logTailLines { logTail.removeFirst(logTail.count - K.Run.logTailLines) }
        case .run(let folder, _):
            runFolder = root.map { Project.folder(folder, in: $0) }
        case .step(let number):
            step = number
        case .action(let text):
            actions.append(text)
        case .would(let text):
            note = "Would \(text)"
            noteTitle = "Dry run"
        case .focus(_, let focus):
            note = focus
            noteTitle = "Focus"
        case .question(let text):
            phase = .asking(text)
            isShowingSettings = false
            inputText = ""
            requestOpen?()
        case .answer(let text, let wasAchieved):
            answer = text
            achieved = wasAchieved
        case .end(let end):
            ended = true
            answer = answer ?? end.answer
            achieved = achieved ?? end.achieved
            outcome = end.why ?? end.outcome
            seconds = end.seconds
            cost = end.cost
            if let root { runFolder = Project.folder(end.folder, in: root) }
        }
    }

    private func exited(_ status: Int32, _ stderr: String) {
        process = nil
        if !ended {
            // Stopped before the loop began, as `clicker` does without a key or
            // without Accessibility permission: what it wrote says why.
            let said = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            let fallback = logTail.suffix(3).joined(separator: "\n")
            errorText = said.isEmpty
                ? (fallback.isEmpty ? "clicker exited with status \(status)." : fallback)
                : String(said.suffix(1200))
        }
        phase = .finished
        requestOpen?()
    }

    private func reset(goal newGoal: String?) {
        goal = newGoal
        step = 0
        actions = []
        note = nil
        noteTitle = ""
        answer = nil
        achieved = nil
        outcome = nil
        errorText = nil
        runFolder = nil
        seconds = nil
        cost = nil
        logTail = []
        ended = false
    }
}
