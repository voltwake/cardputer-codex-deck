import AppKit
import XCTest
@testable import CardBridgeApp

final class BridgeSnapshotTests: XCTestCase {
    func testEveryMenuBarStatusSymbolExists() {
        for symbol in MenuBarStatusSymbols.all {
            XCTAssertNotNil(
                NSImage(systemSymbolName: symbol, accessibilityDescription: nil),
                "Missing menu bar SF Symbol: \(symbol)"
            )
        }
    }

    func testAgentHandshakeRequiresExactBundledBuild() throws {
        let matching = AgentHello(
            type: "hello_ok",
            agent: .init(version: GeneratedVersion.agent, build: GeneratedVersion.agentBuild),
            api: .init(major: GeneratedVersion.agentAPIMajor, minor: GeneratedVersion.agentAPIMinor)
        )
        XCTAssertNil(matching.compatibilityError)

        let stale = AgentHello(
            type: "hello_ok",
            agent: .init(version: GeneratedVersion.agent, build: GeneratedVersion.agentBuild + 1),
            api: matching.api
        )
        XCTAssertNotNil(stale.compatibilityError)
    }

    func testDiagnosticsRedactTokensPairCodesAndHomePath() {
        let token = String(repeating: "ab", count: 32)
        let input = "/Users/example/config token \(token) pairing code for m5: 483291"
        let output = DiagnosticExporter.redact(input, home: "/Users/example")
        XCTAssertFalse(output.contains(token))
        XCTAssertFalse(output.contains("483291"))
        XCTAssertFalse(output.contains("/Users/example"))
        XCTAssertTrue(output.contains("<redacted-token>"))
        XCTAssertTrue(output.contains("<redacted-code>"))
    }

    func testDecodesLiveAgentShapeAndRetainsNoTokenField() throws {
        let json = #"""
        {
          "t":"snapshot",
          "seq":7,
          "agent":{"state":"connected","version":"0.2.0","build":1,"api":{"major":1,"minor":0},"pid":42,"started_at_ms":100,"bridge_id":"bridge","mac_name":"Mac","lan_address":"192.168.1.2","tcp_port":7788,"udp_port":7789,"hook_port":7790,"issues":[],"last_error":""},
          "permissions":{"accessibility":true},
          "audio":{"enabled":true,"running":true,"device":"BlackHole 2ch","gain":8.0,"sample_rate":48000,"received":10,"lost":0,"late":0,"resyncs":0},
          "codex":{"enabled":true,"connected":true,"executable":"/usr/bin/codex","hooks_listening":true,"hooks_installed":true,"sessions":3,"quota_available":true},
          "devices":[{"id":"m5","ip":"192.168.1.3","model":"cardputer-adv","firmware":"0.2.0","protocol":{"major":2,"minor":0},"compatibility":"ok","audio_packets":9}],
          "paired_devices":[{"id":"m5","name":"Cardputer","paired_at":99}],
          "pairing":null
        }
        """#

        let snapshot = try JSONDecoder().decode(BridgeSnapshot.self, from: Data(json.utf8))
        XCTAssertEqual(snapshot.agent.state, "connected")
        XCTAssertEqual(snapshot.devices.first?.firmwareBuild, "unknown")
        XCTAssertEqual(snapshot.devices.first?.protocol.major, 2)
        XCTAssertEqual(snapshot.devices.first?.capabilities, [])
        XCTAssertEqual(snapshot.devices.first?.lastSeenMS, 0)
        XCTAssertTrue(snapshot.permissions.accessibility)
        XCTAssertFalse(String(data: try JSONEncoder().encode(snapshot), encoding: .utf8)!.contains("\"token\""))
    }

    func testDecodesMultiDeviceUsageAndConcurrentPairings() throws {
        let json = #"""
        {
          "t":"snapshot",
          "seq":8,
          "agent":{"state":"connected","version":"1.1.0","build":9,"api":{"major":1,"minor":1},"pid":42,"started_at_ms":100,"bridge_id":"bridge","mac_name":"Mac","lan_address":"192.168.1.2","tcp_port":7788,"udp_port":7789,"hook_port":7790,"issues":[],"last_error":""},
          "permissions":{"accessibility":true},
          "audio":{"enabled":true,"running":true,"device":"CardBridge Microphone Feed","gain":8.0,"sample_rate":48000,"received":10,"lost":0,"late":0,"resyncs":0,"lease_owner_id":"waveshare-a"},
          "codex":{"enabled":true,"connected":true,"executable":null,"hooks_listening":true,"hooks_installed":true,"sessions":1,"quota_available":false,"quota_mode":"unknown","usage":{"available":true,"source":"codex_app_server","updated_at_ms":1000,"sessions":[{"id":"thread-a","turn_id":"turn-a","total":{"total":20,"input":10,"cached_input":2,"output":8,"reasoning_output":0},"last":{"total":20,"input":10,"cached_input":2,"output":8,"reasoning_output":0},"delta":{"total":20,"input":10,"cached_input":2,"output":8,"reasoning_output":0},"window_ms":0,"tokens_per_second":0,"model_context_window":1000}]}},
          "devices":[
            {"id":"waveshare-a","name":"Desk Orb","vendor":"waveshare","ip":"192.168.1.4","model":"esp32-s3-touch-amoled-1.75c","firmware":"0.3.0","firmware_build":"1","protocol":{"major":2,"minor":1},"compatibility":"ok","capabilities":["sync.subscribe.v1"],"connected_at_ms":101,"last_seen_ms":102,"audio_packets":9,"audio_lease":"owner"},
            {"id":"waveshare-b","name":"Desk Orb 2","vendor":"waveshare","ip":"192.168.1.5","model":"esp32-s3-touch-amoled-1.75c","firmware":"0.3.0","firmware_build":"1","protocol":{"major":2,"minor":1},"compatibility":"ok","capabilities":[],"connected_at_ms":103,"last_seen_ms":104,"audio_packets":0,"audio_lease":"busy"}
          ],
          "paired_devices":[],
          "pairing":null,
          "pairings":[{"connection_id":11,"device_id":"waveshare-c","code":"123456","created_at_ms":100,"expires_at_ms":200,"failures":0,"vendor":"waveshare","name":"Desk Orb 3","model":"esp32"}]
        }
        """#

        let snapshot = try JSONDecoder().decode(BridgeSnapshot.self, from: Data(json.utf8))
        XCTAssertEqual(snapshot.devices.count, 2)
        XCTAssertEqual(snapshot.devices[0].name, "Desk Orb")
        XCTAssertEqual(snapshot.devices[0].audioLease, "owner")
        XCTAssertEqual(snapshot.codex.usage?.sessions.first?.delta.total, 20)
        XCTAssertEqual(snapshot.codex.usage?.sessions.first?.total.input, 10)
        XCTAssertEqual(snapshot.codex.usage?.sessions.first?.total.cachedInput, 2)
        XCTAssertEqual(snapshot.codex.usage?.sessions.first?.total.output, 8)
        XCTAssertEqual(snapshot.codex.usage?.sessions.first?.total.reasoningOutput, 0)
        XCTAssertEqual(snapshot.pairings.count, 1)
        XCTAssertEqual(snapshot.pairings[0].deviceID, "waveshare-c")
        XCTAssertFalse(String(data: try JSONEncoder().encode(snapshot), encoding: .utf8)!.contains("\"token\""))

        let report = String(
            decoding: try DiagnosticExporter.encodedReport(snapshot: snapshot),
            as: UTF8.self
        )
        XCTAssertFalse(report.contains("123456"))
        XCTAssertFalse(report.contains("\"code\""))
    }
}
