import Cocoa
import ApplicationServices

/// Reading and driving the QQ window through accessibility: conversations, images and sending.
extension Bridge {
    func snapshot() -> [String:Any] {
        guard AXIsProcessTrusted() else{return ["error":"accessibility_permission"]}
        guard let w=window else{return ["error":"qq_window_missing"]}
        guard string(w,"AXRole")=="AXWindow" else{return ["error":"qq_content_unavailable"]}
        var out:[String:Any] = ["tree":tree(w),"activeConversation":currentGroup(w),"paused":paused,"pid":qq?.processIdentifier ?? 0]
        out["conversationDetails"]=conversationDetails(w)
        out["idleSeconds"]=CGEventSource.secondsSinceLastEventType(.combinedSessionState,eventType:.keyDown)
        return out
    }
    func editor(_ w:AXUIElement) -> AXUIElement? {find(w) {string($0,"AXRole")=="AXTextArea"}}
    var allConversations:Bool {config["reply_all_conversations"] as? Bool ?? false}
    func conversationKey(_ title:String) -> String {groups.contains(title) ? title : "chat:"+title}
    func conversationRows(_ w:AXUIElement) -> [(String,AXUIElement)] {
        guard let list=find(w,{string($0,"AXDescription")=="会话列表"}) else{return []}
        var rows:[(String,AXUIElement)]=[]
        for row in children(list) {
            guard let info=find(row,{(ax($0,"AXDOMClassList") as? [String] ?? []).contains("item__info")}),
                  let label=find(info,{string($0,"AXRole")=="AXStaticText"}) else{continue}
            let title=string(label,"AXValue")
            if !title.isEmpty {rows.append((title,row))}
        }
        return rows.filter { item in rows.filter {$0.0==item.0}.count==1 && (allConversations || groups.contains(item.0)) }
    }
    func conversationAllowed(_ key:String,_ w:AXUIElement) -> Bool {
        conversationRows(w).contains {conversationKey($0.0)==key}
    }
    func conversationDetails(_ w:AXUIElement) -> [String:[String:Any]] {
        var result:[String:[String:Any]]=[:]
        let active=currentTitle(w)
        for (title,row) in conversationRows(w) {
            var kind=groups.contains(title) ? "group" : "unknown"
            if find(row,{string($0,"AXRole")=="AXStaticText" && string($0,"AXValue").range(of:"^\\([0-9]+\\)$",options:.regularExpression) != nil}) != nil {kind="group"}
            if title==active {
                if find(w,{string($0,"AXDescription")=="群成员列表" || string($0,"AXDescription")=="群应用"}) != nil {kind="group"}
                else if find(w,{string($0,"AXDescription")=="发起群聊"}) != nil {kind="private"}
            }
            result[conversationKey(title)]=["title":title,"kind":kind]
        }
        return result
    }
    func currentTitle(_ w:AXUIElement) -> String {
        guard let input=editor(w),
              let area=find(w,{(ax($0,"AXDOMClassList") as? [String] ?? []).contains("aio")}),
              let scopedInput=editor(area),CFEqual(input,scopedInput),
              let header=find(area,{string($0,"AXRole")=="AXButton" &&
                  (ax($0,"AXDOMClassList") as? [String] ?? []).contains("chat-header__contact-name")}) else{return ""}
        let title=string(header,"AXDescription"),inputTitle=string(input,"AXDescription")
        guard !title.isEmpty,inputTitle.isEmpty || inputTitle==title else{return ""}
        return title
    }
    func currentGroup(_ w:AXUIElement) -> String {
        let title=currentTitle(w)
        guard !title.isEmpty else{return ""}
        let key=conversationKey(title)
        return conversationAllowed(key,w) ? key : ""
    }
    func empty(_ e:AXUIElement) -> Bool {
        let v=string(e,"AXValue").trimmingCharacters(in:.whitespacesAndNewlines)
        return v.isEmpty || v=="按住 ⌃ ⌥，使用语音输入文字"
    }
    func imageDraftPresent(_ e:AXUIElement) -> Bool {
        !empty(e) || find(e,{string($0,"AXRole")=="AXImage"}) != nil
    }
    func clickButton(_ e:AXUIElement) -> Bool {
        guard let box=frame(e),box.width>0,box.height>0 else {return false}
        clickAt(CGPoint(x:box.midX,y:box.midY))
        return true
    }
    func press(_ e:AXUIElement) -> Bool {
        AXUIElementPerformAction(e,kAXPressAction as CFString) == .success
    }
    /// `force`: allowed while paused (only used to look at a chat after an uncertain send, never to send).
    func selectGroup(_ name:String,force:Bool=false) -> [String:Any] {
        guard !paused || force,!pendingSend else{return ["error":"paused_or_group_not_allowed"]}
        guard let w=window else{return ["error":"qq_window_missing"]}
        guard conversationAllowed(name,w) else{return ["error":"conversation_not_allowed"]}
        if editor(w) != nil,currentGroup(w)==name {return ["ok":true]}
        if let any=find(w,{string($0,"AXRole")=="AXTextArea"}),!empty(any) {return ["error":"draft_present"]}
        guard find(w,{string($0,"AXDescription")=="会话列表"}) != nil else{
            if let tab=find(w,{string($0,"AXRole")=="AXCheckBox" && string($0,"AXDescription").hasPrefix("消息")}) {return ["ok":press(tab)]}
            return ["error":"open_qq_messages_tab"]
        }
        guard let row=conversationRows(w).first(where:{conversationKey($0.0)==name})?.1 else{return ["error":"group_not_in_visible_list"]}
        if press(row) || clickButton(row) {return ["ok":true]}
        return ["error":"group_press_unsupported"]
    }
    func captureImage(_ c:[String:Any],reply:@escaping ([String:Any])->Void) {
        let group=c["group"] as? String ?? ""
        guard !paused,!pendingSend,!group.isEmpty,let q=qq,let w=window,currentGroup(w)==group else {
            reply(["error":"image_context_changed"]);return
        }
        var mid=c["message_id"] as? String ?? ""
        if c["op"] as? String == "capture_latest_image" {
            let excluded=Set(c["exclude_ids"] as? [String] ?? [])
            var candidates:[AXUIElement]=[]
            func collect(_ element:AXUIElement,depth:Int=0) {
                guard depth<42 else{return}
                let id=string(element,"AXDOMIdentifier")
                if id.count>=10,id.allSatisfy({$0.isNumber}),!excluded.contains(id),
                   find(element,{(ax($0,"AXDOMClassList") as? [String] ?? []).contains(where:{$0=="message-container--self" || $0=="container--self"})})==nil,
                   messageImage(element) != nil {candidates.append(element);return}
                for child in children(element) {collect(child,depth:depth+1)}
            }
            if let listing=find(w,{string($0,"AXDescription")=="消息列表"}) {collect(listing)}
            guard let latest=candidates.last else {reply(["error":"no_new_image"]);return}
            mid=string(latest,"AXDOMIdentifier")
        }
        guard mid.count>=10,mid.allSatisfy({$0.isNumber}),
              let row=find(w,{string($0,"AXDOMIdentifier")==mid}),
              let picture=messageImage(row),
              let box=frame(picture) else {
            reply(["error":"image_unavailable"]);return
        }
        let capturedID=mid
        guard !userTyping,let input=editor(w),empty(input) else {reply(["error":"user_active_or_draft_present"]);return}
        guard box.width>10,box.height>10 else {reply(["error":"image_not_visible"]);return}
        let point=CGPoint(x:box.midX,y:box.midY)
        let pasteboard=NSPasteboard.general
        let initialChange=pasteboard.changeCount
        let previousItems=copyPasteboardItems(pasteboard)
        pendingSend=true
        NSApp.activate(ignoringOtherApps:true);q.activate(options:[])
        AXUIElementPerformAction(w,kAXRaiseAction as CFString)
        DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { [self] in
            guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                  let current=window,currentGroup(current)==group,
                  let exact=find(current,{string($0,"AXDOMIdentifier")==mid}),
                  messageImage(exact) != nil else {
                pendingSend=false;reply(["error":"image_context_changed"]);return
            }
            clickAt(point,right:true)
            DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { [self] in
                guard let current=window,
                      let copy=find(current,{string($0,"AXRole")=="AXMenuItem" && (string($0,"AXTitle")=="复制" || string($0,"AXDescription")=="复制")}),
                      press(copy) else {
                    pendingSend=false;reply(["error":"image_copy_unavailable"]);return
                }
                func inspectCopy(_ attempts:Int) {
                    DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { [self] in
                        let currentChange=pasteboard.changeCount
                        if currentChange==initialChange && attempts>0 {inspectCopy(attempts-1);return}
                        if currentChange==initialChange {
                            pendingSend=false;reply(["error":"image_copy_timeout"]);return
                        }
                        var image=NSImage(pasteboard:pasteboard)
                        if image==nil {
                            for item in pasteboard.pasteboardItems ?? [] {
                                for type in [NSPasteboard.PasteboardType.png,.tiff,NSPasteboard.PasteboardType("public.jpeg")] {
                                    if let data=item.data(forType:type),let decoded=NSImage(data:data) {image=decoded;break}
                                }
                                if image != nil {break}
                            }
                        }
                        if image==nil,let urls=pasteboard.readObjects(forClasses:[NSURL.self],options:[.urlReadingFileURLsOnly:true]) as? [URL] {
                            for url in urls {if let decoded=NSImage(contentsOf:url) {image=decoded;break}}
                        }
                        if image==nil && attempts>0 {inspectCopy(attempts-1);return}
                        defer {
                            if pasteboard.changeCount==currentChange {
                                pasteboard.clearContents()
                                if !previousItems.isEmpty {pasteboard.writeObjects(previousItems)}
                            }
                            pendingSend=false
                        }
                        guard currentChange != initialChange,pasteboard.changeCount==currentChange,
                              let image=image,let tiff=image.tiffRepresentation,
                              let bitmap=NSBitmapImageRep(data:tiff),
                              let jpeg=bitmap.representation(using:.jpeg,properties:[.compressionFactor:0.85]),jpeg.count<25_000_000 else {
                            let types=(pasteboard.pasteboardItems ?? []).flatMap {$0.types.map {$0.rawValue}}.joined(separator:",")
                            reply(["error":"image_clipboard_unreadable","types":String(types.prefix(250))]);return
                        }
                        let path=base.appendingPathComponent("runtime/image-\(UUID().uuidString).jpg")
                        do {try jpeg.write(to:path,options:.atomic);reply(["path":path.path,"message_id":capturedID])}
                        catch {reply(["error":"image_save_failed"])}
                    }
                }
                inspectCopy(9)
            }
        }
    }
    func send(_ c:[String:Any],reply:@escaping ([String:Any])->Void) {
        let group=c["group"] as? String ?? "",text=c["text"] as? String ?? ""
        guard !paused,!pendingSend,!group.isEmpty,!text.isEmpty,!text.contains("\n") else {reply(["error":"send_not_allowed"]);return}
        guard let q=qq,let w=window else {reply(["error":"qq_window_missing"]);return}
        guard let e=editor(w) else {reply(["error":"editor_unavailable"]);return}
        let actual=currentGroup(w)
        guard actual==group else {reply(["error":"wrong_conversation","actual_group":actual]);return}
        guard empty(e) else {reply(["error":"draft_present"]);return}
        guard !userTyping else {reply(["error":"user_typing"]);return}
        pendingSend=true
        NSApp.activate(ignoringOtherApps:true)
        q.activate(options:[])
        AXUIElementPerformAction(w,kAXRaiseAction as CFString)
        DispatchQueue.main.asyncAfter(deadline:.now()+0.35) { [self] in
            guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                  let current=window,let input=editor(current),currentGroup(current)==group,
                  empty(input) else {
                pendingSend=false;reply(["error":"activation_or_draft_changed"]);return
            }
            AXUIElementSetAttributeValue(input,kAXFocusedAttribute as CFString,kCFBooleanTrue)
            clickEditorStart(input)
            DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { [self] in
                guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                      let current=window,let input=editor(current),currentGroup(current)==group,empty(input) else {
                    pendingSend=false;reply(["error":"focus_changed"]);return
                }
                guard AXUIElementSetAttributeValue(input,kAXValueAttribute as CFString,text as CFString) == .success else {pendingSend=false;reply(["error":"editor_write_failed"]);return}
                DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { [self] in
                    guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                          let current=window,let input=editor(current),currentGroup(current)==group,
                          string(input,"AXValue").trimmingCharacters(in:.whitespacesAndNewlines)==text else {
                        pendingSend=false;reply(["error":"focus_or_draft_changed"]);return
                    }
                    AXUIElementSetAttributeValue(input,kAXFocusedAttribute as CFString,kCFBooleanTrue)
                    guard clickButton(input) else {pendingSend=false;reply(["error":"editor_bounds_missing"]);return}
                    DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { [self] in
                        guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                              let latest=window,let draft=editor(latest),currentGroup(latest)==group,
                              string(draft,"AXValue").trimmingCharacters(in:.whitespacesAndNewlines)==text else {
                            pendingSend=false;reply(["error":"text_send_context_changed"]);return
                        }
                        let appRoot=AXUIElementCreateApplication(q.processIdentifier)
                        guard let focused=ax(appRoot,kAXFocusedUIElementAttribute),CFEqual(focused,draft) else {
                            pendingSend=false;reply(["error":"editor_not_focused"]);return
                        }
                        pressReturnKey()
                        DispatchQueue.main.asyncAfter(deadline:.now()+0.6) { [self] in
                            guard let latest=window,let draft=editor(latest),currentGroup(latest)==group else {
                                // Return has been sent; let the backend confirm from the message list.
                                pendingSend=false;reply(["submitted":true,"awaiting_readback":true]);return
                            }
                            if empty(draft) {
                                pendingSend=false;reply(["ok":true,"submitted":true])
                            } else {
                                pendingSend=false;reply(["error":"text_still_in_editor"])
                            }
                        }
                    }
                }
            }
        }
    }
    func sendImage(_ c:[String:Any],reply:@escaping ([String:Any])->Void) {
        let group=c["group"] as? String ?? "",text=c["text"] as? String ?? "",path=c["path"] as? String ?? ""
        let runtime=base.appendingPathComponent("runtime").standardizedFileURL.path+"/"
        let file=URL(fileURLWithPath:path).standardizedFileURL
        guard !paused,!pendingSend,!group.isEmpty,text.count<=120,
              file.path.hasPrefix(runtime),["png","jpg","jpeg"].contains(file.pathExtension.lowercased()),
              let image=NSImage(contentsOf:file) else {reply(["error":"image_send_not_allowed"]);return}
        guard let q=qq,let w=window,let e=editor(w),currentGroup(w)==group else {reply(["error":"wrong_conversation"]);return}
        guard empty(e) else {nativeLog("send_image refused: input box not empty (\(describeEditor(e)))");reply(["error":"draft_present"]);return}
        guard !userTyping else {reply(["error":"user_typing"]);return}
        let pasteboard=NSPasteboard.general
        let previousItems=copyPasteboardItems(pasteboard)
        pendingSend=true
        nativeLog("send_image start: text=\(text) file=\(file.lastPathComponent)")
        NSApp.activate(ignoringOtherApps:true);q.activate(options:[])
        AXUIElementPerformAction(w,kAXRaiseAction as CFString)
        DispatchQueue.main.asyncAfter(deadline:.now()+0.35) { [self] in
            guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                  let current=window,let input=editor(current),currentGroup(current)==group,empty(input) else {
                pendingSend=false;reply(["error":"activation_or_draft_changed"]);return
            }
            AXUIElementSetAttributeValue(input,kAXFocusedAttribute as CFString,kCFBooleanTrue)
            clickEditorStart(input)
            DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { [self] in
            guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                  let current=window,let input=editor(current),currentGroup(current)==group,empty(input) else {
                pendingSend=false;reply(["error":"image_focus_changed"]);return
            }
            // A bare "@name" leaves QQ's mention suggestion open and it swallows Return (a newline appears instead of
            // sending). A trailing space closes it, exactly like the text replies ("@name 开始生成…") that do send.
            let typed=text.hasPrefix("@") && !text.hasSuffix(" ") ? text+" " : text
            guard text.isEmpty || AXUIElementSetAttributeValue(input,kAXValueAttribute as CFString,typed as CFString) == .success else {
                pendingSend=false;reply(["error":"editor_write_failed"]);return
            }
            if !text.isEmpty {
                var end=CFRange(location:typed.utf16.count,length:0)
                if let range=AXValueCreate(.cfRange,&end) {
                    AXUIElementSetAttributeValue(input,kAXSelectedTextRangeAttribute as CFString,range)
                }
            }
            pasteboard.clearContents()
            guard pasteboard.writeObjects([image]) else {
                pendingSend=false;reply(["error":"image_clipboard_write_failed"]);return
            }
            // NSImage alone puts an uncompressed bitmap (~8 MB for 1920x1080) on the clipboard; add the compressed PNG
            // so QQ has much less to process before it accepts "send".
            if let tiff=image.tiffRepresentation,let png=NSBitmapImageRep(data:tiff)?.representation(using:.png,properties:[:]) {
                pasteboard.setData(png,forType:.png)
            }
            let imageClipboardChange=pasteboard.changeCount
            pressPaste()
            DispatchQueue.main.asyncAfter(deadline:.now()+5.0) { [self] in
                guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                      let current=window,let input=editor(current),currentGroup(current)==group else {
                    pendingSend=false;reply(["error":"image_paste_context_changed"]);return
                }
                AXUIElementSetAttributeValue(input,kAXFocusedAttribute as CFString,kCFBooleanTrue)
                // AX focus alone leaves QQ's web container focused after image paste.
                guard let box=frame(input) else {
                    pendingSend=false;reply(["error":"image_editor_bounds_missing"]);return
                }
                clickAt(editorCaretPoint(box))
                DispatchQueue.main.asyncAfter(deadline:.now()+0.25) { [self] in
                guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                      let current=window,let input=editor(current),currentGroup(current)==group else {
                    pendingSend=false;reply(["error":"image_send_context_changed"]);return
                }
                let appRoot=AXUIElementCreateApplication(q.processIdentifier)
                guard let focused=ax(appRoot,kAXFocusedUIElementAttribute),CFEqual(focused,input) else {
                    pendingSend=false;reply(["error":"image_editor_not_focused"]);return
                }
                let sendButton = find(current,{ element in
                    ["AXTitle","AXDescription","AXValue"].contains {string(element,$0)=="发送"}
                })
                nativeLog("send_image input area: "+describeInputArea(current))
                let newlinesBefore=newlineCount(input)
                nativeLog("send_image pasted: \(describeEditor(input)); send button \(sendButton == nil ? "not found" : "found")")
                let sent = sendButton.map {press($0) || clickButton($0)} ?? false
                if !sent {
                    pressReturnKey()
                }
                func finish(_ result:[String:Any]) {
                    if pasteboard.changeCount==imageClipboardChange {
                        pasteboard.clearContents()
                        if !previousItems.isEmpty {pasteboard.writeObjects(previousItems)}
                    }
                    pendingSend=false;reply(result)
                }
                /// Checks the outcome of a Return/click. QQ ignores Return as "send" while it is still processing the pasted
                /// image and inserts a line break instead; then: undo the break, wait, focus the editor again, retry.
                func check(attempt:Int) {
                    DispatchQueue.main.asyncAfter(deadline:.now()+3.0) { [self] in
                        guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                              let latest=window,let draft=editor(latest),currentGroup(latest)==group else {
                            finish(["error":"image_send_context_changed"]);return
                        }
                        if !imageDraftPresent(draft) {
                            nativeLog("send_image done: attempt \(attempt), \(attempt==1 && sent ? "button" : "return")")
                            finish(["ok":true,"submitted":true,"method":attempt==1 ? (sent ? "click" : "return") : "return+retry"]);return
                        }
                        let added=newlineCount(draft)-newlinesBefore
                        nativeLog("send_image attempt \(attempt) did not send (\(describeEditor(draft)))")
                        if added>0 {pressBackspace(times:added)}
                        guard attempt<3 else {
                            finish(["error":added>0 ? "image_newline_instead_of_send" : "image_still_in_editor"]);return
                        }
                        DispatchQueue.main.asyncAfter(deadline:.now()+4.0) { [self] in
                            guard !paused,NSWorkspace.shared.frontmostApplication?.processIdentifier==q.processIdentifier,
                                  let current=window,let again=editor(current),currentGroup(current)==group,imageDraftPresent(again),
                                  let box=frame(again) else {
                                finish(["error":"image_send_context_changed"]);return
                            }
                            AXUIElementSetAttributeValue(again,kAXFocusedAttribute as CFString,kCFBooleanTrue)
                            clickAt(editorCaretPoint(box))
                            DispatchQueue.main.asyncAfter(deadline:.now()+0.25) { [self] in
                                let appRoot=AXUIElementCreateApplication(q.processIdentifier)
                                guard let current=window,let focusedDraft=editor(current),
                                      let focused=ax(appRoot,kAXFocusedUIElementAttribute),CFEqual(focused,focusedDraft) else {
                                    finish(["error":"image_editor_not_focused"]);return
                                }
                                nativeLog("send_image retry \(attempt+1): Return again")
                                pressReturnKey()
                                check(attempt:attempt+1)
                            }
                        }
                    }
                }
                check(attempt:1)
                }
            }
            }
        }
    }
    /// Removes the bot's own stuck message from the input box: only when the box holds exactly `expected`, so text
    /// the user typed there is never touched.
    func clearDraft(_ c:[String:Any]) -> [String:Any] {
        let group=c["group"] as? String ?? "",expected=c["text"] as? String ?? ""
        guard !userTyping else{return ["error":"user_typing"]}
        guard !pendingSend,!expected.isEmpty,let w=window,let e=editor(w) else{return ["error":"editor_unavailable"]}
        guard currentGroup(w)==group else{return ["error":"wrong_conversation"]}
        let squash={(t:String) in t.components(separatedBy:.whitespacesAndNewlines).joined()}
        guard squash(string(e,"AXValue"))==squash(expected) else{return ["error":"draft_differs"]}
        guard AXUIElementSetAttributeValue(e,kAXValueAttribute as CFString,"" as CFString) == .success,
              let after=editor(w),empty(after) else{return ["error":"clear_failed"]}
        nativeLog("cleared the bot's stuck draft after an uncertain send")
        return ["ok":true]
    }
}
