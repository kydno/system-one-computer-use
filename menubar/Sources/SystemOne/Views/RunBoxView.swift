import AppKit
import SwiftUI

/// The second box, from Menu-Bar-Chat's answer box: for each run since the last
/// Clear, what it was asked, what it did, and what it found or wants to know,
/// oldest first. Only exists once there is something to show; grows to fit,
/// capped at `K.RunBox.maxHeight`.
struct RunBoxView: View {

    @ObservedObject var model: RunModel

    @State private var intrinsicHeight: CGFloat = 0

    var body: some View {
        ScrollView(.vertical) {
            content
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, K.RunBox.paddingTop)
                .padding(.horizontal, K.RunBox.paddingSides)
                .padding(.bottom, K.RunBox.paddingBottom)
                // Measured from behind so it can never affect its own size.
                .background { SizeReader { intrinsicHeight = $0.height } }
        }
        .scrollIndicators(.automatic)
        // The newest run is at the bottom: open on it, and stay on it as it grows.
        .defaultScrollAnchor(.bottom, for: .initialOffset)
        .defaultScrollAnchor(.bottom, for: .sizeChanges)
        .frame(height: min(max(intrinsicHeight, 0), K.RunBox.maxHeight))
        .frame(width: K.Panel.width)
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: K.RunBox.sectionGap) {
            ForEach(model.past) { run in
                turn(run, live: false)
                Divider().opacity(K.RunBox.runDividerOpacity)
            }
            if let current = model.current {
                turn(current, live: true)
            }
        }
    }

    /// One run's goal, actions and answer. Only the live one, the last, can be
    /// asking or carry a note, and its footer waits for it to finish.
    @ViewBuilder
    private func turn(_ run: RunRecord, live: Bool) -> some View {
        if let goal = run.goal {
            section("Goal") {
                bodyText(goal).opacity(K.RunBox.goalOpacity)
            }
        }

        if !run.actions.isEmpty {
            section("Did", trailing: run.actions.count == 1 ? "1 action" : "\(run.actions.count) actions") {
                VStack(alignment: .leading, spacing: K.RunBox.actionGap) {
                    ForEach(Array(run.actions.enumerated()), id: \.offset) { _, action in
                        Text(action)
                            .font(.system(size: K.RunBox.actionFontSize))
                            .foregroundStyle(.primary)
                            .opacity(K.RunBox.actionOpacity)
                            .lineLimit(2)
                            .textSelection(.enabled)
                    }
                }
            }
        }

        let asking = live ? model.question : nil
        if let asking {
            section("System One asks") { bodyText(asking) }
        } else if let answer = run.answer {
            section("Answer", trailing: verdict(run.achieved)) { bodyText(answer) }
        } else if live, let note = model.note {
            section(model.noteTitle) { bodyText(note) }
        }

        if run.answer == nil, asking == nil, let outcome = run.outcome {
            section("Ended") { bodyText(outcome.prefix(1).uppercased() + String(outcome.dropFirst())) }
        }

        if let error = run.errorText {
            bodyText(error)
                .foregroundStyle(Color.red)
                .opacity(K.RunBox.errorOpacity)
        }

        if !live || model.phase == .finished, run.runFolder != nil {
            footer(run)
        }
    }

    private func verdict(_ achieved: Bool?) -> String? {
        guard let achieved else { return nil }
        return achieved ? "goal achieved" : "goal not achieved"
    }

    private func footer(_ run: RunRecord) -> some View {
        HStack(spacing: K.InputBar.elementGap) {
            if let seconds = run.seconds {
                Text(String(format: "%.0f s", seconds))
                    .monospacedDigit()
                    .modifier(LabelStyle())
            }
            Spacer(minLength: 0)
            if let cost = run.cost {
                Text(String(format: "$%.4f", cost))
                    .monospacedDigit()
                    .modifier(LabelStyle())
                    .help("What the run cost, as OpenRouter reported it")
                Text("·").modifier(LabelStyle())
            }
            HoverButton(systemName: "folder", help: "Open the run folder") {
                model.openRunFolder(run.runFolder)
            }
        }
    }

    private func section<Content: View>(
        _ label: String,
        trailing: String? = nil,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: K.RunBox.labelGap) {
            SectionLabel(text: label, trailing: trailing)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func bodyText(_ text: String) -> some View {
        Text(BoldMarkup.attributed(text))
            .font(.system(size: K.RunBox.bodyFontSize))
            .lineSpacing(Self.bodyLineSpacing)
            .foregroundStyle(.primary)
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// SwiftUI's `lineSpacing` is additive, so the multiple becomes extra
    /// points on top of the font's own line height.
    private static var bodyLineSpacing: CGFloat {
        let size = K.RunBox.bodyFontSize
        let font = NSFont.systemFont(ofSize: size)
        let natural = font.ascender - font.descender + font.leading
        return max(0, size * K.RunBox.lineHeightMultiple - natural)
    }
}

// MARK: - Labels

/// "GOAL", "ANSWER · GOAL ACHIEVED": 10pt, uppercase, tracked, faint. Menu-Bar-Chat's turn label.
struct SectionLabel: View {

    let text: String
    var trailing: String?

    var body: some View {
        HStack(spacing: 4) {
            Text(text.uppercased()).modifier(LabelStyle())
            if let trailing, !trailing.isEmpty {
                Text("·").modifier(LabelStyle())
                Text(trailing.uppercased()).modifier(LabelStyle()).lineLimit(1)
            }
            Spacer(minLength: 0)
        }
    }
}

struct LabelStyle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .font(.system(size: K.RunBox.labelFontSize, weight: .medium))
            .tracking(K.RunBox.labelTracking)
            .foregroundStyle(.primary)
            .opacity(K.RunBox.labelOpacity)
    }
}

// MARK: - Bold-only markup

/// From Menu-Bar-Chat: `**bold**` runs become bold, everything else stays literal.
enum BoldMarkup {
    static func attributed(_ string: String) -> AttributedString {
        var result = AttributedString()
        var remaining = string[...]

        while let open = remaining.range(of: "**") {
            let before = remaining[..<open.lowerBound]
            if !before.isEmpty {
                result.append(AttributedString(String(before)))
            }
            remaining = remaining[open.upperBound...]
            guard let close = remaining.range(of: "**") else {
                result.append(AttributedString("**"))
                result.append(AttributedString(String(remaining)))
                return result
            }
            let inner = remaining[..<close.lowerBound]
            if inner.isEmpty {
                result.append(AttributedString("****"))
            } else {
                var bold = AttributedString(String(inner))
                bold.inlinePresentationIntent = .stronglyEmphasized
                result.append(bold)
            }
            remaining = remaining[close.upperBound...]
        }

        if !remaining.isEmpty {
            result.append(AttributedString(String(remaining)))
        }
        return result
    }
}
