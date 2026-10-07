"""Dedicated visible browser: navigation, reading and media playback only."""
import ipaddress
import json
from pathlib import Path
import re
import socket
import sys
import urllib.parse
import urllib.request
from video_content import inspect_video, capture_frames


def public_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("仅支持公开 HTTP/HTTPS 网页")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("不允许访问本机或内网地址")
    return value


def snapshot(page):
    dates = page.evaluate("""() => {
      const get = keys => keys.map(key => document.querySelector(`meta[property="${key}"],meta[name="${key}"]`)?.content).find(Boolean) || '';
      return {
        published: get(['article:published_time','datePublished','pubdate','date']) || document.querySelector('time[datetime]')?.getAttribute('datetime') || '',
        modified: get(['article:modified_time','dateModified','last-modified'])
      };
    }""")
    return {"url": page.url, "title": page.title(),
            "dates": dates,
            "text": page.locator("body").inner_text(timeout=5000)[:14000],
            "links": page.locator("a[href]").evaluate_all("els => els.filter(e => e.innerText.trim()).slice(0,60).map(e => ({text:e.innerText.slice(0,100),url:e.href}))"),
            "media": [frame.locator("video,audio").evaluate_all("els => els.map(e => ({paused:e.paused,time:e.currentTime,ready:e.readyState,ended:e.ended}))") for frame in page.frames],
            "video": inspect_video(page)}


def read_page(url):
    url = public_url(url)
    request = urllib.request.Request("https://r.jina.ai/" + url, headers={"User-Agent": "QQChatBridge/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        text = response.read(100000).decode(errors="replace")[:18000]
    header = text[:1200]
    published = re.search(r"(?im)^(?:Published Time|Published Date|Publication Date):\s*(.+)$", header)
    modified = re.search(r"(?im)^(?:Last Modified|Modified Time):\s*(.+)$", header)
    return {"url": url, "source": "Jina Reader", "text": text,
            "dates": {"published": published.group(1).strip()[:80] if published else "",
                      "modified": modified.group(1).strip()[:80] if modified else ""}}


def execute(context, page, action):
    op = action.get("action")
    if op == "open":
        url = public_url(action.get("url", ""))
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(800)
    elif op == "read":
        pass
    elif op == "scroll":
        page.mouse.wheel(0, 650)
        page.wait_for_timeout(400)
    elif op in ("play", "pause"):
        found = False
        errors = []
        for frame in page.frames:
            media = frame.locator("video,audio")
            if media.count():
                found = True
                try:
                    media.first.evaluate("async e => {e.dataset.qqPlaybackAllowed='true';e.muted=false;await e.play()}" if op == "play" else "e => {delete e.dataset.qqPlaybackAllowed;e.pause()}", timeout=8000)
                except Exception as exc:
                    errors.append(str(exc)[:200])
        if not found:
            raise RuntimeError("网页尚未出现播放器，可能需要登录或加载")
        page.wait_for_timeout(1200)
        state = snapshot(page)
        if op == "play" and not any(not m["paused"] and m["ready"] >= 2 for items in state["media"] for m in items):
            state["error"] = "未确认播放成功：" + "; ".join(errors)
        return state
    elif op == "wait":
        page.wait_for_timeout(1500)
    elif op == "reader":
        return read_page(action.get("url", ""))
    elif op == "video_frames":
        info = inspect_video(page)
        if action.get("worth_watching") is not True:
            raise ValueError("尚未判断值得继续观看")
        if info.get("subtitles_status") == "available" and action.get("needs_visual") is not True:
            raise ValueError("已有可用字幕且无需画面，本次不抽帧")
        return {"url": page.url, "video": info, **capture_frames(page, Path(__file__).resolve().parent / "runtime/video-frames", action.get("frame_count", 8))}
    else:
        raise ValueError("未知浏览动作")
    return snapshot(page)


def main():
    from playwright.sync_api import sync_playwright
    profile = Path(sys.argv[1])
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(profile), channel="chrome", headless=False, chromium_sandbox=True,
                    accept_downloads=False)
        context.add_init_script("""document.addEventListener('play', e => {
          if(e.target instanceof HTMLMediaElement && e.target.dataset.qqPlaybackAllowed !== 'true') {
            e.target.muted=true;e.target.pause();
          }
        }, true);""")
        def route(request_route):
            try:
                public_url(request_route.request.url)
                request_route.continue_()
            except Exception:
                request_route.abort()
        context.route("**/*", route)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(8000)
        for line in sys.stdin:
            try:
                result = execute(context, page, json.loads(line))
            except Exception as exc:
                result = {"error": str(exc)[:500]}
            print(json.dumps(result, ensure_ascii=False), flush=True)
        context.close()


if __name__ == "__main__":
    main()
