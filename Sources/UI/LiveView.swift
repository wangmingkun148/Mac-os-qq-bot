import SwiftUI

/// Small always-on-top window: every message and what the bot decided to do about it.
struct LiveView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            header
            Rectangle().fill(CC.border).frame(height: 1)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    if model.paused { pausedNotice }
                    if let preview = model.live.preview, !model.paused { TopicPreviewCard(preview: preview) { model.chooseTopic($0) } }
                    if let unvisited = model.live.unvisited, !unvisited.isEmpty, !model.paused { UnvisitedCard(chats: unvisited) }
                    ForEach(model.live.waiting) { WaitingCard(batch: $0) }
                    if let turn = model.live.current { TurnCard(turn: turn, expanded: true) }
                    if model.compactLive {
                        ForEach(model.live.finished) { CompactRow(turn: $0) }
                    } else {
                        ForEach(Array(model.live.finished.enumerated()), id: \.element.id) { index, turn in
                            TurnCard(turn: turn, expanded: index == 0 && model.live.current == nil,
                                     rating: model.ratings[turn.id], onRate: { model.rate(turn, $0) })
                        }
                    }
                    if model.live.turns.isEmpty && model.live.waiting.isEmpty && !model.paused { emptyState }
                }
                .padding(12)
            }
            Rectangle().fill(CC.border).frame(height: 1)
            footer
        }
        .background(CC.background)
        .foregroundColor(CC.text)
        .font(CCFont.pixel(12))
        .frame(minWidth: 320, minHeight: 300)
    }

    // MARK: Header

    private var header: some View {
        HStack(spacing: 8) {
            PixelLED(color: model.phase.color, blinking: model.phase.isBusy, size: 10)
            VStack(alignment: .leading, spacing: 1) {
                Text(model.live.current.map { Outcome.stageName($0) } ?? model.phase.label).font(CCFont.pixel(24))
                Text(model.live.engine.message ?? model.modelName).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary).lineLimit(1)
            }
            Spacer(minLength: 4)
            HStack(spacing: 2) {
                Button { model.compactLive.toggle() } label: { PixelIcon( "list.bullet") }
                    .buttonStyle(GhostIconStyle(active: model.compactLive)).help("紧凑列表")
                Button { model.pinned.toggle() } label: { PixelIcon( model.pinned ? "pin.fill" : "pin") }
                    .buttonStyle(GhostIconStyle(active: model.pinned)).help("置顶显示")
                Button { model.control?.togglePaused() } label: { PixelIcon( model.paused ? "play.fill" : "pause.fill") }
                    .buttonStyle(GhostIconStyle()).help(model.paused ? "开始自动回复" : "暂停自动回复")
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(CC.sidebar)
    }

    private var pausedNotice: some View {
        Card(fill: CC.sunken) {
            HStack(spacing: 8) {
                PixelIcon( "pause.circle").foregroundColor(CC.textTertiary)
                Text("已暂停。开始后会先记录现有消息作为基线，不回复历史。").font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            WolfMark().frame(width: 44, height: 44).opacity(0.85)
            Text("等待新消息").font(CCFont.title(15))
            Text("每条被处理的消息、是否回复、模型的判断理由都会出现在这里。")
                .font(CCFont.pixel(12)).foregroundColor(CC.textTertiary).multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 40)
    }

    // MARK: Footer

    private var footer: some View {
        HStack(spacing: 10) {
            Text("回复 \(model.live.stats.replied)").foregroundColor(CC.good)
            Text("不回 \(model.live.stats.silent)").foregroundColor(CC.textSecondary)
            Text("失败 \(model.live.stats.failed)").foregroundColor(model.live.stats.failed > 0 ? CC.bad : CC.textTertiary)
            Spacer()
            if let line = model.live.activity.first {
                Text(line.text).lineLimit(1).truncationMode(.tail).foregroundColor(CC.textTertiary).frame(maxWidth: 170, alignment: .trailing)
            }
        }
        .font(CCFont.pixel(12))
        .padding(.horizontal, 12).padding(.vertical, 7)
        .background(CC.sidebar)
    }
}

struct CompactRow: View {
    let turn: Turn
    var body: some View {
        let chip = Outcome.chip(turn)
        HStack(spacing: 8) {
            PixelIcon( chip.icon).font(CCFont.pixel(12)).foregroundColor(chip.color)
                .frame(width: 18, height: 18).background(Rectangle().fill(chip.soft))
            if let message = turn.messages.last { MessageLine(message: message, lineLimit: 1) }
            Text(Format.ago(turn.ended ?? turn.started)).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(PixelRect().fill(CC.card))
        .overlay(PixelRect().strokeBorder(CC.border, lineWidth: 1))
    }
}
