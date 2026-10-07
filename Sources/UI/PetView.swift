import SwiftUI
import Combine

// MARK: - Sprite rendering

enum PetSprites {
    /// pose -> frames -> rows of palette colours (nil = transparent)
    private static let grids: [String: [[[UInt32?]]]] = PetArt.frames.mapValues { frames in
        frames.map { rows in rows.map { row in row.map { PetArt.palette[$0] } } }
    }
    /// `key` is a pose name ("walk") or a transition frame ("in_alert").
    static func frame(key: String, _ index: Int) -> [[UInt32?]] {
        let frames = grids[key] ?? grids["idle"]!
        return frames[index % frames.count]
    }
    static func frameCount(key: String) -> Int { (grids[key] ?? grids["idle"]!).count }
    static func frame(_ pose: PetPose, _ index: Int) -> [[UInt32?]] { frame(key: pose.rawValue, index) }
    static func frameCount(_ pose: PetPose) -> Int { frameCount(key: pose.rawValue) }

    /// Getting up from sitting: head dips, body crouches, then straightens. Sitting down plays it backwards.
    static let rise = ["up_pre", "up_0", "up_1", "up_2"]

    /// The bridge frames played before `to` so poses do not snap: one frame for most, two when waking up, and the
    /// four-frame rise/sit-down around walking.
    static func transition(from: PetPose, to: PetPose) -> [String] {
        let wake = from == .sleep ? ["in_sleep", "in_idle"] : []
        if to == .walk { return from == .walk ? [] : wake + rise }
        if from == .walk { return rise.reversed() + (to == .idle ? [] : ["in_\(to.rawValue)"]) }
        if from == .sleep { return wake }
        return to == .idle ? ["in_idle"] : ["in_\(to.rawValue)"]
    }
    /// Reactions to a click, as one entry per animation step (0.15 s): (sprite key, frame, bubble). Every one starts with a bridge
    /// frame and ends with `in_idle`, so it settles back into the sitting pose without a jump.
    enum Reaction: CaseIterable {
        case wag, howl
        typealias Beat = (key: String, index: Int, bubble: String?)
        var script: [Beat] {
            func rep(_ key: String, _ index: Int, _ n: Int, _ bubble: String? = nil) -> [Beat] { Array(repeating: (key, index, bubble), count: n) }
            switch self {
            case .wag:
                return rep("in_wag", 0, 2) + (0..<14).map { ("wag", $0 % 4, $0 % 4 == 1 ? "♥" : nil) } + rep("in_idle", 0, 2)
            case .howl:
                return rep("in_howl", 0, 2) + (0..<14).map { ("howl", ($0 / 2) % 2, "嗷呜～") } + rep("in_howl", 0, 2) + rep("in_idle", 0, 2)
            }
        }
    }

    /// How many animation steps (0.15 s each) a bridge frame is shown: the rise frames are quick, the others linger a little.
    static func steps(_ key: String) -> Int { key.hasPrefix("up_") ? 1 : 2 }

    /// Which frame to show at animation step `tick` (one step = 0.15 s).
    static func frameIndex(_ pose: PetPose, tick: Int) -> Int {
        switch pose {
        case .idle:  return [0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 2, 0, 0, 1, 1][tick % 18]       // tail flicks, now and then a blink
        case .walk:  return tick % 4                         // four-frame diagonal gait, 0.15 s per frame
        case .talk:  return (tick / 2) % 2
        case .think: return (tick / 3) % 4
        case .alert: return (tick / 2) % 2
        case .yawn:  return [0, 1, 1, 1, 1, 0][tick % 6]
        case .dizzy: return (tick / 2) % 2
        case .sleep: return (tick / 6) % 2
        }
    }
}

struct SpriteRef: Equatable { var key = "idle"; var index = 0 }

struct PetSpriteView: View {
    let key: String
    let frame: Int
    let scale: CGFloat
    var body: some View {
        Canvas { context, _ in
            let grid = PetSprites.frame(key: key, frame)
            for (y, row) in grid.enumerated() {
                for (x, color) in row.enumerated() {
                    guard let color else { continue }
                    let rect = CGRect(x: CGFloat(x) * scale, y: CGFloat(y) * scale, width: scale, height: scale)
                    context.fill(Path(rect), with: .color(Color(red: Double((color >> 16) & 0xFF) / 255, green: Double((color >> 8) & 0xFF) / 255,
                                                                blue: Double(color & 0xFF) / 255)))
                }
            }
        }
        .frame(width: CGFloat(PetArt.width) * scale, height: CGFloat(PetArt.height) * scale)
    }
}

// MARK: - Speech bubble

struct PetBubble: View {
    let text: String
    var body: some View {
        VStack(spacing: 0) {
            Text(text)
                .font(CCFont.pixel(12)).foregroundColor(CC.text)
                .multilineTextAlignment(.leading).lineLimit(3).fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 11).padding(.vertical, 8)
                .frame(maxWidth: 210)
                .pixelPanel(CC.card, shadow: true)
            // stair-stepped tail pointing at the pet
            VStack(spacing: 0) {
                Rectangle().fill(CC.card).frame(width: 12, height: 3).overlay(HStack { Rectangle().fill(CC.border).frame(width: 1); Spacer(); Rectangle().fill(CC.border).frame(width: 1) })
                Rectangle().fill(CC.card).frame(width: 6, height: 3).overlay(HStack { Rectangle().fill(CC.border).frame(width: 1); Spacer(); Rectangle().fill(CC.border).frame(width: 1) })
                Rectangle().fill(CC.border).frame(width: 6, height: 1)
            }
            .offset(y: -1)
        }
    }
}

// MARK: - Model: mood + animation + wandering

struct PetSettings: Equatable {
    var enabled = true
    var scale = 4
    var wander = true
    var bubble = true
}

final class PetModel: ObservableObject {
    @Published private(set) var mood = PetMood(pose: .idle)
    @Published private(set) var tick = 0
    @Published private(set) var sprite = SpriteRef()
    @Published private(set) var walking = false
    @Published private(set) var facingLeft = false
    @Published private(set) var reactionBubble: String?
    @Published var settings = PetSettings()

    private let brain = PetBrain()
    private var lastPose: PetPose?
    private var transition: [String] = []
    private var transitionTicks = 0
    private weak var app: AppModel?
    private var timer: Timer?
    private var idleSince = Date()
    private var nextWalk = Date().addingTimeInterval(6)
    private var walkRemaining: CGFloat = 0
    private var pausedUntil = Date.distantPast
    private var reaction: [PetSprites.Reaction.Beat] = []
    private var pendingReaction: PetSprites.Reaction?
    private var lastReaction: PetSprites.Reaction?
    /// Moves the pet window by dx points; returns false if it hit the edge of the screen.
    var move: ((CGFloat) -> Bool)?
    /// Room to the left/right of the pet before it would leave the screen.
    var room: (() -> (left: CGFloat, right: CGFloat))?

    init(app: AppModel?) { self.app = app }
    deinit { timer?.invalidate() }

    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] _ in self?.step() }
    }
    func stop() { timer?.invalidate(); timer = nil; walking = false }

    /// The user is dragging the pet: stand still for a while.
    func userMoved() { walking = false; walkRemaining = 0; pausedUntil = Date().addingTimeInterval(10); pendingReaction = nil }

    /// The user clicked the pet: react with a random action (never the same twice in a row). Only while it is idle; a walking
    /// pet sits down first.
    func poke(_ choice: PetSprites.Reaction? = nil, now: Date = Date()) {
        guard settings.enabled, reaction.isEmpty, pendingReaction == nil, mood.pose == .idle || mood.pose == .walk else { return }
        let options = PetSprites.Reaction.allCases.filter { $0 != lastReaction }
        pendingReaction = choice ?? options.randomElement()
        walking = false; walkRemaining = 0
        pausedUntil = now.addingTimeInterval(8)
        nextWalk = now.addingTimeInterval(10)
    }

    func step(now: Date = Date()) {
        tick &+= 1
        guard let app else { return }
        var next = brain.update(live: app.live, phase: app.phase, paused: app.paused, configError: app.configError, now: now)
        if !settings.bubble { next.bubble = nil }
        if next.pose != .idle { walking = false; walkRemaining = 0; idleSince = now; nextWalk = now.addingTimeInterval(8); reaction = []; pendingReaction = nil }
        if next.pose == .idle && reaction.isEmpty { wander(now) }
        if walking { next = PetMood(pose: .walk) }
        if let last = lastPose, last != next.pose {
            transition = PetSprites.transition(from: last, to: next.pose).flatMap { Array(repeating: $0, count: PetSprites.steps($0)) }
            transitionTicks = 0
        }
        lastPose = next.pose
        if next != mood { mood = next }
        var ref: SpriteRef
        if next.pose == .idle, !walking, transition.isEmpty, reaction.isEmpty, let chosen = pendingReaction, lastPose == .idle {
            pendingReaction = nil; lastReaction = chosen; reaction = chosen.script
        }
        var shownBubble: String? = nil
        if !reaction.isEmpty && transition.isEmpty {
            let beat = reaction.removeFirst()
            ref = SpriteRef(key: beat.key, index: beat.index); shownBubble = beat.bubble
            nextWalk = now.addingTimeInterval(8)
        } else if !transition.isEmpty {
            ref = SpriteRef(key: transition[min(transitionTicks, transition.count - 1)], index: 0)
            transitionTicks += 1
            if transitionTicks >= transition.count { transition = [] }
        } else {
            ref = SpriteRef(key: next.pose.rawValue, index: PetSprites.frameIndex(next.pose, tick: tick))
        }
        if ref != sprite { sprite = ref }
        if shownBubble != reactionBubble && settings.bubble { reactionBubble = shownBubble }
    }

    /// Starts walking `distance` points right away (the wander timer does the same after a random pause).
    func forceWalk(left: Bool, distance: CGFloat) { facingLeft = left; walkRemaining = distance; walking = true; pausedUntil = .distantPast }

    private func wander(_ now: Date) {
        guard settings.wander, now > pausedUntil else { walking = false; return }
        if walking {
            if lastPose != .walk || !transition.isEmpty { return }      // rising: stay put until the wolf is on its feet
            let step: CGFloat = 7
            let delta = facingLeft ? -step : step
            if walkRemaining <= 0 || move?(delta) == false { walking = false; nextWalk = now.addingTimeInterval(Double.random(in: 6...18)); return }
            walkRemaining -= step
            return
        }
        guard now >= nextWalk, let room = room?() else { return }
        let goLeft = room.left > 80 && (room.right < 80 || Bool.random())
        guard goLeft ? room.left > 60 : room.right > 60 else { nextWalk = now.addingTimeInterval(5); return }
        facingLeft = goLeft
        walkRemaining = CGFloat.random(in: 70...260)
        walking = true
    }
}

// MARK: - The view

struct PetView: View {
    @ObservedObject var pet: PetModel
    var onDrag: (Bool) -> Void              // true = began, false = ended
    var onDragMove: () -> Void
    var menu: [(String, () -> Void)]

    var body: some View {
        let scale = CGFloat(pet.settings.scale)
        VStack(spacing: 2) {
            Spacer(minLength: 0)
            bubble.offset(x: scale * 5)          // the head is right of the sprite's centre
            PetSpriteView(key: pet.sprite.key, frame: pet.sprite.index, scale: scale)
                .scaleEffect(x: pet.facingLeft && pet.walking ? -1 : 1, y: 1)
                .contentShape(Rectangle())
                .onTapGesture { pet.poke() }
                .gesture(DragGesture(minimumDistance: 3)
                    .onChanged { _ in onDragMove() }
                    .onEnded { _ in onDrag(false) })
                .contextMenu { ForEach(Array(menu.enumerated()), id: \.offset) { _, item in Button(item.0, action: item.1) } }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
        .animation(.easeOut(duration: 0.18), value: pet.mood.bubble)
    }

    @ViewBuilder private var bubble: some View {
        if let text = pet.mood.bubble ?? pet.reactionBubble {
            PetBubble(text: text).transition(.opacity.combined(with: .scale(scale: 0.9, anchor: .bottom)))
        } else if pet.mood.pose == .think && pet.settings.bubble {
            PetBubble(text: String(repeating: "·", count: 1 + (pet.tick / 3) % 3)).transition(.opacity)
        }
    }
}
