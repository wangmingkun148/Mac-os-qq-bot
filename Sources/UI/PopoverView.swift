import SwiftUI

extension Phase {
    var color: Color {
        switch self {
        case .listening: return CC.good
        case .thinking, .starting, .switching: return CC.accent
        case .sending: return CC.info
        case .waiting: return CC.warn
        case .attention, .offline: return CC.bad
        case .paused: return CC.textTertiary
        }
    }
}

/// Menu bar popover: what is happening now, how it went lately, and the few controls used day to day.
struct PopoverView: View {
    @ObservedObject var model: AppModel
    @State private var moreOpen = false
    @State private var reportOpen = false

    var body: some View {
        VStack(spacing: 12) {
            header
            nowSection
            statsStrip
            if model.live.preview == nil || model.paused { recentSection }
            controlsSection
            if reportOpen { DailyReportPanel(days: model.daily) { reportOpen = false } } else if moreOpen { moreMenu }
            footer
        }
        .padding(16)
        .frame(width: 380)
        .background(CC.background)
        .foregroundColor(CC.text)
        .font(CCFont.pixel(12))
    }

    // MARK: Header

    private var header: some View {
        HStack(spacing: 10) {
            WolfMark().frame(width: 36, height: 36)
            VStack(alignment: .leading, spacing: 2) {
                Text("QQ 自动回复").font(CCFont.title(24))
                HStack(spacing: 5) {
                    PixelLED(color: model.phase.color, blinking: model.phase.isBusy, size: 8)
                    Text(model.phase.label).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
                    Text("· \(model.modelName)").font(CCFont.pixel(12)).foregroundColor(CC.textTertiary).lineLimit(1)
                }
            }
            Spacer(minLength: 6)
            Button { model.control?.togglePaused() } label: {
                HStack(spacing: 5) {
                    PixelIcon( model.paused ? "play.fill" : "pause.fill").font(CCFont.pixel(12))
                    Text(model.paused ? "开始" : "暂停")
                }
            }
            .buttonStyle(ClayButtonStyle(prominent: model.paused))
        }
    }

    // MARK: Now

    @ViewBuilder private var nowSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel(text: "现在", trailing: model.paused ? nil : "监听 \(model.live.waiting.count + (model.live.current == nil ? 0 : 1)) 个待处理")
            let preview = model.paused ? nil : model.live.preview
            if let preview { TopicPreviewCard(preview: preview) { model.chooseTopic($0) } }
            if let turn = model.live.current, !model.paused {
                TurnCard(turn: turn, expanded: true, showTimeline: false)
            } else if let batch = model.live.waiting.first, !model.paused {
                WaitingCard(batch: batch)
            } else if let unvisited = model.live.unvisited, !unvisited.isEmpty, !model.paused {
                UnvisitedCard(chats: unvisited)
            } else if preview == nil {
                idleCard
            }
        }
    }

    private var idleCard: some View {
        Card {
            HStack(alignment: .top, spacing: 10) {
                PixelIcon( model.configError != nil ? "exclamationmark.triangle" : model.paused ? "pause.circle" : (model.phase == .attention || model.phase == .offline ? "exclamationmark.triangle" : "ear"), scale: 3)
                    .foregroundColor(model.phase.color)
                VStack(alignment: .leading, spacing: 3) {
                    Text(idleTitle).font(CCFont.pixel(12))
                    Text(idleDetail).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
    private var idleTitle: String {
        model.configError != nil ? "配置有误" : model.paused ? "已暂停" : (model.phase == .offline ? "后台没有响应" : (model.phase == .attention ? "需要注意" : "正在监听新消息"))
    }
    private var idleDetail: String {
        if let problem = model.configError { return problem.replacingOccurrences(of: "配置有误，后台没有启动：", with: "后台没有启动：") + "。请在「设置」里修正后点「保存并重启后台」，或直接编辑 config.json。" }
        if model.paused { return "点击「开始」后会先记录现有消息作为基线，不会回复历史消息。" }
        if model.phase == .offline { return "回复进程长时间没有更新状态，请检查 QQ 与辅助功能权限（macOS 27 里叫“设备控制和数据访问”），必要时退出后重开。" }
        return model.live.engine.message ?? "有新的文字消息时才会调用模型。"
    }

    // MARK: Stats

    private var statsStrip: some View {
        HStack(spacing: 0) {
            stat("\(model.live.stats.replied)", "已回复", CC.good)
            divider
            stat("\(model.live.stats.silent)", "选择不回", CC.textSecondary)
            divider
            stat("\(model.live.stats.failed)", "失败", model.live.stats.failed > 0 ? CC.bad : CC.textSecondary)
            divider
            stat(model.counters.lastInferenceSeconds.map { String(format: "%.1fs", $0) } ?? "—", "上次耗时", CC.textSecondary)
        }
        .padding(.vertical, 9)
        .background(PixelRect().fill(CC.sunken))
    }
    private var divider: some View { Rectangle().fill(CC.border).frame(width: 1, height: 26) }
    private func stat(_ value: String, _ label: String, _ color: Color) -> some View {
        VStack(spacing: 1) {
            Text(value).font(CCFont.pixel(24)).foregroundColor(color)
            Text(label).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: Recent

    @ViewBuilder private var recentSection: some View {
        let items = Array(model.live.finished.prefix(4))
        VStack(alignment: .leading, spacing: 4) {
            SectionLabel(text: "最近处理", trailing: nil)
            if items.isEmpty {
                Text("本次运行还没有处理过消息").font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 6)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.element.id) { index, turn in
                        RecentRow(turn: turn).onTapGesture { model.control?.showLive() }
                        if index < items.count - 1 { Rectangle().fill(CC.border).frame(height: 1).padding(.leading, 30) }
                    }
                }
                .background(PixelRect().fill(CC.card))
                .overlay(PixelRect().strokeBorder(CC.border, lineWidth: 1))
            }
        }
    }

    // MARK: Controls

    private var controlsSection: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                Text(model.providerName).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
                Text(model.modelName).font(CCFont.pixel(12))
            }
            Spacer()
            Toggle(isOn: Binding(get: { model.suffix }, set: { model.control?.setSuffix($0) })) {
                Text("回复后缀").font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
            }.toggleStyle(PixelToggleStyle())
        }
        .padding(12).background(PixelRect().fill(CC.card))
        .overlay(PixelRect().strokeBorder(CC.border, lineWidth: 1))
    }

    // MARK: Footer

    private var footer: some View {
        HStack(spacing: 8) {
            footerButton("rectangle.on.rectangle", "状态窗") { model.control?.showLive() }
            footerButton("slider.horizontal.3", "设置") { model.control?.showSettings() }
            footerButton("circle.grid.2x2", "QQ 空间") { model.control?.showSpace() }
            Button { moreOpen.toggle(); reportOpen = false } label: {
                PixelIcon("ellipsis", scale: 2).foregroundColor(CC.textSecondary)
                    .frame(width: 30, height: 28)
                    .pixelPanel(moreOpen ? CC.accentSoft : CC.card, border: moreOpen ? CC.accent : CC.border)
            }
            .buttonStyle(.plain)
            Button { model.control?.quitApp() } label: {
                PixelIcon("power", scale: 2).foregroundColor(CC.bad)
                    .frame(width: 30, height: 28)
                    .background(PixelRect().fill(CC.badSoft))
                    .overlay(PixelRect().strokeBorder(CC.bad.opacity(0.35), lineWidth: 1))
            }
            .buttonStyle(.plain).help("退出 QQ 自动回复")
        }
    }

    private var moreMenu: some View {
        let items: [(String, Bool, () -> Void)] = [
            ("今日简报  ›", false, { reportOpen = true }),
            ("主动发起话题", model.paused, { model.control?.requestProactive() }),
            ("外观：\(AppModel.appearanceNames[model.appearance] ?? "跟随系统")（点击切换）", false, {
                let order = ["system", "light", "dark"]
                model.appearance = order[((order.firstIndex(of: model.appearance) ?? 0) + 1) % order.count]
            }),
            (model.pet.enabled ? "隐藏桌宠" : "显示桌宠", false, { model.control?.setPetEnabled(!model.pet.enabled) }),
            ("打开配置文件", false, { model.control?.openConfigFile() }),
            ("辅助功能权限（设备控制和数据访问）", false, { model.control?.openPermissions() }),
        ]
        return VStack(spacing: 0) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                Button { item.2(); moreOpen = false } label: {
                    HStack { Text(item.0).font(CCFont.pixel(12)); Spacer() }
                        .foregroundColor(item.1 ? CC.textTertiary : CC.text)
                        .padding(.horizontal, 10).padding(.vertical, 6).contentShape(Rectangle())
                }
                .buttonStyle(.plain).disabled(item.1)
                if index < items.count - 1 { Rectangle().fill(CC.border).frame(height: 1) }
            }
        }
        .pixelPanel(CC.card, shadow: true)
    }

    private func footerButton(_ icon: String, _ title: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 5) { PixelIcon( icon).font(CCFont.pixel(12)); Text(title).lineLimit(1) }.frame(maxWidth: .infinity)
        }
        .buttonStyle(ClayButtonStyle(prominent: false, compact: true))
    }
}

struct RecentRow: View {
    let turn: Turn
    var body: some View {
        let chip = Outcome.chip(turn)
        HStack(alignment: .top, spacing: 8) {
            ZStack {
                Rectangle().fill(chip.soft).frame(width: 20, height: 20)
                PixelIcon( chip.icon).font(CCFont.pixel(12)).foregroundColor(chip.color)
            }
            VStack(alignment: .leading, spacing: 2) {
                if let message = turn.messages.last { MessageLine(message: message, lineLimit: 1) }
                else { Text(Outcome.kindName(turn.kind)).font(CCFont.pixel(12)) }
                Text(detail).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary).lineLimit(1)
            }
            Spacer(minLength: 4)
            Text(Format.ago(turn.ended ?? turn.started)).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
        }
        .padding(.horizontal, 10).padding(.vertical, 8).contentShape(Rectangle())
    }
    private var detail: String {
        switch turn.outcome {
        case "replied": return "→ " + (turn.reply?.text ?? "已回复")
        case "silent": return turn.decision?.reason ?? "选择不回复"
        default: return turn.error ?? turn.timeline.last?.text ?? Outcome.chip(turn).text
        }
    }
}

/// The "今日简报" sub-menu: what the bot did today (and yesterday, for comparison).
struct DailyReportPanel: View {
    let days: [String: [String: Double]]
    var back: () -> Void

    private static func key(_ offset: Int) -> String {
        let formatter = DateFormatter(); formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: Calendar.current.date(byAdding: .day, value: offset, to: Date()) ?? Date())
    }
    private func value(_ day: [String: Double], _ name: String) -> String {
        Format.count(day[name] ?? 0)
    }
    private func average(_ day: [String: Double]) -> String {
        guard let calls = day["timed_calls"], calls > 0 else { return "—" }
        return String(format: "%.1fs", (day["model_seconds"] ?? 0) / calls)
    }
    private func tokens(_ day: [String: Double]) -> String {
        "\(Format.compact(day["input_tokens"] ?? 0)) / \(Format.compact(day["output_tokens"] ?? 0))"
    }

    var body: some View {
        let today = days[Self.key(0)] ?? [:], yesterday = days[Self.key(-1)] ?? [:]
        let rows: [(String, String, String)] = [
            ("已回复", value(today, "replied"), value(yesterday, "replied")),
            ("选择不回", value(today, "silent"), value(yesterday, "silent")),
            ("模型失败", value(today, "failed"), value(yesterday, "failed")),
            ("自动切换线路", value(today, "switches"), value(yesterday, "switches")),
            ("自动切回首选", value(today, "switch_backs"), value(yesterday, "switch_backs")),
            ("发送不确定而暂停", value(today, "uncertain_pauses"), value(yesterday, "uncertain_pauses")),
            ("自动恢复", value(today, "auto_resumes"), value(yesterday, "auto_resumes")),
            ("QQ 被切到前台", value(today, "wakes"), value(yesterday, "wakes")),
            ("联网搜索", value(today, "searches"), value(yesterday, "searches")),
            ("主动话题（发出）", value(today, "topics_sent"), value(yesterday, "topics_sent")),
            ("话题有人接 / 没人理", "\(value(today, "topics_good")) / \(value(today, "topics_ignored"))",
             "\(value(yesterday, "topics_good")) / \(value(yesterday, "topics_ignored"))"),
            ("平均耗时", average(today), average(yesterday)),
            ("Token 输入 / 输出", tokens(today), tokens(yesterday)),
        ]
        return VStack(spacing: 0) {
            HStack(spacing: 6) {
                Button(action: back) {
                    HStack(spacing: 4) { PixelIcon("chevron.right").rotationEffect(.degrees(180)); Text("返回") }
                        .font(CCFont.pixel(12)).foregroundColor(CC.textSecondary).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                Spacer()
                Text("今日简报").font(CCFont.pixel(12))
                Spacer()
                Text("今天 / 昨天").font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
            }
            .padding(.horizontal, 10).padding(.vertical, 7)
            Rectangle().fill(CC.border).frame(height: 1)
            ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                HStack {
                    Text(row.0).foregroundColor(CC.textSecondary)
                    Spacer()
                    Text(row.1).foregroundColor(CC.text)
                    Text(row.2).foregroundColor(CC.textTertiary).frame(minWidth: 64, alignment: .trailing)
                }
                .font(CCFont.pixel(12)).padding(.horizontal, 10).padding(.vertical, 4)
                .background(index % 2 == 1 ? CC.sunken.opacity(0.6) : Color.clear)
            }
        }
        .pixelPanel(CC.card, shadow: true)
    }
}

