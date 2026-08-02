import AppKit
import SwiftUI

struct BridgeMenuView: View {
    @ObservedObject var client: AgentClient
    @ObservedObject private var microphoneDriver = MicrophoneDriverManager.shared

    private var connectedDevices: [BridgeSnapshot.Device] {
        client.snapshot.devices
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header

            if !client.snapshot.pairings.isEmpty {
                ForEach(client.snapshot.pairings) { pairing in
                    pairingCard(pairing)
                }
            } else if let pairing = client.snapshot.pairing {
                legacyPairingCard(pairing)
            }

            if connectedDevices.isEmpty {
                emptyDeviceCard
            } else {
                ForEach(connectedDevices) { device in
                    deviceCard(device)
                }
            }

            Divider()
            healthRows
            if !microphoneDriver.isInstalled {
                Button {
                    Task {
                        if await microphoneDriver.install() {
                            client.restartAgent()
                        }
                    }
                } label: {
                    Label("启用 CardBridge 麦克风…", systemImage: "mic.badge.plus")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(microphoneDriver.isBusy)
            }
            if !client.snapshot.permissions.accessibility {
                Button {
                    SystemSettings.openAccessibility()
                } label: {
                    Label("授权键盘控制…", systemImage: "hand.raised")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }
            Divider()
            footer
        }
        .padding(16)
        .frame(width: 360)
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            ZStack {
                Circle()
                    .fill(statusColor.opacity(0.14))
                Image(systemName: statusSymbol)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(statusColor)
            }
            .frame(width: 42, height: 42)

            VStack(alignment: .leading, spacing: 2) {
                Text("Codex Deck")
                    .font(.headline)
                Text(statusTitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text("v\(GeneratedVersion.app)")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.tertiary)
        }
    }

    private func pairingCard(_ pairing: BridgeSnapshot.Pairing) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("M5 请求配对", systemImage: "link.badge.plus")
                .font(.subheadline.weight(.semibold))
            Text(pairing.code)
                .font(.system(size: 30, weight: .bold, design: .monospaced))
                .textSelection(.enabled)
            Text("在 Cardputer 上输入这个六位码")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.blue.opacity(0.09), in: RoundedRectangle(cornerRadius: 12))
    }

    private func legacyPairingCard(_ pairing: BridgeSnapshot.Pairing) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(L10n.text("设备请求配对"), systemImage: "link.badge.plus")
                .font(.subheadline.weight(.semibold))
            Text(pairing.code)
                .font(.system(size: 30, weight: .bold, design: .monospaced))
                .textSelection(.enabled)
            Text(L10n.text("在设备上输入这个六位码"))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.blue.opacity(0.09), in: RoundedRectangle(cornerRadius: 12))
    }

    private func pairingCard(_ pairing: BridgeSnapshot.PairingRequest) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label(
                    pairing.name ?? pairing.model ?? pairing.deviceID,
                    systemImage: "link.badge.plus"
                )
                .font(.subheadline.weight(.semibold))
                Spacer()
                if let vendor = pairing.vendor, !vendor.isEmpty {
                    Text(vendor).font(.caption).foregroundStyle(.secondary)
                }
            }
            Text(pairing.code)
                .font(.system(size: 26, weight: .bold, design: .monospaced))
                .textSelection(.enabled)
            Text(L10n.text("在设备上输入这个六位码"))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.blue.opacity(0.09), in: RoundedRectangle(cornerRadius: 12))
    }

    private func deviceCard(_ device: BridgeSnapshot.Device) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label(
                    device.name ?? device.model,
                    systemImage: "rectangle.and.hand.point.up.left"
                )
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Text("已连接")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.green)
            }
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 5) {
                GridRow {
                    Text("地址").foregroundStyle(.secondary)
                    Text(device.ip).textSelection(.enabled)
                }
                GridRow {
                    Text("固件").foregroundStyle(.secondary)
                    Text("\(device.firmware) (\(device.firmwareBuild))")
                }
                GridRow {
                    Text("协议").foregroundStyle(.secondary)
                    Text("\(device.protocol.major).\(device.protocol.minor) · \(device.compatibility)")
                }
                GridRow {
                    Text("厂商/型号").foregroundStyle(.secondary)
                    Text("\(device.vendor ?? "未知") · \(device.model)")
                }
                GridRow {
                    Text("能力").foregroundStyle(.secondary)
                    Text(
                        device.capabilities.isEmpty
                            ? L10n.text("未声明")
                            : device.capabilities.joined(separator: ", ")
                    )
                    .lineLimit(3)
                }
                GridRow {
                    Text("最后活动").foregroundStyle(.secondary)
                    if device.lastSeenMS > 0 {
                        Text(
                            Date(timeIntervalSince1970: Double(device.lastSeenMS) / 1000),
                            style: .relative
                        )
                    } else {
                        Text(L10n.text("未知"))
                    }
                }
                GridRow {
                    Text("音频租约").foregroundStyle(.secondary)
                    Text(device.audioLease ?? L10n.text("未知"))
                }
            }
            .font(.caption)
        }
        .padding(12)
        .background(.primary.opacity(0.055), in: RoundedRectangle(cornerRadius: 12))
    }

    private var emptyDeviceCard: some View {
        HStack(spacing: 10) {
            Image(systemName: "wifi")
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(L10n.text("等待设备连接"))
                    .font(.subheadline.weight(.medium))
                Text(L10n.text("确保 Mac 和设备位于同一网络"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 12))
    }

    private var healthRows: some View {
        VStack(spacing: 8) {
            HealthRow(
                title: L10n.text("本地网络"),
                detail: client.snapshot.agent.issues.contains("network")
                    ? L10n.text("本地网络不可用")
                    : client.snapshot.agent.lanAddress,
                symbol: "network",
                healthy: !client.snapshot.agent.issues.contains("network")
            )
            HealthRow(
                title: L10n.text("键盘控制"),
                detail: client.snapshot.permissions.accessibility
                    ? L10n.text("Accessibility 已授权")
                    : L10n.text("需要授权"),
                symbol: "keyboard",
                healthy: client.snapshot.permissions.accessibility
            )
            HealthRow(
                title: L10n.text("麦克风桥接"),
                detail: client.snapshot.audio.device ?? L10n.text("CardBridge 麦克风不可用"),
                symbol: "waveform",
                healthy: client.snapshot.audio.running
            )
            HealthRow(
                title: L10n.text("Codex 状态"),
                detail: client.snapshot.codex.connected
                    ? L10n.format("%@ 个会话", String(client.snapshot.codex.sessions))
                    : L10n.text("未连接"),
                symbol: "terminal",
                healthy: client.snapshot.codex.connected
            )
            let usage = client.snapshot.codex.usage
            HealthRow(
                title: L10n.text("Token 统计"),
                detail: usage?.available == true
                    ? L10n.format("%@ 个会话", String(usage?.sessions.count ?? 0))
                    : L10n.text("不可用/未知"),
                symbol: "number",
                healthy: usage?.available == true
            )
        }
    }

    private var footer: some View {
        HStack {
            Button {
                if client.connectionState == .stopped {
                    client.startBridge()
                } else {
                    client.stopBridge()
                }
            } label: {
                Label(
                    client.connectionState == .stopped
                        ? L10n.text("启动桥接")
                        : L10n.text("停止桥接"),
                    systemImage: client.connectionState == .stopped ? "play.fill" : "stop.fill"
                )
            }
            .buttonStyle(.borderless)

            if client.connectionState != .stopped {
                Button {
                    client.restartAgent()
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .help("重启桥接")
                .accessibilityLabel("重启桥接")
            }

            Spacer()

            Button("设置…") {
                NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
            }
            .buttonStyle(.borderless)

            Button("检查更新…") {
                UpdaterController.shared.checkForUpdates()
            }
            .buttonStyle(.borderless)

            Button("退出") {
                NSApp.terminate(nil)
            }
            .buttonStyle(.borderless)
        }
        .font(.caption)
    }

    private var statusTitle: String {
        switch client.connectionState {
        case .connected:
            if connectedDevices.count == 1 { return L10n.text("1 台设备已连接") }
            if !connectedDevices.isEmpty {
                return L10n.format("%@ 台设备已连接", String(connectedDevices.count))
            }
            return L10n.text("桥接器已就绪")
        case .connecting:
            return L10n.text("正在连接桥接器…")
        case let .incompatible(message), let .failed(message):
            return message
        case .stopped:
            return L10n.text("桥接器未启动")
        }
    }

    private var statusSymbol: String {
        switch client.connectionState {
        case .connected:
            return connectedDevices.isEmpty ? "checkmark" : "link"
        case .connecting:
            return "arrow.triangle.2.circlepath"
        case .incompatible, .failed:
            return "exclamationmark"
        case .stopped:
            return "pause"
        }
    }

    private var statusColor: Color {
        switch client.connectionState {
        case .connected:
            return connectedDevices.isEmpty ? .blue : .green
        case .connecting:
            return .orange
        case .incompatible, .failed:
            return .red
        case .stopped:
            return .secondary
        }
    }
}

private struct HealthRow: View {
    let title: String
    let detail: String
    let symbol: String
    let healthy: Bool

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: symbol)
                .frame(width: 18)
                .foregroundStyle(.secondary)
            Text(title)
                .font(.caption)
            Spacer()
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Image(systemName: healthy ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                .foregroundStyle(healthy ? .green : .orange)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(title))
        .accessibilityValue(Text(detail))
    }
}
