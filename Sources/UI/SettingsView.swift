import SwiftUI
import ApplicationServices

enum SettingsSection: String, CaseIterable, Identifiable {
    case general, providers, vision, people, space, diagnostics
    var id: String { rawValue }
    var title: String {
        ["general": "常规", "providers": "AI 供应商", "vision": "图片", "people": "群友备注", "space": "QQ 空间", "diagnostics": "诊断"][rawValue] ?? rawValue
    }
    var icon: String {
        ["general": "slider.horizontal.3", "models": "cpu", "providers": "network", "vision": "photo", "people": "person", "space": "circle.grid.2x2",
         "diagnostics": "stethoscope"][rawValue] ?? "gearshape"
    }
}

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var draft: ConfigDraft
    @State private var notice = ""
    @State private var problemText = ""

    var body: some View {
        HStack(spacing: 0) {
            sidebar
            Rectangle().fill(CC.border).frame(width: 1)
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        content
                    }
                    .padding(EdgeInsets(top: 40, leading: 24, bottom: 24, trailing: 24)).frame(maxWidth: .infinity, alignment: .leading)
                }
                Rectangle().fill(CC.border).frame(height: 1)
                footer
            }
            .background(CC.background)
        }
        .foregroundColor(CC.text)
        .font(CCFont.pixel(12))
        .frame(minWidth: 780, minHeight: 560)
    }

    // MARK: Chrome

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                WolfMark().frame(width: 28, height: 28)
                Text("设置").font(CCFont.title(24))
            }
            .padding(.horizontal, 10).padding(.top, 36).padding(.bottom, 14)
            ForEach(SettingsSection.allCases) { item in
                let on = item == model.settingsSection
                Button { model.settingsSection = item } label: {
                    HStack(spacing: 9) {
                        PixelIcon( item.icon).font(CCFont.pixel(12)).frame(width: 18)
                            .foregroundColor(on ? CC.accentStrong : CC.textSecondary)
                        Text(item.title).font(CCFont.pixel(12))
                        Spacer()
                    }
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .background(PixelRect().fill(on ? CC.card : Color.clear))
                    .overlay(PixelRect().strokeBorder(on ? CC.border : Color.clear, lineWidth: 1))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            Spacer()
            HStack(spacing: 5) {
                PixelLED(color: model.phase.color, blinking: model.phase.isBusy, size: 7)
                Text(model.phase.label).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
            }
            .padding(.horizontal, 10).padding(.bottom, 6)
        }
        .padding(10).frame(width: 190).background(CC.sidebar)
    }

    private var footer: some View {
        HStack(spacing: 10) {
            if !problemText.isEmpty {
                Chip(text: problemText, color: CC.bad, soft: CC.badSoft, icon: "exclamationmark")
            } else if draft.dirty {
                Chip(text: "有未保存的更改", color: CC.warn, soft: CC.warnSoft, icon: "circle.fill")
            } else if !notice.isEmpty {
                Chip(text: notice, color: CC.good, soft: CC.goodSoft, icon: "checkmark")
            }
            Spacer()
            Button("还原") { draft.load(model.control?.config ?? [:]); notice = "" }
                .buttonStyle(ClayButtonStyle(prominent: false)).disabled(!draft.dirty).opacity(draft.dirty ? 1 : 0.45)
            Button("保存并重启后台") { save(restart: true) }.buttonStyle(ClayButtonStyle(prominent: false))
            Button("保存并应用") { save(restart: false) }.buttonStyle(ClayButtonStyle(prominent: true)).disabled(!draft.dirty).opacity(draft.dirty ? 1 : 0.45)
                .keyboardShortcut("s", modifiers: .command)
        }
        .padding(.horizontal, 20).padding(.vertical, 12).background(CC.sidebar)
    }

    private func save(restart: Bool) {
        if let problem = model.control?.applyConfig(draft.result, restart: restart) { notice = ""; problemText = problem; return }
        problemText = ""
        draft.load(model.control?.config ?? draft.result)
        notice = restart ? "已保存，后台正在重启" : "已保存，当前任务结束后生效"
    }

    @ViewBuilder private var content: some View {
        switch model.settingsSection {
        case .general: GeneralPane(draft: draft, model: model, chats: model.chats)
        case .providers: ProvidersPane(draft: draft)
        case .vision: VisionPane(draft: draft)
        case .people: PeoplePane(store: model.peopleStore(), recentNames: model.recentSpeakers)
        case .space: SpacePane(draft: draft, space: model.space)
        case .diagnostics: DiagnosticsPane(model: model)
        }
    }
}

// MARK: - Form building blocks

struct PaneHeader: View {
    let title: String
    let subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(CCFont.title(22))
            Text(subtitle).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary).fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct FormCard<Content: View>: View {
    var title: String? = nil
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let title {
                Text(title).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
                    .padding(.horizontal, 14).padding(.top, 12).padding(.bottom, 2)
            }
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(PixelRect().fill(CC.card))
        .overlay(PixelRect().strokeBorder(CC.border, lineWidth: 1))
    }
}

struct FormRow<Control: View>: View {
    let label: String
    var hint: String? = nil
    var last = false
    @ViewBuilder var control: Control
    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(label).font(CCFont.pixel(12))
                    if let hint { Text(hint).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary).fixedSize(horizontal: false, vertical: true) }
                }
                Spacer(minLength: 12)
                control
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            if !last { Rectangle().fill(CC.border).frame(height: 1).padding(.leading, 14) }
        }
    }
}

struct ClayField: View {
    @Binding var text: String
    var placeholder = ""
    var width: CGFloat? = 260
    var mono = false
    var body: some View {
        TextField(placeholder, text: $text)
            .textFieldStyle(.plain).font(CCFont.pixel(12))
            .padding(.horizontal, 8).padding(.vertical, 5)
            .pixelPanel(CC.sunken)
            .frame(width: width)
    }
}

struct SecretField: View {
    @Binding var text: String
    var configured: Bool
    var body: some View {
        SecureField(configured ? "已配置，留空保持不变" : "尚未配置", text: $text)
            .textFieldStyle(.plain).font(CCFont.pixel(12))
            .padding(.horizontal, 8).padding(.vertical, 5)
            .pixelPanel(CC.sunken)
            .frame(width: 260)
    }
}

struct NumberField: View {
    @Binding var value: Int
    var unit = ""
    var range: ClosedRange<Int> = 0...100_000
    var body: some View {
        HStack(spacing: 6) {
            TextField("", value: $value, format: .number.grouping(.never))
                .textFieldStyle(.plain).multilineTextAlignment(.trailing).font(CCFont.pixel(12))
                .padding(.horizontal, 8).padding(.vertical, 5).frame(width: 70)
                .pixelPanel(CC.sunken)
            if !unit.isEmpty { Text(unit).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary) }
            PixelStepper(value: $value, range: range)
        }
    }
}

struct Dropdown: View {
    var options: [String]
    @Binding var selection: String
    var width: CGFloat = 150
    var body: some View {
        let list = options.contains(selection) || selection.isEmpty ? options : [selection] + options
        PixelDropdown(items: list, title: { $0 }, selected: selection.isEmpty ? nil : selection, width: width) { selection = $0 }
    }
}

struct ClayToggle: View {
    @Binding var isOn: Bool
    var body: some View { Toggle("", isOn: $isOn).labelsHidden().toggleStyle(PixelToggleStyle()) }
}

// MARK: - Panes

struct GeneralPane: View {
    @ObservedObject var draft: ConfigDraft
    @ObservedObject var model: AppModel
    var chats: [ChatEntry] = []
    var body: some View {
        PaneHeader(title: "常规与首次使用", subtitle: "先配置本账号、主群和 AI，再开启辅助功能权限，最后启动监听。模型应原生支持图片输入。")
        FormCard(title: "首次使用") {
            FormRow(label: "1. 登录 QQ", hint: "打开 QQ 主窗口并登录要使用的账号；启动时会核对昵称。") { EmptyView() }
            FormRow(label: "2. 填写 AI", hint: "到 AI 供应商页填写 OpenAI 兼容接口和原生多模态模型。所有 AI 任务共用该配置。") { EmptyView() }
            FormRow(label: "3. 开启辅助功能", hint: "系统设置 → 隐私与安全性 → 辅助功能；较新系统可能显示设备控制和数据访问。重新构建后可能需要关闭再开启。") {
                Button("打开权限设置") { model.control?.openPermissions() }.buttonStyle(ClayButtonStyle(prominent: false, compact: true))
            }
            FormRow(label: "4. 保存并开始", hint: "保存配置后回菜单栏点“开始”。电脑需保持唤醒；窗口切换和粘贴会使用当前桌面。", last: true) { EmptyView() }
        }
        FormCard(title: "账号与主群") {
            FormRow(label: "本账号昵称", hint: "填写 QQ 界面显示的昵称，用于避免错账号发送；不填群友昵称。") { ClayField(text: names, placeholder: "填写本账号昵称", width: 220) }
            FormRow(label: "主群完整名称", hint: "必须与 QQ 会话列表完整名称一致。") { ClayField(text: groups, placeholder: "填写主群完整名称", width: 220) }
            FormRow(label: "本账号 QQ 号", hint: "QQ 空间功能使用；不使用空间可留空。") { ClayField(text: draft.text("qq_account"), width: 220) }
            FormRow(label: "Python 路径", hint: "留空自动查找项目 .venv、系统 Python 或 Homebrew Python。", last: true) { ClayField(text: draft.text("python"), width: 220, mono: true) }
        }
        FormCard(title: "自定义设定（可选）") {
            Text("留空使用通用聊天规则。设定、风格摘要和群友记忆只保存在你自己的电脑中。").foregroundColor(CC.textSecondary)
            TextEditor(text: draft.text("persona")).frame(height: 100)
        }
        FormCard(title: "打分总结（回复偏好）") {
            FormRow(label: "新攒的打分", hint: "状态窗里给回复点 👍 / 👎；所有打分都会永久保存，每攒够 \(model.feedbackEvery) 条新打分总结一轮，写进回复的主提示词。只总结“怎么说”（长短、语气、句式），不记聊的是什么内容、不记人名") {
                Text("\(model.pendingRatings) / \(model.feedbackEvery) 条 · 已总结 \(model.preferences.rounds) 轮").font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
            }
            FormRow(label: model.preferences.updatedAt.map { "上次总结：\($0)" } ?? "还没有总结过",
                    hint: model.preferences.versions > 0 ? "觉得上一轮总结得不对，可以撤回；那一轮用到的打分会在下次重新总结" : nil) {
                Button("撤回上一轮") { model.control?.revertFeedbackRound() }
                    .buttonStyle(ClayButtonStyle(prominent: false, compact: true)).disabled(model.preferences.versions == 0)
            }
            FormRow(label: "查看现在的偏好", last: true) { StyleTextButton(text: model.preferences.text, empty: "（还没有偏好：攒够 \(model.feedbackEvery) 条打分后会自动总结）") }
        }
        FormCard(title: "风格总结") {
            FormRow(label: "长度", hint: "群聊风格总结每攒够 100 条新消息会追加新特点；写满（约 1900 字）时自动压缩，旧版本会保存") {
                Text("\(model.styleInfo.chars) / 1999 字").font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
            }
            FormRow(label: model.styleInfo.compressedAt.map { "上次压缩：\($0)" } ?? "还没有压缩过",
                    hint: model.styleInfo.versions > 0 ? "觉得压缩后说话变味了，可以撤回到压缩前的版本（之后新加的特点会一起撤掉）" : nil) {
                Button("撤回上次压缩") { model.control?.revertStyleCompression() }
                    .buttonStyle(ClayButtonStyle(prominent: false, compact: true)).disabled(model.styleInfo.versions == 0)
            }
            FormRow(label: "查看现在的总结", last: true) { StyleTextButton(text: model.styleInfo.text) }
        }
        FormCard(title: "外观") {
            FormRow(label: "界面明暗", hint: "立即生效，只影响这台电脑，不写入配置文件", last: true) {
                Segmented(options: [("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")],
                          selection: Binding(get: { model.appearance }, set: { model.appearance = $0 }))
                    .frame(width: 260)
            }
        }
        FormCard(title: "节奏") {
            FormRow(label: "回复冷却", hint: "同一会话两次回复之间至少间隔") { NumberField(value: draft.number("cooldown_seconds", 12), unit: "秒") }
            FormRow(label: "消息合并等待", hint: "消息静止这么久后再一起判断") { NumberField(value: draft.number("merge_seconds", 6), unit: "秒") }
            FormRow(label: "合并等待最多次数", hint: "连续消息每来一条就重新计时一次（第一条算第 1 次），最多这么多次，之后不再延后；0 表示不限次数") {
                NumberField(value: draft.number("max_merge_waits", 3), unit: "次", range: 0...50)
            }
            FormRow(label: "最长合并等待", hint: "不论次数，一批消息最多等这么久") { NumberField(value: draft.number("max_merge_seconds", 20), unit: "秒") }
            FormRow(label: "其他会话最长等待", hint: "其他群或私聊有新消息时，最多等这么久就先放下主群去查看；0 表示始终主群优先") {
                NumberField(value: draft.number("secondary_max_wait_seconds", 8), unit: "秒", range: 0...120)
            }
            FormRow(label: "单条回复上限") { NumberField(value: draft.number("max_reply_chars", 160), unit: "字") }
            FormRow(label: "上下文条数", hint: "每次判断带上的最近消息数", last: true) { NumberField(value: draft.number("context_messages", 12), unit: "条", range: 1...60) }
        }
        FormCard(title: "范围与标记") {
            FormRow(label: "回复其他群聊与私聊", hint: "主群优先；其他会话有新消息才会切过去") { ClayToggle(isOn: draft.flag("reply_all_conversations", false)) }
            FormRow(label: "回复添加自定义后缀", hint: "后缀文字在 AI 供应商页填写", last: true) { ClayToggle(isOn: draft.flag("ai.suffix_enabled", true)) }
        }
        FormCard(title: "静音的聊天") {
            let rows = muteRows
            if rows.isEmpty {
                FormRow(label: "还没有读到任何聊天", hint: "机器人开始运行并看过聊天后，这里会列出群和私聊", last: true) { EmptyView() }
            }
            ForEach(Array(rows.enumerated()), id: \.element.title) { index, chat in
                FormRow(label: chat.title, hint: index == 0 ? "打开后只读取记录这个聊天，不回复、不主动发话" : nil, last: index == rows.count - 1) {
                    HStack(spacing: 8) {
                        Text(chat.kind == "group" ? "群聊" : chat.kind == "private" ? "私聊" : "").font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
                        ClayToggle(isOn: muteBinding(chat.title))
                    }
                }
            }
        }
        FormCard(title: "桌宠（白色像素小狼）") {
            FormRow(label: "显示桌宠", hint: "悬浮在桌面上，收到消息、思考、回复、不接话、出错时有不同表现；可拖动，右键有菜单") { ClayToggle(isOn: draft.flag("pet.enabled", true)) }
            FormRow(label: "大小", hint: "每个像素放大的倍数") { NumberField(value: draft.number("pet.scale", 4), unit: "倍", range: 1...12) }
            FormRow(label: "空闲时自己走动") { ClayToggle(isOn: draft.flag("pet.wander", true)) }
            FormRow(label: "头顶气泡", hint: "回复时显示回复内容，不接话时显示理由，出错时显示原因", last: true) { ClayToggle(isOn: draft.flag("pet.bubble", true)) }
        }
        FormCard(title: "状态窗") {
            FormRow(label: "开始运行时自动显示小窗", last: true) { ClayToggle(isOn: draft.flag("live_window.auto_show", true)) }
        }
    }
}

extension GeneralPane {
    /// Configured groups, chats seen so far, and anything muted earlier, without duplicates.
    private var names: Binding<String> {
        Binding(get: { (draft.value("self_names") as? [String] ?? []).joined(separator: "、") },
                set: { draft.set("self_names", $0.split(separator: "、").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }) })
    }
    private var groups: Binding<String> {
        Binding(get: { (draft.value("groups") as? [String] ?? []).first ?? "" },
                set: { draft.set("groups", [$0.trimmingCharacters(in: .whitespaces)]) })
    }

    var muteRows: [ChatEntry] {
        var seen = Set<String>(), rows: [ChatEntry] = []
        func add(_ chat: ChatEntry) { if !chat.title.isEmpty, seen.insert(chat.title).inserted { rows.append(chat) } }
        for name in draft.value("groups") as? [String] ?? [] { add(ChatEntry(title: name, kind: "group")) }
        chats.forEach(add)
        for name in draft.value("muted_chats") as? [String] ?? [] { add(ChatEntry(title: name, kind: "unknown")) }
        return rows
    }
    func muteBinding(_ title: String) -> Binding<Bool> {
        Binding(get: { (draft.value("muted_chats") as? [String] ?? []).contains(title) },
                set: { on in
                    var list = (draft.value("muted_chats") as? [String] ?? []).filter { $0 != title }
                    if on { list.append(title) }
                    draft.set("muted_chats", list)
                })
    }
}

struct ProvidersPane: View {
    @ObservedObject var draft: ConfigDraft
    private let efforts = ["", "minimal", "low", "medium", "high"]
    var body: some View {
        PaneHeader(title: "AI 供应商", subtitle: "请使用原生多模态模型，支持文字与 image_url 图片输入、中文和 JSON 输出。回复判断、聊天、总结、压缩、浏览器、主动话题与空间评论均使用此模型。")
        FormCard {
            FormRow(label: "供应商名称", hint: "自定义显示名称，不影响请求地址。") { ClayField(text: draft.text("ai.name"), width: 220) }
            FormRow(label: "接口地址", hint: "OpenAI 兼容 /v1 基础地址，或完整 /chat/completions 地址。") { ClayField(text: draft.text("ai.base_url"), placeholder: "https://…/v1", mono: true) }
            FormRow(label: "API Key") { SecretField(text: draft.secret("ai.api_key"), configured: draft.hasSecret("ai.api_key")) }
            FormRow(label: "模型名称") { ClayField(text: draft.text("ai.model"), mono: true) }
            FormRow(label: "回复后缀", hint: "可留空；例如 ～AI。") { ClayField(text: draft.text("ai.suffix"), width: 160) }
            FormRow(label: "思考强度", hint: "留空由接口默认决定；不支持的可选参数会自动省略。") { Dropdown(options: efforts, selection: draft.text("ai.reasoning_effort"), width: 110) }
            FormRow(label: "请求超时") { NumberField(value: draft.number("ai.timeout_seconds", 60), unit: "秒", range: 5...300) }
            FormRow(label: "超时重试", last: true) { NumberField(value: draft.number("ai.timeout_retries", 1), unit: "次", range: 0...3) }
        }
        FormCard(title: "网页和主动话题") {
            FormRow(label: "启用浏览器任务", hint: "需先安装 requirements-browser.txt 与 Chromium；网页和视频分析仍使用此 AI。") { ClayToggle(isOn: draft.flag("browser.enabled", false)) }
            FormRow(label: "启用自动主动话题", hint: "群内沉默后可概率开场；手动主动话题按钮仍可用。") { ClayToggle(isOn: draft.flag("proactive_enabled", false)) }
            FormRow(label: "主动话题沉默阈值", last: true) { NumberField(value: draft.number("proactive_idle_seconds", 1800), unit: "秒", range: 60...86400) }
        }
    }
}

struct VisionPane: View {
    @ObservedObject var draft: ConfigDraft
    var body: some View {
        PaneHeader(title: "图片", subtitle: "识图会临时复制群里的新图片交给模型；生图需有人 @ 并明确提出要求，审核通过后才会生成。")
        FormCard(title: "发给模型的图片") {
            FormRow(label: "最长边上限", hint: "群里的图片发给模型前，超过这个像素的会先等比缩小，减小上传体积；不会放大；0 表示不缩小", last: true) {
                NumberField(value: draft.number("image_max_edge", 2048), unit: "像素", range: 0...8192)
            }
        }
        FormCard(title: "图片生成") {
            FormRow(label: "启用图片生成") { ClayToggle(isOn: draft.flag("image_generation.enabled", false)) }
            FormRow(label: "接口地址") { ClayField(text: draft.text("image_generation.endpoint"), mono: true) }
            FormRow(label: "模型") { ClayField(text: draft.text("image_generation.model"), width: 200, mono: true) }
            FormRow(label: "输出尺寸", hint: "格式为 宽*高，返回尺寸必须一致") { ClayField(text: draft.text("image_generation.size", "1920*1080"), width: 140, mono: true) }
            FormRow(label: "每人 24 小时上限") { NumberField(value: draft.number("image_generation.max_per_24h", 2), unit: "张") }
            FormRow(label: "API Key", last: true) { SecretField(text: draft.secret("image_generation.api_key"), configured: draft.hasSecret("image_generation.api_key")) }
        }
    }
}

struct SpacePane: View {
    @ObservedObject var draft: ConfigDraft
    @ObservedObject var space: SpaceViewModel
    var body: some View {
        PaneHeader(title: "QQ 空间", subtitle: "浏览好友动态，结合群聊风格点赞或评论；视频和不可读内容会跳过，已评论过的不会重复。沿用当前聊天模型。")
        Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    Chip(text: space.running ? (space.busy ? "处理中" : "运行中") : "未运行",
                         color: space.running ? CC.accentStrong : CC.textSecondary, soft: space.running ? CC.accentSoft : CC.sunken,
                         icon: space.running ? "play.fill" : "pause.fill")
                    Text(space.status).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary).lineLimit(2)
                    Spacer(minLength: 0)
                }
                HStack(spacing: 8) {
                    Button { space.onToggle() } label: {
                        Label(space.running ? "暂停自动浏览" : "开始自动浏览", systemImage: space.running ? "pause.fill" : "play.fill")
                    }
                    .buttonStyle(ClayButtonStyle(prominent: !space.running))
                    Button("打开 QQ 空间") { space.onOpen() }.buttonStyle(ClayButtonStyle(prominent: false)).disabled(space.busy)
                    Button("刷新动态") { space.onRefresh() }.buttonStyle(ClayButtonStyle(prominent: false)).disabled(space.busy)
                    Button("下一屏") { space.onNext() }.buttonStyle(ClayButtonStyle(prominent: false)).disabled(space.busy)
                    Spacer(minLength: 0)
                }
            }
        }
        FormCard(title: "最近动作") {
            if space.lines.isEmpty {
                Text("还没有记录。点“开始自动浏览”后，每一步（读取、判断、点赞、评论、确认）会显示在这里。")
                    .font(CCFont.pixel(12)).foregroundColor(CC.textTertiary).padding(14)
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(space.lines.suffix(14).reversed().enumerated()), id: \.offset) { _, line in
                        Text(line).font(CCFont.mono(11)).foregroundColor(CC.textSecondary).lineLimit(2).textSelection(.enabled)
                    }
                }
                .padding(14).frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        FormCard(title: "每日定时") {
            FormRow(label: "每天自动浏览一轮") { ClayToggle(isOn: draft.flag("qzone.schedule_enabled", true)) }
            FormRow(label: "开始时间", hint: "按下面的时区，晚于该时间启动会补跑当天一轮") { NumberField(value: draft.number("qzone.hour", 19), unit: "点", range: 0...23) }
            FormRow(label: "时区") { ClayField(text: draft.text("qzone.timezone", TimeZone.current.identifier), width: 170, mono: true) }
            FormRow(label: "处理间隔", hint: "每条动态之间的等待", last: true) { NumberField(value: draft.number("qzone.interval_seconds", 60), unit: "秒", range: 10...3600) }
        }
        Text("需要 QQ 与本程序保持运行，电脑唤醒并联网。QQ 在发送群聊消息时，空间操作会等待，不会抢着用输入框。")
            .font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
    }
}

struct DiagnosticsPane: View {
    @ObservedObject var model: AppModel
    @State private var trusted = AXIsProcessTrusted()
    @State private var qqRunning = NSRunningApplication.runningApplications(withBundleIdentifier: "com.tencent.qq").first != nil
    @State private var notifyText = "检测中…"
    @State private var notifyOK = false

    var body: some View {
        PaneHeader(title: "诊断", subtitle: "出问题时先看这里：权限、QQ 与后台是否正常，以及日志和配置文件的位置。")
        configCard
        FormCard(title: "运行条件") {
            check("辅助功能权限", trusted, trusted ? "已授权" : "未授权，无法读取和发送 QQ 消息（macOS 27 里叫“设备控制和数据访问”）")
            check("QQ 正在运行", qqRunning, qqRunning ? "已检测到" : "未检测到 QQ")
            check("回复后台", model.alive, model.alive ? "正常，状态每 2 秒刷新" : "超过 15 秒没有更新")
            check("系统通知", notifyOK, notifyText, last: true)
        }
        HStack(spacing: 8) {
            Button("重新检测") {
                trusted = AXIsProcessTrusted()
                qqRunning = NSRunningApplication.runningApplications(withBundleIdentifier: "com.tencent.qq").first != nil
                Notifier.status { notifyText = $0; notifyOK = $1 }
            }
            .buttonStyle(ClayButtonStyle(prominent: false))
            Button("辅助功能设置…") { model.control?.openPermissions() }.buttonStyle(ClayButtonStyle(prominent: false))
            Button("发送测试通知") {
                Notifier.post("QQ 自动回复", "这是一条测试通知", force: true)
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { Notifier.status { notifyText = $0; notifyOK = $1 } }
            }
            .buttonStyle(ClayButtonStyle(prominent: false))
            Button("通知设置…") {
                if let url = URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension") { NSWorkspace.shared.open(url) }
            }
            .buttonStyle(ClayButtonStyle(prominent: false))
            Spacer()
        }
        FormCard(title: "文件") {
            file("运行日志", "runtime/bridge.log")
            file("后台错误输出", "runtime/backend.log")
            file("配置文件", "config.json")
            file("项目文件夹", "", last: true)
        }
        Text("config.json 含 API Key，仅限本人读取（权限 0600）；请不要把它或日志发给他人。")
            .font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
            .onAppear { Notifier.status { notifyText = $0; notifyOK = $1 } }
    }

    @ViewBuilder private var configCard: some View {
        let errors = model.counters.configErrors, warnings = model.counters.configWarnings
        FormCard(title: "配置检查") {
            if errors.isEmpty && warnings.isEmpty {
                FormRow(label: "config.json", hint: "没有发现问题", last: true) {
                    PixelIcon( "checkmark.circle.fill").foregroundColor(CC.good)
                }
            } else {
                ForEach(Array((errors.map { ($0, true) } + warnings.map { ($0, false) }).enumerated()), id: \.offset) { index, item in
                    FormRow(label: item.0, last: index == errors.count + warnings.count - 1) {
                        PixelIcon( item.1 ? "xmark.octagon.fill" : "exclamationmark.triangle.fill")
                            .foregroundColor(item.1 ? CC.bad : CC.warn)
                    }
                }
            }
        }
    }

    private func check(_ title: String, _ ok: Bool, _ detail: String, last: Bool = false) -> some View {
        FormRow(label: title, hint: detail, last: last) {
            PixelIcon( ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill").foregroundColor(ok ? CC.good : CC.bad)
        }
    }
    private func file(_ title: String, _ path: String, last: Bool = false) -> some View {
        FormRow(label: title, hint: path.isEmpty ? nil : path, last: last) {
            Button("打开") {
                if let base = model.control?.baseURL { NSWorkspace.shared.open(path.isEmpty ? base : base.appendingPathComponent(path)) }
            }
            .buttonStyle(ClayButtonStyle(prominent: false, compact: true))
        }
    }
}

/// Shows the full style summary inline when asked (it is long).
private struct StyleTextButton: View {
    let text: String
    var empty = "（还没有总结）"
    @State private var open = false
    var body: some View {
        VStack(alignment: .trailing, spacing: 6) {
            Button(open ? "收起" : "展开") { open.toggle() }.buttonStyle(ClayButtonStyle(prominent: false, compact: true))
            if open {
                ScrollView {
                    Text(text.isEmpty ? empty : text).font(CCFont.pixel(12)).foregroundColor(CC.textSecondary)
                        .frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
                }
                .frame(width: 420, height: 220).padding(8).pixelPanel(CC.sunken)
            }
        }
    }
}

