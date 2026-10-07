import SwiftUI

/// Editable copy of config.json addressed by dotted paths ("ai.model").
final class ConfigDraft: ObservableObject {
    @Published private(set) var data: [String: Any] = [:]
    @Published var secrets: [String: String] = [:]
    private var original: [String: Any] = [:]

    func load(_ config: [String: Any]) {
        original = config
        data = config
        secrets = [:]
    }

    var dirty: Bool {
        !NSDictionary(dictionary: data).isEqual(to: original) || secrets.values.contains { !$0.isEmpty }
    }

    /// Draft with typed-in secrets merged in; this is what gets saved.
    var result: [String: Any] {
        var merged = data
        for (path, value) in secrets where !value.isEmpty { Self.set(&merged, path.split(separator: ".").map(String.init), value) }
        return merged
    }

    func value(_ path: String) -> Any? {
        var current: Any? = data
        for key in path.split(separator: ".") { current = (current as? [String: Any])?[String(key)] }
        return current
    }
    func string(_ path: String, _ fallback: String = "") -> String { value(path) as? String ?? fallback }
    func bool(_ path: String, _ fallback: Bool) -> Bool { value(path) as? Bool ?? fallback }
    func int(_ path: String, _ fallback: Int) -> Int { (value(path) as? NSNumber)?.intValue ?? fallback }

    func set(_ path: String, _ value: Any) {
        var copy = data
        Self.set(&copy, path.split(separator: ".").map(String.init), value)
        data = copy
    }

    private static func set(_ dict: inout [String: Any], _ keys: [String], _ value: Any) {
        guard let first = keys.first else { return }
        if keys.count == 1 { dict[first] = value; return }
        var child = dict[first] as? [String: Any] ?? [:]
        set(&child, Array(keys.dropFirst()), value)
        dict[first] = child
    }

    func text(_ path: String, _ fallback: String = "") -> Binding<String> {
        Binding(get: { self.string(path, fallback) }, set: { self.set(path, $0) })
    }
    func flag(_ path: String, _ fallback: Bool) -> Binding<Bool> {
        Binding(get: { self.bool(path, fallback) }, set: { self.set(path, $0) })
    }
    func number(_ path: String, _ fallback: Int) -> Binding<Int> {
        Binding(get: { self.int(path, fallback) }, set: { self.set(path, $0) })
    }
    func secret(_ path: String) -> Binding<String> {
        Binding(get: { self.secrets[path] ?? "" }, set: { self.secrets[path] = $0 })
    }
    func hasSecret(_ path: String) -> Bool { !string(path).isEmpty }
}
