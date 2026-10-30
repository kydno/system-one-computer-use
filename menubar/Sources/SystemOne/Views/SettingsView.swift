import SwiftUI

/// The second box while the gear is on, from Menu-Bar-Chat's settings box: the
/// keys `clicker` reads, written to the checkout's `.env` rather than the
/// Keychain, so a run from the terminal sees the same ones.
struct SettingsView: View {

    @ObservedObject var model: RunModel

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var segmentThumb

    @FocusState private var focusedKey: String?
    @State private var saved: [String: String] = [:]
    @State private var decisionModel = DecisionModel.current
    @State private var drafts: [String: String] = [:]
    @State private var errorText: String?
    @State private var intrinsicHeight: CGFloat = 0
    @State private var permissions = Permissions.status

    var body: some View {
        ScrollView(.vertical) {
            content
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, K.RunBox.paddingTop)
                .padding(.horizontal, K.RunBox.paddingSides)
                .padding(.bottom, K.RunBox.paddingBottom)
                .background { SizeReader(onChange: resize) }
        }
        .scrollIndicators(.automatic)
        .frame(height: min(max(intrinsicHeight, 0), K.Settings.maxHeight))
        .frame(width: K.Panel.width)
        .onAppear(perform: load)
        // Grants are made in System Settings, so look again while the box is up.
        .task {
            while !Task.isCancelled {
                permissions = Permissions.status
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    // MARK: - Permissions

    private var permissionsRow: some View {
        HStack(spacing: K.InputBar.elementGap) {
            permissionMark("Accessibility", permissions.accessibility)
            permissionMark("Screen", permissions.screenRecording)
            Spacer(minLength: 0)
            PillButton(title: "Prompt Permissions") {
                Permissions.prompt()
                permissions = Permissions.status
            }
        }
    }

    private func permissionMark(_ title: String, _ granted: Bool) -> some View {
        Label(title, systemImage: granted ? "checkmark.circle.fill" : "circle")
            .font(.system(size: K.Settings.captionSize))
            .foregroundStyle(.secondary)
            .opacity(granted ? 1 : K.Settings.captionOpacity)
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: K.RunBox.sectionGap) {
            HStack {
                SectionLabel(text: "Settings")
                PillButton(title: "Done") { model.closeSettings() }
            }

            if !hasDecisionKey {
                Text("Add an OpenRouter key")
                    .font(.system(size: K.Settings.captionSize))
                    .foregroundStyle(Color.red)
                    .opacity(K.RunBox.errorOpacity)
                    .fixedSize(horizontal: false, vertical: true)
            }

            ForEach(Array(EnvSetting.all.enumerated()), id: \.element.id) { index, setting in
                if index > 0 { Divider() }
                row(setting)
            }

            Divider()

            decisionModelPicker

            Divider()

            ReviewerModelView(
                model: saved[ReviewerRouting.modelKey],
                routing: saved[ReviewerRouting.key],
                write: write
            )

            Divider()

            permissionsRow

            Divider()

            caption(footerText)
            if let errorText {
                caption(errorText)
                    .foregroundStyle(Color.red)
                    .opacity(K.RunBox.errorOpacity)
            }
        }
    }

    // MARK: - A row

    private func row(_ setting: EnvSetting) -> some View {
        let stored = saved[setting.key]
        let draft = Binding(
            get: { drafts[setting.key, default: ""] },
            set: { drafts[setting.key] = $0 }
        )
        let hasDraft = !draft.wrappedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty

        return VStack(alignment: .leading, spacing: K.Settings.rowGap) {
            HStack(spacing: K.InputBar.elementGap) {
                Text(setting.title)
                    .font(.system(size: K.RunBox.bodyFontSize, weight: .medium))
                    .foregroundStyle(.primary)
                Spacer(minLength: 0)
                Text(stored.map { display($0, secret: setting.isSecret) } ?? "Not set")
                    .font(.system(size: K.Settings.captionSize))
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .opacity(stored == nil ? K.Settings.captionOpacity : 1)
                    .lineLimit(1)
                    .truncationMode(.middle)
                if stored != nil {
                    PillButton(title: "Clear") { write(setting.key, "") }
                }
            }

            HStack(spacing: K.InputBar.elementGap) {
                field(setting, stored: stored, text: draft)
                    .textFieldStyle(.plain)
                    .font(.system(size: K.RunBox.bodyFontSize))
                    .focused($focusedKey, equals: setting.key)
                    .onSubmit { save(setting) }
                    .padding(.horizontal, K.Settings.fieldPaddingH)
                    .padding(.vertical, K.Settings.fieldPaddingV)
                    .background {
                        RoundedRectangle(cornerRadius: K.Settings.fieldCornerRadius, style: .continuous)
                            .fill(Color.primary.opacity(K.Settings.fieldFillOpacity))
                    }
                PillButton(title: "Save", isEnabled: hasDraft) { save(setting) }
            }

            caption(setting.caption)
        }
    }

    // MARK: - Decision model

    /// Menu-Bar-Chat's surface picker: a shared track whose thumb slides
    /// between segments, which is what says "exactly one of these".
    private var decisionModelPicker: some View {
        VStack(alignment: .leading, spacing: K.Settings.rowGap) {
            Text("Decision model")
                .font(.system(size: K.RunBox.bodyFontSize, weight: .medium))
                .foregroundStyle(.primary)

            HStack(spacing: 0) {
                ForEach(DecisionModel.all) { option in
                    segment(option)
                }
            }
            .padding(K.Settings.segmentInset)
            .background {
                RoundedRectangle(cornerRadius: K.Settings.segmentTrackRadius, style: .continuous)
                    .fill(Color.primary.opacity(K.Settings.segmentTrackOpacity))
            }
            .houseAnimation(K.Motion.buttonHover, reduceMotion: reduceMotion, value: decisionModel)

        }
    }

    private func segment(_ option: DecisionModel) -> some View {
        let selected = option == decisionModel
        return Button {
            write(DecisionModel.key, option.id)
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
                            .matchedGeometryEffect(id: "decisionThumb", in: segmentThumb)
                    }
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(option.title)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    @ViewBuilder
    private func field(_ setting: EnvSetting, stored: String?, text: Binding<String>) -> some View {
        let prompt = stored == nil
            ? (setting.isSecret ? "Paste your key" : "you@example.com")
            : (setting.isSecret ? "Replace the saved key" : "Replace")
        if setting.isSecret {
            SecureField(prompt, text: text)
        } else {
            TextField(prompt, text: text)
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

    private var hasDecisionKey: Bool {
        EnvSetting.decisionKeys.contains { saved[$0] != nil }
    }

    private var footerText: String {
        guard let url = EnvFile.url else { return ProjectError.noRoot.message }
        let path = (url.path as NSString).abbreviatingWithTildeInPath
        return "Saved to \(path)"
    }

    /// A key by its last few characters only, enough to tell two apart.
    private func display(_ value: String, secret: Bool) -> String {
        guard secret else { return value }
        return "Saved · ••••" + String(value.suffix(K.Settings.keyTailLength))
    }

    /// The first height is taken as it is, so the box opens at its size; after
    /// that it grows and shrinks on the house curve, as the reviewer's results come and go.
    private func resize(_ size: CGSize) {
        guard intrinsicHeight > 0 else {
            intrinsicHeight = size.height
            return
        }
        withAnimation(Motion.curve(K.Motion.answerAppear, reduceMotion: reduceMotion)) {
            intrinsicHeight = size.height
        }
    }

    private func load() {
        saved = EnvFile.values().filter { !$0.value.isEmpty }
        decisionModel = DecisionModel.current
        focusedKey = EnvSetting.all.first { saved[$0.key] == nil }?.key
    }

    private func save(_ setting: EnvSetting) {
        let value = drafts[setting.key, default: ""].trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        write(setting.key, value)
    }

    private func write(_ key: String, _ value: String) {
        do {
            try EnvFile.set(key, to: value)
            errorText = nil
            drafts[key] = ""
            load()
        } catch let error as ProjectError {
            errorText = error.message
        } catch {
            errorText = "Could not write .env: \(error.localizedDescription)"
        }
    }
}

// MARK: - Pill button

/// Menu-Bar-Chat's settings pill: a caption-sized word that shows a faint
/// capsule on hover.
struct PillButton: View {

    let title: String
    var isEnabled: Bool = true
    let action: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: K.Settings.captionSize, weight: .medium))
                .foregroundStyle(.primary)
                .opacity(isEnabled ? (isHovering ? K.InputBar.buttonHoverOpacity : K.InputBar.buttonRestOpacity + 0.2) : K.InputBar.buttonDisabledOpacity)
                .padding(.horizontal, K.Settings.pillPaddingH)
                .padding(.vertical, K.Settings.pillPaddingV)
                .background {
                    Capsule(style: .continuous)
                        .fill(Color.primary.opacity(isHovering ? K.InputBar.buttonHoverBackgroundOpacity : 0))
                }
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .onHover { isHovering = isEnabled && $0 }
        .houseAnimation(K.Motion.buttonHover, reduceMotion: reduceMotion, value: isHovering)
    }
}
