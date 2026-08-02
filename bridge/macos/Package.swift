// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "CardBridge",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "CardBridgeApp", targets: ["CardBridgeApp"]),
    ],
    targets: [
        .binaryTarget(
            name: "Sparkle",
            path: ".deps/Sparkle/Sparkle.xcframework"
        ),
        .executableTarget(
            name: "CardBridgeApp",
            dependencies: [
                "Sparkle",
            ],
            path: ".",
            exclude: ["App", "Tests", "dist", "scripts"],
            sources: ["Shared", "Sources/CardBridgeApp"]
        ),
        .testTarget(
            name: "CardBridgeAppTests",
            dependencies: ["CardBridgeApp"],
            path: "Tests/CardBridgeAppTests"
        ),
    ],
    swiftLanguageModes: [.v5]
)
