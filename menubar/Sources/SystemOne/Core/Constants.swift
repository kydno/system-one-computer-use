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
        static let clearSymbol = "xmark.circle"

        static let buttonHitSize: CGFloat = 20
        static let buttonGlyphSize: CGFloat = 13
        static let buttonRestOpacity: Double = 0.50
        static let buttonHoverOpacity: Double = 0.95
        static let buttonDisabledOpacity: Double = 0.22
        static let buttonHoverCornerRadius: CGFloat = 5
        static let buttonHoverBackgroundOpacity: Double = 0.09
    }

    // MARK: - The run's status strip, in place of the input bar

    enum RunStrip {
        static let fontSize: CGFloat = 12.5
        static let textOpacity: Double = 0.80
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

    // MARK: - Settings, in place of the run box

    enum Settings {
        /// Taller than the run box's cap: the keys, both models and the reviewer
        /// search's three results fit without scrolling.
        static let maxHeight: CGFloat = 640
        static let rowGap: CGFloat = 6
        static let captionSize: CGFloat = 11
        static let captionOpacity: Double = 0.75
        static let fieldPaddingH: CGFloat = 8
        static let fieldPaddingV: CGFloat = 5
        static let fieldCornerRadius: CGFloat = 6
        static let fieldFillOpacity: Double = 0.06
        static let pillPaddingH: CGFloat = 8
        static let pillPaddingV: CGFloat = 3
        /// How much of a saved key the box shows.
        static let keyTailLength = 4
        /// The gear turns this far while the pointer is over it, as Menu-Bar-Chat's does.
        static let gearHoverRotation: Double = 30

        /// Menu-Bar-Chat's surface picker: a shared track with a sliding thumb.
        static let segmentInset: CGFloat = 2
        static let segmentTrackRadius: CGFloat = 8
        static var segmentThumbRadius: CGFloat { segmentTrackRadius - segmentInset }
        static let segmentTrackOpacity: Double = 0.05
        static let segmentSelectedOpacity: Double = 0.10
        static let segmentIdleTextOpacity: Double = 0.75
        static let segmentFontSize: CGFloat = 12
        static let segmentVerticalPadding: CGFloat = 4
    }

    // MARK: - The reviewer model search, in settings

    enum Reviewer {
        /// `config.DEFAULT_OPENROUTER_ANSWER_MODEL`, what runs while `.env` names none.
        static let defaultModel = "openai/gpt-6.1-terra"
        static let modelsURL = URL(string: "https://openrouter.ai/api/v1/models")!
        /// `{id}` is the model's id, author and slug both.
        static let endpointsURL = "https://openrouter.ai/api/v1/models/{id}/endpoints"
        static let searchPlaceholder = "Search OpenRouter models"
        static let resultCount = 3
        static let secondsPerYear: Double = 365 * 86_400
        /// Typing pauses this long before the search runs; the skeleton shows meanwhile.
        static let debounce: Duration = .milliseconds(260)
        static let requestTimeout: TimeInterval = 10

        static let rowHeight: CGFloat = 38
        static let rowGap: CGFloat = 2
        static let rowCornerRadius: CGFloat = 7
        static let rowPaddingH: CGFloat = 8
        static let rowHoverOpacity: Double = 0.06
        static let rowSelectedOpacity: Double = 0.09
        static let idFontSize: CGFloat = 10.5
        static let idOpacity: Double = 0.55

        static let skeletonOpacity: Double = 0.08
        static let skeletonPulseLow: Double = 0.45
        static let skeletonPulse: Double = 0.9
        static let skeletonLineHeight: CGFloat = 8
        static let skeletonCornerRadius: CGFloat = 3
        static let skeletonLineGap: CGFloat = 5
        /// One breath of the skeleton, dim to bright.
        static let skeletonPulseDuration: Double = 0.7
        /// Widths of each skeleton row's two lines, as a share of the row.
        static let skeletonWidths: [(CGFloat, CGFloat)] = [(0.52, 0.34), (0.44, 0.40), (0.58, 0.30)]
    }

    // MARK: - Permissions

    enum Permissions {
        static let askedScreenKey = "askedScreenRecording"
        static let screenRecordingPane = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!
        static let systemEventsPath = "/System/Library/CoreServices/System%20Events.app"
        /// System Events, and `clicker`'s default browser.
        static let automationTargets = ["com.apple.systemevents", "com.google.Chrome"]
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
        /// `--steps` for no limit: more than any run gets to before Stop, a stall or `done`.
        static let unlimitedSteps = 1_000_000
        static let pinnedDefaultsKey = "keepPanelOpen"
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
