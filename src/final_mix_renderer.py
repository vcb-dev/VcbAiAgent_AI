"""Assemble the preview MP4: concat shots -> burned subtitles -> VO/music/SFX mix.

Music is ducked under the VO with sidechaincompress; loudness normalised to -14 LUFS (social).
"""
import subprocess
from functools import lru_cache

from app_paths import ASSETS, FONT_DIR, MVP, RENDERS, has_ffmpeg_filter
from catalog_store import get_clip
from job_settings import DEFAULTS
from music_library import resolve as music_file
from shot_segment_renderer import render_card_shot, render_clip_shot

COLOR_FILTERS = {"none": "", "warm": ",eq=contrast=1.06:saturation=1.10,colorbalance=rs=0.04:gs=0.01:bs=-0.04",
                 "cool": ",eq=contrast=1.05:saturation=1.02,colorbalance=rs=-0.03:bs=0.05"}
SUB_STYLES = {  # ASS style lines: opaque box (like the real CapCut project) or outline only
    "box": "Style: Sub,Arial Unicode MS,40,&H00FFFFFF,&H00000000,&H99000000,0,3,6,0,2,60,60,230",
    "outline": "Style: Sub,Arial Unicode MS,44,&H00FFFFFF,&H00000000,&H00000000,1,1,3,1,2,60,60,230",
}

SFX_FILES = {"torch": ASSETS / "sfx_torch.wav", "hammer": ASSETS / "sfx_hammer.wav",
             "sparkle": ASSETS / "sfx_sparkle.wav"}


def _run(cmd, cwd=None):
    res = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr[-800:]}")


def _ass_time(t: float) -> str:
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_text(text: str) -> str:
    """Neutralise ASS override blocks/line breaks coming from user script text."""
    return " ".join(str(text).replace("{", "(").replace("}", ")").replace("\\", "/").split())


def _write_ass(job, path, cfg):
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
            f"{SUB_STYLES[cfg['subtitle_style']]}\n"
            "Style: Hook,Arial Unicode MS,54,&H0062ADD1,&H00000000,&H00000000,1,1,4,2,8,50,50,150\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    cues = job["timeline"]["subtitles"] if cfg["subtitles"] else []
    rows = [f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Sub,,0,0,0,,{_ass_text(c['text'])}" for c in cues]
    first = job["parts"][0] if job["parts"] else None
    if cfg["hook_text"] and first and first.get("on_screen_text"):
        rows.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(first['duration'])},Hook,,0,0,0,,{_ass_text(first['on_screen_text'])}")
    path.write_text(head + "\n".join(rows) + "\n", encoding="utf-8")


def _clip_take(clip: dict, src_in: float, duration: float, speed: float) -> float:
    """Không xin lâu hơn số giây còn lại trong file — ffmpeg sẽ pad đen nếu hết nguồn."""
    if not clip:
        return duration
    file_dur = float((clip.get("tech") or {}).get("duration") or 0)
    usable = clip.get("usable") or [0.0, file_dur]
    hi = float(usable[1] if len(usable) > 1 else file_dur or 0)
    if file_dur > 0:
        hi = min(hi, file_dur)
    remain = max(0.0, hi - float(src_in or 0))
    if remain <= 0.05:
        return duration
    return round(min(float(duration), remain / max(float(speed) or 1.0, 0.01)), 3)


def _probe_duration(path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return float((res.stdout or "").strip())
    except ValueError:
        return 0.0


def _segments(job, cfg):
    gens = {g["gen_id"]: g for p in job["parts"] for g in p.get("gen_options", [])}
    dip, last_part = cfg["transition"] == "dip", job["parts"][-1]["part_id"] if job["parts"] else None
    first_part = job["parts"][0]["part_id"] if job["parts"] else None
    count = {}
    for shot in job["timeline"]["shots"]:
        count[shot["part_id"]] = count.get(shot["part_id"], 0) + 1
    files = []
    for shot in job["timeline"]["shots"]:
        sel, pid = shot["selected"], shot["part_id"]
        fin = dip and shot["index"] == 0 and pid != first_part
        fout = dip and shot["index"] == count[pid] - 1 and pid != last_part
        if sel["kind"] == "clip":
            clip = get_clip(sel["clip_id"])
            take = _clip_take(clip, sel.get("src_in", 0), shot["duration"], sel.get("speed", 1))
            files.append(render_clip_shot(clip, sel["src_in"], take, sel["speed"],
                                          sel.get("zoom", 1.0), fin, fout))
        else:
            files.append(render_card_shot(gens.get(sel.get("gen_id"), {"type": "missing"}), shot["duration"], fin, fout))
    return files


@lru_cache(maxsize=None)
def _has_audio_stream(path: str) -> bool:
    """Proxy nào cũng khai has_audio nhưng không phải bản nào cũng còn luồng tiếng."""
    res = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name",
                          "-of", "csv=p=0", path], capture_output=True, text=True, check=False)
    return bool(res.stdout.strip())


def _music_end(job) -> float:
    """Nhạc chạy tới trước outro (hoặc khối tiếng gốc), không kéo vào outro."""
    tl = job.get("timeline") or {}
    if tl.get("music_end") is not None:
        return max(0.0, float(tl["music_end"]))
    T = float(tl.get("duration") or 0)
    starts = [float(p.get("start") or 0) for p in job.get("parts") or []
              if p.get("role") == "outro" or p.get("source_audio")]
    return max(0.0, min(starts)) if starts else T


def _audio_graph(job, first_input, cfg):
    """Build audio inputs + filter graph. Returns (input_args, filter_parts, out_label).

    Loudnorm chỉ cho giọng / outro / SFX. Nhạc nhân volume sau đó — 0% hết nhạc,
    4% không bị kéo lên -14 LUFS như khi mix chung.
    """
    T = job["timeline"]["duration"]
    mus_end = min(_music_end(job), T)
    args, filt, idx = [], [], first_input
    vo_labels, src_labels, sfx_labels = [], [], []
    for n, v in enumerate(job["timeline"]["vo"]):
        args += ["-i", str(MVP / v["audio"])]
        ms = int(v["start"] * 1000)
        filt.append(f"[{idx}:a]adelay={ms}:all=1[vo{n}]")
        vo_labels.append(f"[vo{n}]")
        idx += 1
    # Tiếng sẵn trong clip (outro): không đưa vào sidechain — nhạc đã tắt trước outro.
    for n, s in enumerate(job["timeline"].get("source_audio", [])):
        proxy = str(MVP / get_clip(s["clip_id"])["proxy"])
        if not _has_audio_stream(proxy):
            continue
        args += ["-ss", f"{s['src_in']:.3f}", "-i", proxy]
        tempo = f",atempo={s['speed']:.3f}" if abs(s["speed"] - 1.0) > 0.01 else ""
        take = _clip_take(get_clip(s["clip_id"]), s.get("src_in", 0), s["duration"], s.get("speed", 1))
        filt.append(f"[{idx}:a]atrim=0:{take * s['speed']:.3f},asetpts=N/SR/TB{tempo},"
                    f"afade=t=out:st={max(take - 0.3, 0):.3f}:d=0.3,"
                    f"adelay={int(s['start'] * 1000)}:all=1[src{n}]")
        src_labels.append(f"[src{n}]")
        idx += 1
    for n, s in enumerate(job["timeline"]["sfx"] if cfg["sfx"] else []):
        if SFX_FILES.get(s["kind"]) and SFX_FILES[s["kind"]].exists():
            args += ["-i", str(SFX_FILES[s["kind"]])]
            filt.append(f"[{idx}:a]atrim=0:1.5,adelay={int(s['start'] * 1000)}:all=1,volume=0.35[sfx{n}]")
            sfx_labels.append(f"[sfx{n}]")
            idx += 1
    beds = vo_labels + src_labels + sfx_labels
    if len(beds) > 1:
        filt.append(f"{''.join(beds)}amix=inputs={len(beds)}:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[voice]")
    elif beds:
        filt.append(f"{beds[0]}loudnorm=I=-14:TP=-1.5:LRA=11[voice]")
    else:
        filt.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{T:.3f},asetpts=N/SR/TB[voice]")
    vol = float(cfg.get("music_volume") or 0)
    if vol > 0 and mus_end > 0.05:
        fade = min(0.8, max(mus_end * 0.2, 0.25))
        # File royalty-free thường ~-23 LUFS; nhân đúng số slider thì nhạc nằm quá sâu
        # dưới giọng -14 — kéo 20%↔80% gần như không nghe. Boost để 100% gần ngang giọng.
        gain = round(min(vol, 1.0) * 5.0, 3)
        args += ["-stream_loop", "-1", "-t", f"{mus_end:.3f}", "-i", music_file(cfg["music_track"])]
        filt.append(
            f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={gain},"
            f"afade=t=out:st={max(mus_end - fade, 0):.3f}:d={fade:.3f}[mus]"
        )
        idx += 1
        mix_out = "amix=inputs=2:normalize=0,alimiter=limit=0.95:attack=7:release=50,aresample=48000[aout]"
        if vo_labels:
            filt.append("[voice]asplit=2[vo][vosc]")
            # Duck nhẹ: nhạc vẫn đổi khi kéo fader, không bị nén thành một mức.
            filt.append("[mus][vosc]sidechaincompress=threshold=0.14:ratio=1.6:attack=50:release=220[duck]")
            filt.append(f"[vo][duck]{mix_out}")
        else:
            filt.append(f"[voice][mus]{mix_out}")
    else:
        filt.append("[voice]aresample=48000[aout]")
    return args, filt, "[aout]"


def render_job(job: dict, revision: int) -> str:
    work = RENDERS / job["id"] / f"r{revision}"          # per-revision dir: concurrent renders never share files
    work.mkdir(parents=True, exist_ok=True)
    cfg = {**DEFAULTS, **job.get("settings", {})}
    (work / "concat.txt").write_text("".join(f"file '{f}'\n" for f in _segments(job, cfg)), encoding="utf-8")
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "video.mp4"], cwd=work)
    concat_t = _probe_duration(work / "video.mp4")
    planned = float(job["timeline"]["duration"])
    # Nếu footage hết sớm hơn timeline, cắt theo video concat — đừng pad đen cho đủ T.
    out_t = min(planned, concat_t) if concat_t > 0.2 else planned
    mix_job = {**job, "timeline": {**job["timeline"], "duration": out_t}}
    _write_ass(mix_job, work / "subs.ass", cfg)
    # Phụ đề cháy vào hình cần ffmpeg có libass. Bản không có thì vẫn xuất video, phụ đề
    # đi kèm dưới dạng file .ass/.srt trong gói bàn giao thay vì làm hỏng cả bản render.
    chain = []
    if has_ffmpeg_filter("ass"):
        chain.append(f"ass=subs.ass:fontsdir={FONT_DIR}")
    chain += [f for f in COLOR_FILTERS[cfg["color"]].split(",") if f]
    vfilt = f"[0:v]{','.join(chain)}[v]" if chain else "[0:v]null[v]"
    a_args, a_filt, a_out = _audio_graph(mix_job, 1, cfg)
    out_name = f"{job['id']}_r{revision}.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-i", "video.mp4", *a_args,
          "-filter_complex", ";".join([vfilt, *a_filt]), "-map", "[v]", "-map", a_out,
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-b:a", "160k",
          "-t", f"{out_t:.3f}", "-movflags", "+faststart", str(RENDERS / out_name)], cwd=work)
    poster = RENDERS / out_name.replace(".mp4", ".jpg")             # still frame for the player / screenshots
    _run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", str(RENDERS / out_name), "-frames:v", "1", "-q:v", "3", str(poster)])
    return f"media/renders/{out_name}"


def _picture_src(job: dict):
    """Luôn copy từ bản encode hình gốc, không lấy file remix (tránh chồng tiếng)."""
    render = job.get("render") or {}
    rev = render.get("revision", 0)
    original = RENDERS / f"{job['id']}_r{rev}.mp4"
    if original.exists():
        return original
    src = MVP / (render.get("url") or "")
    return src if src.exists() else None


def export_mp4(job: dict) -> str:
    """Nướng nhạc/âm lượng hiện tại lên bản hình đã dựng — copy video, không encode lại cảnh.

    0% thì không đưa nhạc vào mix. Copy luồng hình nên chỉ mất vài giây.
    """
    render = job.get("render") or {}
    src = _picture_src(job)
    if src is None:
        raise ValueError("Video chưa render xong")
    cfg = {**DEFAULTS, **job.get("settings", {})}
    vol = round(float(cfg.get("music_volume") or 0), 2)
    track = str(cfg.get("music_track") or "default")
    safe_track = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in track)[:80]
    out_name = f"{job['id']}_r{render.get('revision', 0)}_{safe_track}_{int(vol * 100)}_a4.mp4"
    out = RENDERS / out_name
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return f"media/renders/{out_name}"
    T = float((job.get("timeline") or {}).get("duration") or 0)
    if T < 0.2:
        T = _probe_duration(src)
    a_args, a_filt, a_out = _audio_graph(job, 1, cfg)
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), *a_args,
          "-filter_complex", ";".join(a_filt), "-map", "0:v", "-map", a_out,
          "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
          "-t", f"{T:.3f}", "-movflags", "+faststart", str(out)])
    return f"media/renders/{out_name}"
