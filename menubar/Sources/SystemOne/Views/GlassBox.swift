import SwiftUI

extension View {
    /// The house glass surface, from Menu-Bar-Chat without its size and
    /// transparency settings. No stroke: Liquid Glass draws its own edge, and a
    /// second one reads as a mistake.
    func glassBox(cornerRadius: CGFloat = K.Panel.cornerRadius) -> some View {
        glassEffect(.regular, in: .rect(cornerRadius: cornerRadius))
    }
}

/// Reports the size of whatever it is placed *behind*.
///
/// Always used inside `.background { }` so it can never influence the size of
/// the subtree it is measuring; that feedback path is what produces a window
/// resize loop and a flickering panel.
struct SizeReader: View {

    let onChange: (CGSize) -> Void

    var body: some View {
        GeometryReader { geometry in
            Color.clear
                .onChange(of: geometry.size, initial: true) { _, size in
                    onChange(size)
                }
        }
    }
}
