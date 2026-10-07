import SwiftUI

/// Notes about group members, kept in runtime/people.json (read by the backend for each reply).
/// Matched by display name; one person may have several names, so a rename only needs the new name added.
struct Person: Identifiable, Codable, Equatable {
    var id = UUID().uuidString
    var names: [String] = []
    var callAs = ""
    var about = ""
    var notes = ""
    /// Written by the first automatic draft and not edited since.
    var drafted: Bool? = nil

    enum CodingKeys: String, CodingKey { case id, names, callAs = "call_as", about, notes, drafted }
}

final class PeopleStore: ObservableObject {
    @Published var people: [Person] = [] { didSet { if loaded { scheduleSave() } } }
    @Published private(set) var savedAt: Date?
    private var path: URL?
    private var loaded = false
    private var pending: DispatchWorkItem?

    private struct File: Codable { var version = 1; var people: [Person] }

    func load(base: URL) {
        let url = base.appendingPathComponent("runtime/people.json")
        guard path != url else { return }
        loaded = false
        path = url
        if let data = try? Data(contentsOf: url), let file = try? JSONDecoder().decode(File.self, from: data) { people = file.people }
        loaded = true
    }

    func add(name: String = "") {
        people.insert(Person(names: name.isEmpty ? [] : [name]), at: 0)
    }
    func remove(_ id: String) { people.removeAll { $0.id == id } }
    /// Any edit by hand turns a draft into the owner's own note.
    func update(_ id: String, _ change: (inout Person) -> Void) {
        guard let index = people.firstIndex(where: { $0.id == id }) else { return }
        var person = people[index]
        change(&person)
        person.drafted = nil
        people[index] = person
    }

    func knows(_ name: String) -> Bool {
        let key = name.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        return people.contains { $0.names.contains { $0.split(whereSeparator: \.isWhitespace).joined(separator: " ") == key } }
    }

    private func scheduleSave() {
        pending?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.save() }
        pending = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6, execute: work)
    }
    func save() {
        guard let path else { return }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? encoder.encode(File(people: people)) else { return }
        try? data.write(to: path, options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        savedAt = Date()
    }
}

// MARK: - Settings page

struct PeoplePane: View {
    @ObservedObject var store: PeopleStore
    var recentNames: [String]

    var body: some View {
        PaneHeader(title: "群友备注", subtitle: "按群里显示的昵称对上人。模型回复某人时会看到他的备注，只当背景参考，回复里不会提到备注。改动自动保存。")
        HStack(spacing: 8) {
            Button { store.add() } label: { HStack(spacing: 5) { Text("+"); Text("新增群友") } }
                .buttonStyle(ClayButtonStyle(prominent: true))
            Spacer()
            if store.savedAt != nil { Text("已保存").font(CCFont.pixel(12)).foregroundColor(CC.textTertiary) }
        }
        let unknown = recentNames.filter { !store.knows($0) }
        if !unknown.isEmpty {
            FormCard(title: "最近发言、还没有备注的人") {
                FlowRow(items: unknown) { name in
                    Button { store.add(name: name) } label: { Text("+ " + name).font(CCFont.pixel(12)) }
                        .buttonStyle(ClayButtonStyle(prominent: false, compact: true))
                }
                .padding(14)
            }
        }
        if store.people.isEmpty {
            Text("还没有备注。点“新增群友”，或从上面最近发言的人里添加。")
                .font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
        }
        ForEach(store.people) { person in PersonCard(person: person, store: store) }
    }
}

private struct PersonCard: View {
    let person: Person
    @ObservedObject var store: PeopleStore

    private func binding(_ keyPath: WritableKeyPath<Person, String>) -> Binding<String> {
        Binding(get: { store.people.first { $0.id == person.id }?[keyPath: keyPath] ?? "" },
                set: { value in store.update(person.id) { $0[keyPath: keyPath] = value } })
    }
    private var names: Binding<String> {
        Binding(get: { (store.people.first { $0.id == person.id }?.names ?? []).joined(separator: "，") },
                set: { value in
                    let list = value.split(whereSeparator: { "，,、\n".contains($0) }).map { String($0).trimmingCharacters(in: .whitespaces) }
                    store.update(person.id) { $0.names = list.filter { !$0.isEmpty } }
                })
    }

    var body: some View {
        FormCard(title: person.names.first ?? "新群友") {
            if person.drafted == true {
                FormRow(label: "这张是根据聊天记录自动写的草稿", hint: "请核对；改动任何一项后就算你自己的备注") {
                    Chip(text: "草稿", color: CC.warn, soft: CC.warnSoft)
                }
            }
            FormRow(label: "昵称", hint: "群里显示的名字，可以填多个，用逗号隔开；有人改名就把新名字加上") {
                ClayField(text: names, placeholder: "例如：June，小六", width: 300)
            }
            FormRow(label: "怎么称呼", hint: "机器人叫他时用的称呼；留空就不特别称呼") {
                ClayField(text: binding(\.callAs), placeholder: "例如：老冯", width: 300)
            }
            FormRow(label: "他是谁", hint: "在群里的身份、常聊的话题、和谁比较熟") { NoteField(text: binding(\.about)) }
            FormRow(label: "说话注意", hint: "他喜欢或不喜欢的玩笑、不要碰的话题") { NoteField(text: binding(\.notes)) }
            FormRow(label: "删除这张备注", last: true) {
                Button("删除") { store.remove(person.id) }.buttonStyle(ClayButtonStyle(prominent: false, compact: true))
            }
        }
    }
}

private struct NoteField: View {
    @Binding var text: String
    var body: some View {
        TextField("", text: $text, axis: .vertical)
            .textFieldStyle(.plain).font(CCFont.pixel(12)).lineLimit(2...5)
            .padding(.horizontal, 8).padding(.vertical, 5)
            .frame(width: 300, alignment: .leading)
            .pixelPanel(CC.sunken)
    }
}

/// Simple wrapping row of small views.
struct FlowRow<Item: Hashable, Content: View>: View {
    var items: [Item]
    @ViewBuilder var content: (Item) -> Content
    var body: some View {
        FlowLayout(spacing: 6) { ForEach(items, id: \.self) { content($0) } }
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 600
        var x: CGFloat = 0, y: CGFloat = 0, row: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width { x = 0; y += row + spacing; row = 0 }
            x += size.width + spacing; row = max(row, size.height)
        }
        return CGSize(width: width, height: y + row)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, row: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX { x = bounds.minX; y += row + spacing; row = 0 }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing; row = max(row, size.height)
        }
    }
}
