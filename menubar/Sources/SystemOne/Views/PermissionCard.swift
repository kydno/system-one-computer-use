import SwiftUI

/// What the run box shows in place of the question when a run under Ask first
/// holds an action for the user's OK: the action in a card of its own, with an
/// icon for its kind, where it happens and the words it would type, then Don't
/// allow and Allow. Typing a reply in the field above still answers it, so a
/// "no, open the reviews instead" still reaches the run.
struct PermissionCard: View {

    let request: AgentEvent.PermissionRequest
    let onDeny: () -> Void
    let onAllow: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: K.RunBox.sectionGap) {
            SectionLabel(text: "Needs your OK")

            VStack(alignment: .leading, spacing: K.PermissionCard.innerGap) {
                HStack(spacing: K.PermissionCard.glyphGap) {
                    Image(systemName: symbol)
                        .font(.system(size: K.PermissionCard.glyphFontSize, weight: .medium))
                        .foregroundStyle(.primary)
                        .frame(width: K.PermissionCard.glyphSize, height: K.PermissionCard.glyphSize)
                        .background {
                            RoundedRectangle(cornerRadius: K.PermissionCard.glyphRadius, style: .continuous)
                                .fill(Color.primary.opacity(K.PermissionCard.glyphFillOpacity))
                        }
                    VStack(alignment: .leading, spacing: 1) {
                        Text(request.title)
                            .font(.system(size: K.RunBox.bodyFontSize, weight: .medium))
                            .foregroundStyle(.primary)
                            .lineLimit(2)
                        if let place = request.place {
                            Text(place)
                                .font(.system(size: K.Settings.captionSize))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                    }
                    Spacer(minLength: 0)
                }

                if let text = request.text {
                    Text(text)
                        .font(.system(size: K.PermissionCard.quoteFontSize))
                        .foregroundStyle(.primary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, K.PermissionCard.quotePaddingH)
                        .padding(.vertical, K.PermissionCard.quotePaddingV)
                        .background {
                            RoundedRectangle(cornerRadius: K.PermissionCard.quoteRadius, style: .continuous)
                                .fill(Color.primary.opacity(K.PermissionCard.quoteFillOpacity))
                        }
                }
            }
            .padding(.horizontal, K.PermissionCard.cardPaddingH)
            .padding(.vertical, K.PermissionCard.cardPaddingV)
            .background {
                RoundedRectangle(cornerRadius: K.PermissionCard.cardRadius, style: .continuous)
                    .fill(Color.primary.opacity(K.PermissionCard.cardFillOpacity))
            }

            HStack(spacing: K.PermissionCard.buttonGap) {
                CardButton(title: "Don’t allow", isPrimary: false, action: onDeny)
                CardButton(title: "Allow", isPrimary: true, action: onAllow)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
    }

    private var symbol: String {
        switch request.kind {
        case "type": "keyboard"
        case "key": "return"
        case "drag": "hand.draw"
        case "shortcut": "command"
        default: "cursorarrow.click"
        }
    }
}

/// One of the card's two full-width buttons. Allow is filled with the text
/// colour; Don't allow is the faint fill the rest of the panel uses.
private struct CardButton: View {

    let title: String
    let isPrimary: Bool
    let action: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: K.PermissionCard.buttonFontSize, weight: .medium))
                .foregroundStyle(isPrimary ? AnyShapeStyle(.background) : AnyShapeStyle(.primary))
                .frame(maxWidth: .infinity)
                .padding(.vertical, K.PermissionCard.buttonPaddingV)
                .background {
                    RoundedRectangle(cornerRadius: K.PermissionCard.buttonRadius, style: .continuous)
                        .fill(Color.primary.opacity(fillOpacity))
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { isHovering = $0 }
        .houseAnimation(K.Motion.buttonHover, reduceMotion: reduceMotion, value: isHovering)
    }

    private var fillOpacity: Double {
        if isPrimary { return isHovering ? K.PermissionCard.primaryHoverOpacity : K.PermissionCard.primaryOpacity }
        return isHovering ? K.PermissionCard.secondaryHoverOpacity : K.PermissionCard.secondaryOpacity
    }
}
