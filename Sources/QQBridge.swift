import Cocoa
import ApplicationServices

final class Bridge: NSObject, NSApplicationDelegate {
    var item: NSStatusItem!
    var paused = true
    var backend: Process?
    var backendInput: FileHandle?
    var backendOutput: FileHandle?
    var backendErrors: FileHandle?
    var buffer = Data()
    var observer: AXObserver?
    var observedPID: pid_t = 0
    var lastEvent = Date.distantPast
    var pendingSend = false
    var ownsPIDFile = false
    var projectAccess:URL?
    var base: URL
    var config: [String:Any] = [:]
    var firstRun = false
    lazy var model = AppModel(control: self)
    var popoverController: PopoverController?
    var liveController: LivePanelController?
    var settingsController: SettingsWindowController?
    var petController: PetController?
    var spaceController: QQSpaceController?

    override init() {
        if let i = CommandLine.arguments.firstIndex(of:"--base"), CommandLine.arguments.count > i+1 {
            base = URL(fileURLWithPath:CommandLine.arguments[i+1])
        } else { base = Bundle.main.bundleURL.deletingLastPathComponent() }
        super.init()
        if !CommandLine.arguments.contains("--authorize-project") {
            var stale=false
            if let data=UserDefaults.standard.data(forKey:"QQBridgeOpenSourceProjectAccess"),
               let url=try? URL(resolvingBookmarkData:data,options:.withSecurityScope,relativeTo:nil,bookmarkDataIsStale:&stale),
               projectFilesAvailable(url),
               (url.standardizedFileURL==base.standardizedFileURL || !projectFilesAvailable(base)),
               url.startAccessingSecurityScopedResource() {projectAccess=url;base=url}
            loadConfig()
        }
        normalizeConfig()
    }
    private func projectFilesAvailable(_ directory: URL) -> Bool {
        ["bridge.py", "config.example.json", "prompts/reply-instructions.txt"].allSatisfy {
            FileManager.default.isReadableFile(atPath:directory.appendingPathComponent($0).path)
        }
    }
    /// Downloaded apps may run from a translocated path. Ask for the real project folder rather than starting without its files.
    private func prepareProject() -> Bool {
        if CommandLine.arguments.contains("--authorize-project") || !projectFilesAvailable(base) {
            NSApp.setActivationPolicy(.regular);NSApp.activate(ignoringOtherApps:true)
            let panel=NSOpenPanel();panel.canChooseFiles=false;panel.canChooseDirectories=true;panel.allowsMultipleSelection=false
            panel.title="选择 QQ 聊天 Bot 项目文件夹";panel.prompt="使用此文件夹"
            panel.message="找不到应用旁边的程序文件，可能正在从下载隔离路径运行。请选择解压后的整个文件夹，其中应包含 bridge.py、config.example.json 和 prompts。"
            panel.directoryURL=FileManager.default.urls(for:.downloadsDirectory,in:.userDomainMask).first
            guard panel.runModal() == .OK,let url=panel.url else {return false}
            guard projectFilesAvailable(url) else {
                launchProblem("所选文件夹缺少程序文件，请完整解压下载包后重新打开。");return false
            }
            if url.startAccessingSecurityScopedResource() {projectAccess=url}
            base=url
            if let bookmark=try? url.bookmarkData(options:.withSecurityScope,includingResourceValuesForKeys:nil,relativeTo:nil) {
                UserDefaults.standard.set(bookmark,forKey:"QQBridgeOpenSourceProjectAccess")
            }
        }
        do {
            let local=base.appendingPathComponent("config.json")
            if !FileManager.default.fileExists(atPath:local.path) {
                try Data(contentsOf:base.appendingPathComponent("config.example.json")).write(to:local,options:.atomic)
                try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:local.path)
                firstRun=true
            }
            try FileManager.default.createDirectory(at:base.appendingPathComponent("runtime"),withIntermediateDirectories:true)
            loadConfig()
            return true
        } catch {
            launchProblem("无法写入项目文件夹。请将完整解压文件夹移到可写位置后重试。\n"+error.localizedDescription)
            return false
        }
    }
    private func launchProblem(_ text: String) {
        let alert=NSAlert();alert.messageText="QQ 聊天 Bot 无法启动";alert.informativeText=text;alert.runModal()
    }
    /// Re-reads config.json. Call before changing and saving it: edits made on disk while the app runs (by hand or by
    /// another tool) must not be overwritten by this process's older in-memory copy.
    func loadConfig() {
        if let data=try? Data(contentsOf:base.appendingPathComponent("config.json")),let value=try? JSONSerialization.jsonObject(with:data) as? [String:Any] {config=value;normalizeConfig()}
    }
    private func normalizeConfig() {
        config["reply_mode"] = "regular"
        config["groups"] = (config["groups"] as? [String] ?? []).filter {$0 != "填写主群完整名称"}
        config["self_names"] = (config["self_names"] as? [String] ?? []).filter {$0 != "填写本账号昵称"}
    }
    var groups: [String] {config["groups"] as? [String] ?? []}
    /// True while the user typed within the last `typing_quiet_seconds` (default 3): QQ is then never brought to the
    /// front, so the screen does not switch under the user (and their keystrokes cannot land in QQ's input box).
    var userTyping: Bool { secondsSinceTyping() < ((config["typing_quiet_seconds"] as? NSNumber)?.doubleValue ?? 3) }
    var qq: NSRunningApplication? {NSRunningApplication.runningApplications(withBundleIdentifier:"com.tencent.qq").first}
    var window: AXUIElement? {
        guard let q=qq else{return nil}
        let root=AXUIElementCreateApplication(q.processIdentifier)
        AXUIElementSetAttributeValue(root,"AXManualAccessibility" as CFString,kCFBooleanTrue)
        AXUIElementSetAttributeValue(root,"AXEnhancedUserInterface" as CFString,kCFBooleanTrue)
        return (ax(root,"AXWindows") as? [AXUIElement] ?? []).first {string($0,"AXTitle")=="QQ" && string($0,"AXRole")=="AXWindow"}
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        Notifier.log = { [weak self] line in self?.nativeLog(line) }
        guard prepareProject() else {NSApp.terminate(nil);return}
        CCFont.register(extra: base.appendingPathComponent("Resources/Fonts/ArkPixel12.otf"))
        let pidFile=base.appendingPathComponent("runtime/app.pid")
        if let value=try? String(contentsOf:pidFile,encoding:.utf8),let old=Int32(value.trimmingCharacters(in:.whitespacesAndNewlines)),old != getpid(),kill(old,0)==0,
           NSRunningApplication.runningApplications(withBundleIdentifier:Bundle.main.bundleIdentifier ?? "").contains(where:{$0.processIdentifier==old}) {
            NSApp.terminate(nil);return
        }
        try? String(getpid()).write(to:pidFile,atomically:true,encoding:.utf8)
        ownsPIDFile=true
        NSApp.setActivationPolicy(.accessory)
        item = NSStatusBar.system.statusItem(withLength:NSStatusItem.variableLength)
        popoverController = PopoverController(model: model)
        liveController = LivePanelController(model: model)
        settingsController = SettingsWindowController(model: model)
        model.onPhaseChange = { [weak self] _ in self?.refreshStatusItem() }
        model.onAppearanceChange = { mode in NSApp.appearance = AppModel.nsAppearance(mode) }
        NSApp.appearance = AppModel.nsAppearance(model.appearance)
        model.onPinChange = { [weak self] pinned in self?.liveController?.setPinned(pinned) }
        if let button = item.button {
            button.imagePosition = .imageLeading
            button.target = self
            button.action = #selector(statusItemClicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        refreshStatusItem()
        model.start()
        spaceController=QQSpaceController(bridge:self,model:model.space)
        petController=PetController(model:model)
        if configurationProblem(config)==nil {startBackend()} else {update("请先填写本账号昵称、主群和 AI 设置")}
        Timer.scheduledTimer(withTimeInterval:2,repeats:true) { [weak self] _ in self?.watch() }
        watch()
        Timer.scheduledTimer(withTimeInterval:60,repeats:true) { [weak self] _ in self?.checkSpaceSchedule() }
        checkSpaceSchedule()
        if firstRun || configurationProblem(config) != nil {DispatchQueue.main.asyncAfter(deadline:.now()+0.5) {self.showSettings()}}
        if CommandLine.arguments.contains("--start") && !firstRun && configurationProblem(config)==nil {toggle()}
        if let flag=CommandLine.arguments.first(where:{$0.hasPrefix("--show=")}) {
            // Development aid: open one UI surface on launch (popover | live | settings).
            DispatchQueue.main.asyncAfter(deadline:.now()+0.8) { [self] in
                switch flag.dropFirst(7) {
                case "popover": if let button=item.button {popoverController?.toggle(from:button)}
                case "live": showLive()
                case "settings": showSettings()
                case "space": showSpace()
                default: break
                }
            }
        }
        if CommandLine.arguments.contains("--qzone") {showSpace()}
    }
    func pythonURL(_ settings: [String:Any]? = nil) -> URL {
        let specified=(settings ?? config)["python"] as? String ?? ""
        if !specified.isEmpty { return URL(fileURLWithPath:specified) }
        let paths=[base.appendingPathComponent(".venv/bin/python3").path, "/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
        return URL(fileURLWithPath:paths.first(where:{FileManager.default.isExecutableFile(atPath:$0)}) ?? "/usr/bin/python3")
    }
    func startBackend() {
        let p=Process();p.executableURL=pythonURL()
        p.arguments=["-u",base.appendingPathComponent("bridge.py").path,"--base",base.path]
        let input=Pipe(),output=Pipe();p.standardInput=input;p.standardOutput=output
        let log=base.appendingPathComponent("runtime/backend.log")
        let errors=Pipe();p.standardError=errors
        backendErrors=errors.fileHandleForReading
        var diagnostics:Data?
        errors.fileHandleForReading.readabilityHandler={ handle in
            let data=handle.availableData
            guard !data.isEmpty else{handle.readabilityHandler=nil;return}
            if diagnostics==nil {diagnostics=(try? Data(contentsOf:log)) ?? Data()}
            diagnostics?.append(data)
            if let bytes=diagnostics,bytes.count>1_048_576 {diagnostics=Data(bytes.suffix(1_048_576))}
            try? diagnostics?.write(to:log,options:.atomic)
        }
        backendInput=input.fileHandleForWriting
        backendOutput=output.fileHandleForReading
        let outputFD=output.fileHandleForReading.fileDescriptor
        let flags=fcntl(outputFD,F_GETFL)
        if flags >= 0 { _ = fcntl(outputFD,F_SETFL,flags | O_NONBLOCK) }
        output.fileHandleForReading.readabilityHandler={ [weak self] handle in
            var bytes=[UInt8](repeating:0,count:65536)
            let count=Darwin.read(handle.fileDescriptor,&bytes,bytes.count)
            if count < 0 {
                if errno != EAGAIN && errno != EINTR {handle.readabilityHandler=nil}
                return
            }
            if count == 0 {handle.readabilityHandler=nil;return}
            let data=Data(bytes.prefix(count))
            DispatchQueue.main.async {self?.consume(data)}
        }
        p.terminationHandler={ [weak self, weak p] _ in DispatchQueue.main.async {
            guard let self, let p, self.backend === p else { return }
            output.fileHandleForReading.readabilityHandler=nil
            errors.fileHandleForReading.readabilityHandler=nil
            self.backendOutput=nil
            self.backendErrors=nil
            let status=(try? Data(contentsOf:self.base.appendingPathComponent("runtime/status.json"))).flatMap {try? JSONSerialization.jsonObject(with:$0) as? [String:Any]}
            let refused=status?["state"] as? String == "config_error"
            let reason=refused ? (status?["message"] as? String ?? "配置有误，后台没有启动") : "回复进程已停止，请退出后重开"
            self.paused=true;self.update(reason);Notifier.post(refused ? "配置有误" : "回复进程已停止",reason)
        }}
        do {try p.run();backend=p;emit(["event":"ready"])} catch {
            output.fileHandleForReading.readabilityHandler=nil
            errors.fileHandleForReading.readabilityHandler=nil
            backendOutput=nil
            backendErrors=nil
            update("启动失败：\(error.localizedDescription)")
        }
    }
    func emit(_ obj:[String:Any]) {
        guard let d=try? JSONSerialization.data(withJSONObject:obj),let h=backendInput else{return}
        do {try h.write(contentsOf:d+Data([10]))} catch {paused=true;update("回复进程连接中断")}
    }
    func consume(_ data:Data) {
        buffer.append(data)
        while let end=buffer.firstIndex(of:10) {
            let line=buffer[..<end];buffer.removeSubrange(...end)
            if let obj=try? JSONSerialization.jsonObject(with:line) as? [String:Any] {command(obj)}
        }
    }
    func command(_ c:[String:Any]) {
        let id=c["id"] ?? NSNull()
        func reply(_ value:[String:Any]) {emit(["id":id,"result":value])}
        switch c["op"] as? String {
        case "snapshot": reply(snapshot())
        case "typing": reply(["typing":userTyping,"seconds":secondsSinceTyping()])
        case "wake":
            guard !userTyping else {reply(["error":"user_typing"]);return}
            guard let q=qq else {reply(["error":"qq_not_running"]);return}
            q.activate(options:[])
            if let w=window {AXUIElementPerformAction(w,kAXRaiseAction as CFString)}
            reply(["ok":true])
        case "capture_image", "capture_latest_image": captureImage(c,reply:reply)
        case "select": reply(selectGroup(c["group"] as? String ?? "",force:c["force"] as? Bool ?? false))
        case "clear_draft": reply(clearDraft(c))
        case "resume":
            // the backend checked an uncertain send and found it safe to carry on: same as the user pressing 继续
            if paused {toggle()}
            Notifier.post("已自动恢复",c["text"] as? String ?? "")
            reply(["ok":true])
        case "send": send(c,reply:reply)
        case "send_image": sendImage(c,reply:reply)
        case "status": update(c["text"] as? String ?? "");reply(["ok":true])
        case "pause":
            paused=true;let text=c["text"] as? String ?? "已暂停";update(text);Notifier.post("已自动暂停",text);reply(["ok":true])
        case "notify": Notifier.post(c["title"] as? String ?? "QQChatBridge",c["text"] as? String ?? "");reply(["ok":true])
        default: reply(["error":"unknown_operation"])
        }
    }
    func update(_ text:String) {
        model.statusText=text
        model.syncSettings()
        refreshStatusItem()
    }
    func refreshStatusItem() {
        guard let button=item?.button else{return}
        button.image=MenuBarIcon.image(attention:model.phase == .attention || model.phase == .offline,dim:model.phase == .paused)
        button.title=" "+model.phase.menuTitle
    }
    @objc func toggle() {
        if paused,let problem=configurationProblem(config) {update(problem);showSettings();return}
        paused.toggle(); update(paused ? "已暂停" : "正在记录现有消息")
        emit(["event":"paused","paused":paused])
        if !paused,(config["live_window"] as? [String:Any])?["auto_show"] as? Bool != false {liveController?.show(activate:false)}
    }
    @objc func startProactive() {
        guard !paused, backend?.isRunning == true else { return }
        guard let w=window, groups.contains(currentGroup(w)) else {
            update("请先打开一个已配置的群聊")
            return
        }
        let group=currentGroup(w)
        emit(["event":"proactive_now","group":group])
        update("已请求在当前群发起话题，写好后请选一条")
    }
    /// The QQ Space browser lives in the main window (Settings → QQ 空间).
    @objc func showSpace() {
        model.settingsSection = .space
        showSettings()
    }
    @objc func statusItemClicked(_ sender: NSStatusBarButton) {
        popoverController?.toggle(from: sender)         // left and right click both open the popover
    }
    @objc func showSettings() {
        loadConfig()
        popoverController?.close()
        settingsController?.show()
    }
    @objc func showLive() {
        popoverController?.close()
        liveController?.show(activate:true)
    }
    @objc func permissions() {
        NSWorkspace.shared.open(URL(string:"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
    }
    @objc func showConfig() {NSWorkspace.shared.open(base.appendingPathComponent("config.json"))}
    @objc func quit() {NSApp.terminate(nil)}
    func applicationWillTerminate(_ notification:Notification) {
        paused=true;emit(["event":"shutdown"])
        backendInput?.closeFile()
        if ownsPIDFile {try? FileManager.default.removeItem(at:base.appendingPathComponent("runtime/app.pid"))}
        projectAccess?.stopAccessingSecurityScopedResource()
    }
    func watch() {
        guard configurationProblem(config)==nil else {return}
        if !AXIsProcessTrusted() {update("需要为 QQChatBridge 开启辅助功能权限");return}
        if let q=qq,q.processIdentifier != observedPID {
            observedPID=q.processIdentifier
            var o:AXObserver?
            let callback:AXObserverCallback={_,_,_,ref in
                guard let ref=ref else{return}
                let b=Unmanaged<Bridge>.fromOpaque(ref).takeUnretainedValue()
                if Date().timeIntervalSince(b.lastEvent)>0.5 {b.lastEvent=Date();b.emit(["event":"change"])}
            }
            if AXObserverCreate(q.processIdentifier,callback,&o) == .success,let o=o {
                observer=o
                let root=AXUIElementCreateApplication(q.processIdentifier)
                for name in ["AXValueChanged","AXLayoutChanged","AXSelectedChildrenChanged","AXFocusedUIElementChanged"] {
                    AXObserverAddNotification(o,root,name as CFString,Unmanaged.passUnretained(self).toOpaque())
                    if let w=window {AXObserverAddNotification(o,w,name as CFString,Unmanaged.passUnretained(self).toOpaque())}
                }
                CFRunLoopAddSource(CFRunLoopGetMain(),AXObserverGetRunLoopSource(o),.defaultMode)
            }
        }
        emit(["event":"tick"])
    }
}

extension Bridge {
    /// Appends a timestamped line to runtime/native.log (capped); used to trace the fragile QQ automation steps.
    func nativeLog(_ line:String) {
        let url=base.appendingPathComponent("runtime/native.log")
        let stamp=DateFormatter();stamp.dateFormat="yyyy-MM-dd HH:mm:ss"
        let text="\(stamp.string(from:Date())) \(line)\n"
        if let size=(try? FileManager.default.attributesOfItem(atPath:url.path)[.size]) as? Int,size>512_000 {
            try? FileManager.default.removeItem(at:url)
        }
        if !FileManager.default.fileExists(atPath:url.path) {
            FileManager.default.createFile(atPath:url.path,contents:nil,attributes:[.posixPermissions:0o600])
        }
        if let handle=try? FileHandle(forWritingTo:url) {
            handle.seekToEndOfFile();handle.write(Data(text.utf8));try? handle.close()
        }
    }
}

extension Bridge: BridgeControl {
    var baseURL: URL {base}
    var isPaused: Bool {paused}
    func togglePaused() {toggle()}
    func setSuffix(_ on:Bool) {setAISuffix(on)}
    func requestProactive() {startProactive()}
    func chooseTopic(_ index:Int) {emit(["event":"topic_choice","index":index])}
    func setPetEnabled(_ on:Bool) {
        var pet=config["pet"] as? [String:Any] ?? [:]
        pet["enabled"]=on;config["pet"]=pet
        saveAndApply(message:on ? "桌宠已显示" : "桌宠已隐藏")
    }
    func openPermissions() {permissions()}
    func openConfigFile() {showConfig()}
    func quitApp() {quit()}
    func revertStyleCompression() {emit(["event":"style_revert"])}
    func revertFeedbackRound() {emit(["event":"feedback_revert"])}
    func rateReply(_ turn: LiveSnapshot.Turn, rating: String?) {
        let path=base.appendingPathComponent("runtime/reply-feedback.json")
        var all=(try? Data(contentsOf:path)).flatMap {try? JSONSerialization.jsonObject(with:$0) as? [String:Any]} ?? [:]
        if let rating {
            all[turn.id]=["rating":rating,"group":turn.group,"title":turn.title,"reply":turn.reply?.text ?? "",
                          "reason":turn.decision?.reason ?? "","time":Date().timeIntervalSince1970,
                          "context":turn.messages.suffix(3).map {["sender":$0.sender,"text":$0.text]}]
        } else {
            all.removeValue(forKey:turn.id)
        }
        guard let data=try? JSONSerialization.data(withJSONObject:all,options:[.prettyPrinted,.sortedKeys]) else{return}
        try? data.write(to:path,options:.atomic)
        try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
    }
    /// Asks the Python backend (same rules it enforces at startup) whether a config is usable. nil = fine or unknown.
    func configProblem(_ cfg:[String:Any]) -> String? {
        guard let data=try? JSONSerialization.data(withJSONObject:cfg) else {return nil}
        let file=base.appendingPathComponent("runtime/config-check-\(UUID().uuidString).json")
        guard (try? data.write(to:file)) != nil else {return nil}
        try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
        defer {try? FileManager.default.removeItem(at:file)}
        let process=Process(),output=Pipe()
        process.executableURL=pythonURL(cfg)
        process.arguments=[base.appendingPathComponent("bridge.py").path,"--check-config",file.path]
        process.standardOutput=output;process.standardError=FileHandle.nullDevice
        guard (try? process.run()) != nil else {return nil}
        let deadline=Date().addingTimeInterval(8)
        while process.isRunning && Date()<deadline {usleep(20_000)}
        if process.isRunning {process.terminate();return nil}
        guard let report=try? JSONSerialization.jsonObject(with:output.fileHandleForReading.readDataToEndOfFile()) as? [String:Any],
              let first=(report["errors"] as? [String])?.first else {return nil}
        return "配置有误：\(first)"
    }
    private func configurationProblem(_ settings: [String:Any]) -> String? {
        let groups=settings["groups"] as? [String] ?? []
        if groups.isEmpty || groups.contains(where:{$0.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || $0=="填写主群完整名称"}) {
            return "请填写主群完整名称，提示文字不能作为群名"
        }
        let names=settings["self_names"] as? [String] ?? []
        if names.isEmpty || names.contains(where:{$0.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || $0=="填写本账号昵称"}) {
            return "请填写本账号昵称，提示文字不能作为昵称"
        }
        if !AppModel.configured(settings["ai"] as? [String:Any] ?? [:]) {return "请填写 AI 接口地址、API Key 和模型名称"}
        return nil
    }
    /// Returns a user-facing problem description, or nil when the configuration was accepted.
    func applyConfig(_ cfg:[String:Any],restart:Bool) -> String? {
        let updated=cfg
        if let problem=configurationProblem(updated) {return problem}
        if let problem=configProblem(updated) {return problem}
        config=updated
        if restart || backend?.isRunning != true {saveAndRestart(message:"配置已保存，回复服务已重启")} else {saveAndApply(message:"配置已保存，热切换中")}
        return nil
    }
}

@main
struct QQBridgeApplication {
    static func main() {
        let application=NSApplication.shared
        let delegate=Bridge()
        application.delegate=delegate
        application.run()
    }
}
