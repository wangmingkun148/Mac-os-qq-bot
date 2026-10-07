"""Developer harness: serve the web UI on a throw-away project folder so it can be opened in any browser.

    .venv\\Scripts\\python.exe -X utf8 tools\\dev_ui.py          # prints the URLs and keeps running
Sample turns are injected into the live feed so every card type is visible. Nothing touches QQ (dry run)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from winapp import win32  # noqa: E402
from winapp.app import App  # noqa: E402
from winapp.webui import WebUI  # noqa: E402


def main():
    base = Path(tempfile.mkdtemp(prefix="qqbot-ui-"))
    shutil.copytree(ROOT / "prompts", base / "prompts")
    for name in ("config.example.json", "bridge.py"):
        shutil.copy(ROOT / name, base / name)
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config.update({"groups": ["测试群"], "self_names": ["我"]})
    config["ai"].update({"name": "示例供应商", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-test-secret", "model": "demo-model"})
    (base / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    win32.set_dpi_aware()
    app = App(base, dry_run=True)
    assert app.prepare_project() is None
    app.ensure_native()
    app.start_backend()
    time.sleep(1.0)
    app.toggle()
    time.sleep(1.5)
    live = app.engine.live
    msgs = [{"id": "1", "sender": "小明", "text": "今天天气不错，有人打游戏吗", "has_image": False}]
    t1 = live.begin("测试群", "测试群", "reply", msgs)
    live.update(t1, decision={"should_reply": True, "reason": "有人在问大家要不要一起玩，适合接话", "model": "demo-model", "seconds": 1.8},
                reply={"text": "我可以！晚上几点？", "reason": "语气轻松一点", "model": "demo-model"}, tokens={"input": 1200, "output": 30, "seconds": 1.8})
    live.step(t1, "verifying", "已提交发送，等待 QQ 回显")
    live.finish(t1, "replied", "已发送并确认（2.3s）")
    t2 = live.begin("测试群", "测试群", "reply", [{"id": "2", "sender": "小红", "text": "哈哈哈哈", "has_image": False}])
    live.update(t2, decision={"should_reply": False, "reason": "只是笑声，没有话题可接"})
    live.finish(t2, "silent", "本轮不接话")
    t3 = live.begin("测试群", "测试群", "reply", [{"id": "3", "sender": "小刚", "text": "", "has_image": True}, {"id": "4", "sender": "小刚", "text": "这是什么？", "has_image": False}])
    live.update(t3, error="AI 接口请求失败：HTTP 500")
    live.finish(t3, "failed", "第 1 次失败，60 秒后重试")
    t4 = live.begin("测试群", "测试群", "reply", [{"id": "5", "sender": "小明", "text": "有人在吗？@我", "has_image": False}])
    live.step(t4, "generating", "正在生成回复")
    live.set_waiting({"测试群": ("测试群", [{"id": "6", "sender": "小红", "text": "等一下我也来", "has_image": False}])})
    live.note("基线已建立：测试群")
    live.flush(force=True)

    web = WebUI(app, None)
    web.start()
    for view in ("popover", "live", "settings/general", "settings/providers", "settings/diagnostics"):
        print(web.url(view))
    sys.stdout.flush()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    app.shutdown()
    shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
