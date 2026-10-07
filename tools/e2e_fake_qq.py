"""End-to-end test of the Windows automation against the mock QQ page (no real account involved).

    .venv\\Scripts\\python.exe -X utf8 tools\\e2e_fake_qq.py

It opens the mock QQ in an Edge app window (InPrivate), runs the real engine with a fake AI, and checks:
reading, replying (type + send + read-back confirmation), switching chats, sending an image, copying an image.
It takes over the keyboard/mouse for roughly a minute; do not type while it runs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "fake_qq"))

os.environ["QQBOT_TEST_PROCESS"] = "msedge.exe"

from PIL import Image  # noqa: E402

from server import FakeQQ  # noqa: E402
from winapp import uia, win32  # noqa: E402
from winapp.app import App  # noqa: E402

EDGE = next((str(p) for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
                              Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe") if p.is_file()), "")
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def wait_for(predicate, timeout, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return None


def main():
    if not EDGE:
        print("Edge not found")
        return 2
    win32.set_dpi_aware()
    fake = FakeQQ()
    profile = Path(tempfile.mkdtemp(prefix="qqbot-fake-edge-"))
    base = Path(tempfile.mkdtemp(prefix="qqbot-e2e-"))
    edge = subprocess.Popen([EDGE, f"--app={fake.url}", f"--user-data-dir={profile}", "--inprivate", "--no-first-run",
                             "--window-size=1000,700", "--window-position=60,60", "--disable-sync", "--disable-extensions",
                             "--disable-features=msImplicitSignin,msEdgeOnRamp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = None
    try:
        hwnd = wait_for(lambda: next((w["hwnd"] for w in uia.top_level_windows("msedge.exe")
                                      if w["title"].startswith("QQ - ") and w["visible"]), 0), 20)
        check("mock QQ window opened", bool(hwnd))
        if not hwnd:
            return 1
        time.sleep(1.5)

        shutil.copytree(ROOT / "prompts", base / "prompts")
        for name in ("config.example.json", "bridge.py"):
            shutil.copy(ROOT / name, base / name)
        config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        config.update({"groups": ["测试群"], "self_names": ["小我"], "poll_seconds": 1, "merge_seconds": 1, "max_merge_seconds": 3,
                      "cooldown_seconds": 0, "typing_quiet_seconds": 0.5, "split_reply_min_chars": 0, "verify_seconds": 20})
        config["ai"].update({"name": "fake", "base_url": fake.url + "v1", "api_key": "test", "model": "fake", "suffix": "", "timeout_seconds": 20})
        (base / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        app = App(base)
        assert app.prepare_project() is None
        notices = []
        app.notify_sink = lambda title, body: notices.append((title, body))
        app.ensure_native()
        app.start_backend()
        time.sleep(1)
        app.toggle()
        started = wait_for(lambda: app.engine and app.engine.status.get("baseline_groups") and True, 25)
        check("engine built the baseline from the mock page", bool(started), app.status_text)

        # 1. a message that mentions us -> reply typed into the editor, sent, and confirmed by reading it back
        fake.inject("测试群", "小明", "你好 @小我 在吗")
        sent = wait_for(lambda: [m for m in fake.sent if m.get("chat") == "测试群" and m.get("text")], 40)
        check("reply was typed and sent into the mock chat", bool(sent), json.dumps(sent, ensure_ascii=False) if sent else app.status_text)
        confirmed = wait_for(lambda: app.engine and app.engine.status.get("verified_replies", 0) >= 1, 25)
        check("send was confirmed by reading the message back", bool(confirmed), app.status_text)
        check("no uncertain-send pause", not any("不确定" in t or "无法确认" in t for t, _ in notices), str(notices))

        # 2. reply_all: a message in another chat -> switch to it, reply there
        new = json.loads((base / "config.json").read_text(encoding="utf-8"))
        new["reply_all_conversations"] = True
        problem = app.apply_config(new, restart=True)
        check("config applied (reply_all on)", problem is None, str(problem))
        time.sleep(2)
        if app.paused:
            app.toggle()
        wait_for(lambda: app.engine and app.engine.status.get("baseline_groups") and True, 20)
        time.sleep(3)
        before = len(fake.sent)
        fake.inject("朋友", "朋友", "在吗？@小我")
        sent2 = wait_for(lambda: [m for m in fake.sent[before:] if m.get("chat") == "朋友"], 45)
        check("switched to the other chat and replied there", bool(sent2), json.dumps(fake.sent[before:], ensure_ascii=False) if not sent2 else "")

        # 3. image: send a picture into the open chat, then copy one out of the chat
        app.toggle()                                   # pause the engine so it does not interfere with direct operations
        time.sleep(1)
        app.native.paused = False                      # operations are refused while paused; talk to the native layer directly
        runtime = base / "runtime"
        picture = runtime / "generated-test.png"
        Image.new("RGB", (160, 100), (30, 140, 60)).save(picture)
        selected = app.native.call("select", group="测试群")
        check("select switches back to the main chat", bool(selected.get("ok")), json.dumps(selected))
        time.sleep(1)
        before = len(fake.sent)
        result = app.native.call("send_image", group="测试群", text="", path=str(picture))
        check("send_image returned ok", bool(result.get("ok")), json.dumps(result))
        image_sent = wait_for(lambda: [m for m in fake.sent[before:] if m.get("image")], 10)
        check("image arrived in the mock chat", bool(image_sent))

        fake.inject("测试群", "小红", "", image=True)
        time.sleep(1.5)
        snap = app.native.call("snapshot")
        check("snapshot sees the image message", "error" not in snap, str(snap.get("error")))
        from snapshot import parse_snapshot
        parsed = parse_snapshot(snap, {"groups": ["测试群"], "self_names": ["小我"], "reply_all_conversations": False})
        images = [m for m in parsed.get("messages", []) if m.get("has_image") and not m.get("self")]
        check("parser flags the incoming image", bool(images))
        if images:
            captured = app.native.call("capture_image", group="测试群", message_id=images[-1]["id"])
            ok = bool(captured.get("path")) and Path(captured["path"]).is_file()
            check("capture_image copied the picture out (right-click > 复制)", ok, json.dumps(captured))
            if ok:
                with Image.open(captured["path"]) as img:
                    check("captured picture is a valid image", img.size[0] > 20, str(img.size))
    finally:
        if app:
            app.shutdown()
        edge.terminate()
        for proc in subprocess.run(["powershell", "-NoProfile", "-Command",
                                    f"Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object {{ $_.CommandLine -match 'qqbot-fake-edge' }} | ForEach-Object {{ $_.ProcessId }}"],
                                   capture_output=True, text=True).stdout.split():
            subprocess.run(["taskkill", "/F", "/PID", proc], capture_output=True)
        time.sleep(1)
        fake.stop()
        if fake.logs:
            print("--- page log ---")
            print("\n".join(fake.logs))
        for name in ("native.log", "bridge.log"):
            log = base / "runtime" / name
            if log.exists() and any(not ok for _, ok in results):
                print(f"--- {name} (tail) ---")
                print("\n".join(log.read_text(encoding="utf-8").splitlines()[-40:]))
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)
    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
