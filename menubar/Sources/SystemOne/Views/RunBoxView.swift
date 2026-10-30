import AppKit
import SwiftUI

/// The second box, from Menu-Bar-Chat's answer box: what the run was asked,
/// what it did, and what it found or wants to know. Only exists once there is
/// something to show; grows to fit, capped at `K.RunBox.maxHeight`.
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
        .frame(height: min(max(intrinsicHeight, 0), K.RunBox.maxHeight))
        .frame(width: K.Panel.width)
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: K.RunBox.sectionGap) {
            if let goal = model.goal {
                section("Goal") {
                    bodyText(goal).opacity(K.RunBox.goalOpacity)
                }
            }

            if !model.actions.isEmpty {
                section("Did", trailing: model.actions.count == 1 ? "1 action" : "\(model.actions.count) actions") {
                    VStack(alignment: .leading, spacing: K.RunBox.actionGap) {
                        ForEach(Array(model.actions.enumerated()), id: \.offset) { _, action in
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

            if let question = model.question {
                section("System One asks") { bodyText(question) }
            } else if let answer = model.answer {
                section("Answer", trailing: verdict) { bodyText(answer) }
            } else if let note = model.note {
                section(model.noteTitle) { bodyText(note) }
            }

            if model.answer == nil, !model.isAsking, let outcome = model.outcome {
                section("Ended") { bodyText(outcome.prefix(1).uppercased() + String(outcome.dropFirst())) }
            }

            if let error = model.errorText {
                bodyText(error)
                    .foregroundStyle(Color.red)
                    .opacity(K.RunBox.errorOpacity)
            }

            if model.phase == .finished, model.runFolder != nil {
                footer
            }
        }
    }

    private var verdict: String? {
        guard let achieved = model.achieved else { return nil }
        return achieved ? "goal achieved" : "goal not achieved"
    }

    private var footer: some View {
        HStack(spacing: K.InputBar.elementGap) {
            if let seconds = model.seconds {
                Text(String(format: "%.0f s", seconds))
                    .monospacedDigit()
                    .modifier(LabelStyle())
            }
            Spacer(minLength: 0)
            HoverButton(systemName: "folder", help: "Open the run folder") {
                model.openRunFolder()
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
