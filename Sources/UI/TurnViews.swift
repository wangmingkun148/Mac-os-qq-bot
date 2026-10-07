import SwiftUI

typealias Turn = LiveSnapshot.Turn

// MARK: - Vocabulary

enum Outcome {
    static func chip(_ turn: Turn) -> (text: String, icon: String, color: Color, soft: Color) {
        switch turn.outcome {
        case "replied": return ("已回复", "checkmark", CC.good, CC.goodSoft)
        case "silent": return ("未回复", "minus", CC.textSecondary, CC.sunken)
        case "failed": return ("失败", "exclamationmark", CC.bad, CC.badSoft)
        case "uncertain": return ("未确认", "questionmark", CC.bad, CC.badSoft)
        case "abandoned": return ("已放弃", "xmark", CC.warn, CC.warnSoft)
        case "cancelled": return ("已取消", "pause", CC.textSecondary, CC.sunken)
        default: return (stageName(turn), "ellipsis", CC.accentStrong, CC.accentSoft)
        }
    }
    static func stageName(_ turn: Turn) -> String {
        switch turn.stage {
        case "judging": return turn.kind == "image" ? "审核中" : "判断中"
        case "generating": return turn.kind == "browser" ? "浏览中" : (turn.kind == "image" ? "生成图片" : "生成中")
        case "choosing": return "待选择"
        case "ready": return "待发送"
        case "sending": return "发送中"
        case "verifying": return "确认中"
        default: return "处理中"
        }
    }
    static func kindName(_ kind: String) -> String {
        ["proactive": "主动话题", "browser": "浏览链接", "image": "图片请求"][kind] ?? "新消息"
    }
    static func kindIcon(_ kind: String) -> String {
        ["proactive": "sparkles", "browser": "safari", "image": "photo"][kind] ?? "bubble.left"
    }
}

// MARK: - Progress stepper: 收到 → 判断 → 生成 → 发送 → 确认

struct StageStepper: View {
    let turn: Turn
    private var labels: [String] { [turn.kind == "proactive" ? "触发" : "收到", turn.kind == "browser" ? "浏览" : "判断",
                                    "生成", "发送", "确认"] }
    /// Index of the step in progress (labels.count when everything is done).
    private var current: Int {
        if turn.outcome == "replied" { return 5 }
        switch turn.stage {
        case "judging": return 1
        case "generating": return 2
        case "choosing", "ready", "sending": return 3
        case "verifying": return 4
        default: return turn.outcome == "silent" ? 2 : 5
        }
    }
    private var skipped: Bool { turn.outcome == "silent" || turn.outcome == "cancelled" }
    private var broken: Bool { ["failed", "uncertain", "abandoned"].contains(turn.outcome ?? "") }

    var body: some View {
        VStack(spacing: 5) {
            PixelBar(count: labels.count, filled: skipped ? current : min(current, labels.count), color: skipped ? CC.textTertiary : CC.good,
                     activeIndex: skipped || broken || current >= labels.count ? nil : current, failedIndex: broken ? min(current, labels.count - 1) : nil)
            HStack(spacing: 2) {
                ForEach(Array(labels.enumerated()), id: \.offset) { index, label in
                    let state = stepState(index)
                    Text(label).font(CCFont.pixel(12))
                        .foregroundColor(state == .active ? CC.accentStrong : state == .failed ? CC.bad : state == .pending || state == .skipped ? CC.textTertiary : CC.text)
                        .frame(maxWidth: .infinity)
                }
            }
        }
    }

    private enum StepState { case done, active, pending, skipped, failed }
    private func stepState(_ index: Int) -> StepState {
        if index == 0 { return .done }
        if skipped { return index < current ? .done : .skipped }
        if broken { return index < current ? .done : (index == current ? .failed : .pending) }
        if index < current { return .done }
        return index == current ? .active : .pending
    }
}

// MARK: - Message rows

struct MessageLine: View {
    let message: LiveSnapshot.Message
    var lineLimit = 2
    private var content: String {
        message.text.isEmpty ? (message.image ? "[图片]" : "…") : message.text + (message.image ? " [图片]" : "")
    }
    var body: some View {
        (Text(message.sender.isEmpty ? "群友" : message.sender).foregroundColor(CC.textSecondary)
            + Text("  " + content).foregroundColor(CC.text))
            .font(CCFont.pixel(12)).lineLimit(lineLimit).frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The model's reasoning for this turn: stated reasons first, then provider-exposed thought summaries.
struct ThinkingBlock: View {
    let turn: Turn
    @State private var open = false
    private var entries: [(String, String)] {
        var list: [(String, String)] = []
        if let reason = turn.decision?.reason, !reason.isEmpty {
            list.append((turn.decision?.shouldReply == false ? "判断：不接话" : "判断：接话", reason))
        }
        if let reason = turn.reply?.reason, !reason.isEmpty, reason != turn.decision?.reason { list.append(("回复思路", reason)) }
        for thought in turn.thoughts { list.append(("思考摘要", thought)) }
        if let error = turn.error { list.append(("错误", error)) }
        return list
    }
    var body: some View {
        if !entries.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Button { withAnimation(.easeOut(duration: 0.15)) { open.toggle() } } label: {
                    HStack(spacing: 4) {
                        PixelIcon( "chevron.right").font(CCFont.pixel(12)).rotationEffect(.degrees(open ? 90 : 0))
                        Text("思考过程").font(CCFont.pixel(12))
                        if !open, let first = entries.first {
                            Text(first.1).font(CCFont.pixel(12)).lineLimit(1).foregroundColor(CC.textTertiary)
                        }
                        Spacer(minLength: 0)
                    }
                    .foregroundColor(CC.textSecondary).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                if open {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(entries.enumerated()), id: \.offset) { _, entry in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(entry.0).font(CCFont.pixel(12))
                                    .foregroundColor(entry.0 == "错误" ? CC.bad : CC.accentStrong)
                                Text(entry.1).font(CCFont.pixel(12)).foregroundColor(CC.text).textSelection(.enabled)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .padding(.leading, 12)
                    .overlay(alignment: .leading) { Rectangle().fill(CC.accent.opacity(0.5)).frame(width: 2) }
                }
            }
        }
    }
}

struct TimelineBlock: View {
    let turn: Turn
    @State private var open = false
    var body: some View {
        if turn.timeline.count > 1 {
            VStack(alignment: .leading, spacing: 5) {
                Button { withAnimation(.easeOut(duration: 0.15)) { open.toggle() } } label: {
                    HStack(spacing: 4) {
                        PixelIcon( "chevron.right").font(CCFont.pixel(12)).rotationEffect(.degrees(open ? 90 : 0))
                        Text("处理时间线").font(CCFont.pixel(12))
                        Spacer(minLength: 0)
                    }
                    .foregroundColor(CC.textSecondary).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                if open {
                    ForEach(turn.timeline) { item in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text(Format.clock(item.t)).font(CCFont.mono(10)).foregroundColor(CC.textTertiary)
                            Text(item.text).font(CCFont.pixel(12)).foregroundColor(CC.text).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
        }
    }
}

/// One handled batch of messages and everything that happened to it.
struct TurnCard: View {
    let turn: Turn
    var expanded = true
    var showTimeline = true
    /// Set to show 👍 / 👎 on a sent reply.
    var rating: String? = nil
    var onRate: ((String) -> Void)? = nil
    @State private var open: Bool? = nil
    private var isOpen: Bool { open ?? expanded }

    var body: some View {
        let chip = Outcome.chip(turn)
        Card(padding: 11) {
            VStack(alignment: .leading, spacing: 9) {
                header(chip)
                if turn.isActive && isOpen { StageStepper(turn: turn).padding(.vertical, 2) }
                messages
                if let reply = turn.reply?.text, !reply.isEmpty { replyBubble(reply) }
                else if turn.outcome == "silent" { decisionNote }
                else if ["failed", "uncertain", "abandoned"].contains(turn.outcome ?? "") { failureNote }
                if isOpen {
                    ThinkingBlock(turn: turn)
                    if showTimeline { TimelineBlock(turn: turn) }
                    metrics
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { withAnimation(.easeOut(duration: 0.15)) { open = !isOpen } }
    }

    private func header(_ chip: (text: String, icon: String, color: Color, soft: Color)) -> some View {
        HStack(spacing: 6) {
            Chip(text: chip.text, color: chip.color, soft: chip.soft, icon: turn.isActive ? nil : chip.icon)
            PixelIcon( Outcome.kindIcon(turn.kind)).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
            Text(turn.title).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary).lineLimit(1)
            Spacer(minLength: 4)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(turn.isActive ? Format.elapsed(since: turn.started, now: context.date) : Format.ago(turn.ended ?? turn.started, now: context.date))
                    .font(CCFont.mono(10.5)).foregroundColor(CC.textTertiary)
            }
        }
    }

    @ViewBuilder private var messages: some View {
        if turn.messages.isEmpty {
            Text(Outcome.kindName(turn.kind)).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 4) {
                let shown = isOpen ? turn.messages : Array(turn.messages.suffix(1))
                ForEach(shown) { MessageLine(message: $0, lineLimit: isOpen ? 3 : 1) }
                if turn.messageCount > shown.count {
                    Text("另有 \(turn.messageCount - shown.count) 条一并处理").font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
                }
            }
        }
    }

    private func replyBubble(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 6) {
            PixelIcon( "arrowshape.turn.up.left.fill").font(CCFont.pixel(12)).foregroundColor(CC.accent).padding(.top, 3)
            Text(text).font(CCFont.pixel(12)).foregroundColor(CC.text).lineLimit(isOpen ? 6 : 2)
                .frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
            if let onRate, turn.outcome == "replied" {
                HStack(spacing: 4) {
                    rateButton("thumbs.up", "up", CC.good, onRate).help("像真人，多这样说")
                    rateButton("thumbs.down", "down", CC.bad, onRate).help("别扭，别这样说")
                }
            }
        }
        .padding(8)
        .background(PixelRect().fill(CC.accentSoft))
    }

    private func rateButton(_ icon: String, _ value: String, _ color: Color, _ onRate: @escaping (String) -> Void) -> some View {
        let on = rating == value
        return Button { onRate(value) } label: {
            PixelIcon(icon).foregroundColor(on ? color : CC.textTertiary)
                .frame(width: 22, height: 20)
                .pixelPanel(on ? color.opacity(0.18) : CC.card, border: on ? color : CC.border)
        }
        .buttonStyle(.plain)
    }

    private var decisionNote: some View {
        HStack(alignment: .top, spacing: 5) {
            PixelIcon( "moon.zzz").font(CCFont.pixel(12)).foregroundColor(CC.textTertiary).padding(.top, 2)
            Text(turn.decision?.reason ?? "本轮不接话").font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
                .lineLimit(isOpen ? 4 : 2).frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var failureNote: some View {
        HStack(alignment: .top, spacing: 6) {
            PixelIcon( "exclamationmark.triangle.fill").font(CCFont.pixel(12)).foregroundColor(CC.bad).padding(.top, 2)
            Text(turn.error ?? turn.timeline.last?.text ?? "处理没有完成").font(CCFont.pixel(12)).foregroundColor(CC.bad)
                .lineLimit(isOpen ? 5 : 2).frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(8)
        .background(PixelRect().fill(CC.badSoft))
    }

    @ViewBuilder private var metrics: some View {
        let parts = metricParts
        if !parts.isEmpty {
            Text(parts.joined(separator: " · ")).font(CCFont.mono(10)).foregroundColor(CC.textTertiary).lineLimit(2)
        }
    }
    private var metricParts: [String] {
        var parts: [String] = []
        if let model = turn.reply?.model ?? turn.decision?.model {
            let effort = turn.reply?.reasoningEffort ?? turn.decision?.reasoningEffort
            parts.append(effort.map { "\(model)/\($0)" } ?? model)
        }
        if let complexity = turn.decision?.complexity, !complexity.isEmpty, complexity != "none" { parts.append(complexity) }
        if let seconds = Format.seconds(turn.tokens?.seconds) { parts.append(seconds) }
        if let tokens = turn.tokens, let input = tokens.input, let output = tokens.output, input + output > 0 {
            parts.append("↓\(Format.tokens(input)) ↑\(Format.tokens(output))")
        }
        return parts
    }
}

struct WaitingCard: View {
    let batch: LiveSnapshot.Waiting
    var body: some View {
        Card(padding: 11) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Chip(text: "等待合并", color: CC.info, soft: CC.infoSoft, icon: "hourglass")
                    Text(batch.title).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary).lineLimit(1)
                    Spacer()
                    Text("\(batch.count) 条").font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
                }
                ForEach(batch.messages.suffix(3)) { MessageLine(message: $0, lineLimit: 1) }
            }
        }
    }
}

/// Other chats whose sidebar preview changed but which the bot has not opened yet.
struct UnvisitedCard: View {
    let chats: [LiveSnapshot.Unvisited]
    var body: some View {
        Card(padding: 11, fill: CC.infoSoft) {
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    PixelIcon( "bubble.left.and.exclamationmark.bubble.right").font(CCFont.pixel(12)).foregroundColor(CC.info)
                    Text("其他会话有新消息，等待查看").font(CCFont.pixel(12)).foregroundColor(CC.info)
                }
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(chats.prefix(4)) { chat in
                            HStack {
                                Text(chat.title).font(CCFont.pixel(12)).lineLimit(1)
                                Spacer(minLength: 6)
                                Text("\(chat.count) 条 · 已等 \(max(0, Int(context.date.timeIntervalSince1970 - chat.since))) 秒")
                                    .font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
                            }
                        }
                    }
                }
            }
        }
    }
}
