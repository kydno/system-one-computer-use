import SwiftUI

/// The small chrome buttons in the input bar, from Menu-Bar-Chat: a 20pt hit
/// area, a 13pt glyph at half strength that comes up on hover over a faint plate.
struct HoverButton: View {

    let systemName: String
    var help: String = ""
    /// Latched, for toggles: full strength with its plate showing.
    var isOn: Bool = false
    /// False dims the glyph and stops it responding.
    var isEnabled: Bool = true
    let action: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isHovering = false

    private var glyphOpacity: Double {
        guard isEnabled else { return K.InputBar.buttonDisabledOpacity }
        return isOn || isHovering ? K.InputBar.buttonHoverOpacity : K.InputBar.buttonRestOpacity
    }

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: K.InputBar.buttonGlyphSize, weight: .regular))
                .foregroundStyle(.primary)
                .opacity(glyphOpacity)
                .frame(width: K.InputBar.buttonHitSize, height: K.InputBar.buttonHitSize)
                .background {
                    RoundedRectangle(cornerRadius: K.InputBar.buttonHoverCornerRadius, style: .continuous)
                        .fill(Color.primary.opacity(isOn || isHovering ? K.InputBar.buttonHoverBackgroundOpacity : 0))
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .accessibilityLabel(help)
        .help(help)
        .onHover { isHovering = isEnabled && $0 }
        .houseAnimation(K.Motion.buttonHover, reduceMotion: reduceMotion, value: isHovering)
        .houseAnimation(K.Motion.buttonHover, reduceMotion: reduceMotion, value: isOn)
    }
}
