import AppKit
import Foundation
import UniformTypeIdentifiers

enum DiagnosticExporter {
    private struct Report: Codable {
        let generatedAt: Date
        let appVersion: String
        let appBuild: Int
        let operatingSystem: String
        let architecture: String
        let snapshot: BridgeSnapshot
    }

    @MainActor
    static func export(snapshot: BridgeSnapshot) -> String {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "CardBridge-Diagnostics-\(timestamp()).zip"
        panel.allowedContentTypes = [.zip]
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let destination = panel.url else {
            return ""
        }

        let fileManager = FileManager.default
        let directory = fileManager.temporaryDirectory
            .appendingPathComponent("CardBridge-Diagnostics-\(UUID().uuidString)", isDirectory: true)
        do {
            try fileManager.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            try encodedReport(snapshot: snapshot).write(
                to: directory.appendingPathComponent("status.json"),
                options: .atomic
            )
            try exportLogs(to: directory)
            try createZip(source: directory, destination: destination)
            try? fileManager.removeItem(at: directory)
            NSWorkspace.shared.activateFileViewerSelecting([destination])
            return L10n.text("诊断包已导出；未包含配置文件或配对 token。")
        } catch {
            try? fileManager.removeItem(at: directory)
            return L10n.format("导出失败：%@", error.localizedDescription)
        }
    }

    static func encodedReport(snapshot: BridgeSnapshot) throws -> Data {
        let report = Report(
            generatedAt: Date(),
            appVersion: GeneratedVersion.app,
            appBuild: GeneratedVersion.appBuild,
            operatingSystem: ProcessInfo.processInfo.operatingSystemVersionString,
            architecture: architecture,
            snapshot: snapshot.diagnosticsSnapshot
        )
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(report)
    }

    private static func exportLogs(to directory: URL) throws {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let candidates = [
            home.appendingPathComponent("Library/Logs/CardBridge/Agent.log"),
            home.appendingPathComponent("Library/Logs/CardBridge/Agent-error.log"),
            home.appendingPathComponent(".cardbridge/bridge.log"),
            home.appendingPathComponent(".cardbridge/bridge-error.log"),
        ]
        for source in candidates where FileManager.default.fileExists(atPath: source.path) {
            let data = try Data(contentsOf: source)
            let tail = data.suffix(512 * 1024)
            let text = String(decoding: tail, as: UTF8.self)
            let redacted = redact(text, home: home.path)
            let destination = directory.appendingPathComponent(source.lastPathComponent)
            try Data(redacted.utf8).write(to: destination, options: .atomic)
        }
    }

    static func redact(_ text: String, home: String) -> String {
        var result = text.replacingOccurrences(of: home, with: "~")
        result = replacing(
            #"(?i)\b[0-9a-f]{64}\b"#,
            in: result,
            with: "<redacted-token>"
        )
        result = replacing(
            #"(?i)(pairing[ _-]?code.{0,80}?)(?<![0-9])[0-9]{6}(?![0-9])"#,
            in: result,
            with: "$1<redacted-code>"
        )
        return result
    }

    private static func replacing(_ pattern: String, in text: String, with template: String) -> String {
        guard let expression = try? NSRegularExpression(pattern: pattern) else { return text }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        return expression.stringByReplacingMatches(
            in: text,
            range: range,
            withTemplate: template
        )
    }

    private static func createZip(source: URL, destination: URL) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        process.arguments = [
            "-c", "-k", "--sequesterRsrc", "--keepParent",
            source.path,
            destination.path,
        ]
        let errors = Pipe()
        process.standardError = errors
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let message = String(decoding: errors.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            throw NSError(
                domain: "CardBridgeDiagnostics",
                code: Int(process.terminationStatus),
                userInfo: [NSLocalizedDescriptionKey: message]
            )
        }
    }

    private static var architecture: String {
        #if arch(arm64)
        return "arm64"
        #elseif arch(x86_64)
        return "x86_64"
        #else
        return "unknown"
        #endif
    }

    private static func timestamp() -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        return formatter.string(from: Date())
    }
}
