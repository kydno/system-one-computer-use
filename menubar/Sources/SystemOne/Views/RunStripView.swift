import SwiftUI

/// The locked panel while the run has the screen: one row, the step and what
/// the run did last. It takes no clicks; Stop is on the status item.
struct RunStripView: View {

    @ObservedObject var model: RunModel

    var body: some View {
        HStack(spacing: K.InputBar.elementGap) {
            Image(systemName: K.StatusItem.runningSymbol)
                .font(.system(size: K.InputBar.buttonGlyphSize))
                .foregroundStyle(.secondary)
                .frame(width: K.InputBar.buttonHitSize, height: K.InputBar.buttonHitSize)

            Text(model.progressLine)
                .font(.system(size: K.RunStrip.fontSize))
                .foregroundStyle(.primary)
                .opacity(K.RunStrip.textOpacity)
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentTransition(.opacity)
        }
        .padding(.horizontal, K.InputBar.horizontalPadding)
        .frame(width: K.Panel.width, height: K.InputBar.height)
        .accessibilityElement(children: .combine)
    }
}
