import ApplicationServices

enum AccessibilityPermission {
    @discardableResult
    static func requestIfNeeded() -> Bool {
        if AXIsProcessTrusted() {
            return true
        }
        let options = [
            kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true,
        ] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }
}
