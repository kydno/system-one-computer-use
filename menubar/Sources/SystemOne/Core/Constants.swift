import CoreGraphics
import Foundation

/// Every tunable number, string and identifier in the app lives here, as in
/// Menu-Bar-Chat. Nothing in the view layer hardcodes a metric that appears below.
enum K {

    // MARK: - Panel geometry

    enum Panel {
        /// Width of the whole panel.
        static let width: CGFloat = 380
        /// Zero on purpose: anything larger makes `GlassEffectContainer` merge
        /// neighbouring glass into one blob whose contour cuts inside the panel's
        /// corners. Menu-Bar-Chat's `_Log/20` has the measurement.
        static let glassMergeSpacing: CGFloat = 0
        /// Distance from the bottom of the menu bar to the top of the panel.
        static let topInsetBelowMenuBar: CGFloat = 6
        /// Minimum distance the panel keeps from the left/right screen edges.
        static let screenEdgeClamp: CGFloat = 8
        static let cornerRadius: CGFloat = 13
        /// Transparent margin baked into the window so the open/close scale
        /// animation is not clipped by the window frame.
        static let windowPadding: CGFloat = 24
        /// The click that opens the panel is also a mouse-up outside it. Dismissal
        /// is ignored for this long after an open.
        static let dismissGrace: TimeInterval = 0.4
    }

    // MARK: - Input bar

    enum InputBar {
        static let height: CGFloat = 40
        static let horizontalPadding: CGFloat = 13
        static let elementGap: CGFloat = 9
        static let fontSize: CGFloat = 14
        static let goalPlaceholder = "What should System One do?"
        static let replyPlaceholder = "Reply, or press Escape to skip"

        static let buttonHitSize: CGFloat = 20
        static let buttonGlyphSize: CGFloat = 13
        static let buttonRestOpacity: Double = 0.50
        static let buttonHoverOpacity: Double = 0.95
        static let buttonDisabledOpacity: Double = 0.22
        static let buttonHoverCornerRadius: CGFloat = 5
        static let buttonHoverBackgroundOpacity: Double = 0.09
    }

    // MARK: - The run box, under the input bar

    enum RunBox {
        /// A cap, not a height: the box grows to fit and scrolls past this.
        static let maxHeight: CGFloat = 340
        static let paddingTop: CGFloat = 11
        static let paddingSides: CGFloat = 13
        static let paddingBottom: CGFloat = 12
        static let sectionGap: CGFloat = 11
        static let labelGap: CGFloat = 3
        static let bodyFontSize: CGFloat = 13
        /// Multiplier; SwiftUI's `lineSpacing` is additive, so views derive points from this.
        static let lineHeightMultiple: CGFloat = 1.45

        static let labelFontSize: CGFloat = 10
        static let labelTracking: CGFloat = 0.5
        static let labelOpacity: Double = 0.42
        static let goalOpacity: Double = 0.68

        static let actionFontSize: CGFloat = 11.5
        static let actionOpacity: Double = 0.62
        static let actionGap: CGFloat = 2
        static let errorOpacity: Double = 0.85
    }

    // MARK: - Motion

    enum Motion {
        static let curve = (c0x: 0.16, c0y: 1.0, c1x: 0.3, c1y: 1.0)

        static let panelOpen: Double = 0.26
        static let panelClose: Double = 0.14
        static let answerAppear: Double = 0.30
        static let buttonHover: Double = 0.22

        static let panelOpenSlide: CGFloat = 6
        static let panelOpenScale: CGFloat = 0.972
        static let panelCloseLift: CGFloat = 4
        static let panelCloseScale: CGFloat = 0.985
        static let secondBoxScale: CGFloat = 0.96
    }

    // MARK: - Status item

    enum StatusItem {
        static let symbolSize: CGFloat = 14
        static let idleSymbol = "cursorarrow.rays"
        static let runningSymbol = "cursorarrow.motionlines"
        static let accessibilityName = "System One"
        /// Makes macOS remember where you drag the icon to, across relaunches.
        static let autosaveName = "SystemOneStatusItem"
    }

    // MARK: - The run

    enum Run {
        /// Where the checkout lives: `defaults write com.kydno.SystemOne projectRoot <path>`
        /// overrides the one `Scripts/build.sh` writes into Info.plist.
        static let projectRootDefaultsKey = "projectRoot"
        static let projectRootInfoKey = "SystemOneProjectRoot"
        /// `uv sync` puts the entry point here.
        static let clickerPath = ".venv/bin/clicker"
        /// Whether a run may click and type. Off is `clicker`'s own dry run: one
        /// decision, reported and not carried out.
        static let drivesDefaultsKey = "drivesTheMac"
        /// GUI apps get launchd's PATH; `clicker` shells out to `screencapture`,
        /// `osascript` and `open`, which live here.
        static let path = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
        /// Wait this long past the panel's exit animation before the run reads the
        /// screen, so its first capture cannot catch the panel on the way out.
        static let screenSettle: TimeInterval = 0.15
        /// After Stop, how long the run gets to wind down from Ctrl-C (and write
        /// run.json) before it is terminated.
        static let stopGrace: TimeInterval = 5
        /// Printed lines kept, to explain a run that ends without an `end` event.
        static let logTailLines = 12
    }
}
