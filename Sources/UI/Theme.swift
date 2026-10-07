import SwiftUI
import AppKit

// MARK: - Palette (warm ivory / clay, light + dark)

extension NSColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1) {
        self.init(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }
}

extension Color {
    init(light: UInt32, dark: UInt32) {
        self.init(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return NSColor(hex: isDark ? dark : light)
        })
    }
}

enum CC {
    // Night-ice palette: ink-blue darks, moon-white lights, frost-cyan accent, amber/mint/red status lamps.
    static let background = Color(light: 0xF3F5F9, dark: 0x12151C)
    static let sidebar = Color(light: 0xE8ECF3, dark: 0x0D1016)
    static let card = Color(light: 0xFFFFFF, dark: 0x1A1F2A)
    static let sunken = Color(light: 0xEBEFF5, dark: 0x151923)
    static let border = Color(light: 0xD7DDE8, dark: 0x2A3142)
    static let text = Color(light: 0x141A26, dark: 0xE9EDF5)
    static let textSecondary = Color(light: 0x49546A, dark: 0xA7B0C3)
    static let textTertiary = Color(light: 0x76819A, dark: 0x7A859C)
    static let accent = Color(light: 0x1F8FB0, dark: 0x6FD3E8)
    static let accentStrong = Color(light: 0x167593, dark: 0x8EE0F0)
    static let accentSoft = Color(light: 0xDAF0F6, dark: 0x163039)
    static let good = Color(light: 0x2E8B57, dark: 0x7FD99A)
    static let goodSoft = Color(light: 0xDDF1E5, dark: 0x1B3325)
    static let info = Color(light: 0x3E78B0, dark: 0x7AB8E8)
    static let infoSoft = Color(light: 0xDEE9F5, dark: 0x1C2C40)
    static let warn = Color(light: 0xAD7A12, dark: 0xF2C94C)
    static let warnSoft = Color(light: 0xF6EBCB, dark: 0x3A3114)
    static let bad = Color(light: 0xC0392B, dark: 0xFF7A7A)
    static let badSoft = Color(light: 0xF8DFDB, dark: 0x3D1F22)
    /// The fixed dark tile behind the logo (same in light and dark mode, like an app icon).
    static let shadow = Color(light: 0xC5CCDB, dark: 0x080A0E)
    static let tile = Color(hex: 0x141822)
    static let tileEdge = Color(hex: 0x2B3345)
}

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

enum CCFont {
    static let pixelName = "Ark-Pixel-12px-Prop-zh-Hans-Regular"
    /// Ark Pixel is a 12 px bitmap font: only multiples of 12 pt (12, 24) stay crisp.
    static func pixel(_ size: CGFloat = 12) -> Font { .custom(pixelName, fixedSize: size) }
    static func title(_ size: CGFloat = 17) -> Font { size >= 20 ? pixel(24) : pixel(12) }
    static func body(_ size: CGFloat = 13, _ weight: Font.Weight = .regular) -> Font { pixel(12) }
    static func mono(_ size: CGFloat = 11) -> Font { pixel(12) }

    /// Registers the bundled pixel font for this process (a no-op when it is missing: text falls back to the system font).
    static func register(extra: URL? = nil) {
        var candidates = [Bundle.main.url(forResource: "ArkPixel12", withExtension: "otf")].compactMap { $0 }
        if let extra { candidates.append(extra) }
        for url in candidates { if CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil) { return } }
    }
}

// MARK: - Logo: a "Q" with wolf ears (pixel art, 16 x 16)

enum WolfArt {
    /// '#' body, 'c' accent (the tail of the Q). Keep in sync with tools/make_icon.py.
    static let rows = [
        "................",
        "..##........##..",
        "..###......###..",
        "..####.##.####..",
        "..############..",
        ".####......####.",
        ".###........###.",
        ".###........###.",
        ".###........###.",
        ".####......####.",
        "..####....#####.",
        "...##########cc.",
        "....########.ccc",
        "..............cc",
        "................",
        "................",
    ]
}

/// The logo on its fixed dark tile.
struct WolfMark: View {
    var body: some View {
        GeometryReader { proxy in
            let size = min(proxy.size.width, proxy.size.height)
            ZStack {
                RoundedRectangle(cornerRadius: size * 0.24, style: .continuous).fill(CC.tile)
                RoundedRectangle(cornerRadius: size * 0.24, style: .continuous).strokeBorder(CC.tileEdge, lineWidth: max(1, size * 0.04))
                Canvas { context, canvas in
                    let cell = (canvas.width * 0.78) / 16
                    let origin = (canvas.width - cell * 16) / 2
                    for (y, row) in WolfArt.rows.enumerated() {
                        for (x, ch) in row.enumerated() where ch != "." {
                            let rect = CGRect(x: origin + CGFloat(x) * cell, y: origin + CGFloat(y) * cell, width: cell + 0.5, height: cell + 0.5)
                            context.fill(Path(rect), with: .color(ch == "c" ? Color(hex: 0x6FD3E8) : Color(hex: 0xEEF2FA)))
                        }
                    }
                }
            }
            .frame(width: size, height: size)
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

/// Template image for the menu bar: the logo at 1 pt per pixel, with a "!" in the ring when the bot needs attention
/// and a dithered (dimmed) look when paused.
enum MenuBarIcon {
    static func image(attention: Bool, dim: Bool) -> NSImage {
        let image = NSImage(size: NSSize(width: 16, height: 16), flipped: true) { _ in
            NSColor.black.setFill()
            var rows = WolfArt.rows.map { Array($0) }
            if attention {
                for (x, y) in [(7, 6), (8, 6), (7, 7), (8, 7), (7, 8), (8, 8), (7, 10), (8, 10)] { rows[y][x] = "#" }
            }
            for (y, row) in rows.enumerated() {
                for (x, ch) in row.enumerated() where ch != "." && !(dim && (x + y) % 2 == 0) {
                    NSRect(x: x, y: y, width: 1, height: 1).fill()
                }
            }
            return true
        }
        image.isTemplate = true
        return image
    }
}

// MARK: - Building blocks

struct Card<Content: View>: View {
    var padding: CGFloat = 12
    var fill: Color = CC.card
    @ViewBuilder var content: Content
    var body: some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(PixelRect().fill(fill))
            .overlay(PixelRect().strokeBorder(CC.border, lineWidth: 1))
    }
}

struct Chip: View {
    var text: String
    var color: Color
    var soft: Color
    var icon: String? = nil
    var body: some View {
        HStack(spacing: 3) {
            if let icon { PixelIcon( icon).font(CCFont.pixel(12)) }
            Text(text).font(CCFont.pixel(12))
        }
        .foregroundColor(color)
        .padding(.horizontal, 6).padding(.vertical, 1.5)
        .background(PixelRect().fill(soft))
    }
}

/// A square pixel lamp. Busy lamps blink in whole steps (bright / dim) like a console LED instead of fading.
struct PixelLED: View {
    var color: Color
    var blinking = false
    var size: CGFloat = 8
    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.5)) { context in
            let on = !blinking || Int(context.date.timeIntervalSinceReferenceDate * 2) % 2 == 0
            ZStack {
                Rectangle().fill(color.opacity(on ? 1 : 0.28))
                Rectangle().fill(Color.white.opacity(on ? 0.45 : 0.1)).frame(width: size * 0.25, height: size * 0.25)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).padding(size * 0.15)
            }
            .frame(width: size, height: size)
            .overlay(Rectangle().strokeBorder(Color.black.opacity(0.25), lineWidth: 1))
        }
        .frame(width: size, height: size)
    }
}

/// Segmented "health bar": `filled` of `count` square cells, optionally blinking the next cell.
struct PixelBar: View {
    var count: Int
    var filled: Int
    var color: Color
    var activeIndex: Int? = nil
    var failedIndex: Int? = nil
    var cell: CGFloat = 10
    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.5)) { context in
            let blink = Int(context.date.timeIntervalSinceReferenceDate * 2) % 2 == 0
            HStack(spacing: 2) {
                ForEach(0..<count, id: \.self) { index in
                    Rectangle()
                        .fill(fill(index, blink: blink))
                        .frame(height: cell * 0.6)
                        .overlay(Rectangle().strokeBorder(CC.border.opacity(index < filled ? 0 : 1), lineWidth: 1))
                }
            }
        }
    }
    private func fill(_ index: Int, blink: Bool) -> Color {
        if index == failedIndex { return CC.bad }
        if index < filled { return color }
        if index == activeIndex { return blink ? CC.accent : CC.accent.opacity(0.3) }
        return CC.sunken
    }
}

struct ClayButtonStyle: ButtonStyle {
    var prominent = true
    var compact = false
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(CCFont.pixel(12))
            .foregroundColor(prominent ? Color(light: 0xFFFFFF, dark: 0x0D1016) : CC.text)
            .padding(.horizontal, compact ? 10 : 14).padding(.vertical, compact ? 5 : 7)
            .background(PixelRect()
                .fill(prominent ? (configuration.isPressed ? CC.accentStrong : CC.accent) : (configuration.isPressed ? CC.sunken : CC.card)))
            .overlay(PixelRect()
                .strokeBorder(prominent ? Color.clear : CC.border, lineWidth: 1))
            .opacity(!isEnabled ? 0.45 : configuration.isPressed ? 0.92 : 1)
    }
}

struct GhostIconStyle: ButtonStyle {
    var active = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(CCFont.pixel(12))
            .foregroundColor(active ? CC.accentStrong : CC.textSecondary)
            .frame(width: 26, height: 26)
            .background(PixelRect()
                .fill(active ? CC.accentSoft : (configuration.isPressed ? CC.sunken : Color.clear)))
    }
}

/// Segmented control with the warm card look.
struct Segmented<T: Hashable>: View {
    var options: [(T, String)]
    @Binding var selection: T
    var body: some View {
        HStack(spacing: 2) {
            ForEach(options, id: \.0) { value, label in
                let on = value == selection
                Button { withAnimation(.easeOut(duration: 0.15)) { selection = value } } label: {
                    Text(label).font(CCFont.pixel(12))
                        .foregroundColor(on ? CC.text : CC.textSecondary)
                        .frame(maxWidth: .infinity).padding(.vertical, 5)
                        .background(PixelRect().fill(on ? CC.card : Color.clear)
                            .shadow(color: Color.black.opacity(on ? 0.08 : 0), radius: 1.5, y: 1))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(2)
        .background(PixelRect().fill(CC.sunken))
    }
}

struct SectionLabel: View {
    var text: String
    var trailing: String? = nil
    var body: some View {
        HStack {
            Text(text).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary)
            Spacer()
            if let trailing { Text(trailing).font(CCFont.pixel(12)).foregroundColor(CC.textTertiary) }
        }
    }
}

// MARK: - Formatting

enum Format {
    static func count(_ value: Double) -> String { value == value.rounded() ? String(Int(value)) : String(format: "%.1f", value) }
    /// 12345 -> "12.3k", 2_300_000 -> "2.3M"
    static func compact(_ value: Double) -> String {
        value >= 1_000_000 ? String(format: "%.1fM", value / 1_000_000) : value >= 1000 ? String(format: "%.1fk", value / 1000) : String(Int(value))
    }
    static func ago(_ time: Double, now: Date = Date()) -> String {
        let seconds = max(0, now.timeIntervalSince1970 - time)
        if seconds < 5 { return "刚刚" }
        if seconds < 60 { return "\(Int(seconds)) 秒前" }
        if seconds < 3600 { return "\(Int(seconds / 60)) 分钟前" }
        if seconds < 86_400 { return "\(Int(seconds / 3600)) 小时前" }
        return "\(Int(seconds / 86_400)) 天前"
    }
    static func elapsed(since time: Double, now: Date = Date()) -> String {
        let seconds = max(0, Int(now.timeIntervalSince1970 - time))
        return seconds >= 3600 ? String(format: "%d:%02d:%02d", seconds / 3600, seconds % 3600 / 60, seconds % 60)
                               : String(format: "%d:%02d", seconds / 60, seconds % 60)
    }
    static func clock(_ time: Double) -> String {
        let formatter = DateFormatter(); formatter.dateFormat = "HH:mm:ss"
        return formatter.string(from: Date(timeIntervalSince1970: time))
    }
    static func seconds(_ value: Double?) -> String? { value.map { String(format: "%.1fs", $0) } }
    static func tokens(_ value: Int) -> String { value >= 10_000 ? String(format: "%.1fk", Double(value) / 1000) : "\(value)" }
}
