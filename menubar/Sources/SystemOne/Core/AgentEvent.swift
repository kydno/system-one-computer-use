import Foundation

/// One line of `clicker --events` output. `typesafe_computer_use/events.py`
/// writes these and documents each field; this is the reading half.
enum AgentEvent: Equatable, Sendable {
    /// A line the terminal would have printed. Anything on stdout that is not
    /// an event reads as one of these too, so a stray print cannot break a run.
    case log(String)
    case run(folder: String, act: Bool)
    case step(Int)
    case action(String)
    case would(String)
    case focus(text: String, focus: String)
    case question(String)
    case answer(text: String, achieved: Bool)
    case end(RunEnd)

    /// The parts of `run.json` the panel shows.
    struct RunEnd: Equatable, Sendable {
        /// The runner's own name for how the run ended: `done`, `stalled`, `dry run`, `aborted (Ctrl-C)`…
        var outcome: String
        /// The same in a sentence, for the outcomes the writer is handed; nil for the rest.
        var why: String?
        var answer: String?
        var achieved: Bool?
        var folder: String
        var steps: Int
        var seconds: Double
    }

    init(line: String) {
        guard
            let data = line.data(using: .utf8),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let kind = object["event"] as? String,
            let event = Self.parse(kind, object)
        else {
            self = .log(line)
            return
        }
        self = event
    }

    private static func parse(_ kind: String, _ o: [String: Any]) -> AgentEvent? {
        let text = o["text"] as? String
        switch kind {
        case "log":
            return text.map { .log($0) }
        case "run":
            guard let folder = o["folder"] as? String else { return nil }
            return .run(folder: folder, act: o["act"] as? Bool ?? false)
        case "step":
            return (o["step"] as? Int).map { .step($0) }
        case "action":
            return text.map { .action($0) }
        case "would":
            return text.map { .would($0) }
        case "focus":
            guard let focus = o["focus"] as? String else { return nil }
            return .focus(text: text ?? "", focus: focus)
        case "question":
            return text.map { .question($0) }
        case "answer":
            guard let text else { return nil }
            return .answer(text: text, achieved: o["achieved"] as? Bool ?? false)
        case "end":
            guard let outcome = o["outcome"] as? String, let folder = o["folder"] as? String else { return nil }
            return .end(RunEnd(
                outcome: outcome,
                why: o["why"] as? String,
                answer: o["answer"] as? String,
                achieved: o["goal_achieved"] as? Bool,
                folder: folder,
                steps: o["steps_taken"] as? Int ?? 0,
                seconds: (o["seconds"] as? NSNumber)?.doubleValue ?? 0
            ))
        default:
            // An event this build does not know yet: shown nowhere, broken nothing.
            return .log("")
        }
    }
}
