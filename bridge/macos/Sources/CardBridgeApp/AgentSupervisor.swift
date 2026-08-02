import Foundation

@MainActor
final class AgentSupervisor {
    static let shared = AgentSupervisor()

    private var process: Process?
    private var restartTask: Task<Void, Never>?
    private var unavailableTask: Task<Void, Never>?
    private var shouldRun = false

    private init() {}

    func start() {
        guard !shouldRun else { return }
        shouldRun = true
        hardenSupportDirectory()
        if migrateLegacyLaunchAgentIfNeeded() {
            ensureRunning(respectExistingSocket: false)
            return
        }
        ensureRunning(respectExistingSocket: true)
    }

    func stop() {
        shouldRun = false
        restartTask?.cancel()
        restartTask = nil
        unavailableTask?.cancel()
        unavailableTask = nil
        if let process, process.isRunning {
            process.terminate()
        }
        process = nil
    }

    func noteAgentAvailable() {
        unavailableTask?.cancel()
        unavailableTask = nil
    }

    func noteAgentUnavailable() {
        guard shouldRun, process == nil, unavailableTask == nil else { return }
        unavailableTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            guard !Task.isCancelled, let self else { return }
            self.unavailableTask = nil
            self.ensureRunning(respectExistingSocket: false)
        }
    }

    private func ensureRunning(respectExistingSocket: Bool) {
        guard shouldRun, process == nil else { return }
        if respectExistingSocket,
           FileManager.default.fileExists(atPath: AgentClient.defaultSocketPath) {
            return
        }
        guard let executable = bundledAgentExecutable else {
            return
        }

        let nextProcess = Process()
        nextProcess.executableURL = executable
        nextProcess.arguments = [
            "--gain", String(UserDefaults.standard.object(forKey: "audioGain") as? Double ?? 8.0),
            "--control-socket", AgentClient.defaultSocketPath,
        ]
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = [
            environment["PATH"] ?? "",
            FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin").path,
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ].filter { !$0.isEmpty }.joined(separator: ":")
        nextProcess.environment = environment

        if let handles = try? logHandles() {
            nextProcess.standardOutput = handles.output
            nextProcess.standardError = handles.error
        }
        nextProcess.terminationHandler = { [weak self, weak nextProcess] _ in
            Task { @MainActor in
                guard let self, self.process === nextProcess else { return }
                self.process = nil
                self.scheduleRestart()
            }
        }
        do {
            try nextProcess.run()
            process = nextProcess
        } catch {
            scheduleRestart()
        }
    }

    private func scheduleRestart() {
        guard shouldRun, restartTask == nil else { return }
        restartTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            guard !Task.isCancelled, let self else { return }
            self.restartTask = nil
            self.ensureRunning(respectExistingSocket: true)
        }
    }

    private var bundledAgentExecutable: URL? {
        let candidate = Bundle.main.bundleURL
            .appendingPathComponent("Contents/Helpers/CardBridgeAgent.app", isDirectory: true)
            .appendingPathComponent("Contents/MacOS/CardBridgeAgent", isDirectory: false)
        return FileManager.default.isExecutableFile(atPath: candidate.path) ? candidate : nil
    }

    private func logHandles() throws -> (output: FileHandle, error: FileHandle) {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/CardBridge", isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let outputURL = directory.appendingPathComponent("Agent.log")
        let errorURL = directory.appendingPathComponent("Agent-error.log")
        for url in [outputURL, errorURL] where !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        let output = try FileHandle(forWritingTo: outputURL)
        let error = try FileHandle(forWritingTo: errorURL)
        try output.seekToEnd()
        try error.seekToEnd()
        return (output, error)
    }

    private func migrateLegacyLaunchAgentIfNeeded() -> Bool {
        let fileManager = FileManager.default
        let legacyURL = fileManager.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/local.cardbridge.service.plist")
        guard fileManager.fileExists(atPath: legacyURL.path), bundledAgentExecutable != nil else {
            return false
        }

        let launchctl = Process()
        launchctl.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        launchctl.arguments = [
            "bootout",
            "gui/\(getuid())/local.cardbridge.service",
        ]
        launchctl.standardOutput = FileHandle.nullDevice
        launchctl.standardError = FileHandle.nullDevice
        do {
            try launchctl.run()
            launchctl.waitUntilExit()
        } catch {
            return false
        }
        guard launchctl.terminationStatus == 0 else { return false }

        let backupDirectory = fileManager.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/CardBridge/Migration", isDirectory: true)
        do {
            try fileManager.createDirectory(
                at: backupDirectory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            let backupURL = backupDirectory.appendingPathComponent("local.cardbridge.service.plist.backup")
            if fileManager.fileExists(atPath: backupURL.path) {
                try fileManager.removeItem(at: legacyURL)
            } else {
                try fileManager.moveItem(at: legacyURL, to: backupURL)
            }
            try fileManager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: backupURL.path)
            UserDefaults.standard.set(true, forKey: "didMigrateLegacyLaunchAgent")
            return true
        } catch {
            return true
        }
    }

    private func hardenSupportDirectory() {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/CardBridge", isDirectory: true)
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o700],
                ofItemAtPath: directory.path
            )
        } catch {
            // The Agent will surface a startup error if this directory is unusable.
        }
    }
}
