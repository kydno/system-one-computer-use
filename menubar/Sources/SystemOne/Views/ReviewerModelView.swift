import SwiftUI

/// The settings box's reviewer section: the model `clicker` hands the screen to
/// whenever the decision model stops (`CLICKER_ANSWER_MODEL`), found by
/// searching OpenRouter, and how OpenRouter picks its provider
/// (`CLICKER_ANSWER_SORT`). Writes go through the settings box, which owns `.env`.
struct ReviewerModelView: View {

    /// What `.env` names, nil for none.
    let model: String?
    let routing: String?
    let write: (String, String) -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var segmentThumb
    @FocusState private var isSearchFocused: Bool

    @State private var query = ""
    @State private var phase = Phase.idle
    @State private var catalog: [OpenRouter.Model] = []
    @State private var cheapest: OpenRouter.Endpoint?

    private enum Phase: Equatable {
        case idle
        case loading
        case results([OpenRouter.Model])
        case failed
    }

    private var current: String { model ?? K.Reviewer.defaultModel }
    private var currentRouting: ReviewerRouting { ReviewerRouting.named(routing) }

    var body: some View {
        VStack(alignment: .leading, spacing: K.Settings.rowGap) {
            header
            searchField
            if phase != .idle {
                resultsBox
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
            routingPicker
            if let routingCaption {
                caption(routingCaption)
                    .transition(.opacity)
            }
        }
        .houseAnimation(K.Motion.answerAppear, reduceMotion: reduceMotion, value: phase)
        .houseAnimation(K.Motion.answerAppear, reduceMotion: reduceMotion, value: currentRouting)
        .onChange(of: query) { _, _ in phase = query.trimmed.isEmpty ? .idle : .loading }
        // Restarts on every keystroke, so only the last pause in typing searches.
        .task(id: query) { await search() }
        .task(id: current) { await loadCurrent() }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: K.InputBar.elementGap) {
            Text("Reviewer model")
                .font(.system(size: K.RunBox.bodyFontSize, weight: .medium))
                .foregroundStyle(.primary)
            Spacer(minLength: 0)
            Text(displayName(current))
                .font(.system(size: K.Settings.captionSize))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
                .help(current)
            if model != nil {
                PillButton(title: "Default") { write(ReviewerRouting.modelKey, "") }
            }
        }
    }

    private var searchField: some View {
        HStack(spacing: K.Settings.fieldPaddingH - 2) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: K.Settings.captionSize, weight: .medium))
                .foregroundStyle(.secondary)
            TextField(K.Reviewer.searchPlaceholder, text: $query)
                .textFieldStyle(.plain)
                .font(.system(size: K.RunBox.bodyFontSize))
                .focused($isSearchFocused)
                .onSubmit {
                    if case .results(let models) = phase, let first = models.first { choose(first) }
                }
            if !query.isEmpty {
                Button { query = "" } label: {
                    Image(systemName: K.InputBar.clearSymbol)
                        .font(.system(size: K.Settings.captionSize))
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear search")
                .transition(.opacity)
            }
        }
        .padding(.horizontal, K.Settings.fieldPaddingH)
        .padding(.vertical, K.Settings.fieldPaddingV)
        .background {
            RoundedRectangle(cornerRadius: K.Settings.fieldCornerRadius, style: .continuous)
                .fill(Color.primary.opacity(K.Settings.fieldFillOpacity))
        }
        .houseAnimation(K.Motion.buttonHover, reduceMotion: reduceMotion, value: query.isEmpty)
    }

    // MARK: - Results

    @ViewBuilder
    private var resultsBox: some View {
        Group {
            switch phase {
            case .idle:
                EmptyView()
            case .loading:
                VStack(spacing: K.Reviewer.rowGap) {
                    ForEach(0..<K.Reviewer.resultCount, id: \.self) { index in
                        SkeletonRow(widths: K.Reviewer.skeletonWidths[index % K.Reviewer.skeletonWidths.count])
                    }
                }
                .transition(.opacity)
            case .results(let models) where models.isEmpty:
                note("No model that reads screenshots matches “\(query.trimmed)”")
            case .results(let models):
                VStack(spacing: K.Reviewer.rowGap) {
                    ForEach(models) { option in
                        ResultRow(option: option, isCurrent: option.id == current) { choose(option) }
                    }
                }
                .transition(.opacity)
            case .failed:
                note("Could not reach OpenRouter")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func note(_ text: String) -> some View {
        caption(text)
            .frame(maxWidth: .infinity, minHeight: K.Reviewer.rowHeight, alignment: .leading)
            .padding(.horizontal, K.Reviewer.rowPaddingH)
            .transition(.opacity)
    }

    // MARK: - Routing

    /// The decision model picker's track, for Auto, Cheapest and Fastest.
    private var routingPicker: some View {
        HStack(spacing: 0) {
            ForEach(ReviewerRouting.all) { option in
                segment(option)
            }
        }
        .padding(K.Settings.segmentInset)
        .background {
            RoundedRectangle(cornerRadius: K.Settings.segmentTrackRadius, style: .continuous)
                .fill(Color.primary.opacity(K.Settings.segmentTrackOpacity))
        }
        .houseAnimation(K.Motion.buttonHover, reduceMotion: reduceMotion, value: currentRouting)
    }

    private func segment(_ option: ReviewerRouting) -> some View {
        let selected = option == currentRouting
        return Button {
            write(ReviewerRouting.key, option.id)
        } label: {
            Text(option.title)
                .font(.system(size: K.Settings.segmentFontSize, weight: selected ? .medium : .regular))
                .foregroundStyle(.primary)
                .opacity(selected ? 1 : K.Settings.segmentIdleTextOpacity)
                .lineLimit(1)
                .padding(.vertical, K.Settings.segmentVerticalPadding)
                .frame(maxWidth: .infinity)
                .background {
                    if selected {
                        RoundedRectangle(cornerRadius: K.Settings.segmentThumbRadius, style: .continuous)
                            .fill(Color.primary.opacity(K.Settings.segmentSelectedOpacity))
                            .matchedGeometryEffect(id: "routingThumb", in: segmentThumb)
                    }
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(option.title) provider")
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    /// What Cheapest and Fastest do; Auto has nothing to say.
    private var routingCaption: String? {
        switch currentRouting {
        case .cheapest:
            guard let cheapest else { return "Cheapest provider first, the next one if it fails" }
            let price = OpenRouter.price(prompt: cheapest.prompt, completion: cheapest.completion)
            return "Cheapest first: \(cheapest.title) now, \(price) per M tokens"
        case .fastest:
            return "Fastest provider first, by OpenRouter's live throughput"
        default:
            return nil
        }
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(.system(size: K.Settings.captionSize))
            .foregroundStyle(.secondary)
            .opacity(K.Settings.captionOpacity)
            .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: - State

    private func displayName(_ id: String) -> String {
        let name = catalog.first { $0.id == id }?.name ?? id
        return id == K.Reviewer.defaultModel && model == nil ? "\(name) · default" : name
    }

    private func search() async {
        let text = query.trimmed
        guard !text.isEmpty else { return }
        do {
            try await Task.sleep(for: K.Reviewer.debounce)
            let models = try await OpenRouter.models()
            try Task.checkCancellation()
            catalog = models
            phase = .results(OpenRouter.search(text, in: models, count: K.Reviewer.resultCount))
        } catch is CancellationError {
            // A newer keystroke took over.
        } catch {
            if !Task.isCancelled { phase = .failed }
        }
    }

    /// The current model's name, and its cheapest provider for the caption.
    private func loadCurrent() async {
        cheapest = nil
        if catalog.isEmpty, let models = try? await OpenRouter.models() { catalog = models }
        cheapest = try? await OpenRouter.endpoints(for: current).first
    }

    private func choose(_ option: OpenRouter.Model) {
        write(ReviewerRouting.modelKey, option.id == K.Reviewer.defaultModel ? "" : option.id)
        isSearchFocused = false
        query = ""
    }
}

// MARK: - A result

private struct ResultRow: View {

    let option: OpenRouter.Model
    let isCurrent: Bool
    let action: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: K.InputBar.elementGap) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(option.name)
                        .font(.system(size: K.Settings.segmentFontSize, weight: .medium))
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    Text(option.id)
                        .font(.system(size: K.Reviewer.idFontSize))
                        .foregroundStyle(.secondary)
                        .opacity(K.Reviewer.idOpacity / K.Settings.captionOpacity)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Spacer(minLength: 0)
                Text(OpenRouter.price(prompt: option.prompt, completion: option.completion))
                    .font(.system(size: K.Reviewer.idFontSize))
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .help("Dollars per million tokens, in / out")
                if isCurrent {
                    Image(systemName: "checkmark")
                        .font(.system(size: K.Reviewer.idFontSize, weight: .semibold))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, K.Reviewer.rowPaddingH)
            .frame(height: K.Reviewer.rowHeight)
            .background {
                RoundedRectangle(cornerRadius: K.Reviewer.rowCornerRadius, style: .continuous)
                    .fill(Color.primary.opacity(fillOpacity))
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(option.name), \(option.id)")
        .accessibilityAddTraits(isCurrent ? [.isSelected] : [])
        .onHover { isHovering = $0 }
        .houseAnimation(K.Motion.buttonHover, reduceMotion: reduceMotion, value: isHovering)
    }

    private var fillOpacity: Double {
        if isHovering { return K.Reviewer.rowHoverOpacity }
        return isCurrent ? K.Reviewer.rowSelectedOpacity : 0
    }
}

// MARK: - Skeleton

/// A result's shape while the search runs: two faint bars that breathe.
private struct SkeletonRow: View {

    let widths: (CGFloat, CGFloat)

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isBright = false

    var body: some View {
        GeometryReader { geometry in
            VStack(alignment: .leading, spacing: K.Reviewer.skeletonLineGap) {
                bar(geometry.size.width * widths.0)
                bar(geometry.size.width * widths.1)
            }
            .frame(maxHeight: .infinity, alignment: .center)
        }
        .padding(.horizontal, K.Reviewer.rowPaddingH)
        .frame(height: K.Reviewer.rowHeight)
        .opacity(isBright ? K.Reviewer.skeletonPulse : K.Reviewer.skeletonPulseLow)
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.easeInOut(duration: K.Reviewer.skeletonPulseDuration).repeatForever(autoreverses: true)) { isBright = true }
        }
        .accessibilityLabel("Searching")
    }

    private func bar(_ width: CGFloat) -> some View {
        RoundedRectangle(cornerRadius: K.Reviewer.skeletonCornerRadius, style: .continuous)
            .fill(Color.primary.opacity(K.Reviewer.skeletonOpacity))
            .frame(width: width, height: K.Reviewer.skeletonLineHeight)
    }
}

private extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
