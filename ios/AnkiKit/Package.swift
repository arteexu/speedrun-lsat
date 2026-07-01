// swift-tools-version:5.9
// Copyright: Speedrun LSAT contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
import PackageDescription

// AnkiKit wraps the shared Rust engine (built into AnkiFFI.xcframework by
// ../build-xcframework.sh) in a small Swift API. Add this as a local package to
// a SwiftUI app target.
let package = Package(
    name: "AnkiKit",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "AnkiKit", targets: ["AnkiKit"])
    ],
    targets: [
        .binaryTarget(name: "AnkiFFI", path: "../AnkiFFI.xcframework"),
        .target(name: "AnkiKit", dependencies: ["AnkiFFI"]),
    ]
)
