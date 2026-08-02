import Foundation

struct AgentHello: Codable, Equatable, Sendable {
    struct Agent: Codable, Equatable, Sendable {
        let version: String
        let build: Int
    }

    struct API: Codable, Equatable, Sendable {
        let major: Int
        let minor: Int
    }

    let type: String
    let agent: Agent
    let api: API

    enum CodingKeys: String, CodingKey {
        case type = "t"
        case agent, api
    }

    var compatibilityError: String? {
        guard agent.version == GeneratedVersion.agent,
              agent.build == GeneratedVersion.agentBuild else {
            return L10n.format(
                "App %@ (%@) 与 Agent %@ (%@) 不匹配",
                GeneratedVersion.app,
                String(GeneratedVersion.appBuild),
                agent.version,
                String(agent.build)
            )
        }
        guard api.major == GeneratedVersion.agentAPIMajor else {
            return L10n.format("Agent API %@ 不兼容", "\(api.major).\(api.minor)")
        }
        return nil
    }
}

struct BridgeSnapshot: Codable, Equatable, Sendable {
    struct Agent: Codable, Equatable, Sendable {
        struct API: Codable, Equatable, Sendable {
            let major: Int
            let minor: Int
        }

        let state: String
        let version: String
        let build: Int
        let api: API
        let pid: Int
        let startedAtMS: Int64
        let bridgeID: String
        let macName: String
        let lanAddress: String
        let tcpPort: Int
        let udpPort: Int
        let hookPort: Int?
        let issues: [String]
        let lastError: String

        enum CodingKeys: String, CodingKey {
            case state, version, build, api, pid, issues
            case startedAtMS = "started_at_ms"
            case bridgeID = "bridge_id"
            case macName = "mac_name"
            case lanAddress = "lan_address"
            case tcpPort = "tcp_port"
            case udpPort = "udp_port"
            case hookPort = "hook_port"
            case lastError = "last_error"
        }
    }

    struct Permissions: Codable, Equatable, Sendable {
        let accessibility: Bool
    }

    struct Audio: Codable, Equatable, Sendable {
        let enabled: Bool
        let running: Bool
        let device: String?
        let gain: Double
        let sampleRate: Double?
        let received: Int
        let lost: Int
        let late: Int
        let resyncs: Int

        enum CodingKeys: String, CodingKey {
            case enabled, running, device, gain, received, lost, late, resyncs
            case sampleRate = "sample_rate"
        }

        init(
            enabled: Bool,
            running: Bool,
            device: String?,
            gain: Double,
            sampleRate: Double?,
            received: Int,
            lost: Int,
            late: Int,
            resyncs: Int
        ) {
            self.enabled = enabled
            self.running = running
            self.device = device
            self.gain = gain
            self.sampleRate = sampleRate
            self.received = received
            self.lost = lost
            self.late = late
            self.resyncs = resyncs
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            enabled = try container.decodeIfPresent(Bool.self, forKey: .enabled) ?? true
            running = try container.decodeIfPresent(Bool.self, forKey: .running) ?? false
            device = try container.decodeIfPresent(String.self, forKey: .device)
            gain = try container.decodeIfPresent(Double.self, forKey: .gain) ?? 1
            sampleRate = try container.decodeIfPresent(Double.self, forKey: .sampleRate)
            received = try container.decodeIfPresent(Int.self, forKey: .received) ?? 0
            lost = try container.decodeIfPresent(Int.self, forKey: .lost) ?? 0
            late = try container.decodeIfPresent(Int.self, forKey: .late) ?? 0
            resyncs = try container.decodeIfPresent(Int.self, forKey: .resyncs) ?? 0
        }
    }

    struct Codex: Codable, Equatable, Sendable {
        struct UsageBreakdown: Codable, Equatable, Sendable {
            let total: Int
            let input: Int
            let cachedInput: Int
            let output: Int
            let reasoningOutput: Int

            enum CodingKeys: String, CodingKey {
                case total, input, output
                case cachedInput = "cached_input"
                case reasoningOutput = "reasoning_output"
            }

            init(
                total: Int,
                input: Int,
                cachedInput: Int,
                output: Int,
                reasoningOutput: Int
            ) {
                self.total = total
                self.input = input
                self.cachedInput = cachedInput
                self.output = output
                self.reasoningOutput = reasoningOutput
            }

            init(from decoder: Decoder) throws {
                let container = try decoder.container(keyedBy: CodingKeys.self)
                total = try container.decodeIfPresent(Int.self, forKey: .total) ?? 0
                input = try container.decodeIfPresent(Int.self, forKey: .input) ?? 0
                cachedInput = try container.decodeIfPresent(Int.self, forKey: .cachedInput) ?? 0
                output = try container.decodeIfPresent(Int.self, forKey: .output) ?? 0
                reasoningOutput = try container.decodeIfPresent(Int.self, forKey: .reasoningOutput) ?? 0
            }
        }

        struct UsageSession: Codable, Equatable, Sendable, Identifiable {
            let id: String
            let turnID: String
            let total: UsageBreakdown
            let last: UsageBreakdown
            let delta: UsageBreakdown
            let windowMS: Int
            let tokensPerSecond: Double
            let modelContextWindow: Int?

            var identity: String { "\(id):\(turnID)" }

            enum CodingKeys: String, CodingKey {
                case id, total, last, delta
                case turnID = "turn_id"
                case windowMS = "window_ms"
                case tokensPerSecond = "tokens_per_second"
                case modelContextWindow = "model_context_window"
            }
        }

        struct Usage: Codable, Equatable, Sendable {
            let available: Bool
            let source: String
            let updatedAtMS: Int64
            let reason: String?
            let sessions: [UsageSession]

            enum CodingKeys: String, CodingKey {
                case available, source, reason, sessions
                case updatedAtMS = "updated_at_ms"
            }

            static let unavailable = Usage(
                available: false,
                source: "unavailable",
                updatedAtMS: 0,
                reason: "not_observed",
                sessions: []
            )
        }

        let enabled: Bool
        let connected: Bool
        let executable: String?
        let hooksListening: Bool
        let hooksInstalled: Bool
        let sessions: Int
        let quotaAvailable: Bool
        let quotaMode: String?
        let usage: Usage?

        enum CodingKeys: String, CodingKey {
            case enabled, connected, executable, sessions, usage
            case hooksListening = "hooks_listening"
            case hooksInstalled = "hooks_installed"
            case quotaAvailable = "quota_available"
            case quotaMode = "quota_mode"
        }
    }

    struct Device: Codable, Equatable, Identifiable, Sendable {
        struct ProtocolVersion: Codable, Equatable, Sendable {
            let major: Int
            let minor: Int
        }

        let id: String
        let ip: String
        let model: String
        let firmware: String
        let firmwareBuild: String
        let `protocol`: ProtocolVersion
        let compatibility: String
        let capabilities: [String]
        let connectedAtMS: Int64
        let lastSeenMS: Int64
        let audioPackets: Int
        let name: String?
        let vendor: String?
        let audioInvalidPackets: Int?
        let audioLease: String?
        let subscriptions: [String]?
        let minIntervalMS: Int?

        enum CodingKeys: String, CodingKey {
            case id, ip, model, firmware, `protocol`, compatibility, capabilities, name, vendor
            case firmwareBuild = "firmware_build"
            case connectedAtMS = "connected_at_ms"
            case lastSeenMS = "last_seen_ms"
            case audioPackets = "audio_packets"
            case audioInvalidPackets = "audio_invalid_packets"
            case audioLease = "audio_lease"
            case subscriptions
            case minIntervalMS = "min_interval_ms"
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            id = try container.decode(String.self, forKey: .id)
            ip = try container.decodeIfPresent(String.self, forKey: .ip) ?? ""
            model = try container.decodeIfPresent(String.self, forKey: .model) ?? "unknown"
            firmware = try container.decodeIfPresent(String.self, forKey: .firmware) ?? "unknown"
            firmwareBuild = try container.decodeIfPresent(String.self, forKey: .firmwareBuild) ?? "unknown"
            `protocol` = try container.decodeIfPresent(ProtocolVersion.self, forKey: .protocol)
                ?? ProtocolVersion(major: 1, minor: 0)
            compatibility = try container.decodeIfPresent(String.self, forKey: .compatibility) ?? "unknown"
            capabilities = try container.decodeIfPresent([String].self, forKey: .capabilities) ?? []
            connectedAtMS = try container.decodeIfPresent(Int64.self, forKey: .connectedAtMS) ?? 0
            let connectedAt = connectedAtMS
            lastSeenMS = try container.decodeIfPresent(Int64.self, forKey: .lastSeenMS) ?? connectedAt
            audioPackets = try container.decodeIfPresent(Int.self, forKey: .audioPackets) ?? 0
            name = try container.decodeIfPresent(String.self, forKey: .name)
            vendor = try container.decodeIfPresent(String.self, forKey: .vendor)
            audioInvalidPackets = try container.decodeIfPresent(Int.self, forKey: .audioInvalidPackets)
            audioLease = try container.decodeIfPresent(String.self, forKey: .audioLease)
            subscriptions = try container.decodeIfPresent([String].self, forKey: .subscriptions)
            minIntervalMS = try container.decodeIfPresent(Int.self, forKey: .minIntervalMS)
        }
    }

    struct PairedDevice: Codable, Equatable, Identifiable, Sendable {
        let id: String
        let name: String
        let pairedAt: Int64

        enum CodingKeys: String, CodingKey {
            case id, name
            case pairedAt = "paired_at"
        }
    }

    struct Pairing: Codable, Equatable, Sendable {
        let deviceID: String
        let code: String
        let createdAtMS: Int64

        enum CodingKeys: String, CodingKey {
            case code
            case deviceID = "device_id"
            case createdAtMS = "created_at_ms"
        }
    }

    struct PairingRequest: Codable, Equatable, Sendable, Identifiable {
        let connectionID: Int64?
        let deviceID: String
        let code: String
        let createdAtMS: Int64
        let expiresAtMS: Int64?
        let failures: Int?
        let vendor: String?
        let name: String?
        let model: String?

        var id: String { "\(connectionID ?? 0)-\(deviceID)" }

        enum CodingKeys: String, CodingKey {
            case code, failures, vendor, name, model
            case connectionID = "connection_id"
            case deviceID = "device_id"
            case createdAtMS = "created_at_ms"
            case expiresAtMS = "expires_at_ms"
        }
    }

    let type: String
    let sequence: Int
    let agent: Agent
    let permissions: Permissions
    let audio: Audio
    let codex: Codex
    let devices: [Device]
    let pairedDevices: [PairedDevice]
    let pairing: Pairing?
    let pairings: [PairingRequest]

        enum CodingKeys: String, CodingKey {
        case type = "t"
        case sequence = "seq"
        case agent, permissions, audio, codex, devices, pairing
            case pairedDevices = "paired_devices"
            case pairings
        }

    init(
        type: String,
        sequence: Int,
        agent: Agent,
        permissions: Permissions,
        audio: Audio,
        codex: Codex,
        devices: [Device],
        pairedDevices: [PairedDevice],
        pairing: Pairing?,
        pairings: [PairingRequest]
    ) {
        self.type = type
        self.sequence = sequence
        self.agent = agent
        self.permissions = permissions
        self.audio = audio
        self.codex = codex
        self.devices = devices
        self.pairedDevices = pairedDevices
        self.pairing = pairing
        self.pairings = pairings
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        type = try container.decode(String.self, forKey: .type)
        sequence = try container.decode(Int.self, forKey: .sequence)
        agent = try container.decode(Agent.self, forKey: .agent)
        permissions = try container.decode(Permissions.self, forKey: .permissions)
        audio = try container.decode(Audio.self, forKey: .audio)
        codex = try container.decode(Codex.self, forKey: .codex)
        devices = try container.decode([Device].self, forKey: .devices)
        pairedDevices = try container.decode([PairedDevice].self, forKey: .pairedDevices)
        pairing = try container.decodeIfPresent(Pairing.self, forKey: .pairing)
        pairings = try container.decodeIfPresent([PairingRequest].self, forKey: .pairings) ?? []
    }
}

extension BridgeSnapshot {
    var diagnosticsSnapshot: BridgeSnapshot {
        BridgeSnapshot(
            type: type,
            sequence: sequence,
            agent: agent,
            permissions: permissions,
            audio: audio,
            codex: codex,
            devices: devices,
            pairedDevices: pairedDevices,
            pairing: nil,
            pairings: []
        )
    }

    static let empty = BridgeSnapshot(
        type: "snapshot",
        sequence: 0,
        agent: Agent(
            state: "offline",
            version: GeneratedVersion.agent,
            build: GeneratedVersion.agentBuild,
            api: .init(
                major: GeneratedVersion.agentAPIMajor,
                minor: GeneratedVersion.agentAPIMinor
            ),
            pid: 0,
            startedAtMS: 0,
            bridgeID: "",
            macName: "",
            lanAddress: "",
            tcpPort: 7788,
            udpPort: 7789,
            hookPort: nil,
            issues: [],
            lastError: ""
        ),
        permissions: Permissions(accessibility: false),
        audio: Audio(
            enabled: true,
            running: false,
            device: nil,
            gain: 1,
            sampleRate: nil,
            received: 0,
            lost: 0,
            late: 0,
            resyncs: 0
        ),
            codex: Codex(
            enabled: true,
            connected: false,
            executable: nil,
            hooksListening: false,
            hooksInstalled: false,
                sessions: 0,
                quotaAvailable: false,
                quotaMode: "unknown",
                usage: .unavailable
        ),
        devices: [],
        pairedDevices: [],
        pairing: nil,
        pairings: []
    )
}
