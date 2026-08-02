import AppKit
import ServiceManagement
import SwiftUI

struct SettingsView: View {
    @ObservedObject var client: AgentClient
    @ObservedObject private var microphoneDriver = MicrophoneDriverManager.shared
    @State private var launchAtLogin = SMAppService.mainApp.status == .enabled
    @State private var loginError = ""
    @State private var gain = 1.0
    @State private var diagnosticMessage = ""
    @State private var automaticUpdates = true

    var body: some View {
        Form {
            Section("常规") {
                Toggle("登录后自动启动 Codex Deck", isOn: $launchAtLogin)
                    .onChange(of: launchAtLogin) { enabled in
                        updateLoginItem(enabled)
                    }
                LabeledContent("本机名称", value: client.snapshot.agent.macName)
                LabeledContent("局域网地址", value: client.snapshot.agent.lanAddress)
                if !loginError.isEmpty {
                    Text(loginError)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }

            Section("权限") {
                LabeledContent("Accessibility") {
                    HStack {
                        Text(
                            client.snapshot.permissions.accessibility
                                ? L10n.text("已授权")
                                : L10n.text("需要授权")
                        )
                        Button("打开系统设置…") {
                            SystemSettings.openAccessibility()
                        }
                    }
                }
                Text("请在列表中允许 Codex Deck；该权限只用于把设备按键发送到 Mac。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("音频") {
                HStack {
                    Text("软件增益")
                    Slider(value: $gain, in: 0.1...20, step: 0.1) { editing in
                        if !editing {
                            UserDefaults.standard.set(gain, forKey: "audioGain")
                            client.setGain(gain)
                        }
                    }
                    Text(gain.formatted(.number.precision(.fractionLength(1))))
                        .monospacedDigit()
                        .frame(width: 34, alignment: .trailing)
                }
                LabeledContent(
                    "输出设备",
                    value: client.snapshot.audio.device ?? L10n.text("不可用")
                )
                LabeledContent("CardBridge 麦克风") {
                    HStack {
                        Text(
                            microphoneDriver.isInstalled
                                ? L10n.text("已安装 · USB 兼容模式")
                                : L10n.text("未安装")
                        )
                        Button(
                            microphoneDriver.isInstalled
                                ? L10n.text("移除")
                                : L10n.text("安装…")
                        ) {
                            Task {
                                let changed = microphoneDriver.isInstalled
                                    ? await microphoneDriver.uninstall()
                                    : await microphoneDriver.install()
                                if changed { client.restartAgent() }
                            }
                        }
                        .disabled(microphoneDriver.isBusy)
                    }
                }
                if microphoneDriver.isBusy {
                    ProgressView()
                        .controlSize(.small)
                }
                if !microphoneDriver.message.isEmpty {
                    Text(microphoneDriver.message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Text("首次安装需要管理员授权。USB 兼容模式只改变 Core Audio 的设备声明，不代表真实 USB 硬件。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Codex") {
                LabeledContent("App Server") {
                    Text(client.snapshot.codex.connected ? L10n.text("已连接") : L10n.text("未连接"))
                }
                LabeledContent("Token 统计") {
                    if let usage = client.snapshot.codex.usage, usage.available {
                        Text(L10n.format("%@ 个会话", String(usage.sessions.count)))
                    } else {
                        Text(L10n.text("不可用/未知"))
                            .foregroundStyle(.secondary)
                    }
                }
                if let usage = client.snapshot.codex.usage, usage.available,
                   let latest = usage.sessions.first {
                    LabeledContent("累计总量") {
                        Text(latest.total.total.formatted(.number))
                            .monospacedDigit()
                    }
                    LabeledContent("输入") {
                        Text(latest.total.input.formatted(.number))
                            .monospacedDigit()
                    }
                    LabeledContent("缓存输入") {
                        Text(latest.total.cachedInput.formatted(.number))
                            .monospacedDigit()
                    }
                    LabeledContent("输出") {
                        Text(latest.total.output.formatted(.number))
                            .monospacedDigit()
                    }
                    LabeledContent("推理输出") {
                        Text(latest.total.reasoningOutput.formatted(.number))
                            .monospacedDigit()
                    }
                    LabeledContent("最近速率") {
                        Text("\(latest.tokensPerSecond.formatted(.number.precision(.fractionLength(1)))) tok/s")
                            .monospacedDigit()
                    }
                }
                LabeledContent("任务 Hooks") {
                    HStack {
                        Text(
                            client.snapshot.codex.hooksInstalled
                                ? L10n.text("已安装")
                                : L10n.text("未安装")
                        )
                        Button(
                            client.snapshot.codex.hooksInstalled
                                ? L10n.text("移除")
                                : L10n.text("安装")
                        ) {
                            if client.snapshot.codex.hooksInstalled {
                                client.uninstallHooks()
                            } else {
                                client.installHooks()
                            }
                        }
                    }
                }
                Text("安装后请在 Codex 中检查并信任 CardBridge Hook 路径；不安装也不影响键盘和音频桥接。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("版本") {
                LabeledContent("Codex Deck App", value: "\(GeneratedVersion.app) (\(GeneratedVersion.appBuild))")
                LabeledContent("Bridge Agent", value: "\(client.snapshot.agent.version) (\(client.snapshot.agent.build))")
                if client.snapshot.devices.isEmpty {
                    Text("没有在线设备")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(client.snapshot.devices) { device in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(device.name ?? device.model)
                                .font(.subheadline.weight(.medium))
                            Text(
                                "\(device.firmware) (\(device.firmwareBuild)) · "
                                    + "\(device.protocol.major).\(device.protocol.minor)"
                            )
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                    }
                }
                Toggle("自动检查更新", isOn: $automaticUpdates)
                    .onChange(of: automaticUpdates) { enabled in
                        UpdaterController.shared.setAutomaticallyChecksForUpdates(enabled)
                    }
                Button("立即检查更新…") {
                    UpdaterController.shared.checkForUpdates()
                }
            }

            Section("设备") {
                if client.snapshot.pairedDevices.isEmpty {
                    Text("没有已配对设备")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(client.snapshot.pairedDevices) { device in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(device.name)
                                Text(device.id)
                                    .font(.caption.monospaced())
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(
                                client.snapshot.devices.contains(where: { $0.id == device.id })
                                    ? L10n.text("在线")
                                    : L10n.text("离线")
                            )
                            .font(.caption)
                            .foregroundStyle(
                                client.snapshot.devices.contains(where: { $0.id == device.id })
                                    ? .green
                                    : .secondary
                            )
                            Button("取消配对", role: .destructive) {
                                client.unpair(deviceID: device.id)
                            }
                        }
                    }
                }
            }

            Section("诊断") {
                Button("导出脱敏诊断包…") {
                    diagnosticMessage = DiagnosticExporter.export(snapshot: client.snapshot)
                }
                if !diagnosticMessage.isEmpty {
                    Text(diagnosticMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(width: 560, height: 680)
        .onAppear {
            gain = client.snapshot.audio.gain
            automaticUpdates = UpdaterController.shared.automaticallyChecksForUpdates
        }
        .onChange(of: client.snapshot.audio.gain) { newValue in
            gain = newValue
        }
    }

    private func updateLoginItem(_ enabled: Bool) {
        UserDefaults.standard.set(true, forKey: LoginItemManager.configuredKey)
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
            loginError = ""
        } catch {
            loginError = error.localizedDescription
            launchAtLogin = SMAppService.mainApp.status == .enabled
        }
    }
}

enum SystemSettings {
    static func openAccessibility() {
        AccessibilityPermission.requestIfNeeded()
        guard let url = URL(
            string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        ) else { return }
        NSWorkspace.shared.open(url)
    }
}
