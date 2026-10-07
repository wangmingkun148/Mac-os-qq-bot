import SwiftUI

/// The openings written after 主动发起话题: the owner sends one of them, or none.
struct TopicPreviewCard: View {
    let preview: LiveSnapshot.Preview
    var choose: (Int) -> Void

    private static let shapeNames = ["relatable": "共鸣", "callback": "接旧梗", "hot_take": "小暴论", "call_out": "点名",
                                     "light_question": "小问题", "share_link": "分享链接"]
    private var answered: Bool { preview.chosen != nil }

    var body: some View {
        Card(padding: 11, fill: CC.accentSoft) {
            VStack(alignment: .leading, spacing: 8) {
                header
                ForEach(Array(preview.options.enumerated()), id: \.offset) { index, option in row(index, option) }
                footer
            }
        }
    }

    private var header: some View {
        HStack(spacing: 6) {
            Chip(text: answered ? "已选好" : "待选择", color: CC.accentStrong, soft: CC.card, icon: answered ? "checkmark" : "sparkles")
            Text(preview.title).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary).lineLimit(1)
            Spacer(minLength: 4)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(remaining(context.date)).font(CCFont.mono(10.5)).foregroundColor(CC.textTertiary)
            }
        }
    }

    private func remaining(_ now: Date) -> String {
        let seconds = Int(preview.expires - now.timeIntervalSince1970)
        if answered { return "等待发送" }
        return seconds <= 0 ? "即将作废" : seconds >= 60 ? "还剩 \(seconds / 60) 分钟" : "还剩 \(seconds) 秒"
    }

    private func row(_ index: Int, _ option: LiveSnapshot.Preview.Option) -> some View {
        let picked = preview.chosen == index
        return HStack(alignment: .top, spacing: 8) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 5) {
                    Text("\(index + 1)").font(CCFont.pixel(12)).foregroundColor(CC.accentStrong)
                    Text(Self.shapeNames[option.shape] ?? "开场").font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
                    if option.link { PixelIcon("globe").foregroundColor(CC.textTertiary) }
                }
                Text(option.text).font(CCFont.pixel(12)).foregroundColor(CC.text).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
            }
            Button(picked ? "已选" : "发这条") { choose(index) }
                .buttonStyle(ClayButtonStyle(prominent: !answered, compact: true)).disabled(answered)
        }
        .padding(8)
        .background(PixelRect().fill(CC.card))
        .overlay(PixelRect().strokeBorder(picked ? CC.accent : CC.border, lineWidth: picked ? 1.5 : 1))
        .help(option.reason)
    }

    private var footer: some View {
        HStack(spacing: 8) {
            Text(answered ? "当前的回复发完就会发出去" : "选一条发出去，也可以都不发").font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
            Spacer(minLength: 4)
            Button("都不发") { choose(-1) }.buttonStyle(ClayButtonStyle(prominent: false, compact: true)).disabled(answered)
        }
    }
}
