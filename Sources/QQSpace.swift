import Cocoa
import ApplicationServices

private func hasClass(_ element:AXUIElement,_ name:String)->Bool {
    (ax(element,"AXDOMClassList") as? [String] ?? []).contains(name)
}
private func elements(_ root:AXUIElement,depth:Int=0)->[AXUIElement] {
    guard depth<42 else{return [root]}
    return [root]+children(root).flatMap {elements($0,depth:depth+1)}
}
private func textContent(_ root:AXUIElement)->String {
    elements(root).filter {string($0,"AXRole")=="AXStaticText"}.map {string($0,"AXValue")}.joined(separator:"\n")
}
private func linkURL(_ element:AXUIElement)->URL? {
    if let value=ax(element,"AXURL") as? URL {return value}
    return URL(string:string(element,"AXURL"))
}

/// Reads and operates QQ's authenticated Space window; never uses the group editor.
final class QQSpaceDriver {
    private weak var bridge:Bridge?
    /// QQ number whose Space page is driven; set `qq_account` in config.json to override.
    private var account:String {bridge?.config["qq_account"] as? String ?? ""}
    private var ownsControl=false
    private var clipboard:[NSPasteboardItem]?
    private(set) var error=""
    init(bridge:Bridge) {self.bridge=bridge}
    private var root:AXUIElement? {
        guard let app=bridge?.qq else{return nil}
        let root=AXUIElementCreateApplication(app.processIdentifier)
        for key in ["AXManualAccessibility","AXEnhancedUserInterface"] where ax(root,key) as? Bool != true {
            AXUIElementSetAttributeValue(root,key as CFString,kCFBooleanTrue)
        }
        return root
    }
    private var spaceWindow:AXUIElement? {
        guard AXIsProcessTrusted(),let root else{return nil}
        return (ax(root,"AXWindows") as? [AXUIElement] ?? []).first { window in
            find(window) {string($0,"AXRole")=="AXWebArea" && string($0,"AXTitle").contains("\(account).qzone.qq.com")} != nil
        }
    }
    private var page:AXUIElement? {
        guard let window=spaceWindow else{return nil}
        return find(window) {string($0,"AXRole")=="AXWebArea" && string($0,"AXTitle").contains("\(account).qzone.qq.com")}
    }
    private func card(_ id:String)->AXUIElement? {
        guard let page,find(page,{string($0,"AXDOMIdentifier")=="tb_logout"}) != nil,
              let feed=find(page,{string($0,"AXDOMIdentifier")=="feed_friend_list"}) else{return nil}
        return find(feed) {string($0,"AXDOMIdentifier")==id && hasClass($0,"f-single")}
    }
    /// `manual`: the user pressed a button just now, so the typing guard does not apply.
    func open(manual:Bool=false)->Bool {
        guard !account.isEmpty else {error="请先在常规设置填写本账号 QQ 号";return false}
        guard AXIsProcessTrusted(),let bridge,!bridge.pendingSend,manual || !bridge.userTyping,let app=bridge.qq else{return false}
        if let window=spaceWindow {app.activate(options:[]);AXUIElementPerformAction(window,kAXRaiseAction as CFString);return true}
        guard let window=bridge.window,let button=find(window,{string($0,"AXRole")=="AXButton" && string($0,"AXDescription")=="空间"}) else{return false}
        app.activate(options:[]);AXUIElementPerformAction(window,kAXRaiseAction as CFString)
        return bridge.press(button)
    }
    func scan()->[String:Any] {
        guard AXIsProcessTrusted() else{return ["ok":false,"error":"需要为 QQChatBridge 开启辅助功能权限"]}
        guard let page,find(page,{string($0,"AXDOMIdentifier")=="tb_logout"}) != nil,
              let feed=find(page,{string($0,"AXDOMIdentifier")=="feed_friend_list"}) else {
            return ["ok":false,"error":"请打开 QQ 左侧的空间入口，等待已登录的好友动态加载"]
        }
        let posts:[[String:Any]]=elements(feed).compactMap { card in
            let id=string(card,"AXDOMIdentifier")
            guard id.hasPrefix("fct_"),hasClass(card,"f-single"),
                  let body=find(card,{string($0,"AXDOMIdentifier").hasPrefix("feed_")}) else{return nil}
            let nodes=elements(card)
            let ad=nodes.contains {hasClass($0,"f-ad") || hasClass($0,"advertisement") || string($0,"AXValue")=="广告"}
            let text=String(textContent(body).trimmingCharacters(in:.whitespacesAndNewlines).prefix(1800))
            guard !ad else{return nil}
            let media=mediaInfo(body,text:text)
            guard !text.isEmpty || media["media_kind"] as? String != "text" else{return nil}
            let comments=nodes.filter {hasClass($0,"comments-item")}
            return ["id":id,"text":text,"author":nodes.first(where:{hasClass($0,"f-name")}).map {string($0,"AXDescription")} ?? "好友",
                    "liked":liked(id),"own_comment":comments.contains {ownComment($0)},"advertisement":false,
                    "comments":comments.prefix(8).map {String(textContent($0).prefix(250))}].merging(media) {_,new in new}
        }
        return ["ok":true,"posts":posts]
    }
    private func mediaInfo(_ body:AXUIElement,text:String)->[String:Any] {
        let nodes=elements(body)
        let classes=nodes.flatMap {ax($0,"AXDOMClassList") as? [String] ?? []}.map {$0.lowercased()}
        let video=classes.contains {$0.contains("video") || $0.contains("player")} || nodes.contains {string($0,"AXRole")=="AXVideo"}
        let unavailable=["暂不支持查看","内容无法查看","内容已删除","无法播放媒体","无权限查看"].contains {text.contains($0)}
        let unsupported=classes.contains {$0.contains("audio") || $0.contains("music") || $0.contains("flash") || $0.contains("unsupported") || $0.contains("appcard") || ($0.hasPrefix("f-ct-") && $0 != "f-ct-txtimg")}
        let externalLink=nodes.contains { node in
            guard string(node,"AXRole")=="AXLink",let url=linkURL(node),["http","https"].contains(url.scheme ?? "") else{return false}
            return url.host != "user.qzone.qq.com"
        }
        let items=nodes.filter {hasClass($0,"img-item")}
        let images=nodes.filter {string($0,"AXRole")=="AXImage" && linkURL($0)?.host?.hasSuffix("qpic.cn")==true}
        let urls=images.compactMap {linkURL($0)?.absoluteString}
        let count=max(items.count,images.count)
        let kind=video ? "video" : (unavailable || unsupported || externalLink ? "unavailable" : (count>0 ? "images" : "text"))
        return ["media_kind":kind,"image_count":count,"image_urls":urls]
    }
    private func ownComment(_ element:AXUIElement)->Bool {
        let author=elements(element).first {string($0,"AXRole")=="AXLink" && linkURL($0)?.host=="user.qzone.qq.com"}
        return author.map {linkURL($0)?.path.trimmingCharacters(in:CharacterSet(charactersIn:"/"))==account} ?? false
    }
    func liked(_ id:String)->Bool {
        guard let card=card(id),let button=find(card,{hasClass($0,"qz_like_btn_v3")}) else{return false}
        return hasClass(button,"item-on")
    }
    func commented(_ id:String,_ text:String)->Bool {
        guard let card=card(id) else{return false}
        return elements(card).filter {hasClass($0,"comments-item")}.contains {
            ownComment($0) && textContent($0).contains(": \(text)") && find($0,{string($0,"AXDescription")=="发送中"})==nil
        }
    }
    func beginControl()->Bool {
        guard let bridge,!bridge.pendingSend,let app=bridge.qq,let window=spaceWindow,!bridge.userTyping else{return false}
        bridge.pendingSend=true;ownsControl=true
        app.activate(options:[]);AXUIElementPerformAction(window,kAXRaiseAction as CFString)
        return true
    }
    func restoreClipboard() {
        if let clipboard {NSPasteboard.general.clearContents();NSPasteboard.general.writeObjects(clipboard);self.clipboard=nil}
    }
    func endControl() {restoreClipboard();if ownsControl {bridge?.pendingSend=false;ownsControl=false}}
    private func ready()->Bool {
        guard ownsControl,let bridge,let app=bridge.qq,let root,let window=spaceWindow,
              NSWorkspace.shared.frontmostApplication?.processIdentifier==app.processIdentifier,
              let focused=ax(root,"AXFocusedWindow"),CFEqual(focused,window) else{return false}
        return true
    }
    func like(_ id:String)->Bool {
        guard ready(),let card=card(id),let button=find(card,{hasClass($0,"qz_like_btn_v3")}) else{return false}
        return hasClass(button,"item-on") || AXUIElementPerformAction(button,kAXPressAction as CFString) == .success
    }
    func prepareComment(_ id:String)->Bool {
        guard ready(),let card=card(id),let editor=find(card,{string($0,"AXRole")=="AXTextArea"}) else{return false}
        let value=string(editor,"AXValue").trimmingCharacters(in:.whitespacesAndNewlines)
        guard value.isEmpty || value=="评论" else{return false}
        if let trigger=find(editor,{string($0,"AXRole")=="AXLink" && string($0,"AXDescription")=="评论"}) {
            return AXUIElementPerformAction(trigger,kAXPressAction as CFString) == .success
        }
        return bridge?.clickButton(editor)==true
    }
    private func expandedEditor(_ id:String)->AXUIElement? {
        guard let card=card(id) else{return nil}
        return find(card) {string($0,"AXRole")=="AXTextArea" && string($0,"AXDOMIdentifier").hasSuffix("_content_content")}
    }
    func focusComment(_ id:String)->Bool {
        guard ready(),let editor=expandedEditor(id) else{return false}
        AXUIElementSetAttributeValue(editor,kAXFocusedAttribute as CFString,kCFBooleanTrue)
        return bridge?.clickButton(editor)==true
    }
    func fillComment(_ id:String,_ text:String)->Bool {
        guard ready() else{error="QQ 空间窗口焦点已切换";return false}
        guard let editor=expandedEditor(id) else{error="展开的评论输入框尚未出现";return false}
        guard string(editor,"AXValue").trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else{error="评论框存在草稿";return false}
        guard let root,let focused=ax(root,kAXFocusedUIElementAttribute),CFEqual(focused,editor) else{error="评论输入框焦点未确认";return false}
        let board=NSPasteboard.general
        clipboard=copyPasteboardItems(board)
        board.clearContents()
        guard board.setString(text,forType:.string) else{error="无法写入评论剪贴板";return false}
        pressPaste()
        return true
    }
    func submitComment(_ id:String,_ text:String)->Bool {
        guard ready(),let card=card(id),let editor=expandedEditor(id),
              string(editor,"AXValue").trimmingCharacters(in:.whitespacesAndNewlines)==text,
              let button=find(card,{hasClass($0,"btn-post") && string($0,"AXRole")=="AXLink"}) else{return false}
        return AXUIElementPerformAction(button,kAXPressAction as CFString) == .success
    }
    func navigate(_ refresh:Bool)->Bool {
        guard beginControl() else{return false}
        guard let page else{endControl();return false}
        if refresh {
            let ok=find(page,{string($0,"AXDOMIdentifier")=="feed_friend_refresh"}).map {AXUIElementPerformAction($0,kAXPressAction as CFString) == .success} ?? false
            endControl();return ok
        }
        AXUIElementSetAttributeValue(page,kAXFocusedAttribute as CFString,kCFBooleanTrue)
        DispatchQueue.main.asyncAfter(deadline:.now()+0.3) { [weak self] in
            guard let self else{return}
            defer {self.endControl()}
            guard self.ready(),let position=ax(page,"AXPosition"),let size=ax(page,"AXSize"),
                  CFGetTypeID(position)==AXValueGetTypeID(),CFGetTypeID(size)==AXValueGetTypeID() else{return}
            var origin=CGPoint.zero,extent=CGSize.zero
            AXValueGetValue(unsafeBitCast(position,to:AXValue.self),.cgPoint,&origin)
            AXValueGetValue(unsafeBitCast(size,to:AXValue.self),.cgSize,&extent)
            let event=CGEvent(scrollWheelEvent2Source:nil,units:.pixel,wheelCount:1,wheel1:-Int32(max(400,extent.height*0.8)),wheel2:0,wheel3:0)
            event?.location=CGPoint(x:origin.x+extent.width*0.4,y:origin.y+extent.height*0.5)
            event?.post(tap:.cghidEventTap)
        }
        return true
    }
}

/// Runs the QQ Space auto-browse rounds; the UI (Settings → QQ 空间) observes and drives it through `SpaceViewModel`.
final class QQSpaceController:NSObject {
    private weak var bridge:Bridge?
    private let driver:QQSpaceDriver
    private let model:SpaceViewModel
    private let base:URL
    private var timer:Timer?
    private var worker:Process?
    private var running=false {didSet {model.running=running}}
    private var busy=false {didSet {model.busy=busy}}
    private var epoch=0
    private var emptyRounds=0
    private var roundIds=Set<String>()
    private var records:[[String:Any]]=[]
    init(bridge:Bridge,model:SpaceViewModel) {
        self.bridge=bridge;self.model=model;base=bridge.base;driver=QQSpaceDriver(bridge:bridge);super.init()
        if let data=try? Data(contentsOf:statePath),let value=try? JSONSerialization.jsonObject(with:data) as? [[String:Any]] {records=value}
        model.onOpen={ [weak self] in self?.openSpace() }
        model.onRefresh={ [weak self] in self?.refreshPage() }
        model.onNext={ [weak self] in self?.nextPage() }
        model.onToggle={ [weak self] in self?.toggle() }
    }
    private var statePath:URL {base.appendingPathComponent("runtime/qzone-actions.json")}
    private func log(_ value:String) {
        DispatchQueue.main.async {self.model.push(value)}
        let stamp=DateFormatter();stamp.dateFormat="HH:mm:ss"
        let line="\(stamp.string(from:Date())) \(value)\n"
        let state:[String:Any]=["running":running,"busy":busy,"message":value,"updated_at":Date().timeIntervalSince1970]
        if let data=try? JSONSerialization.data(withJSONObject:state) {try? data.write(to:base.appendingPathComponent("runtime/qzone-status.json"),options:.atomic)}
        let path=base.appendingPathComponent("runtime/qzone.log")
        if !FileManager.default.fileExists(atPath:path.path) {FileManager.default.createFile(atPath:path.path,contents:nil)}
        if let file=try? FileHandle(forWritingTo:path) {file.seekToEndOfFile();file.write(Data(line.utf8));try? file.close()}
    }
    func startScheduled(base:URL,config:[String:Any])->Bool {
        if running {return true}
        if bridge?.userTyping == true {return false}          // try again at the next minute check, not under the user's typing
        return start()
    }
    private func openSpace() {guard !busy else{return};log(driver.open(manual:true) ? "已打开 QQ 内置空间" : "无法打开空间，请检查 QQ 和辅助功能权限")}
    private func refreshPage() {guard !busy else{return};log(driver.navigate(true) ? "正在刷新好友动态" : "QQ 正在发送消息或空间未打开，请稍后再试")}
    private func nextPage() {guard !busy else{return};log(driver.navigate(false) ? "已请求浏览下一屏" : "请先打开 QQ 空间，或等待当前群聊消息发送完成")}
    private func toggle() {if running {stop();log("已暂停自动浏览")} else{_ = start(manual:true)}}
    private func start(manual:Bool=false)->Bool {
        guard driver.open(manual:manual) else{log("无法打开空间，请检查 QQ 登录和辅助功能权限；群聊发送中可稍后重试");return false}
        running=true;busy=true;epoch+=1;emptyRounds=0;roundIds=[]
        let interval=(bridge?.config["qzone"] as? [String:Any])?["interval_seconds"] as? Double ?? 60
        timer=Timer.scheduledTimer(withTimeInterval:max(10,interval),repeats:true) { [weak self] _ in self?.scan() }
        log("正在加载 QQ 内置空间，沿用已有登录状态")
        awaitFeed(generation:epoch,remaining:15,refresh:true)
        return true
    }
    private func awaitFeed(generation:Int,remaining:Int,refresh:Bool) {
        guard running,epoch==generation else{return}
        if driver.scan()["ok"] as? Bool==true {
            if refresh {
                if driver.navigate(true) {
                    log("正在刷新好友动态，获取最新内容")
                    DispatchQueue.main.asyncAfter(deadline:.now()+3) { [weak self] in self?.awaitFeed(generation:generation,remaining:15,refresh:false) }
                    return
                }
            } else {busy=false;scan();return}
        }
        guard remaining>0 else{fail("空间未加载或尚未登录，请检查 QQ 内置空间后再次开始");return}
        DispatchQueue.main.asyncAfter(deadline:.now()+2) { [weak self] in self?.awaitFeed(generation:generation,remaining:remaining-1,refresh:refresh) }
    }
    private func stop() {
        running=false;epoch+=1;timer?.invalidate();timer=nil;worker?.terminate();worker=nil;busy=false;driver.endControl()
    }
    private func fail(_ value:String) {stop();log(value)}
    private func scan() {
        guard running,!busy else{return}
        let snapshot=driver.scan()
        guard snapshot["ok"] as? Bool==true,let posts=snapshot["posts"] as? [[String:Any]] else{fail(snapshot["error"] as? String ?? "无法读取动态");return}
        var handled=Set(records.compactMap {$0["id"] as? String})
        var candidates:[[String:Any]]=[]
        for post in posts {
            let id=post["id"] as? String ?? ""
            // 动态按时间从新到旧排列：遇到本轮之前就互动过的一条，后面的都已看过，结束这一轮
            let before=records.first {$0["id"] as? String==id}?["state"] as? String ?? ""
            let interacted=post["liked"] as? Bool==true || post["own_comment"] as? Bool==true || ["confirmed","attempted","existing_comment"].contains(before)
            if interacted && !roundIds.contains(id) {
                stop();log("读到已互动过的动态，这一轮浏览结束");return
            }
            guard !handled.contains(id) else{continue}
            if post["own_comment"] as? Bool==true {
                record(id:id,comment:"",state:"existing_comment");handled.insert(id);continue
            }
            let kind=post["media_kind"] as? String ?? "text"
            if kind=="video" || kind=="unavailable" {
                record(id:id,comment:"",state:"skipped",reason:kind=="video" ? "视频动态不互动" : "内容不可读取")
                handled.insert(id);log(kind=="video" ? "跳过视频动态" : "跳过不可读取的动态");continue
            }
            candidates=[post];break
        }
        if candidates.isEmpty {
            if bridge?.pendingSend==true {log("等待当前群聊发送完成后继续翻页");return}
            guard driver.navigate(false) else{log("等待 QQ 空间可操作后继续");return}
            emptyRounds+=1
            if emptyRounds>=3 {stop();log("这一轮空间已浏览完毕");return}
            log("当前动态已处理，继续向下浏览");return
        }
        emptyRounds=0;busy=true;choose(candidates,generation:epoch)
    }
    private func choose(_ posts:[[String:Any]],generation:Int) {
        log("正在生成互动：\(posts[0]["author"] as? String ?? "好友") · \(String((posts[0]["text"] as? String ?? "").prefix(90)))")
        let token=UUID().uuidString
        let input=base.appendingPathComponent("runtime/qzone-input-\(token).json"),output=base.appendingPathComponent("runtime/qzone-output-\(token).json")
        let job:[String:Any]=["posts":posts,"recent":records.compactMap {$0["comment"] as? String}.filter {!$0.isEmpty}.suffix(12).map {$0}]
        do {let data=try JSONSerialization.data(withJSONObject:job);try data.write(to:input,options:.atomic);try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:input.path)} catch {fail("无法准备动态任务");return}
        let process=Process();process.executableURL=bridge?.pythonURL() ?? URL(fileURLWithPath:"/usr/bin/python3")
        process.arguments=[base.appendingPathComponent("qzone_agent.py").path,"--base",base.path,"--input",input.path,"--output",output.path]
        process.standardInput=FileHandle.nullDevice;process.standardOutput=FileHandle.nullDevice;process.standardError=FileHandle.nullDevice
        process.terminationHandler={ [weak self] _ in
            let bytes=try? Data(contentsOf:output)
            try? FileManager.default.removeItem(at:input);try? FileManager.default.removeItem(at:output)
            DispatchQueue.main.async {
                guard let self,self.running,self.epoch==generation else{return};self.worker=nil
                guard let bytes,let result=try? JSONSerialization.jsonObject(with:bytes) as? [String:Any] else{self.fail("空间模型任务没有返回结果");return}
                guard result["ok"] as? Bool==true,let action=result["action"] as? [String:Any] else{self.fail(result["error"] as? String ?? "模型调用失败");return}
                let id=action["post_id"] as? String ?? ""
                guard !id.isEmpty else{
                    self.record(id:posts[0]["id"] as? String ?? "",comment:"",state:"skipped",reason:action["reason"] as? String ?? "")
                    self.busy=false;self.log(action["reason"] as? String ?? "这条动态暂不互动");return
                }
                guard posts.contains(where:{$0["id"] as? String==id}) else{self.fail("互动目标不在当前动态中");return}
                self.log("\(action["model"] as? String ?? "模型") · \(action["seconds"] ?? 0)秒 · \(action["reason"] as? String ?? "")")
                self.perform(action,generation:generation)
            }
        }
        worker=process
        do {try process.run()} catch {try? FileManager.default.removeItem(at:input);fail("无法启动空间模型：\(error.localizedDescription)")}
    }
    private func record(id:String,comment:String,state:String,reason:String="") {
        roundIds.insert(id);records.removeAll {$0["id"] as? String==id};records.append(["id":id,"comment":comment,"state":state,"reason":reason,"time":Date().timeIntervalSince1970])
        if let data=try? JSONSerialization.data(withJSONObject:records,options:.prettyPrinted) {try? data.write(to:statePath,options:.atomic);try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:statePath.path)}
    }
    private func perform(_ action:[String:Any],generation:Int) {
        guard running,epoch==generation else{return}
        let id=action["post_id"] as? String ?? "",comment=action["comment"] as? String ?? ""
        guard !id.isEmpty,comment.count<=80 else{fail("评论格式无效");return}
        guard driver.beginControl() else{
            log("评论已生成，等待当前群聊发送或输入操作结束")
            DispatchQueue.main.asyncAfter(deadline:.now()+5) { [weak self] in self?.perform(action,generation:generation) };return
        }
        record(id:id,comment:comment,state:"attempted")
        DispatchQueue.main.asyncAfter(deadline:.now()+0.4) { [weak self] in
            guard let self,self.running,self.epoch==generation else{return}
            if action["like"] as? Bool != true {self.comment(id:id,text:comment,generation:generation);return}
            guard self.driver.like(id) else{self.fail("点赞入口失效或窗口被切换，已暂停");return}
            self.verify(generation:generation,remaining:8,check:{self.driver.liked(id)}) {ok in
                guard ok else{self.fail("点赞结果未确认，已暂停且不重试");return}
                self.log("已确认点赞");self.comment(id:id,text:comment,generation:generation)
            }
        }
    }
    private func comment(id:String,text:String,generation:Int) {
        guard running,epoch==generation else{return}
        if text.isEmpty {finish(id:id,comment:"");return}
        guard driver.prepareComment(id) else{fail("无法展开评论入口或已有草稿，已暂停");return}
        verify(generation:generation,remaining:5,check:{self.driver.focusComment(id)}) { [weak self] focused in
            guard let self,self.running,self.epoch==generation else{return}
            guard focused else{self.fail("评论输入框未就绪或窗口已切换，已暂停");return}
            DispatchQueue.main.asyncAfter(deadline:.now()+0.3) {
            guard self.running,self.epoch==generation else{return}
            guard self.driver.fillComment(id,text) else{self.fail("\(self.driver.error)，已暂停");return}
            self.log("准备评论：\(text)")
            DispatchQueue.main.asyncAfter(deadline:.now()+0.5) {
                guard self.running,self.epoch==generation else{return}
                self.driver.restoreClipboard()
                guard self.driver.submitComment(id,text) else{self.fail("评论未提交或窗口被切换，已暂停");return}
                self.verify(generation:generation,remaining:10,check:{self.driver.commented(id,text)}) {ok in
                    guard ok else{self.fail("评论结果未确认，已暂停且不重试");return}
                    self.finish(id:id,comment:text)
                }
            }
            }
        }
    }
    private func finish(id:String,comment:String) {
        record(id:id,comment:comment,state:"confirmed");driver.endControl();busy=false
        log(comment.isEmpty ? "已确认点赞，等待下一条动态" : "已确认评论：\(comment)")
    }
    private func verify(generation:Int,remaining:Int,check:@escaping ()->Bool,completion:@escaping (Bool)->Void) {
        guard running,epoch==generation else{return}
        if check() {completion(true);return}
        guard remaining>0 else{completion(false);return}
        DispatchQueue.main.asyncAfter(deadline:.now()+1) { [weak self] in self?.verify(generation:generation,remaining:remaining-1,check:check,completion:completion) }
    }
}
