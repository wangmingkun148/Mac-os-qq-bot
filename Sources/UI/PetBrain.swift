import Foundation

enum PetPose: String { case idle, alert, think, talk, yawn, dizzy, sleep, walk }

/// What the pet should look like right now.
struct PetMood: Equatable {
    var pose: PetPose
    var bubble: String? = nil
}

/// Turns the bot's live state into a pet mood. Pure logic (no UI) so it can be tested.
///
/// - a new message / new unread chat -> `alert` (ears up, "!") for a moment
/// - model judging or generating     -> `think` ("?")
/// - reply being sent / just sent    -> `talk`, with the reply text in the bubble
/// - chose not to answer             -> `yawn`
/// - failure / backend problem       -> `dizzy`
/// - paused, or nothing for 5 minutes -> `sleep` (lying down; any new message wakes it)
final class PetBrain {
    private struct Reaction { var pose: PetPose; var until: Date; var bubble: String? }
    private var reaction: Reaction?
    private var seenTurns = Set<String>()
    private var handled = Set<String>()
    private var lastWaiting = 0, lastUnvisited = 0
    private var primed = false
    private var lastActivity = Date.distantPast
    /// Seconds without any message or work before the pet lies down to sleep.
    var idleSleepAfter: TimeInterval = 300

    static func clip(_ text: String, _ limit: Int = 70) -> String {
        let flat = text.split(whereSeparator: \.isNewline).joined(separator: " ").trimmingCharacters(in: .whitespaces)
        return flat.count <= limit ? flat : String(flat.prefix(limit - 1)) + "…"
    }

    func update(live: LiveSnapshot, phase: Phase, paused: Bool, configError: String?, now: Date = Date()) -> PetMood {
        if !primed { prime(live); primed = true; lastActivity = now }       // do not replay what happened before the pet appeared
        if paused { reaction = nil; lastActivity = now; return PetMood(pose: .sleep) }
        if let configError { return PetMood(pose: .dizzy, bubble: Self.clip(configError.replacingOccurrences(of: "配置有误，后台没有启动：", with: "配置有误："), 40)) }
        if phase == .offline { return PetMood(pose: .dizzy, bubble: "后台没有响应") }
        if phase == .attention && live.current == nil { return PetMood(pose: .dizzy, bubble: Self.clip(live.engine.message ?? "需要注意", 40)) }

        observe(live: live, now: now)
        if let current = reaction, current.until > now { lastActivity = now; return PetMood(pose: current.pose, bubble: current.bubble) }
        reaction = nil
        if let turn = live.current {
            lastActivity = now
            switch turn.stage {
            case "ready", "sending", "verifying":
                let text = turn.reply?.text.map { Self.clip($0) }
                return PetMood(pose: text == nil ? .think : .talk, bubble: text)
            default:
                return PetMood(pose: .think)
            }
        }
        if now.timeIntervalSince(lastActivity) >= idleSleepAfter { return PetMood(pose: .sleep) }
        return PetMood(pose: .idle)
    }

    private func prime(_ live: LiveSnapshot) {
        seenTurns = Set(live.turns.map(\.id))
        handled = Set(live.finished.map(\.id))
        lastWaiting = live.waiting.reduce(0) { $0 + $1.count }
        lastUnvisited = live.unvisited?.count ?? 0
    }

    private func observe(live: LiveSnapshot, now: Date) {
        // finished turns, oldest first, so the newest one wins
        for turn in live.finished.reversed() where !handled.contains(turn.id) {
            handled.insert(turn.id)
            seenTurns.insert(turn.id)
            guard now.timeIntervalSince1970 - (turn.ended ?? turn.started) < 30 else { continue }
            switch turn.outcome {
            case "replied": reaction = Reaction(pose: .talk, until: now + 5, bubble: turn.reply?.text.map { Self.clip($0) })
            case "silent": reaction = Reaction(pose: .yawn, until: now + 3, bubble: "不接话：" + Self.clip(turn.decision?.reason ?? "没什么好说的", 36))
            case "failed", "uncertain", "abandoned":
                reaction = Reaction(pose: .dizzy, until: now + 5, bubble: Self.clip(turn.error ?? turn.timeline.last?.text ?? "出错了", 44))
            default: break
            }
        }
        var startled = false
        if let turn = live.current, !seenTurns.contains(turn.id) { seenTurns.insert(turn.id); startled = true }
        let waiting = live.waiting.reduce(0) { $0 + $1.count }
        if waiting > lastWaiting { startled = true }
        lastWaiting = waiting
        let unvisited = live.unvisited?.count ?? 0
        if unvisited > lastUnvisited { startled = true }
        lastUnvisited = unvisited
        // a message arriving must not cut short a reply bubble or an error
        if startled { lastActivity = now }
        if startled, reaction == nil || reaction!.until <= now || reaction!.pose == .yawn {
            reaction = Reaction(pose: .alert, until: now + 1.4, bubble: nil)
        }
    }
}
