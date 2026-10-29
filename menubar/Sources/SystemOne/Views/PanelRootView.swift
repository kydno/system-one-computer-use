import SwiftUI

/// Everything inside the panel window. Menu-Bar-Chat's root view, down to the
/// input bar and one box under it.
struct PanelRootView: View {

    @ObservedObject var model: RunModel

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var isFieldFocused: Bool
    @State private var isPresented = false

    var body: some View {
        GlassEffectContainer(spacing: K.Panel.glassMergeSpacing) {
            // One glass surface for the whole column: two boxes each draw their
            // own specular edge, so even touching they seam.
            VStack(spacing: 0) {
                InputBarView(model: model, isFieldFocused: $isFieldFocused)
                    .geometryGroup()

                if model.hasRunContent {
                    RunBoxView(model: model)
                        .transition(.opacity.combined(with: .scale(scale: K.Motion.secondBoxScale, anchor: .top)))
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            .glassBox()
        }
        .frame(width: K.Panel.width)
        .fixedSize(horizontal: false, vertical: true)
        .background { SizeReader { model.reportContentHeight($0.height) } }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .houseAnimation(K.Motion.answerAppear, reduceMotion: reduceMotion, value: model.hasRunContent)
        .opacity(isPresented ? 1 : 0)
        .scaleEffect(isPresented ? 1 : restingScale, anchor: .top)
        .offset(y: isPresented ? 0 : restingOffset)
        .padding(K.Panel.windowPadding)
        // The app never activates, so in the sense that matters the panel never
        // has focus; drawing it as though it did would claim otherwise.
        .environment(\.appearsActive, false)
        .onAppear(perform: playOpen)
        .onChange(of: model.openToken) { _, _ in playOpen() }
        .onChange(of: model.isClosing) { _, closing in
            if closing { playClose() }
        }
    }

    private var restingScale: CGFloat {
        model.isClosing ? K.Motion.panelCloseScale : K.Motion.panelOpenScale
    }

    private var restingOffset: CGFloat {
        model.isClosing ? -K.Motion.panelCloseLift : -K.Motion.panelOpenSlide
    }

    private func playOpen() {
        var instant = Transaction()
        instant.disablesAnimations = true
        withTransaction(instant) { isPresented = false }

        DispatchQueue.main.async {
            withAnimation(Motion.curve(K.Motion.panelOpen, reduceMotion: reduceMotion)) {
                isPresented = true
            }
            isFieldFocused = true
        }
    }

    private func playClose() {
        isFieldFocused = false
        withAnimation(Motion.curve(K.Motion.panelClose, reduceMotion: reduceMotion)) {
            isPresented = false
        }
    }
}
