import Combine
import Foundation

@MainActor
final class MicrophoneDriverManager: ObservableObject {
    static let shared = MicrophoneDriverManager()

    @Published private(set) var isInstalled = false
    @Published private(set) var isBusy = false
    @Published private(set) var message = ""

    private let installedURL = URL(
        fileURLWithPath: "/Library/Audio/Plug-Ins/HAL/CardBridgeMicrophone.driver",
        isDirectory: true
    )

    private init() {
        refresh()
    }

    var bundledURL: URL? {
        let candidate = Bundle.main.bundleURL
            .appendingPathComponent("Contents/Resources/AudioDriver", isDirectory: true)
            .appendingPathComponent("CardBridgeMicrophone.driver", isDirectory: true)
        return FileManager.default.fileExists(atPath: candidate.path) ? candidate : nil
    }

    func refresh() {
        isInstalled = Bundle(url: installedURL)?.bundleIdentifier
            == "com.voltwake.cardbridge.microphone.driver"
    }

    func install() async -> Bool {
        guard let bundledURL else {
            message = L10n.text("App 中没有内置麦克风驱动")
            return false
        }
        isBusy = true
        message = ""
        let source = Self.shellQuote(bundledURL.path)
        let target = Self.shellQuote(installedURL.path)
        let executable = Self.shellQuote(
            installedURL.appendingPathComponent("Contents/MacOS/CardBridgeMicrophone").path
        )
        let command = [
            "/usr/bin/ditto \(source) \(target)",
            "/usr/sbin/chown -R root:wheel \(target)",
            "/bin/chmod -R go-w \(target)",
            "/bin/chmod 755 \(executable)",
            "(/usr/bin/killall coreaudiod || true)",
        ].joined(separator: " && ")
        let result = await Self.runAuthorized(command)
        isBusy = false
        refresh()
        if result.status == 0, isInstalled {
            message = L10n.text("CardBridge 麦克风驱动已安装")
            return true
        }
        message = result.output.isEmpty
            ? L10n.text("麦克风驱动安装失败")
            : result.output
        return false
    }

    func uninstall() async -> Bool {
        isBusy = true
        message = ""
        let target = Self.shellQuote(installedURL.path)
        let command = "/bin/rm -rf \(target) && (/usr/bin/killall coreaudiod || true)"
        let result = await Self.runAuthorized(command)
        isBusy = false
        refresh()
        if result.status == 0, !isInstalled {
            message = L10n.text("CardBridge 麦克风驱动已移除")
            return true
        }
        message = result.output.isEmpty
            ? L10n.text("麦克风驱动移除失败")
            : result.output
        return false
    }

    private nonisolated static func runAuthorized(_ command: String) async -> (status: Int32, output: String) {
        await Task.detached(priority: .userInitiated) {
            let process = Process()
            let pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
            process.arguments = [
                "-e",
                "do shell script \"\(appleScriptEscape(command))\" with administrator privileges",
            ]
            process.standardOutput = pipe
            process.standardError = pipe
            do {
                try process.run()
                process.waitUntilExit()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(decoding: data, as: UTF8.self)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                return (process.terminationStatus, output)
            } catch {
                return (Int32(-1), error.localizedDescription)
            }
        }.value
    }

    private nonisolated static func shellQuote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    private nonisolated static func appleScriptEscape(_ value: String) -> String {
        value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }
}
