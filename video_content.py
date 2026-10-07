"""Subtitle inspection and bounded, silent sampling of HTML video elements."""
import math
import os
from pathlib import Path
import time
import uuid


def frame_times(duration, count=8):
    if not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("视频没有可定位的有限时长，无法抽帧")
    count = max(5, min(20, int(count)))
    return [round(duration * (i + 0.5) / count, 3) for i in range(count)]


def primary_video(page):
    candidates = []
    for frame in page.frames:
        for video in frame.locator("video").all():
            if video.is_visible():
                bounds = video.bounding_box()
                if bounds:
                    candidates.append((bounds["width"] * bounds["height"], video))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def inspect_video(page):
    video = primary_video(page)
    if video is None:
        return {"present": False, "subtitles_status": "unknown", "subtitles": ""}
    # Hidden text tracks load cues without displaying or playing the video.
    result = video.evaluate("""async v => {
      const tracks = Array.from(v.textTracks).filter(t => ['subtitles','captions'].includes(t.kind));
      const modes = tracks.map(t => t.mode);
      try {
        tracks.forEach(t => {if (t.mode === 'disabled') t.mode='hidden'});
        if (tracks.length && !tracks.some(t => t.cues && t.cues.length))
          await new Promise(r => setTimeout(r, 1200));
        const cues = tracks.flatMap(t => Array.from(t.cues || []).map(c => ({start:c.startTime,end:c.endTime,text:c.text})));
        return {present:true, duration:Number.isFinite(v.duration)?v.duration:null,
          ready:v.readyState, current_time:v.currentTime, paused:v.paused,
          subtitles_status:cues.length?'available':(tracks.length?'unreadable':'unavailable'),
          subtitles:cues.map(c => `[${c.start.toFixed(1)}s] ${c.text}`).join('\\n').slice(0,20000)};
      } finally {tracks.forEach((t,i) => t.mode=modes[i])}
    }""")
    # Some sites expose transcripts as ordinary DOM instead of HTML text tracks.
    if not result["subtitles"]:
        for frame in page.frames:
            rows = frame.locator("ytd-transcript-segment-renderer, .bpx-player-subtitle-panel-text, .subtitle-item-text")
            if rows.count():
                transcript = "\n".join(rows.all_inner_texts())[:20000].strip()
                if transcript:
                    result.update(subtitles_status="available", subtitles=transcript)
                    break
    return result


def capture_frames(page, directory, count=8):
    video = primary_video(page)
    if video is None:
        raise RuntimeError("当前页面没有可见的视频播放器")
    original = video.evaluate("v => ({time:v.currentTime,paused:v.paused,muted:v.muted,duration:Number.isFinite(v.duration)?v.duration:null})")
    positions = frame_times(original["duration"], count)
    output = []
    errors = []
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 90
    try:
        video.evaluate("v => {v.muted=true;v.pause()}")
        for target in positions:
            if time.monotonic() >= deadline:
                errors.append("已达到抽帧时间上限")
                break
            try:
                actual = video.evaluate("""(v, target) => new Promise((resolve,reject) => {
                  const timer=setTimeout(() => {cleanup();reject(new Error('seek timeout'))},3500);
                  function cleanup(){clearTimeout(timer);v.removeEventListener('seeked',done)}
                  function done(){if(v.readyState>=2){cleanup();resolve(v.currentTime)}}
                  v.addEventListener('seeked',done);v.currentTime=target;
                })""", target)
                video.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                path = directory / f"frame-{uuid.uuid4().hex}.jpg"
                try:
                    video.screenshot(path=str(path), type="jpeg", quality=65, timeout=4000)
                except Exception:
                    path.unlink(missing_ok=True)
                    raise
                os.chmod(path, 0o600)
                output.append({"path": str(path), "time": round(actual, 3)})
            except Exception as exc:
                errors.append(str(exc)[:160])
    finally:
        try:
            video.evaluate("""(v,s) => {v.pause();v.currentTime=s.time;v.muted=s.muted;
              if(!s.paused) v.play().catch(()=>{});} """, original)
        except Exception:
            pass
    return {"frames": output, "requested_frames": len(positions), "captured_frames": len(output),
            "duration": original["duration"], "errors": errors,
            "coverage": "稀疏采样，可能漏掉帧间动作；没有分析音频"}
