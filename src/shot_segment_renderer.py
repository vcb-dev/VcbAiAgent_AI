"""Render one timeline shot to a cached, concat-ready segment (720x1280, 30fps, H.264, no audio).

Real footage shots are trimmed from the proxy; AI-generation / missing shots become labelled cards
so the client sees exactly where generated footage will go.
"""
import hashlib
import os
import subprocess
import textwrap
import uuid

from app_paths import CANVAS_H, CANVAS_W, FONT_FILE, FPS, MVP, SHOT_CACHE, has_ffmpeg_filter

ENCODE = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
          "-r", str(FPS), "-video_track_timescale", "15360", "-movflags", "+faststart"]
CARD_TITLES = {"product_video": "ĐỀ XUẤT AI · CẢNH SẢN PHẨM", "huyk_avatar": "ĐỀ XUẤT AI · HUYK NÓI (AVATAR)",
               "illustration": "ĐỀ XUẤT AI · B-ROLL MINH HỌA", "shoot_request": "PHIẾU QUAY BỔ SUNG",
               "missing": "THIẾU FOOTAGE"}


def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr[-500:]}")


HAS_DRAWTEXT = has_ffmpeg_filter("drawtext")


def _encode_atomic(cmd_without_output, out):
    """Encode to a temp file then rename, so a killed/failed ffmpeg never leaves a reusable partial file."""
    tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex[:6]}.tmp.mp4")
    try:
        _run([*cmd_without_output, str(tmp)])
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


def _frames(duration: float) -> int:
    return max(1, round(duration * FPS))


def _fades(duration: float, fade_in: bool, fade_out: bool) -> str:
    """Dip-to-black transition edges (0.18 s) for the first/last shot of a part."""
    parts = ["fade=t=in:st=0:d=0.18"] if fade_in else []
    if fade_out:
        parts.append(f"fade=t=out:st={max(duration - 0.18, 0):.3f}:d=0.18")
    return ("," + ",".join(parts)) if parts else ""


def render_clip_shot(clip: dict, src_in: float, duration: float, speed: float, zoom: float = 1.0,
                     fade_in: bool = False, fade_out: bool = False) -> str:
    zoom = min(max(float(zoom or 1.0), 1.0), 1.4)
    key = hashlib.sha1(f"{clip['id']}|{src_in}|{duration}|{speed}|{zoom}|{fade_in}|{fade_out}".encode()).hexdigest()[:16]
    out = SHOT_CACHE / f"clip_{key}.mp4"
    if not out.exists():
        crop = f"crop=iw/{zoom}:ih/{zoom}," if zoom > 1.0 else ""          # centre punch-in
        vf = (f"setpts=PTS/{speed},fps={FPS},{crop}scale={CANVAS_W}:{CANVAS_H},format=yuv420p"
              f"{_fades(duration, fade_in, fade_out)}")
        _encode_atomic(["ffmpeg", "-y", "-v", "error", "-ss", f"{src_in:.3f}", "-i", str(MVP / clip["proxy"]),
                        "-t", f"{duration * speed + 0.2:.3f}", "-vf", vf, "-frames:v", str(_frames(duration)), *ENCODE], out)
    return str(out)


def render_card_shot(gen: dict, duration: float, fade_in: bool = False, fade_out: bool = False) -> str:
    """Labelled placeholder card for an AI generation suggestion (or a missing slot)."""
    kind = gen.get("type", "missing")
    # every line is wrapped: drawtext centres on the widest line, so nothing may exceed the card width
    lines = textwrap.wrap(CARD_TITLES.get(kind, "ĐỀ XUẤT AI"), 24) + [""]
    lines += textwrap.wrap(gen.get("provider", ""), 26) + [""]
    lines += textwrap.wrap(gen.get("prompt", "Kho chưa có cảnh phù hợp"), 26)[:6]
    if gen.get("est_cost_usd"):
        lines += ["", f"Ước tính: ${gen['est_cost_usd']:.2f}"]
    body = "\n".join(lines)
    key = hashlib.sha1(f"v2|{kind}|{body}|{duration}|{fade_in}|{fade_out}".encode()).hexdigest()[:16]
    out = SHOT_CACHE / f"card_{key}.mp4"
    if not out.exists():
        txt = SHOT_CACHE / f"card_{key}.txt"
        txt.write_text(body, encoding="utf-8")
        accent = "0xd1ad62" if kind != "missing" else "0xd9776b"
        # Không có drawtext thì vẫn dựng thẻ, chỉ mất phần chữ: thiếu một cảnh phụ còn hơn
        # hỏng cả bản render. Nội dung thẻ vẫn nằm trong timeline.json để bàn giao.
        label = (f",drawtext=fontfile='{FONT_FILE}':textfile='{txt}':expansion=none:fontcolor=white:fontsize=30:"
                 f"line_spacing=12:x=(w-text_w)/2:y=max(290\\,(h-text_h)/2)") if HAS_DRAWTEXT else ""
        vf = (f"drawbox=x=40:y=40:w={CANVAS_W - 80}:h={CANVAS_H - 80}:color={accent}@0.9:t=4"
              f"{label}{_fades(duration, fade_in, fade_out)}")  # chữ nằm dưới dải caption của hook
        _encode_atomic(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"color=c=0x16130d:s={CANVAS_W}x{CANVAS_H}:r={FPS}:d={duration + 0.2:.3f}",
                        "-vf", vf, "-frames:v", str(_frames(duration)), *ENCODE], out)
    return str(out)
