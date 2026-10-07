import Foundation
import Combine
import AppKit

// MARK: - What the UI needs from the menu bar app

protocol BridgeControl: AnyObject {
    var baseURL: URL { get }
    var isPaused: Bool { get }
    var config: [String: Any] { get }
    func togglePaused()
    func setSuffix(_ on: Bool)
    func requestProactive()
    func setPetEnabled(_ on: Bool)
    func applyConfig(_ config: [String: Any], restart: Bool) -> String?
    func showLive()
    func showSettings()
    func showSpace()
    func openPermissions()
    func openConfigFile()
    func quitApp()
    /// 👍 "up" / 👎 "down" / nil (withdrawn) on a sent reply; saved to runtime/reply-feedback.json.
    func rateReply(_ turn: LiveSnapshot.Turn, rating: String?)
    /// Ask the backend to restore the style summary from before its last compression.
    func revertStyleCompression()
    /// Ask the backend to undo the last round of turning ratings into reply preferences.
    func revertFeedbackRound()
    /// Answer the openings offered after 主动发起话题: the number to post, or -1 to post none.
    func chooseTopic(_ index: Int)
}

// MARK: - runtime/live.json (written by live_feed.py)

struct LiveSnapshot: Decodable, Equatable {
    struct Engine: Decodable, Equatable {
        var state: String?
        var message: String?
        var paused: Bool?
        var backend: String?
        var provider: String?
        var model: String?
        var replyMode: String?
        var since: Double?
    }
    struct Stats: Decodable, Equatable { var replied = 0, silent = 0, failed = 0 }
    struct Message: Decodable, Equatable, Identifiable {
        var id: String
        var sender: String
        var text: String
        var image: Bool
    }
    struct Waiting: Decodable, Equatable, Identifiable {
        var group: String
        var title: String
        var since: Double
        var count: Int
        var messages: [Message]
        var id: String { group }
    }
    struct Decision: Decodable, Equatable {
        var shouldReply: Bool?
        var reason: String?
        var model: String?
        var reasoningEffort: String?
        var complexity: String?
        var seconds: Double?
    }
    struct Reply: Decodable, Equatable {
        var text: String?
        var reason: String?
        var model: String?
        var reasoningEffort: String?
        var seconds: Double?
    }
    struct Tokens: Decodable, Equatable {
        var input: Int?
        var output: Int?
        var seconds: Double?
    }
    struct TimelineItem: Decodable, Equatable, Identifiable {
        var t: Double
        var stage: String
        var text: String
        var id: String { "\(t)-\(stage)-\(text)" }
    }
    struct BrowserAction: Decodable, Equatable {
        var action: String?
        var url: String?
        var error: String?
    }
    struct Turn: Decodable, Equatable, Identifiable {
        var id: String
        var group: String
        var title: String
        var kind: String
        var started: Double
        var stage: String
        var outcome: String?
        var ended: Double?
        var messages: [Message]
        var messageCount: Int
        var decision: Decision?
        var reply: Reply?
        var thoughts: [String]
        var timeline: [TimelineItem]
        var tokens: Tokens?
        var error: String?
        var browser: [BrowserAction]?
        var isActive: Bool { outcome == nil }
    }
    struct Unvisited: Decodable, Equatable, Identifiable {
        var group: String
        var title: String
        var since: Double
        var count: Int
        var id: String { group }
    }
    struct Activity: Decodable, Equatable, Identifiable {
        var t: Double
        var text: String
        var id: String { "\(t)-\(text)" }
    }
    /// Openings written after the owner pressed 主动发起话题, waiting for him to pick one (or none).
    struct Preview: Decodable, Equatable {
        struct Option: Decodable, Equatable {
            var text: String
            var shape: String
            var reason: String
            var link: Bool
        }
        var turn: String
        var group: String
        var title: String
        var since: Double
        var expires: Double
        var chosen: Int?
        var options: [Option]
    }

    var updatedAt: Double
    var sessionStarted: Double
    var engine: Engine
    var stats: Stats
    var waiting: [Waiting]
    var unvisited: [Unvisited]?
    var turns: [Turn]
    var activity: [Activity]
    var preview: Preview? = nil

    static let empty = LiveSnapshot(updatedAt: 0, sessionStarted: 0, engine: Engine(), stats: Stats(), waiting: [], unvisited: nil, turns: [], activity: [])
    /// The turn in progress; the one waiting for the owner's pick is shown as the preview card instead.
    var current: Turn? { turns.first(where: { $0.isActive && $0.id != preview?.turn }) }
    var finished: [Turn] { turns.filter { !$0.isActive } }
}

struct PreferencesInfo: Equatable {
    var text = ""
    var rounds = 0
    var summarized: [String: String] = [:]
    var versions = 0
    var updatedAt: String?
}

struct StyleInfo: Equatable {
    var chars = 0
    var text = ""
    var compressedAt: String?
    var versions = 0
}

struct ChatEntry: Equatable, Hashable {
    var title: String
    var kind: String          // group / private / unknown
}

struct Counters: Equatable {
    var modelCalls = 0, verifiedReplies = 0, inputTokens = 0, outputTokens = 0
    var lastInferenceSeconds: Double?
    var model = ""
    var backend = ""
    var archived = 0
    var configWarnings: [String] = []
    var configErrors: [String] = []
}

/// One word describing what the bot is doing right now.
enum Phase: Equatable {
    case offline, paused, starting, listening, waiting, thinking, sending, switching, attention

    var label: String {
        switch self {
        case .offline: return "后台无响应"
        case .paused: return "已暂停"
        case .starting: return "正在建立基线"
        case .listening: return "监听中"
        case .waiting: return "等待中"
        case .thinking: return "思考中"
        case .sending: return "发送中"
        case .switching: return "切换模型中"
        case .attention: return "需要注意"
        }
    }
    var menuTitle: String {
        switch self {
        case .paused, .offline: return "暂停"
        case .attention: return "注意"
        case .thinking: return "思考中"
        case .sending: return "发送中"
        default: return "自动"
        }
    }
    var isBusy: Bool { self == .thinking || self == .sending || self == .starting || self == .switching }
}

// MARK: - Model shared by popover, live window and settings

final class AppModel: ObservableObject {
    @Published private(set) var live = LiveSnapshot.empty
    @Published private(set) var counters = Counters()
    @Published private(set) var heartbeat: Date?
    @Published private(set) var paused = true
    @Published private(set) var replyMode = "regular"
    @Published private(set) var backend = "ai"
    @Published private(set) var provider = "custom"
    @Published private(set) var suffix = true
    @Published private(set) var providerModels: [String: String] = [:]
    @Published private(set) var configuredProviders: Set<String> = []
    @Published private(set) var pet = PetSettings()
    /// Chats the bot has seen (from runtime/status.json), for the mute list in settings.
    @Published private(set) var chats: [ChatEntry] = []
    /// runtime/daily-stats.json: day (yyyy-MM-dd) -> counter -> value, for the 今日简报 panel.
    @Published private(set) var daily: [String: [String: Double]] = [:]
    private var dailyStamp: Date?
    /// turn id -> "up" / "down" from runtime/reply-feedback.json
    @Published private(set) var ratings: [String: String] = [:]
    /// Main group's style summary: length, when it was last compressed, how many older versions are kept.
    @Published private(set) var styleInfo = StyleInfo()
    private var styleStamp: Date?
    /// runtime/owner-preferences.json: the preferences text, rounds so far, which ratings each covered.
    @Published private(set) var preferences = PreferencesInfo()
    private var preferencesStamp: Date?
    /// Ratings not summarised yet.
    /// How many new ratings make one summarising round (config `feedback_summary_every`, default 20).
    var feedbackEvery: Int { (control?.config["feedback_summary_every"] as? NSNumber)?.intValue ?? 20 }
    var pendingRatings: Int { ratings.filter { preferences.summarized[$0.key] != $0.value }.count }
    private var ratingStamp: Date?
    @Published var statusText = ""
    /// Which page the settings window shows (so other parts of the app can open it on a given page).
    @Published var settingsSection: SettingsSection = .general
    let space = SpaceViewModel()
    let people = PeopleStore()
    /// The notes store, loaded from this project's runtime folder on first use.
    func peopleStore() -> PeopleStore {
        if let base = control?.baseURL { people.load(base: base) }
        return people
    }
    /// Members who spoke in the turns shown in the status window (newest first), for quick-adding notes.
    var recentSpeakers: [String] {
        var seen = Set<String>(), names: [String] = []
        for turn in live.turns { for message in turn.messages.reversed() where !message.sender.isEmpty && seen.insert(message.sender).inserted { names.append(message.sender) } }
        for batch in live.waiting { for message in batch.messages where !message.sender.isEmpty && seen.insert(message.sender).inserted { names.append(message.sender) } }
        return Array(names.prefix(20))
    }
    /// "system" / "light" / "dark": a per-Mac interface preference, kept in UserDefaults (not config.json).
    @Published var appearance = UserDefaults.standard.string(forKey: "QQBridgeAppearance") ?? "system" {
        didSet { UserDefaults.standard.set(appearance, forKey: "QQBridgeAppearance"); onAppearanceChange?(appearance) }
    }
    static let appearanceNames = ["system": "跟随系统", "light": "浅色", "dark": "深色"]
    static func nsAppearance(_ mode: String) -> NSAppearance? {
        mode == "light" ? NSAppearance(named: .aqua) : mode == "dark" ? NSAppearance(named: .darkAqua) : nil
    }
    var onAppearanceChange: ((String) -> Void)?
    @Published var pinned = true { didSet { onPinChange?(pinned) } }
    @Published var compactLive = false

    weak var control: BridgeControl?
    var onPhaseChange: ((Phase) -> Void)?
    var onPinChange: ((Bool) -> Void)?
    private var timer: Timer?
    private var liveStamp: Date?
    private var reading = false
    private let io = DispatchQueue(label: "qqbridge.model.io", qos: .utility)
    private(set) var phase: Phase = .paused

    init(control: BridgeControl?) { self.control = control }
    deinit { timer?.invalidate() }

    func start() {
        guard timer == nil else { return }
        syncSettings()
        reload()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.reload() }
    }

    /// Copy menu-bar-owned settings (mode, backend, provider…) so the views stay in step with the menu.
    func syncSettings() {
        guard let control else { return }
        let config = control.config
        paused = control.isPaused
        replyMode = "regular"
        backend = "ai"
        provider = "custom"
        suffix = (config["ai"] as? [String:Any])?["suffix_enabled"] as? Bool ?? true
        let petConfig = config["pet"] as? [String: Any] ?? [:]
        let petNow = PetSettings(enabled: petConfig["enabled"] as? Bool ?? true,
                                 scale: max(1, min(12, (petConfig["scale"] as? NSNumber)?.intValue ?? 4)),
                                 wander: petConfig["wander"] as? Bool ?? true, bubble: petConfig["bubble"] as? Bool ?? true)
        if petNow != pet { pet = petNow }
        let ai = config["ai"] as? [String: Any] ?? [:]
        providerModels = ["custom": ai["model"] as? String ?? ""]
        configuredProviders = Self.configured(ai) ? ["custom"] : []
        updatePhase()
    }

    static func configured(_ api: [String: Any]) -> Bool {
        let required = ["base_url", "model", "api_key"]
        return required.allSatisfy { !(api[$0] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    func reload() {
        guard let base = control?.baseURL, !reading else { syncSettings(); return }
        reading = true
        let known = liveStamp
        let knownDaily = self.dailyStamp
        let knownRating = self.ratingStamp
        let knownStyle = self.styleStamp
        let knownPreferences = self.preferencesStamp
        let mainGroup = (control?.config["reply_style_group"] as? String) ?? (control?.config["groups"] as? [String])?.first ?? ""
        io.async { [weak self] in
            let manager = FileManager.default
            let livePath = base.appendingPathComponent("runtime/live.json")
            let statusPath = base.appendingPathComponent("runtime/status.json")
            let stamp = (try? manager.attributesOfItem(atPath: livePath.path)[.modificationDate]) as? Date
            let beat = (try? manager.attributesOfItem(atPath: statusPath.path)[.modificationDate]) as? Date
            var snapshot: LiveSnapshot?
            if let stamp, stamp != known, let data = try? Data(contentsOf: livePath) {
                let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
                snapshot = try? decoder.decode(LiveSnapshot.self, from: data)
            }
            var counters: Counters?
            var chats: [ChatEntry]?
            var daily: [String: [String: Double]]?
            var ratings: [String: String]?
            var styleInfo: StyleInfo?
            var preferences: PreferencesInfo?
            let preferencesPath = base.appendingPathComponent("runtime/owner-preferences.json")
            let preferencesStamp = (try? manager.attributesOfItem(atPath: preferencesPath.path)[.modificationDate]) as? Date
            if let preferencesStamp, preferencesStamp != knownPreferences, let data = try? Data(contentsOf: preferencesPath),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                preferences = PreferencesInfo(text: json["text"] as? String ?? "", rounds: json["rounds"] as? Int ?? 0,
                                              summarized: json["summarized"] as? [String: String] ?? [:],
                                              versions: (json["versions"] as? [Any])?.count ?? 0, updatedAt: json["updated_at"] as? String)
            }
            let stylePath = base.appendingPathComponent("runtime/style-profile.json")
            let styleStamp = (try? manager.attributesOfItem(atPath: stylePath.path)[.modificationDate]) as? Date
            if let styleStamp, styleStamp != knownStyle, let data = try? Data(contentsOf: stylePath),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let groups = json["groups"] as? [String: [String: Any]] {
                let entry = groups[mainGroup] ?? [:]
                let parts = ["historical_summary", "summary"].compactMap { (entry[$0] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
                styleInfo = StyleInfo(chars: parts.map(\.count).reduce(0, +) + (parts.count > 1 ? 2 : 0), text: parts.joined(separator: "\n"),
                                      compressedAt: entry["compressed_at"] as? String, versions: (entry["versions"] as? [Any])?.count ?? 0)
            }
            let ratingPath = base.appendingPathComponent("runtime/reply-feedback.json")
            let ratingStamp = (try? manager.attributesOfItem(atPath: ratingPath.path)[.modificationDate]) as? Date
            if let ratingStamp, ratingStamp != knownRating, let data = try? Data(contentsOf: ratingPath),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Any]] {
                ratings = json.compactMapValues { $0["rating"] as? String }
            }
            let dailyPath = base.appendingPathComponent("runtime/daily-stats.json")
            let dailyStamp = (try? manager.attributesOfItem(atPath: dailyPath.path)[.modificationDate]) as? Date
            if let dailyStamp, dailyStamp != knownDaily, let data = try? Data(contentsOf: dailyPath),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Any]] {
                daily = json.mapValues { $0.compactMapValues { ($0 as? NSNumber)?.doubleValue } }
            }
            if let data = try? Data(contentsOf: statusPath), let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                counters = Counters(modelCalls: json["model_calls"] as? Int ?? 0, verifiedReplies: json["verified_replies"] as? Int ?? 0,
                                    inputTokens: json["input_tokens"] as? Int ?? 0, outputTokens: json["output_tokens"] as? Int ?? 0,
                                    lastInferenceSeconds: json["last_inference_seconds"] as? Double, model: json["model"] as? String ?? "",
                                    backend: json["model_backend"] as? String ?? "", archived: json["archived_messages"] as? Int ?? 0,
                                    configWarnings: json["config_warnings"] as? [String] ?? [], configErrors: json["config_errors"] as? [String] ?? [])
                let details = json["conversations"] as? [String: [String: Any]] ?? [:]
                chats = details.map { key, detail in ChatEntry(title: (detail["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? key, kind: detail["kind"] as? String ?? "unknown") }
                    .sorted { $0.title.localizedCompare($1.title) == .orderedAscending }
            }
            DispatchQueue.main.async {
                guard let self else { return }
                self.reading = false
                if let snapshot, snapshot != self.live { self.live = snapshot }
                if stamp != nil { self.liveStamp = stamp }
                if let counters, counters != self.counters { self.counters = counters }
                if let chats, chats != self.chats { self.chats = chats }
                if let daily { self.daily = daily; self.dailyStamp = dailyStamp }
                if let ratings { self.ratings = ratings; self.ratingStamp = ratingStamp }
                if let styleInfo { self.styleInfo = styleInfo; self.styleStamp = styleStamp }
                if let preferences { self.preferences = preferences; self.preferencesStamp = preferencesStamp }
                self.heartbeat = beat
                self.syncSettings()
            }
        }
    }

    /// Pick an opening (or -1 for none). The card answers at once; the backend confirms through live.json.
    func chooseTopic(_ index: Int) {
        if index >= 0 { live.preview?.chosen = index } else { live.preview = nil }
        control?.chooseTopic(index)
    }

    /// Rate a sent reply (tap again to withdraw). The UI updates at once; the app writes the file.
    func rate(_ turn: Turn, _ rating: String) {
        let next: String? = ratings[turn.id] == rating ? nil : rating
        ratings[turn.id] = next
        control?.rateReply(turn, rating: next)
    }

    /// Replace the data wholesale (used by previews and tests).
    func apply(live: LiveSnapshot, counters: Counters = Counters(), heartbeat: Date? = Date()) {
        self.live = live; self.counters = counters; self.heartbeat = heartbeat; updatePhase()
    }
    func apply(paused: Bool, replyMode: String, backend: String, provider: String, suffix: Bool,
               models: [String: String] = [:], configured: Set<String> = []) {
        self.paused = paused; self.replyMode = replyMode; self.backend = backend; self.provider = provider
        self.suffix = suffix; providerModels = models; configuredProviders = configured; updatePhase()
    }

    /// Set while the backend refused to start because config.json is unusable.
    var configError: String? { live.engine.state == "config_error" ? (live.engine.message ?? "配置有误") : nil }

    var alive: Bool { heartbeat.map { Date().timeIntervalSince($0) < 15 } ?? false }

    private func updatePhase() {
        let next = computePhase()
        guard next != phase else { return }
        phase = next
        objectWillChange.send()
        onPhaseChange?(next)
    }

    private func computePhase() -> Phase {
        if paused { return .paused }
        if !alive { return .offline }
        switch live.engine.state ?? "" {
        case "starting": return .starting
        case "thinking": return .thinking
        case "reply_ready", "verifying": return .sending
        case "switch_pending": return .switching
        case "error", "model_error", "delivery_uncertain", "config_error": return .attention
        case "waiting": return .waiting
        default: return .listening
        }
    }

    var providerName: String {
        let ai=control?.config["ai"] as? [String:Any] ?? [:]
        return ai["name"] as? String ?? "自定义 AI"
    }

    var modelName: String {
        let name = providerModels["custom"] ?? ""
        return name.isEmpty ? "未配置 AI" : name
    }
}
