import Foundation
import UserNotifications

/// macOS notifications for things that need the user (automatic line switch, auto-pause, backend gone).
enum Notifier {
    private static let delegate = Presenter()
    private static var recent: [String: Date] = [:]
    /// Where outcomes are written (native.log), so "no notification appeared" can be diagnosed afterwards.
    static var log: ((String) -> Void)?

    private final class Presenter: NSObject, UNUserNotificationCenterDelegate {
        func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                    withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
            completionHandler([.banner, .list, .sound])
        }
    }

    static func describe(_ status: UNAuthorizationStatus) -> (text: String, ok: Bool) {
        switch status {
        case .authorized, .provisional, .ephemeral: return ("已允许", true)
        case .denied: return ("已被拒绝：请在 系统设置 → 通知 里找到 QQ 自动回复并允许", false)
        case .notDetermined: return ("还没有请求过权限：发送一条测试通知会弹出授权提示", false)
        @unknown default: return ("未知状态", false)
        }
    }

    /// The notification center only exists for a real app bundle (not for previews / tests run as a bare binary).
    private static var available: Bool { Bundle.main.bundleIdentifier != nil }

    static func status(_ done: @escaping (String, Bool) -> Void) {
        guard available else { done("只有作为应用运行时才能发通知", false); return }
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            let result = describe(settings.authorizationStatus)
            DispatchQueue.main.async { done(result.text, result.ok) }
        }
    }

    static func post(_ title: String, _ body: String, force: Bool = false) {
        let key = title + "\n" + body
        if !force, let last = recent[key], Date().timeIntervalSince(last) < 60 { return }       // the same message at most once a minute
        recent[key] = Date()
        guard available else { return }
        let center = UNUserNotificationCenter.current()
        center.delegate = delegate
        func send() {
            let content = UNMutableNotificationContent()
            content.title = title; content.body = body; content.sound = .default
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)) { error in
                log?("notify \"\(title)\": " + (error.map { "failed: \($0.localizedDescription)" } ?? "delivered to the system"))
            }
        }
        center.getNotificationSettings { settings in
            log?("notify \"\(title)\": permission " + describe(settings.authorizationStatus).text)
            switch settings.authorizationStatus {
            case .notDetermined:
                center.requestAuthorization(options: [.alert, .sound]) { granted, error in
                    log?("notify: permission request " + (granted ? "granted" : "not granted\(error.map { " (\($0.localizedDescription))" } ?? "")"))
                    if granted { send() }
                }
            case .authorized, .provisional, .ephemeral: send()
            default: break
            }
        }
    }
}
