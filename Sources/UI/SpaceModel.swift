import Foundation
import Combine

/// State and actions of the QQ Space auto-browser, shown in Settings → QQ 空间. `QQSpaceController` (which drives QQ)
/// fills it in and wires the closures.
final class SpaceViewModel: ObservableObject {
    @Published var status = "通过 QQ 左侧的空间入口复用登录状态"
    @Published private(set) var lines: [String] = []
    @Published var running = false
    @Published var busy = false
    var onOpen: () -> Void = {}
    var onRefresh: () -> Void = {}
    var onNext: () -> Void = {}
    var onToggle: () -> Void = {}

    func push(_ text: String) {
        let stamp = DateFormatter(); stamp.dateFormat = "HH:mm:ss"
        status = text
        lines = Array((lines + ["\(stamp.string(from: Date()))  \(text)"]).suffix(60))
    }
}
