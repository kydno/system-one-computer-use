import SwiftUI

/// One easing curve everywhere, as in Menu-Bar-Chat. Reduce Motion turns every animation
/// off, not down — `nil` is returned so `withAnimation(nil)` / `.animation(nil,…)`
/// makes the change instant.
enum Motion {

    /// `.timingCurve(0.16, 1, 0.3, 1, duration:)`
    static func curve(_ duration: Double) -> Animation {
        .timingCurve(
            K.Motion.curve.c0x, K.Motion.curve.c0y,
            K.Motion.curve.c1x, K.Motion.curve.c1y,
            duration: duration
        )
    }

    /// Returns the curve, or `nil` when Reduce Motion is on.
    static func curve(_ duration: Double, reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : curve(duration)
    }
}

extension View {
    /// Applies the house curve for `duration`, respecting Reduce Motion.
    func houseAnimation<V: Equatable>(
        _ duration: Double,
        reduceMotion: Bool,
        value: V
    ) -> some View {
        animation(Motion.curve(duration, reduceMotion: reduceMotion), value: value)
    }
}
