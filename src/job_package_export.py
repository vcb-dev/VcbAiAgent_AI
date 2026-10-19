"""Export a hand-off package for a rendered job: final MP4 + SRT subtitles + timeline JSON + README.

This is the "structured manual assembly" fallback described in docs 05 §3.4 until the CapCut adapter ships.
"""
import json
import zipfile

from app_paths import MVP, RENDERS
from catalog_store import get_clip
from final_mix_renderer import export_mp4


def _srt_time(t: float) -> str:
    ms = int(round(max(t, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(job) -> str:
    rows = [f"{i}\n{_srt_time(c['start'])} --> {_srt_time(c['end'])}\n{c['text']}\n"
            for i, c in enumerate(job["timeline"]["subtitles"], 1)]
    return "\n".join(rows)


def _timeline_json(job) -> str:
    """Editor-neutral timeline (the MVP's Timeline IR): shots with source files + in/out, VO, SFX, settings."""
    shots = []
    for s in job["timeline"]["shots"]:
        sel = dict(s["selected"])
        if sel["kind"] == "clip":
            clip = get_clip(sel["clip_id"]) or {}
            sel.update(source_file=clip.get("file"), source_name=clip.get("name"))
        shots.append({"start": s["start"], "duration": s["duration"], "part_id": s["part_id"], "selected": sel})
    payload = {"schema": "vcb.mvp.timeline.v1", "job_id": job["id"], "duration": job["timeline"]["duration"],
               "canvas": {"w": 1080, "h": 1920, "fps": 30}, "template": job["template_id"], "sku": job["sku"],
               "settings": job.get("settings", {}), "shots": shots, "vo": job["timeline"]["vo"],
               "sfx": job["timeline"]["sfx"], "logo": job["timeline"]["logo"],
               "parts": [{k: p.get(k) for k in ("part_id", "role", "vo_text", "craft_step", "status", "emotion_override")}
                         for p in job["parts"]]}
    return json.dumps(payload, ensure_ascii=False, indent=1)


README = """VCB Video Agent — gói bàn giao
- final.mp4: video preview đã dựng (720x1280, -14 LUFS)
- subtitles.srt: phụ đề theo lời đọc
- timeline.json: bản dựng trung gian (shot, file nguồn trên NAS, điểm in, tốc độ, VO, SFX, cấu hình)
- vo/: lời đọc từng phần (wav)
Dùng để lắp lại trong CapCut khi chưa có adapter xuất project tự động.
"""


def build_package(job: dict) -> str:
    if job["render"].get("status") != "done" or not job["render"].get("url"):
        raise ValueError("Video chưa render xong")
    rev = job["render"]["revision"]
    out = RENDERS / job["id"] / f"package_r{rev}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(MVP / export_mp4(job), "final.mp4")
            z.writestr("subtitles.srt", _srt(job))
            z.writestr("timeline.json", _timeline_json(job))
            z.writestr("README.txt", README)
            for v in job["timeline"]["vo"]:
                z.write(MVP / v["audio"], f"vo/{v['part_id']}.wav")
    return str(out)
