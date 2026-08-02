import AppKit
import SwiftUI

final class CardBridgeAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        LoginItemManager.registerDefaultIfNeeded()
        // CardBridgeAgent is launched as a child of the main app, so macOS TCC
        // attributes its synthetic keyboard events to CardBridge (the
        // responsible process). The main app must therefore own the
        // Accessibility request even though the Agent posts the events.
        AccessibilityPermission.requestIfNeeded()
        UpdaterController.shared.start()
        Task { @MainActor in
            let defaults = UserDefaults.standard
            let driver = MicrophoneDriverManager.shared
            if !driver.isInstalled,
               !defaults.bool(forKey: "didOfferMicrophoneDriverInstall") {
                // Offer exactly once on first launch. Cancellation still lets
                // the bridge start, and the menu/settings button remains.
                defaults.set(true, forKey: "didOfferMicrophoneDriverInstall")
                _ = await driver.install()
            }
            AgentSupervisor.shared.start()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        AgentSupervisor.shared.stop()
    }
}

@main
struct CardBridgeMenuBarApp: App {
    @NSApplicationDelegateAdaptor(CardBridgeAppDelegate.self) private var appDelegate
    @StateObject private var client = AgentClient()

    var body: some Scene {
        MenuBarExtra {
            BridgeMenuView(client: client)
                .onAppear { client.start() }
        } label: {
            MenuBarStatusLabel(client: client)
                .onAppear { client.start() }
        }
        .menuBarExtraStyle(.window)

        Settings {
            SettingsView(client: client)
        }
    }
}

enum MenuBarStatusSymbols {
    static let ready = "rectangle.connected.to.line.below"
    static let connected = "link.circle.fill"
    static let connecting = "arrow.triangle.2.circlepath"
    static let warning = "exclamationmark.triangle"
    static let stopped = "rectangle.slash"

    static let all = [ready, connected, connecting, warning, stopped]
}

private struct MenuBarStatusLabel: View {
    @ObservedObject var client: AgentClient

    private var symbol: String {
        switch client.connectionState {
        case .connected:
            return client.snapshot.devices.isEmpty
                ? MenuBarStatusSymbols.ready
                : MenuBarStatusSymbols.connected
        case .connecting:
            return MenuBarStatusSymbols.connecting
        case .incompatible, .failed:
            return MenuBarStatusSymbols.warning
        case .stopped:
            return MenuBarStatusSymbols.stopped
        }
    }

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: symbol)
            Text("Codex Deck")
                .lineLimit(1)
        }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Codex Deck")
            .accessibilityValue(Text(accessibilityStatus))
    }

    private var accessibilityStatus: String {
        switch client.connectionState {
        case .connected:
            let count = client.snapshot.devices.count
            return count == 0
                ? L10n.text("桥接器已就绪")
                : L10n.format("%@ 台设备已连接", String(count))
        case .connecting:
            return L10n.text("正在连接桥接器…")
        case let .incompatible(message), let .failed(message):
            return message
        case .stopped:
            return L10n.text("桥接器未启动")
        }
    }
}
