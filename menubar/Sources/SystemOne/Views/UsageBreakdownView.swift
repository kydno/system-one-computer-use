import SwiftUI

/// The settings box's usage section: what the runs in this checkout cost, or how many tokens they
/// took, split by the role each model played, as `run.json` reports it, and the decision model
/// those runs suggest. Folded to its title until the caret opens it; then the pie sweeps in, a third
/// of the wheel's hues to each role and up to three tones of it, one per model, the smallest folded
/// into "Other".
struct UsageBreakdownView: View {

    /// The decision model `.env` names, and how the box writes a new one.
    let decisionModel: String
    let write: (String, String) -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var windowThumb
    @Namespace private var metricThumb

    @State private var isExpanded = false
    @State private var window = UsageWindow.lifetime
    @State private var metric = UsageMetric.cost
    @State private var runs: [RunUsage]?
    @State private var sweep: Double = 0
    @State private var detailsHeight: CGFloat = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            // Folds by its bottom edge rolling up over it, the content held in place, rather
            // than the content drifting up as it fades.
            details
                .padding(.top, K.Settings.rowGap)
                .fixedSize(horizontal: false, vertical: true)
                .background { SizeReader { detailsHeight = $0.height } }
                .frame(height: isExpanded ? detailsHeight : 0, alignment: .top)
                .clipped()
                .accessibilityHidden(!isExpanded)
        }
        .houseAnimation(K.Motion.answerAppear, reduceMotion: reduceMotion, value: isExpanded)
        // Read again on every open, so the runs since the last one count.
        .task(id: isExpanded) {
            guard isExpanded, let root = Project.root else { return }
            runs = await Task.detached(priority: .userInitiated) { UsageLedger.load(root: root) }.value
            sweepIn()
        }
    }

    // MARK: - Header

    private var header: some View {
        Button {
            isExpanded.toggle()
        } label: {
            HStack(spacing: K.InputBar.elementGap) {
                Text("Usage breakdown")
                    .font(.system(size: K.RunBox.bodyFontSize, weight: .medium))
                    .foregroundStyle(.primary)
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.system(size: K.Usage.caretSize, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .rotationEffect(.degrees(isExpanded ? 90 : 0))
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Usage breakdown")
        .accessibilityValue(isExpanded ? "Expanded" : "Collapsed")
    }

    // MARK: - Details

    private var details: some View {
        let shown = runs.map { UsageLedger.within($0, window) }
        return VStack(alignment: .leading, spacing: K.RunBox.sectionGap) {
            HStack(spacing: K.Usage.pickerGap) {
                picker(UsageWindow.allCases, selected: window, thumb: windowThumb, title: \.title) { window = $0 }
                picker(UsageMetric.allCases, selected: metric, thumb: metricThumb, title: \.title) { metric = $0 }
            }
            if let shown {
                breakdown(shown)
                Divider()
                suggestion(shown)
            } else {
                caption("Reading the run folders…")
            }
        }
    }

    // MARK: - Pickers

    /// Menu-Bar-Chat's surface picker, as the decision model's: a shared track whose thumb slides.
    private func picker<Option: Identifiable & Equatable>(
        _ options: [Option],
        selected: Option,
        thumb: Namespace.ID,
        title: KeyPath<Option, String>,
        choose: @escaping (Option) -> Void
    ) -> some View {
        HStack(spacing: 0) {
            ForEach(options) { option in
                let isSelected = option == selected
                Button {
                    withAnimation(Motion.curve(K.Motion.answerAppear, reduceMotion: reduceMotion)) { choose(option) }
                } label: {
                    Text(option[keyPath: title])
                        .font(.system(size: K.Settings.segmentFontSize, weight: isSelected ? .medium : .regular))
                        .foregroundStyle(.primary)
                        .opacity(isSelected ? 1 : K.Settings.segmentIdleTextOpacity)
                        .lineLimit(1)
                        .padding(.vertical, K.Settings.segmentVerticalPadding)
                        .frame(maxWidth: .infinity)
                        .background {
                            if isSelected {
                                RoundedRectangle(cornerRadius: K.Settings.segmentThumbRadius, style: .continuous)
                                    .fill(Color.primary.opacity(K.Settings.segmentSelectedOpacity))
                                    .matchedGeometryEffect(id: "thumb", in: thumb)
                            }
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(option[keyPath: title])
                .accessibilityAddTraits(isSelected ? [.isSelected] : [])
            }
        }
        .padding(K.Settings.segmentInset)
        .background {
            RoundedRectangle(cornerRadius: K.Settings.segmentTrackRadius, style: .continuous)
                .fill(Color.primary.opacity(K.Settings.segmentTrackOpacity))
        }
    }

    // MARK: - The pie and its legend

    private func breakdown(_ shown: [RunUsage]) -> some View {
        let slices = UsageLedger.slices(UsageLedger.totals(shown, metric: metric))
        return HStack(alignment: .top, spacing: K.Usage.pieLegendGap) {
            pie(slices)
            legend(slices)
        }
    }

    private func pie(_ slices: [UsageSlice]) -> some View {
        let total = slices.reduce(0) { $0 + $1.value }
        let bounds = slices.reduce(into: [Double]()) { $0.append(($0.last ?? 0) + $1.value / total) }
        return ZStack {
            if slices.isEmpty {
                Circle().fill(Color.primary.opacity(K.Usage.emptyPieOpacity))
            }
            ForEach(Array(slices.enumerated()), id: \.element.id) { index, slice in
                PieSlice(
                    start: (index == 0 ? 0 : bounds[index - 1]) * sweep,
                    end: bounds[index] * sweep,
                    gap: slices.count > 1 ? K.Usage.sliceGap : 0
                )
                .fill(color(slice))
            }
        }
        .frame(width: K.Usage.pieSize, height: K.Usage.pieSize)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            slices.isEmpty
                ? "No \(metric.title.lowercased()) logged"
                : slices.map { "\($0.role.title) \($0.label) \(metric.format($0.value))" }.joined(separator: ", ")
        )
    }

    /// With nothing logged for the metric, every figure reads N/A, greyed like the pie.
    private func legend(_ slices: [UsageSlice]) -> some View {
        let total = slices.reduce(0) { $0 + $1.value }
        return VStack(alignment: .leading, spacing: K.Usage.legendRoleGap) {
            HStack {
                SectionLabel(text: "Total")
                figure(slices.isEmpty ? nil : total).font(.system(size: K.Usage.legendFontSize, weight: .medium))
            }
            ForEach(UsageRole.allCases) { role in
                let mine = slices.filter { $0.role == role }
                VStack(alignment: .leading, spacing: K.Usage.legendRowGap) {
                    SectionLabel(text: role.title, trailing: mine.isEmpty ? "N/A" : metric.format(mine.reduce(0) { $0 + $1.value }))
                    ForEach(mine) { slice in legendRow(slice) }
                }
                .opacity(mine.isEmpty ? K.Usage.emptyTextOpacity : 1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func legendRow(_ slice: UsageSlice) -> some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color(slice))
                .frame(width: K.Usage.legendDotSize, height: K.Usage.legendDotSize)
            Text(slice.label)
                .lineLimit(1)
                .truncationMode(.middle)
                .foregroundStyle(.primary)
            Spacer(minLength: 4)
            figure(slice.value)
        }
        .font(.system(size: K.Usage.legendFontSize))
        .help(slice.label)
    }

    private func figure(_ value: Double?) -> some View {
        Text(value.map(metric.format) ?? "N/A")
            .monospacedDigit()
            .foregroundStyle(.secondary)
            .opacity(value == nil ? K.Usage.emptyTextOpacity : 1)
    }

    // MARK: - Suggested decision model

    @ViewBuilder
    private func suggestion(_ shown: [RunUsage]) -> some View {
        let records = UsageLedger.decisionRecords(shown)
        let pick = UsageLedger.suggestion(records)
        VStack(alignment: .leading, spacing: K.Usage.legendRowGap) {
            SectionLabel(text: "Suggested decision model", trailing: pick?.name)
            if let pick {
                HStack(spacing: K.InputBar.elementGap) {
                    Text(pick.name)
                        .font(.system(size: K.RunBox.bodyFontSize, weight: .medium))
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    if let option = option(for: pick.name) {
                        if option.id == decisionModel {
                            Text("In use").font(.system(size: K.Settings.captionSize)).foregroundStyle(.secondary)
                        } else {
                            PillButton(title: "Use") { write(DecisionModel.key, option.id) }
                        }
                    }
                }
            } else {
                caption("Each model needs \(K.Usage.runsToSuggest) runs that ended with a verdict on the goal before one is suggested.")
            }
            ForEach(records) { record in
                HStack(spacing: 6) {
                    Text(record.name).lineLimit(1).truncationMode(.middle)
                    Spacer(minLength: 4)
                    Text(record.runs > 0 ? "\(Int((record.successRate * 100).rounded()))% of \(record.runs)" : "no verdicts")
                        .foregroundStyle(.secondary)
                    Text("·").foregroundStyle(.secondary)
                    Text(record.costPerMillion.map { "\(pricePerToken($0))/1M" } ?? "N/A")
                        .foregroundStyle(.secondary)
                        .opacity(record.costPerMillion == nil ? K.Usage.emptyTextOpacity : 1)
                }
                .font(.system(size: K.Usage.legendFontSize))
                .monospacedDigit()
            }
        }
    }

    /// USD to a tenth of a cent, and to the cent when that tenth is 0: $0.038, $0.02.
    private func pricePerToken(_ cost: Double) -> String {
        let mills = (cost * 1000).rounded()
        return String(format: mills.truncatingRemainder(dividingBy: 10) == 0 ? "$%.2f" : "$%.3f", mills / 1000)
    }

    /// The decision model setting that runs `name`: the same model, or the `-latest` alias its build follows.
    private func option(for name: String) -> DecisionModel? {
        DecisionModel.all.first { option in
            let short = UsageLedger.shortName(option.id)
            if short == name { return true }
            guard short.hasSuffix("-latest") else { return false }
            return name.hasPrefix(String(short.dropLast("latest".count)))
        }
    }

    // MARK: - Parts

    private func color(_ slice: UsageSlice) -> Color {
        let hue: Double
        switch slice.role {
        case .decision: hue = K.Usage.decisionHue
        case .reviewer: hue = K.Usage.reviewerHue
        case .writer: hue = K.Usage.writerHue
        }
        let (saturation, brightness) = K.Usage.tones[min(slice.tone, K.Usage.tones.count - 1)]
        return Color(hue: hue, saturation: saturation, brightness: brightness)
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(.system(size: K.Settings.captionSize))
            .foregroundStyle(.secondary)
            .opacity(K.Settings.captionOpacity)
            .fixedSize(horizontal: false, vertical: true)
    }

    /// The pie grows round from twelve o'clock, once the section has opened and the runs are read.
    private func sweepIn() {
        sweep = 0
        withAnimation(Motion.curve(K.Usage.sweepDuration, reduceMotion: reduceMotion)) { sweep = 1 }
    }
}

/// One wedge of the pie, from `start` to `end` as fractions of the turn clockwise from twelve
/// o'clock. Both animate, so the pie can sweep in and a slice can grow or shrink as the window
/// changes. `gap`, in points at the rim, is left on either side so neighbours read apart.
struct PieSlice: Shape {
    var start: Double
    var end: Double
    var gap: CGFloat = 0

    var animatableData: AnimatablePair<Double, Double> {
        get { AnimatablePair(start, end) }
        set {
            start = newValue.first
            end = newValue.second
        }
    }

    func path(in rect: CGRect) -> Path {
        let radius = min(rect.width, rect.height) / 2
        let center = CGPoint(x: rect.midX, y: rect.midY)
        let pad = radius > 0 ? Double(gap / 2 / radius) : 0
        let from = start * 2 * .pi + pad
        let to = end * 2 * .pi - pad
        var path = Path()
        guard to > from else { return path }
        path.move(to: center)
        path.addArc(
            center: center, radius: radius,
            startAngle: .radians(from - .pi / 2), endAngle: .radians(to - .pi / 2),
            clockwise: false
        )
        path.closeSubpath()
        return path
    }
}
