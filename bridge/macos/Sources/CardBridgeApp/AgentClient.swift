import Combine
import Foundation
import Network

@MainActor
final class AgentClient: ObservableObject {
    enum ConnectionState: Equatable {
        case stopped
        case connecting
        case connected
        case incompatible(String)
        case failed(String)

        var isConnected: Bool {
            self == .connected
        }
    }

    @Published private(set) var snapshot = BridgeSnapshot.empty
    @Published private(set) var connectionState: ConnectionState = .stopped

    private let socketPath: String
    private let queue = DispatchQueue(label: "com.voltwake.cardbridge.agent-client")
    private var connection: NWConnection?
    private var receiveBuffer = Data()
    private var reconnectTask: Task<Void, Never>?
    private var reconnectDelay: UInt64 = 1
    private var commandID = 0
    private var running = false

    init(socketPath: String? = nil) {
        self.socketPath = socketPath ?? AgentClient.defaultSocketPath
    }

    static var defaultSocketPath: String {
        if let override = ProcessInfo.processInfo.environment["CARDBRIDGE_CONTROL_SOCKET"],
           !override.isEmpty {
            return override
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/CardBridge/run/agent.sock")
            .path
    }

    func start() {
        guard !running else { return }
        running = true
        reconnectDelay = 1
        connect()
    }

    func stop() {
        running = false
        reconnectTask?.cancel()
        reconnectTask = nil
        connection?.cancel()
        connection = nil
        receiveBuffer.removeAll(keepingCapacity: false)
        connectionState = .stopped
    }

    func restartAgent() {
        sendCommand(name: "restart")
    }

    func stopBridge() {
        stop()
        AgentSupervisor.shared.stop()
    }

    func startBridge() {
        AgentSupervisor.shared.start()
        start()
    }

    func unpair(deviceID: String) {
        sendCommand(name: "unpair", fields: ["device_id": deviceID])
    }

    func setGain(_ value: Double) {
        sendCommand(name: "set_gain", fields: ["value": value])
    }

    func installHooks() {
        sendCommand(name: "install_hooks")
    }

    func uninstallHooks() {
        sendCommand(name: "uninstall_hooks")
    }

    private func connect() {
        guard running else { return }
        reconnectTask?.cancel()
        reconnectTask = nil
        connection?.cancel()
        receiveBuffer.removeAll(keepingCapacity: true)
        connectionState = .connecting

        let nextConnection = NWConnection(
            to: .unix(path: socketPath),
            using: .tcp
        )
        connection = nextConnection
        nextConnection.stateUpdateHandler = { [weak self, weak nextConnection] state in
            Task { @MainActor in
                guard let self, self.connection === nextConnection else { return }
                self.handleConnectionState(state)
            }
        }
        nextConnection.start(queue: queue)
    }

    private func handleConnectionState(_ state: NWConnection.State) {
        switch state {
        case .ready:
            reconnectDelay = 1
            send([
                "t": "hello",
                "api": [
                    "major": GeneratedVersion.agentAPIMajor,
                    "minor": GeneratedVersion.agentAPIMinor,
                ],
                "app": [
                    "version": GeneratedVersion.app,
                    "build": GeneratedVersion.appBuild,
                ],
            ])
            receiveNext()
        case let .waiting(error), let .failed(error):
            connectionState = .failed(error.localizedDescription)
            AgentSupervisor.shared.noteAgentUnavailable()
            scheduleReconnect()
        case .cancelled:
            if running { scheduleReconnect() }
        default:
            break
        }
    }

    private func receiveNext() {
        guard let connection else { return }
        connection.receive(
            minimumIncompleteLength: 1,
            maximumLength: 64 * 1024
        ) { [weak self, weak connection] data, _, isComplete, error in
            Task { @MainActor in
                guard let self, self.connection === connection else { return }
                if let data, !data.isEmpty {
                    self.consume(data)
                }
                if let error {
                    self.connectionState = .failed(error.localizedDescription)
                    self.scheduleReconnect()
                } else if isComplete {
                    self.connectionState = .failed(L10n.text("Bridge Agent 已断开"))
                    self.scheduleReconnect()
                } else {
                    self.receiveNext()
                }
            }
        }
    }

    private func consume(_ data: Data) {
        receiveBuffer.append(data)
        while let newline = receiveBuffer.firstIndex(of: 0x0A) {
            let line = receiveBuffer[..<newline]
            receiveBuffer.removeSubrange(...newline)
            guard !line.isEmpty else { continue }
            handleLine(Data(line))
        }
        if receiveBuffer.count > 64 * 1024 {
            connectionState = .failed(L10n.text("Agent 消息超过大小限制"))
            connection?.cancel()
        }
    }

    private func handleLine(_ data: Data) {
        guard
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let type = object["t"] as? String
        else {
            return
        }
        switch type {
        case "hello_ok":
            guard let hello = try? JSONDecoder().decode(AgentHello.self, from: data) else {
                connectionState = .failed(L10n.text("无法解析 Agent 版本"))
                connection?.cancel()
                return
            }
            if let error = hello.compatibilityError {
                connectionState = .incompatible(error)
                running = false
                connection?.cancel()
                return
            }
            connectionState = .connected
            AgentSupervisor.shared.noteAgentAvailable()
            send(["t": "subscribe"])
        case "snapshot":
            guard let decoded = try? JSONDecoder().decode(BridgeSnapshot.self, from: data) else {
                connectionState = .failed(L10n.text("无法解析 Bridge 状态"))
                return
            }
            snapshot = decoded
            connectionState = .connected
        case "api_incompatible":
            let required = object["required"] as? [String: Any]
            let major = required?["major"] as? Int ?? 0
            let minor = required?["minor"] as? Int ?? 0
            connectionState = .incompatible(
                L10n.format("需要 Agent API %@", "\(major).\(minor)")
            )
            running = false
            connection?.cancel()
        default:
            break
        }
    }

    private func sendCommand(name: String, fields: [String: Any] = [:]) {
        commandID += 1
        var request: [String: Any] = [
            "t": "command",
            "id": commandID,
            "name": name,
        ]
        request.merge(fields) { _, new in new }
        send(request)
    }

    private func send(_ object: [String: Any]) {
        guard
            let connection,
            JSONSerialization.isValidJSONObject(object),
            var data = try? JSONSerialization.data(withJSONObject: object)
        else {
            return
        }
        data.append(0x0A)
        connection.send(content: data, completion: .contentProcessed { _ in })
    }

    private func scheduleReconnect() {
        guard running, reconnectTask == nil else { return }
        connection?.cancel()
        connection = nil
        let delay = reconnectDelay
        reconnectDelay = min(reconnectDelay * 2, 30)
        reconnectTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: delay * 1_000_000_000)
            guard !Task.isCancelled, let self else { return }
            self.reconnectTask = nil
            self.connect()
        }
    }
}
