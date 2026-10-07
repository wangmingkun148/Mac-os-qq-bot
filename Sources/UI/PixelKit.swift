import SwiftUI

// MARK: - Pixel shapes, icons and controls (the whole UI is built from these: no smooth curves)

/// Rectangle with stair-stepped corners: one "pixel" (2 pt) is cut from each corner.
struct PixelRect: InsettableShape {
    var inset: CGFloat = 0
    var notch: CGFloat = 4
    func inset(by amount: CGFloat) -> PixelRect { PixelRect(inset: inset + amount, notch: notch) }
    /// Two-step stair corners (each step is notch / 2 = 2 pt).
    func path(in rect: CGRect) -> Path {
        let r = rect.insetBy(dx: inset, dy: inset), n = min(notch, r.width / 4, r.height / 4), h = n / 2
        func pts(_ list: [(CGFloat, CGFloat)]) -> [CGPoint] { list.map { CGPoint(x: $0.0, y: $0.1) } }
        let l = r.minX, t = r.minY, rt = r.maxX, b = r.maxY
        let points = pts([
            (l + n, t), (rt - n, t), (rt - n, t + h), (rt - h, t + h), (rt - h, t + n), (rt, t + n),
            (rt, b - n), (rt - h, b - n), (rt - h, b - h), (rt - n, b - h), (rt - n, b),
            (l + n, b), (l + n, b - h), (l + h, b - h), (l + h, b - n), (l, b - n),
            (l, t + n), (l + h, t + n), (l + h, t + h), (l + n, t + h),
        ])
        var p = Path(); p.addLines(points); p.closeSubpath()
        return p
    }
}

/// A pixel panel: fill, hard 1 pt border and an optional offset "drop" block behind it.
struct PixelPanel: ViewModifier {
    var fill: Color
    var border: Color = CC.border
    var shadow = false
    func body(content: Content) -> some View {
        content
            .background(PixelRect().fill(fill))
            .overlay(PixelRect().strokeBorder(border, lineWidth: 1))
            .background(shadow ? PixelRect().fill(CC.shadow).offset(x: 2, y: 2) : nil)
    }
}
extension View {
    func pixelPanel(_ fill: Color = CC.card, border: Color = CC.border, shadow: Bool = false) -> some View {
        modifier(PixelPanel(fill: fill, border: border, shadow: shadow))
    }
}

// MARK: Icons

enum PixelIcons {
    static let alias: [String: String] = [
        "play.fill": "play", "pause.fill": "pause", "pause.circle": "pause.circle", "checkmark.circle.fill": "check.circle",
        "exclamationmark.triangle": "warn", "exclamationmark.triangle.fill": "warn", "xmark.octagon.fill": "xmark.box",
        "bubble.left.and.bubble.right": "bubble", "bubble.left": "bubble", "bubble.left.and.exclamationmark.bubble.right": "bubble.alert",
        "arrowshape.turn.up.left.fill": "reply", "circle.fill": "dot", "safari": "globe", "network": "globe", "gearshape": "gear",
        "shield.lefthalf.filled": "shield", "pin.fill": "pin.fill", "stethoscope": "heart", "moon.zzz": "moon",
        "chevron.up.chevron.down": "updown", "rectangle.on.rectangle": "windows", "circle.grid.2x2": "grid",
        "list.bullet": "list", "slider.horizontal.3": "sliders", "checkmark": "check", "photo": "photo", "sparkles": "star",
    ]
    static let art: [String: [String]] = [
        "play": ["#........", "###......", "#####....", "#######..", "#########", "#######..", "#####....", "###......", "#........"],
        "pause": [".##...##.", ".##...##.", ".##...##.", ".##...##.", ".##...##.", ".##...##.", ".##...##."],
        "power": ["....#....", "....#....", ".#..#..#.", "#...#...#", "#.......#", "#.......#", ".#.....#.", "..#####.."],
        "ellipsis": ["##.##.##", "##.##.##"],
        "chevron.right": ["##..", ".##.", "..##", ".##.", "##.."],
        "caret.up": ["..#..", ".###.", "#####"],
        "caret.down": ["#####", ".###.", "..#.."],
        "updown": ["..#..", ".#.#.", "#...#", ".....", "#...#", ".#.#.", "..#.."],
        "check": [".......#", "......##", "#....##.", "##..##..", ".####...", "..##...."],
        "minus": ["#####", "#####"],
        "exclamationmark": ["##", "##", "##", "##", "..", "##", "##"],
        "questionmark": [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."],
        "xmark": ["#...#", "##.##", ".###.", "..#..", ".###.", "##.##", "#...#"],
        "hourglass": ["#######", ".#####.", "..###..", "...#...", "..#.#..", ".#...#.", "#######"],
        "dot": [".###.", "#####", "#####", "#####", ".###."],
        "list": ["#.#####", ".......", "#.#####", ".......", "#.#####"],
        "pin": ["..###..", "..#.#..", "..#.#..", ".#####.", "...#...", "...#...", "...#..."],
        "pin.fill": ["..###..", "..###..", "..###..", ".#####.", "...#...", "...#...", "...#..."],
        "bubble": ["#########", "#.......#", "#.......#", "#.......#", "#########", "..#......", ".#......."],
        "bubble.alert": ["#########", "#...#...#", "#...#...#", "#.......#", "#########", "..#......", ".#......."],
        "reply": ["...#...", "..##...", ".######", "..##...", "...#..."],
        "moon": ["..###.", ".#....", "#.....", "#.....", ".#....", "..###."],
        "warn": ["....#....", "...###...", "...#.#...", "..##.##..", "..##.##..", ".#######.", ".###.###.", "#########"],
        "xmark.box": ["..#####..", ".#######.", "#########", "##.###.##", "###.#.###", "####.####", "###.#.###", "##.###.##", "#########", ".#######.", "..#####.."],
        "check.circle": ["..#####..", ".#######.", "######.##", "#####.###", "##.#.####", "###.#####", "#########", ".#######.", "..#####.."],
        "pause.circle": ["..#####..", ".#######.", "###.#.###", "###.#.###", "###.#.###", "###.#.###", "###.#.###", ".#######.", "..#####.."],
        "windows": ["..######", "..#....#", "######.#", "#....#.#", "#....###", "#....#..", "######.."],
        "sliders": [".##......", "#########", ".##......", "......##.", "#########", "......##.", "...##....", "#########", "...##...."],
        "grid": ["###.###", "###.###", "###.###", ".......", "###.###", "###.###", "###.###"],
        "cpu": ["..#.#..", ".#####.", "##...##", ".#...#.", "##...##", ".#####.", "..#.#.."],
        "globe": ["..###..", ".#.#.#.", "#..#..#", "#######", "#..#..#", ".#.#.#.", "..###.."],
        "photo": ["#########", "#.....#.#", "#..#....#", "#.###...#", "#########", "#########"],
        "heart": [".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."],
        "gear": ["....#....", ".#..#..#.", "..#####..", "..#...#..", "###...###", "..#...#..", "..#####..", ".#..#..#.", "....#...."],
        "flame": ["...#...", "..##...", "..###.#", ".#####.", "#######", "#######", ".#####.", "..###.."],
        "shield": ["#######", "####..#", "####..#", "####..#", ".####.#", "..###..", "...#..."],
        "star": ["...#...", "...#...", "..###..", "#######", "..###..", "...#...", "...#..."],
        "ear": ["..#....", ".###...", ".####..", "######.", "#####..", ".###..."],
        "thumbs.up": ["....#....", "...##....", "..###....", "#.######.", "#.#######", "#.######.", "#.#######", "#.######."],
        "thumbs.down": ["#.######.", "#.#######", "#.######.", "#.#######", "#.######.", "..###....", "...##....", "....#...."],
        "person": ["..###..", ".#####.", ".#####.", "..###..", ".......", ".#####.", "#######", "#######"],
        "square": ["#####", "#...#", "#...#", "#...#", "#####"],
    ]
}

/// A pixel-art stand-in for an SF Symbol (same names), drawn in the current foreground colour.
struct PixelIcon: View {
    let name: String
    var scale: CGFloat = 1.5
    init(_ name: String, scale: CGFloat = 1.5) { self.name = name; self.scale = scale }
    var body: some View {
        let key = PixelIcons.alias[name] ?? name
        let rows = (PixelIcons.art[key] ?? PixelIcons.art["square"]!).map { Array($0) }
        let width = rows.map(\.count).max() ?? 1
        Canvas { context, _ in
            for (y, row) in rows.enumerated() {
                for (x, ch) in row.enumerated() where ch == "#" {
                    context.fill(Path(CGRect(x: CGFloat(x) * scale, y: CGFloat(y) * scale, width: scale, height: scale)), with: .foreground)
                }
            }
        }
        .frame(width: CGFloat(width) * scale, height: CGFloat(rows.count) * scale)
    }
}

// MARK: Controls

struct PixelToggleStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 8) {
            configuration.label
            Button { configuration.isOn.toggle() } label: {
                ZStack(alignment: configuration.isOn ? .trailing : .leading) {
                    PixelRect().fill(configuration.isOn ? CC.accent : CC.sunken)
                    PixelRect().strokeBorder(configuration.isOn ? CC.accentStrong : CC.border, lineWidth: 1)
                    Rectangle().fill(configuration.isOn ? Color(light: 0xFFFFFF, dark: 0x0D1016) : CC.textTertiary)
                        .frame(width: 10, height: 10).padding(3)
                }
                .frame(width: 34, height: 16)
            }
            .buttonStyle(.plain)
        }
    }
}

struct PixelStepper: View {
    @Binding var value: Int
    var range: ClosedRange<Int>
    var body: some View {
        HStack(spacing: 2) {
            stepButton("minus") { value = max(range.lowerBound, value - 1) }
            stepButton("+") { value = min(range.upperBound, value + 1) }
        }
    }
    private func stepButton(_ glyph: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Group {
                if glyph == "minus" { PixelIcon("minus") } else { Text("+").font(CCFont.pixel(12)) }
            }
            .foregroundColor(CC.textSecondary).frame(width: 20, height: 22).pixelPanel(CC.card)
        }
        .buttonStyle(.plain)
    }
}

/// A dropdown that opens as an inline list (the system pop-up menu is not pixel art).
struct PixelDropdown<Item: Hashable>: View {
    var items: [Item]
    var title: (Item) -> String
    var selected: Item?
    var disabled: (Item) -> Bool = { _ in false }
    var width: CGFloat? = nil
    var onSelect: (Item) -> Void
    @State private var open = false
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Button { open.toggle() } label: {
                HStack(spacing: 6) {
                    Text(selected.map(title) ?? "未设置").font(CCFont.pixel(12)).lineLimit(1)
                    Spacer(minLength: 4)
                    PixelIcon("updown").foregroundColor(CC.textTertiary)
                }
                .padding(.horizontal, 8).padding(.vertical, 5).frame(width: width)
                .pixelPanel(CC.sunken, border: open ? CC.accent : CC.border)
            }
            .buttonStyle(.plain)
            if open {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(items, id: \.self) { item in
                        Button { onSelect(item); open = false } label: {
                            HStack(spacing: 6) {
                                Text(title(item)).font(CCFont.pixel(12)).lineLimit(1)
                                Spacer(minLength: 4)
                                if item == selected { PixelIcon("check").foregroundColor(CC.accent) }
                            }
                            .foregroundColor(disabled(item) ? CC.textTertiary : CC.text)
                            .padding(.horizontal, 8).padding(.vertical, 4).frame(maxWidth: .infinity, alignment: .leading)
                            .background(item == selected ? CC.accentSoft : Color.clear).contentShape(Rectangle())
                        }
                        .buttonStyle(.plain).disabled(disabled(item))
                    }
                }
                .frame(width: width).pixelPanel(CC.card, shadow: true)
            }
        }
        .fixedSize(horizontal: width == nil, vertical: true)
    }
}
