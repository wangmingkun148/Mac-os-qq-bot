import Cocoa

/// Model/line switching and config persistence.
extension Bridge {
    func setAISuffix(_ enabled: Bool) {
        loadConfig()
        var ai=config["ai"] as? [String:Any] ?? [:]
        ai["suffix_enabled"]=enabled;config["ai"]=ai
        saveAndApply(message:enabled ? "回复后缀已开启" : "回复后缀已关闭")
    }
    func saveAndRestart(message: String = "配置已保存，正在重启回复服务") {
        guard let data = try? JSONSerialization.data(withJSONObject:config,options:[.prettyPrinted,.sortedKeys]) else {
            update("保存配置失败");return
        }
        let path = base.appendingPathComponent("config.json")
        do {
            try data.write(to:path,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
        } catch {
            update("保存配置失败");return
        }
        let wasPaused = paused
        self.backend?.terminationHandler = nil
        backendOutput?.readabilityHandler = nil
        backendOutput = nil
        self.backend?.terminate()
        backendInput?.closeFile()
        self.backend = nil
        update(message)
        DispatchQueue.main.asyncAfter(deadline:.now()+0.6) { [weak self] in
            guard let self else { return }
            self.startBackend()
            self.emit(["event":"paused","paused":wasPaused])
        }
    }
    func saveAndApply(message: String, event: String = "configure") {
        guard let data = try? JSONSerialization.data(withJSONObject:config,options:[.prettyPrinted,.sortedKeys]) else {
            update("保存配置失败");return
        }
        let path=base.appendingPathComponent("config.json")
        do {
            try data.write(to:path,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
        } catch {
            update("保存配置失败");return
        }
        emit(["event":event,"config":config])
        update(message)
    }
    func checkSpaceSchedule() {
        let space=config["qzone"] as? [String:Any] ?? [:]
        guard space["schedule_enabled"] as? Bool != false else{return}
        var calendar=Calendar(identifier:.gregorian);calendar.timeZone=TimeZone(identifier:space["timezone"] as? String ?? TimeZone.current.identifier) ?? .current
        let now=Date();guard calendar.component(.hour,from:now)>=(space["hour"] as? Int ?? 19) else{return}
        let formatter=DateFormatter();formatter.dateFormat="yyyy-MM-dd";formatter.timeZone=calendar.timeZone
        let day=formatter.string(from:now),path=base.appendingPathComponent("runtime/qzone-schedule.json")
        if let data=try? Data(contentsOf:path),let state=try? JSONSerialization.jsonObject(with:data) as? [String:String],state["last_started_day"]==day{return}
        if spaceController?.startScheduled(base:base,config:config)==true,
           let data=try? JSONSerialization.data(withJSONObject:["last_started_day":day]) {try? data.write(to:path,options:.atomic)}
    }
}
