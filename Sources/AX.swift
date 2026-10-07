import Cocoa
import ApplicationServices

func providerConfigured(_ api: [String:Any]) -> Bool { AppModel.configured(api) }

func ax(_ e: AXUIElement, _ key: String) -> AnyObject? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(e, key as CFString, &value) == .success else { return nil }
    return value
}
func string(_ e: AXUIElement, _ key: String) -> String { ax(e, key) as? String ?? "" }
func children(_ e: AXUIElement) -> [AXUIElement] { (ax(e, "AXChildren") as? [AXUIElement] ?? []).filter { !CFEqual($0,e) } }
func find(_ e: AXUIElement, depth: Int = 0, _ match: (AXUIElement) -> Bool) -> AXUIElement? {
    if match(e) { return e }
    guard depth < 42 else { return nil }
    for c in children(e) { if let hit = find(c, depth: depth + 1, match) { return hit } }
    return nil
}
func messageImage(_ e: AXUIElement, depth: Int = 0) -> AXUIElement? {
    if (ax(e,"AXDOMClassList") as? [String] ?? []).contains("reply-element") { return nil }
    if string(e,"AXRole") == "AXImage" { return e }
    guard depth < 42 else { return nil }
    for child in children(e) {
        if let image=messageImage(child,depth:depth+1) { return image }
    }
    return nil
}
func pressReturnKey() {
    let down=CGEvent(keyboardEventSource:nil,virtualKey:36,keyDown:true)
    let up=CGEvent(keyboardEventSource:nil,virtualKey:36,keyDown:false)
    down?.post(tap:.cghidEventTap);up?.post(tap:.cghidEventTap)
}
func tree(_ e: AXUIElement, depth: Int = 0) -> [String: Any] {
    var result: [String: Any] = ["role": string(e,"AXRole")]
    for (key, attr) in [("title","AXTitle"),("desc","AXDescription"),("value","AXValue"),("identifier","AXIdentifier"),("domId","AXDOMIdentifier")] {
        let v = string(e,attr); if !v.isEmpty { result[key] = v }
    }
    if let classes=ax(e,"AXDOMClassList") as? [String], !classes.isEmpty {result["classes"]=classes}
    if depth < 42 { let cs = children(e); if !cs.isEmpty { result["children"] = cs.map { tree($0,depth:depth+1) } } }
    return result
}

// MARK: - Geometry, mouse, keyboard and clipboard helpers

/// Screen rectangle of an element; nil unless both position and size can be read.
func frame(_ e: AXUIElement) -> CGRect? {
    guard let position=ax(e,"AXPosition"),let size=ax(e,"AXSize"),
          CFGetTypeID(position)==AXValueGetTypeID(),CFGetTypeID(size)==AXValueGetTypeID() else {return nil}
    var origin=CGPoint.zero,extent=CGSize.zero
    AXValueGetValue(unsafeBitCast(position,to:AXValue.self),.cgPoint,&origin)
    AXValueGetValue(unsafeBitCast(size,to:AXValue.self),.cgSize,&extent)
    return CGRect(origin:origin,size:extent)
}
func clickAt(_ point: CGPoint, right: Bool = false) {
    let (down,up,button):(CGEventType,CGEventType,CGMouseButton) = right ? (.rightMouseDown,.rightMouseUp,.right) : (.leftMouseDown,.leftMouseUp,.left)
    CGEvent(mouseEventSource:nil,mouseType:down,mouseCursorPosition:point,mouseButton:button)?.post(tap:.cghidEventTap)
    CGEvent(mouseEventSource:nil,mouseType:up,mouseCursorPosition:point,mouseButton:button)?.post(tap:.cghidEventTap)
}
/// Click just inside the top-left corner of the input box, where QQ places the caret.
func clickEditorStart(_ input: AXUIElement) {
    guard let position=ax(input,"AXPosition"),CFGetTypeID(position)==AXValueGetTypeID() else {return}
    var point=CGPoint.zero
    AXValueGetValue(unsafeBitCast(position,to:AXValue.self),.cgPoint,&point)
    clickAt(CGPoint(x:point.x+12,y:point.y+12))
}
/// Near the bottom-right of the input box; AX focus alone leaves QQ's web container focused after an image paste.
func editorCaretPoint(_ box: CGRect) -> CGPoint {
    CGPoint(x:box.minX+max(12,box.width-24),y:box.minY+max(12,box.height-24))
}
func pressPaste() {
    let down=CGEvent(keyboardEventSource:nil,virtualKey:9,keyDown:true),up=CGEvent(keyboardEventSource:nil,virtualKey:9,keyDown:false)
    down?.flags = .maskCommand;up?.flags = .maskCommand;down?.post(tap:.cghidEventTap);up?.post(tap:.cghidEventTap)
}
/// Deep copy of the clipboard so it can be put back after a temporary use.
func copyPasteboardItems(_ board: NSPasteboard) -> [NSPasteboardItem] {
    (board.pasteboardItems ?? []).map { item in
        let copy=NSPasteboardItem()
        for type in item.types {if let data=item.data(forType:type) {copy.setData(data,forType:type)}}
        return copy
    }
}

func pressBackspace(times: Int) {
    for _ in 0..<max(0,min(times,10)) {
        CGEvent(keyboardEventSource:nil,virtualKey:51,keyDown:true)?.post(tap:.cghidEventTap)
        CGEvent(keyboardEventSource:nil,virtualKey:51,keyDown:false)?.post(tap:.cghidEventTap)
    }
}
func newlineCount(_ e: AXUIElement) -> Int {
    string(e,"AXValue").reduce(0) {$1=="\n" ? $0+1 : $0}
}
/// Short, content-free description of the input box for diagnostics: length, line breaks, attachment markers.
func describeEditor(_ e: AXUIElement) -> String {
    let value=string(e,"AXValue")
    let attachments=value.unicodeScalars.filter {$0.value==0xFFFC}.count
    return "chars=\(value.count) newlines=\(newlineCount(e)) attachments=\(attachments) endsWithSpace=\(value.hasSuffix(" "))"
}
/// Roles/labels/classes of what sits in QQ's input area (no message text), to see which controls exist while a draft is there.
func describeInputArea(_ window: AXUIElement) -> String {
    guard let area=find(window,{(ax($0,"AXDOMClassList") as? [String] ?? []).contains("chat-input-area")}) else {return "chat-input-area not found"}
    var out:[String]=[]
    func walk(_ e:AXUIElement,_ depth:Int) {
        guard depth<7,out.count<40 else {return}
        let classes=(ax(e,"AXDOMClassList") as? [String] ?? []).joined(separator:".")
        let label=[string(e,"AXTitle"),string(e,"AXDescription")].filter {!$0.isEmpty}.joined(separator:"/")
        if !label.isEmpty || classes.contains("send") || string(e,"AXRole")=="AXButton" {
            out.append("\(string(e,"AXRole")):\(label.prefix(12)):\(classes.prefix(40))")
        }
        for c in children(e) {walk(c,depth+1)}
    }
    walk(area,0)
    return out.joined(separator:" | ")
}

/// Seconds since the last key press anywhere on this Mac.
func secondsSinceTyping() -> Double { CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .keyDown) }
