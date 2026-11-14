import SwiftUI

/// The run permissions as a radio group: a monochrome ring beside each row,
/// and the decision model picker's thumb sliding to the row that holds, with
/// no track behind them. Settings and the `/permissions` card
/// show the same one.
struct PermissionPicker: View {

    let selection: RunPermission
    let onSelect: (RunPermission) -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var thumb

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(RunPermission.allCases) { option in
                row(option)
            }
        }
        .houseAnimation(K.Motion.buttonHover, reduceMotion: reduceMotion, value: selection)
    }

    private func row(_ option: RunPermission) -> some View {
        let selected = option == selection
        return Button {
            onSelect(option)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: K.Settings.radioGap) {
                Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                    .font(.system(size: K.Settings.segmentFontSize))
                    .foregroundStyle(.primary)
                    .opacity(selected ? 1 : K.Settings.segmentIdleTextOpacity)
                VStack(alignment: .leading, spacing: 1) {
                    Text(option.title)
                        .font(.system(size: K.Settings.segmentFontSize, weight: selected ? .medium : .regular))
                        .foregroundStyle(.primary)
                        .opacity(selected ? 1 : K.Settings.segmentIdleTextOpacity)
                    Text(option.caption)
                        .font(.system(size: K.Settings.captionSize))
                        .foregroundStyle(.secondary)
                        .opacity(K.Settings.captionOpacity)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, K.Settings.radioPaddingH)
            .padding(.vertical, K.Settings.radioPaddingV)
            .background {
                if selected {
                    RoundedRectangle(cornerRadius: K.Settings.segmentThumbRadius, style: .continuous)
                        .fill(Color.primary.opacity(K.Settings.segmentSelectedOpacity))
                        .matchedGeometryEffect(id: "permissionThumb", in: thumb)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(option.title). \(option.caption)")
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

/// The card `/permissions` opens in place of the run box: the same radio group,
/// for this session only. It holds until Clear, over what Settings says.
struct SessionPermissionsView: View {

    @ObservedObject var model: RunModel

    var body: some View {
        let setting = RunPermission.current
        VStack(alignment: .leading, spacing: K.RunBox.sectionGap) {
            HStack {
                SectionLabel(text: "Permissions", trailing: "This session")
                if model.sessionPermission != nil {
                    PillButton(title: "Use Settings") { model.setSessionPermission(nil) }
                }
                PillButton(title: "Done") { model.closePermissions() }
            }

            PermissionPicker(selection: model.sessionPermission ?? setting) { model.setSessionPermission($0) }

            Text(
                model.sessionPermission == nil
                    ? "Following Settings (\(setting.title)). A pick here holds for this session, until Clear"
                    : "Overrides Settings (\(setting.title)) for this session, until Clear"
            )
            .font(.system(size: K.Settings.captionSize))
            .foregroundStyle(.secondary)
            .opacity(K.Settings.captionOpacity)
            .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, K.RunBox.paddingTop)
        .padding(.horizontal, K.RunBox.paddingSides)
        .padding(.bottom, K.RunBox.paddingBottom)
        .frame(width: K.Panel.width)
    }
}
