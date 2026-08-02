import Foundation
import ServiceManagement

@MainActor
enum LoginItemManager {
    static let configuredKey = "didConfigureLaunchAtLogin"

    static func registerDefaultIfNeeded() {
        let defaults = UserDefaults.standard
        guard
            !defaults.bool(forKey: configuredKey),
            Bundle.main.bundleURL.path.hasPrefix("/Applications/")
        else {
            return
        }
        do {
            if SMAppService.mainApp.status != .enabled {
                try SMAppService.mainApp.register()
            }
            defaults.set(true, forKey: configuredKey)
        } catch {
            // Settings keeps the current system state visible and allows retry.
        }
    }
}
