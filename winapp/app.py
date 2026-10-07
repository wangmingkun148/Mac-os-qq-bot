"""Application controller: owns the config, the reply engine thread and the native (QQ automation) side.

The UI layers (tray icon, local web UI, console runner) only talk to this class. It is the Windows counterpart of
the macOS ``Bridge`` class plus the data half of ``AppModel``."""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import config_check
import fsutil
from engine import Engine
from procutil import InstanceLock

from . import qqlaunch
from .native import WinNative

PLACEHOLDER_GROUP = "填写主群完整名称"
PLACEHOLDER_NAME = "填写本账号昵称"
REQUIRED_FILES = (("config.example.json", "prompts/reply-instructions.txt") if getattr(sys, "frozen", False)
                  else ("bridge.py", "config.example.json", "prompts/reply-instructions.txt"))


def ai_configured(ai) -> bool:
    ai = ai if isinstance(ai, dict) else {}
    return all(str(ai.get(key) or "").strip() for key in ("base_url", "model", "api_key"))


def configuration_problem(config: dict):
    """The first thing missing before the bot may start, or None (same rules as the macOS app)."""
    groups = config.get("groups") or []
    if not groups or any(not str(g).strip() or g == PLACEHOLDER_GROUP for g in groups):
        return "请填写主群完整名称，提示文字不能作为群名"
    names = config.get("self_names") or []
    if not names or any(not str(n).strip() or n == PLACEHOLDER_NAME for n in names):
        return "请填写本账号昵称，提示文字不能作为昵称"
    if not ai_configured(config.get("ai")):
        return "请填写 AI 接口地址、API Key 和模型名称"
    return None


def normalize_config(config: dict) -> dict:
    config.pop("reply_mode", None)        # the macOS app wrote this; the backend has no such setting
    config["groups"] = [g for g in (config.get("groups") or []) if g != PLACEHOLDER_GROUP]
    config["self_names"] = [n for n in (config.get("self_names") or []) if n != PLACEHOLDER_NAME]
    return config


class App:
    def __init__(self, base: Path, dry_run: bool = False):
        self.base = Path(base).resolve()
        self.dry_run = dry_run
        self.lock = threading.RLock()
        self.config: dict = {}
        self.first_run = False
        self.status_text = ""
        self.paused = True
        self.native: WinNative | None = None
        self.engine: Engine | None = None
        self.engine_thread: threading.Thread | None = None
        self.stopping = False
        self.notify_sink = None              # callable(title, body) installed by the tray
        self.on_state_change = None          # callable() fired when status/paused change (tray refresh)
        self._recent_notices: dict[str, float] = {}
        self.started_at = time.time()
        self.show_settings_requested = False

    # ------------------------------------------------------------------ project / config files
    def project_ok(self, directory: Path) -> bool:
        return all((directory / name).is_file() for name in REQUIRED_FILES)

    def prepare_project(self) -> str | None:
        """Make sure config.json and runtime/ exist. Returns a problem text, or None."""
        if not self.project_ok(self.base):
            return f"{self.base} 里缺少程序文件（{', '.join(REQUIRED_FILES)}），请完整解压后再运行。"
        try:
            (self.base / "runtime").mkdir(exist_ok=True)
            local = self.base / "config.json"
            if not local.exists():
                local.write_bytes((self.base / "config.example.json").read_bytes())
                self.first_run = True
        except OSError as exc:
            return f"无法写入项目文件夹，请把完整文件夹移到可写位置后重试：{exc}"
        self.load_config()
        return None

    def load_config(self):
        """Re-read config.json (edits made by hand while the app runs must not be overwritten by an old copy)."""
        try:
            self.config = normalize_config(json.loads(fsutil.read_json_text(self.base / "config.json")))
        except (OSError, json.JSONDecodeError):
            self.config = normalize_config(self.config or {})
        if self.native:
            self.native.config = self.config

    def save_config(self) -> bool:
        path = self.base / "config.json"
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self.config, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            fsutil.replace(tmp, path)
            return True
        except OSError:
            self.set_status("保存配置失败")
            return False

    def config_problem(self, config: dict):
        """Ask the same validator the backend uses (errors only). None = fine."""
        errors, _ = config_check.check(config_check.apply_defaults(copy.deepcopy(config)))
        return f"配置有误：{errors[0]}" if errors else None

    def apply_config(self, new_config: dict, restart: bool = False):
        """Validate, save and apply a config from the settings window. Returns a problem text or None."""
        updated = normalize_config(copy.deepcopy(new_config))
        problem = configuration_problem(updated) or self.config_problem(updated)
        if problem:
            return problem
        self.config = updated
        if self.native:
            self.native.config = self.config
        running = self.engine_thread is not None and self.engine_thread.is_alive()
        if restart or not running:
            self.save_config()
            self.restart_backend("配置已保存，回复服务已重启")
        else:
            self.save_config()
            self.native.emit({"event": "configure", "config": copy.deepcopy(self.config)})
            self.set_status("配置已保存，热切换中")
        return None

    def set_suffix(self, enabled: bool):
        self.load_config()
        ai = dict(self.config.get("ai") or {})
        ai["suffix_enabled"] = bool(enabled)
        self.config["ai"] = ai
        if self.save_config() and self.native:
            self.native.emit({"event": "configure", "config": copy.deepcopy(self.config)})
            self.set_status("回复后缀已开启" if enabled else "回复后缀已关闭")

    def set_pet_enabled(self, enabled: bool):
        pet = dict(self.config.get("pet") or {})
        pet["enabled"] = bool(enabled)
        self.config["pet"] = pet
        if self.save_config() and self.native:
            self.native.emit({"event": "configure", "config": copy.deepcopy(self.config)})
            self.set_status("桌宠已显示" if enabled else "桌宠已隐藏")

    # ------------------------------------------------------------------ status / notifications
    def set_status(self, text: str):
        self.status_text = text
        self._changed()

    def _changed(self):
        callback = self.on_state_change
        if callback:
            try:
                callback()
            except Exception:
                pass

    def notify(self, title: str, body: str, force: bool = False):
        key = f"{title}\n{body}"
        now = time.time()
        if not force and now - self._recent_notices.get(key, 0) < 60:      # the same message at most once a minute
            return
        self._recent_notices[key] = now
        sink = self.notify_sink
        if self.native:
            self.native.nativelog(f'notify "{title}": ' + ("delivered to the shell" if sink else "no notification sink"))
        if sink:
            try:
                sink(title, body)
            except Exception:
                pass

    # hooks called by WinNative on behalf of the engine
    def on_status(self, text: str):
        self.set_status(text)

    def on_pause(self, text: str):
        self.paused = True
        self.set_status(text)
        self.notify("已自动暂停", text)

    def on_notify(self, title: str, text: str):
        self.notify(title, text)

    def on_resume(self, text: str):
        if self.paused:
            self.toggle()
        self.notify("已自动恢复", text)

    # ------------------------------------------------------------------ backend lifecycle
    def ensure_native(self):
        if self.native is None:
            self.native = WinNative(self.base, self.config, hooks=self)
            if self.dry_run:
                self.native.dry_run = True
        return self.native

    @property
    def backend_running(self) -> bool:
        return self.engine_thread is not None and self.engine_thread.is_alive()

    def start_backend(self):
        if self.backend_running:
            return
        problem = configuration_problem(self.config)
        if problem:
            self.set_status("请先填写本账号昵称、主群和 AI 设置")
            return
        native = self.ensure_native()
        native.config = self.config
        errors, warnings = config_check.check(config_check.apply_defaults(copy.deepcopy(self.config)))
        if errors:
            self._refuse_config(errors)
            return
        while not native.events.empty():                  # events meant for a previous engine
            try:
                native.events.get_nowait()
            except Exception:
                break
        engine_config = config_check.apply_defaults(copy.deepcopy(self.config))
        self.stopping = False
        thread = threading.Thread(target=self._run_engine, args=(engine_config, warnings), name="engine", daemon=True)
        self.engine_thread = thread
        thread.start()
        native.emit({"event": "ready"})

    def _refuse_config(self, errors):
        message = "配置有误，后台没有启动：" + "；".join(errors[:3]) + ("…" if len(errors) > 3 else "")
        self.paused = True
        self.set_status(message)
        self.notify("配置有误", message)
        status = {"state": "config_error", "message": message, "config_errors": errors,
                  "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            (self.base / "runtime/status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _run_engine(self, engine_config, warnings):
        lock = InstanceLock(self.base / "runtime/bridge.lock")
        if not lock.acquire():
            self.set_status("另一个回复进程正在运行，本进程没有启动后台")
            return
        try:
            self.engine = Engine(self.base, engine_config, self.native, config_warnings=warnings)
            self.engine.run()
        except Exception:
            trace = traceback.format_exc()
            try:
                with (self.base / "runtime/backend.log").open("a", encoding="utf-8") as log:
                    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} engine crashed\n{trace}\n")
            except OSError:
                pass
            if not self.stopping:
                self.paused = True
                self.set_status("回复进程崩溃，已暂停；详情见 runtime/backend.log")
                self.notify("回复进程已停止", "回复进程崩溃了，请查看 runtime/backend.log 后重新开始")
        else:
            if not self.stopping:
                self.paused = True
                self.set_status("回复进程已停止，请退出后重开")
                self.notify("回复进程已停止", "回复进程已停止，请退出后重开")
        finally:
            lock.release()
            self.engine = None
            self._changed()

    def stop_backend(self, wait: float = 8.0):
        thread = self.engine_thread
        if thread is None or not thread.is_alive():
            return
        self.stopping = True
        if self.native:
            self.native.shutdown()
        thread.join(wait)

    def restart_backend(self, message: str = "配置已保存，正在重启回复服务"):
        was_paused = self.paused
        self.set_status(message)
        self.stop_backend()
        self.start_backend()
        if self.native:
            self.native.paused = was_paused
            self.native.emit({"event": "paused", "paused": was_paused})

    def shutdown(self):
        self.paused = True
        self.stop_backend(3.0)
        if self.native:
            self.native.close()

    # ------------------------------------------------------------------ user actions
    def toggle(self):
        """Start or pause the bot (the menu's 开始 / 暂停)."""
        problem = configuration_problem(self.config) if self.paused else None
        if problem:
            self.set_status(problem)
            self.show_settings_requested = True
            self._changed()
            return
        if self.paused and not self.backend_running:
            self.start_backend()
        self.paused = not self.paused
        if self.native:
            self.native.paused = self.paused
        self.set_status("已暂停" if self.paused else "正在记录现有消息")
        if self.native:
            self.native.emit({"event": "paused", "paused": self.paused})

    def request_proactive(self):
        """主动发起话题: start a topic in the configured chat that QQ currently shows."""
        if self.paused or not self.backend_running or self.native is None:
            return
        try:
            snapshot = self.native.call("snapshot")
        except Exception:
            snapshot = {}
        group = snapshot.get("activeConversation", "")
        if group not in self.config.get("groups", []):
            self.set_status("请先打开一个已配置的群聊")
            return
        self.native.emit({"event": "proactive_now", "group": group})
        self.set_status("已请求在当前群发起话题，写好后请选一条")

    def diagnostics(self) -> dict:
        """What the 诊断 page shows: is QQ there and readable, is the backend alive, are there permission mismatches."""
        from . import uia, win32
        windows = uia.top_level_windows("QQ.exe")
        visible = [w for w in windows if w["title"] == "QQ" and w["visible"] and not w["minimized"]]
        readable, detail = False, ""
        if visible:
            self.ensure_native()
            try:
                snapshot = self.native.call("snapshot")
                readable = "error" not in snapshot
                detail = snapshot.get("error", "")
            except Exception as exc:
                detail = type(exc).__name__
        elif not visible:
            detail = "没有找到可见的 QQ 主窗口（最小化或收在托盘里时读不到）"
        qq_elevated = None
        if windows:
            qq_elevated = win32.process_elevated(windows[0]["pid"])
        return {"qqRunning": bool(windows), "qqWindow": bool(visible), "qqReadable": readable, "readError": detail,
                "backendAlive": self.backend_running, "appElevated": win32.process_elevated(os.getpid()),
                "qqElevated": qq_elevated, "notifications": self.notify_sink is not None,
                "qqPath": next((w["image"] for w in windows), ""),
                "qqFlags": qqlaunch.flags_active(os.environ.get("QQBOT_TEST_PROCESS", "QQ.exe")) if windows else None}

    def restart_qq(self) -> dict:
        """Close QQ and start it again with the switches that keep it readable while covered (user-confirmed)."""
        result = qqlaunch.restart(self.config, os.environ.get("QQBOT_TEST_PROCESS", "QQ.exe"))
        self.notify("QQ 已重新启动" if result.get("ok") else "重启 QQ 失败", result.get("note") or result.get("error") or "请确认 QQ 已登录")
        return result

    def make_qq_shortcut(self) -> dict:
        return qqlaunch.make_shortcut(self.config, os.environ.get("QQBOT_TEST_PROCESS", "QQ.exe"))

    def choose_topic(self, index: int):
        if self.native:
            self.native.emit({"event": "topic_choice", "index": index})

    def revert_style_compression(self):
        if self.native:
            self.native.emit({"event": "style_revert"})

    def revert_feedback_round(self):
        if self.native:
            self.native.emit({"event": "feedback_revert"})

    def rate_reply(self, turn: dict, rating):
        """👍 'up' / 👎 'down' / None (withdrawn) on a sent reply, saved to runtime/reply-feedback.json."""
        path = self.base / "runtime/reply-feedback.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        turn_id = turn.get("id", "")
        if rating:
            data[turn_id] = {"rating": rating, "group": turn.get("group", ""), "title": turn.get("title", ""),
                             "reply": (turn.get("reply") or {}).get("text", ""),
                             "reason": (turn.get("decision") or {}).get("reason", ""), "time": time.time(),
                             "context": [{"sender": m.get("sender", ""), "text": m.get("text", "")}
                                         for m in (turn.get("messages") or [])[-3:]]}
        else:
            data.pop(turn_id, None)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        fsutil.replace(tmp, path)

    def open_config_file(self):
        os.startfile(str(self.base / "config.json"))  # noqa: S606

    # ------------------------------------------------------------------ derived state for the UI
    def engine_state(self) -> str:
        engine = self.engine
        return (engine.status.get("state") if engine else "") or ""

    def phase(self) -> str:
        """One word for what the bot is doing (same set as the macOS app)."""
        if self.paused:
            return "paused"
        engine = self.engine
        if not self.backend_running or engine is None:
            return "offline"
        beat = engine.status.get("updated_at")
        if beat:
            try:
                age = time.time() - time.mktime(time.strptime(beat, "%Y-%m-%d %H:%M:%S"))
                if age > 15:
                    return "offline"
            except ValueError:
                pass
        state = engine.status.get("state", "")
        return {"starting": "starting", "thinking": "thinking", "reply_ready": "sending", "verifying": "sending",
                "switch_pending": "switching", "error": "attention", "model_error": "attention",
                "delivery_uncertain": "attention", "config_error": "attention", "waiting": "waiting"}.get(state, "listening")
