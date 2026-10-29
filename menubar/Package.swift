// swift-tools-version: 6.0
import PackageDescription

// The menu bar front end for `clicker`. Built from Menu-Bar-Chat's panel
// (https://github.com/kydno/Menu-Bar-Chat); see README.md for what came over.
let package = Package(
    name: "SystemOne",
    platforms: [
        // Liquid Glass (`glassEffect`) is macOS 26 only.
        .macOS("26.0")
    ],
    targets: [
        .executableTarget(
            name: "SystemOne",
            path: "Sources/SystemOne",
            swiftSettings: [
                .swiftLanguageMode(.v5)
            ]
        )
    ]
)
