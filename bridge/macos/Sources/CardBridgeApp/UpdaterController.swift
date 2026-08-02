import Sparkle

private final class UpdateLifecycleDelegate: NSObject, SPUUpdaterDelegate {
    func updaterWillRelaunchApplication(_ updater: SPUUpdater) {
        Task { @MainActor in
            AgentSupervisor.shared.stop()
        }
    }
}

@MainActor
final class UpdaterController {
    static let shared = UpdaterController()

    private let delegate: UpdateLifecycleDelegate
    private let controller: SPUStandardUpdaterController
    private var started = false

    private init() {
        let delegate = UpdateLifecycleDelegate()
        self.delegate = delegate
        controller = SPUStandardUpdaterController(
            startingUpdater: false,
            updaterDelegate: delegate,
            userDriverDelegate: nil
        )
    }

    var automaticallyChecksForUpdates: Bool {
        controller.updater.automaticallyChecksForUpdates
    }

    func start() {
        guard !started else { return }
        started = true
        controller.startUpdater()
    }

    func checkForUpdates() {
        controller.checkForUpdates(nil)
    }

    func setAutomaticallyChecksForUpdates(_ enabled: Bool) {
        controller.updater.automaticallyChecksForUpdates = enabled
    }
}
