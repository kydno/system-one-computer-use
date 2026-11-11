import Foundation

/// What each model does in a run, for what it cost. The first three match `calls.ROLES`; `evals` is
/// what `clicker-eval` batches paid, which no run folder holds.
enum UsageRole: String, CaseIterable, Identifiable, Sendable {
    case decision, reviewer, writer, evals

    var id: String { rawValue }

    var title: String {
        switch self {
        case .decision: return "Decision"
        case .reviewer: return "Reviewer"
        case .writer: return "Writer"
        case .evals: return "Evals"
        }
    }
}

/// How far back the breakdown looks.
enum UsageWindow: String, CaseIterable, Identifiable, Sendable {
    case lifetime, week

    var id: String { rawValue }

    var title: String {
        switch self {
        case .lifetime: return "Lifetime"
        case .week: return "7 days"
        }
    }

    /// The oldest end time a run may have and still count; nil for every run.
    func cutoff(from now: Date) -> Date? {
        switch self {
        case .lifetime: return nil
        case .week: return now.addingTimeInterval(-7 * 86_400)
        }
    }
}

/// What the pie divides.
enum UsageMetric: String, CaseIterable, Identifiable, Sendable {
    case cost, tokens

    var id: String { rawValue }

    var title: String {
        switch self {
        case .cost: return "Cost"
        case .tokens: return "Tokens"
        }
    }

    func format(_ value: Double) -> String {
        switch self {
        case .cost:
            return String(format: "$%.4f", value)
        case .tokens:
            if value >= 1_000_000 { return String(format: "%.1fM", value / 1_000_000) }
            if value >= 1_000 { return String(format: "%.1fK", value / 1_000) }
            return String(format: "%.0f", value)
        }
    }
}

/// One model's share of one run: USD when its replies reported a cost, every token it took, and
/// the tokens of the replies that reported the cost, which a cost per token divides by.
struct Spend: Equatable, Sendable {
    var cost: Double?
    var tokens: Int
    var costedTokens: Int = 0

    mutating func add(_ other: Spend) {
        if let more = other.cost { cost = (cost ?? 0) + more }
        tokens += other.tokens
        costedTokens += other.costedTokens
    }

    func value(_ metric: UsageMetric) -> Double? {
        switch metric {
        case .cost: return cost
        case .tokens: return tokens > 0 ? Double(tokens) : nil
        }
    }
}

/// One request an eval batch paid for, USD, from the eval ledger.
struct EvalSpend: Equatable, Sendable {
    var at: Date
    var usd: Double
}

/// One run: when it ended, whether its goal was reached, and what each model took under each role,
/// keyed by the model's short name.
struct RunUsage: Equatable, Sendable {
    var ended: Date
    var achieved: Bool?
    var spend: [UsageRole: [String: Spend]]

    /// The decision model that took most of the run's decisions, by tokens.
    var decisionModel: String? {
        spend[.decision]?.max { $0.value.tokens < $1.value.tokens }?.key
    }
}

/// One slice of the pie: a model's share of one role, or the rest of that role's models as "Other".
struct UsageSlice: Identifiable, Equatable, Sendable {
    var role: UsageRole
    var label: String
    var value: Double
    /// 0 for the role's biggest model, darker tones after it.
    var tone: Int

    var id: String { "\(role.rawValue)/\(label)" }
}

/// How one decision model has done over the runs it decided.
struct DecisionRecord: Identifiable, Equatable, Sendable {
    var name: String
    /// Runs that ended with a verdict on the goal.
    var runs: Int
    var succeeded: Int
    var cost: Double?
    var tokens: Int
    var costedTokens: Int = 0

    var id: String { name }
    var successRate: Double { runs > 0 ? Double(succeeded) / Double(runs) : 0 }

    /// USD per million tokens, over the replies that reported a cost.
    var costPerMillion: Double? {
        guard let cost, costedTokens > 0 else { return nil }
        return cost / Double(costedTokens) * 1_000_000
    }
}

/// What every run folder in the checkout reports, read from each `run.json`.
///
/// A run written since `usage_by_role` existed says which role each model was under. An older one
/// has only `usage`, per model id, and maybe the models it was set up with: a model that is the
/// answer model was the reviewer, one that is the writer model the writer, and any other the
/// classifier, whose replies name the exact build rather than the id it was asked by. The oldest
/// name no models. There a dated build (`-20261006`) is the classifier's, since only its replies
/// name one, and of the writer client's models the one asked most is taken for the reviewer, which
/// reads every stop, and the rest for the writer, which only fills fields: an estimate, where the
/// newer runs are exact.
enum UsageLedger {

    static func load(root: URL) -> [RunUsage] {
        let runs = root.appendingPathComponent(K.Usage.runsFolder, isDirectory: true)
        let folders = (try? FileManager.default.contentsOfDirectory(
            at: runs, includingPropertiesForKeys: [.contentModificationDateKey], options: [.skipsHiddenFiles]
        )) ?? []
        return folders.compactMap { folder in
            let file = folder.appendingPathComponent("run.json")
            guard let data = try? Data(contentsOf: file),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { return nil }
            let modified = (try? file.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
            return parse(object, folderName: folder.lastPathComponent, modified: modified)
        }
    }

    /// What `load` would read, in a few `stat`s: each finished run's folder and when its `run.json`
    /// was last written. Two equal fingerprints mean no run has ended, changed or gone since. A run
    /// still going has no `run.json` and is not in it: `clicker` writes one when the run ends,
    /// from the terminal as from the app, so that is when a run is counted.
    static func fingerprint(root: URL) -> [String: Date] {
        let runs = root.appendingPathComponent(K.Usage.runsFolder, isDirectory: true)
        let folders = (try? FileManager.default.contentsOfDirectory(
            at: runs, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]
        )) ?? []
        var stamps: [String: Date] = [:]
        for folder in folders {
            let file = folder.appendingPathComponent("run.json")
            if let written = (try? file.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate {
                stamps[folder.lastPathComponent] = written
            }
        }
        // Not a run folder's name, so it cannot collide with one.
        let ledger = root.appendingPathComponent(K.Usage.evalLedger)
        if let written = (try? ledger.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate {
            stamps["evals"] = written
        }
        return stamps
    }

    /// Every request the eval batches paid for. The ledger is append-only JSON lines; a line that is
    /// not a spend, or is cut short by a write in progress, is skipped.
    static func loadEvals(root: URL) -> [EvalSpend] {
        let file = root.appendingPathComponent(K.Usage.evalLedger)
        guard let text = try? String(contentsOf: file, encoding: .utf8) else { return [] }
        let stamp = ISO8601DateFormatter()
        return text.split(separator: "\n").compactMap { line in
            guard let object = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
                  object["event"] as? String == "spend",
                  let usd = (object["usd"] as? NSNumber)?.doubleValue,
                  let at = (object["at"] as? String).flatMap(stamp.date(from:))
            else { return nil }
            return EvalSpend(at: at, usd: usd)
        }
    }

    /// What the eval batches paid within `window`.
    static func evalCost(_ evals: [EvalSpend], _ window: UsageWindow, now: Date = Date()) -> Double {
        let cutoff = window.cutoff(from: now)
        return evals.filter { cutoff == nil || $0.at >= cutoff! }.reduce(0) { $0 + $1.usd }
    }

    /// How many of `runs` took tokens but saved no cost: runs from before `run.json` carried one,
    /// or on models whose replies report none. A cost total leaves them out.
    static func uncostedRuns(_ runs: [RunUsage]) -> Int {
        runs.filter { run in
            let spends = run.spend.values.flatMap { $0.values }
            return spends.contains { $0.tokens > 0 } && !spends.contains { $0.cost != nil }
        }.count
    }

    static func parse(_ run: [String: Any], folderName: String, modified: Date?) -> RunUsage? {
        var spend: [UsageRole: [String: Spend]] = [:]
        func add(_ role: UsageRole, _ model: String, _ usage: Any) {
            guard let entry = usage as? [String: Any] else { return }
            spend[role, default: [:]][shortName(model), default: Spend(cost: nil, tokens: 0)].add(self.spend(entry))
        }
        if let byRole = run["usage_by_role"] as? [String: Any] {
            for (name, models) in byRole {
                guard let role = UsageRole(rawValue: name), let models = models as? [String: Any] else { continue }
                for (model, usage) in models { add(role, model, usage) }
            }
        } else if let usage = run["usage"] as? [String: Any] {
            if let models = run["models"] as? [String: Any] {
                let answer = models["answer"] as? String
                let writer = models["writer"] as? String
                for (model, entry) in usage {
                    add(model == answer ? .reviewer : model == writer ? .writer : .decision, model, entry)
                }
            } else {
                let undated = usage.keys.filter { !isBuild($0) }
                let reviewer = undated.max { requests(usage[$0]) < requests(usage[$1]) }
                for (model, entry) in usage {
                    add(isBuild(model) ? .decision : model == reviewer ? .reviewer : .writer, model, entry)
                }
            }
        }
        guard !spend.isEmpty, let ended = endDate(run, folderName: folderName) ?? modified else { return nil }
        return RunUsage(ended: ended, achieved: run["goal_achieved"] as? Bool, spend: spend)
    }

    /// Whether `id` names a dated build, as only the decision model's replies do.
    static func isBuild(_ id: String) -> Bool {
        id.range(of: #"-\d{8}$"#, options: .regularExpression) != nil
    }

    /// A model id as a person names the model: no provider, no `~`, no build date.
    /// `openai/gpt-6-luna-decisions-20261006` is `gpt-6-luna-decisions`.
    static func shortName(_ id: String) -> String {
        var name = id.split(separator: "/").last.map(String.init) ?? id
        name = name.trimmingCharacters(in: CharacterSet(charactersIn: "~"))
        if let date = name.range(of: #"-\d{8}$"#, options: .regularExpression) {
            name.removeSubrange(date)
        }
        return name.isEmpty ? id : name
    }

    static func within(_ runs: [RunUsage], _ window: UsageWindow, now: Date = Date()) -> [RunUsage] {
        guard let cutoff = window.cutoff(from: now) else { return runs }
        return runs.filter { $0.ended >= cutoff }
    }

    /// `metric` per model under each role, over `runs`; a model that never reported it is left out.
    static func totals(_ runs: [RunUsage], metric: UsageMetric) -> [UsageRole: [String: Double]] {
        var out: [UsageRole: [String: Double]] = [:]
        for run in runs {
            for (role, models) in run.spend {
                for (model, spend) in models {
                    if let value = spend.value(metric) { out[role, default: [:]][model, default: 0] += value }
                }
            }
        }
        return out
    }

    /// The pie's slices, role by role in `UsageRole` order: each role's models biggest first, at most
    /// `K.Usage.tonesPerRole` of them, the smallest folded into one "Other" when there are more.
    static func slices(_ totals: [UsageRole: [String: Double]]) -> [UsageSlice] {
        UsageRole.allCases.flatMap { role -> [UsageSlice] in
            let models = (totals[role] ?? [:]).filter { $0.value > 0 }.sorted { $0.value > $1.value }
            let limit = K.Usage.tonesPerRole
            let kept = models.count > limit ? Array(models.prefix(limit - 1)) : models
            var slices = kept.enumerated().map { tone, entry in
                UsageSlice(role: role, label: entry.key, value: entry.value, tone: tone)
            }
            if models.count > limit {
                let rest = models.dropFirst(limit - 1).reduce(0) { $0 + $1.value }
                slices.append(UsageSlice(role: role, label: K.Usage.otherLabel, value: rest, tone: limit - 1))
            }
            return slices
        }
    }

    /// Each decision model's record over `runs`, most runs first: a run counts for the model that
    /// took most of its decisions, and toward its success rate once the run said whether its goal
    /// was reached.
    static func decisionRecords(_ runs: [RunUsage]) -> [DecisionRecord] {
        var records: [String: DecisionRecord] = [:]
        for run in runs {
            for (model, spend) in run.spend[.decision] ?? [:] {
                var record = records[model] ?? DecisionRecord(name: model, runs: 0, succeeded: 0, cost: nil, tokens: 0)
                if let cost = spend.cost { record.cost = (record.cost ?? 0) + cost }
                record.tokens += spend.tokens
                record.costedTokens += spend.costedTokens
                records[model] = record
            }
            if let model = run.decisionModel, let achieved = run.achieved {
                records[model]?.runs += 1
                if achieved { records[model]?.succeeded += 1 }
            }
        }
        return records.values.sorted { ($0.runs, $1.name) > ($1.runs, $0.name) }
    }

    /// The decision model to use: of those with `K.Usage.runsToSuggest` runs or more, the one that
    /// reached the goal most often; within `K.Usage.suggestMargin` of that, the cheapest per token.
    static func suggestion(_ records: [DecisionRecord]) -> DecisionRecord? {
        let tried = records.filter { $0.runs >= K.Usage.runsToSuggest }
        guard let best = tried.map(\.successRate).max() else { return nil }
        return tried
            .filter { $0.successRate >= best - K.Usage.suggestMargin }
            .min { ($0.costPerMillion ?? .infinity, -$0.successRate) < ($1.costPerMillion ?? .infinity, -$1.successRate) }
    }

    // MARK: - Reading a run.json

    private static func spend(_ entry: [String: Any]) -> Spend {
        let tokens = ["input_tokens", "cached_input_tokens", "output_tokens"]
            .compactMap { (entry[$0] as? NSNumber)?.intValue }
            .reduce(0, +)
        let cost = (entry["cost"] as? NSNumber)?.doubleValue
        return Spend(cost: cost, tokens: tokens, costedTokens: cost == nil ? 0 : tokens)
    }

    private static func requests(_ entry: Any?) -> Int {
        ((entry as? [String: Any])?["requests"] as? NSNumber)?.intValue ?? 0
    }

    /// `ended_at` when the run wrote one, else the time its folder is named for.
    private static func endDate(_ run: [String: Any], folderName: String) -> Date? {
        if let stamp = run["ended_at"] as? String, let date = ISO8601DateFormatter().date(from: stamp) {
            return date
        }
        let named = DateFormatter()
        named.locale = Locale(identifier: "en_US_POSIX")
        named.dateFormat = K.Usage.folderDateFormat
        guard let start = named.date(from: String(folderName.prefix(K.Usage.folderDateFormat.count))) else { return nil }
        let seconds = (run["seconds"] as? NSNumber)?.doubleValue ?? 0
        return start.addingTimeInterval(seconds)
    }
}
