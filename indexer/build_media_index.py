"""Build the MVP media index from the VCB real sample library.

For every source clip: ffprobe -> proxy 720x1280 SDR 30fps (tone-maps HLG, auto-rotates)
-> thumbnail -> 12-frame contact sheet (for AI tagging) -> filename parse -> folder role hints.
Takes longer than 30 s (e.g. raw 2-3 min 4K) go through long_clip_segmenter: one entry per kept window.
Output: mvp/data/media-index.json. Idempotent: existing proxies/sheets are reused.

Run:  python3.11 mvp/indexer/build_media_index.py
"""
import hashlib
import json
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]      # VCB_AI
ROOT = MVP.parent                              # repo root: chứa thư mục footage gốc từ NAS
sys.path.insert(0, str(MVP / "src"))
from footage_filename_parser import parse_filename  # noqa: E402
from long_clip_segmenter import segment_long_clip, should_segment  # noqa: E402

SAMPLE = ROOT / "Tài Nguyên VCB Real Sample"
SOURCE_DIR = SAMPLE / "3.2 Video input (source)"
CAPCUT_DIR = SAMPLE / "3.7 Project Capcut" / "Nhan_Than_Hor" / "materials" / "video"
MEDIA = MVP / "media"
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
VIDEO_EXT = {".mp4", ".mov"}

# folder prefix -> (folder_code, role_hint, rights)
FOLDER_RULES = [
    ("V1.", "V1", "hook_visual", "owned"), ("V2.", "V2", "craft", "owned"),
    ("V3.", "V3", "huyk", "owned"), ("V4.", "V4", "craft_pov", "owned"),
    ("V6.", "V6", "product_final", "owned"), ("V7.", "V7", "outro", "owned"),
    ("V8.", "V8", "craft", "owned"),
]


def folder_info(path: Path):
    rel = unicodedata.normalize("NFC", path.relative_to(SAMPLE).as_posix())  # macOS may return NFD names
    if path.is_relative_to(CAPCUT_DIR):
        return "CAPCUT", "craft", "owned"
    if "V5." in rel:
        return ("V5-SUUTAM", "stock_action", "collected") if "Sưu tầm" in rel else ("V5-TUQUAY", "craft", "owned")
    for prefix, code, role, rights in FOLDER_RULES:
        if f"/{prefix}" in f"/{rel.split('/', 1)[1]}":
            return code, role, rights
    return "OTHER", "unknown", "unknown"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def probe(path: Path) -> dict:
    res = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    data = json.loads(res.stdout or "{}")
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        rot = int(sd.get("rotation", 0) or 0)
    num, den = (v.get("r_frame_rate") or "30/1").split("/")
    return {"duration": round(float(data.get("format", {}).get("duration", 0)), 2),
            "width": v.get("width"), "height": v.get("height"), "rotation": rot,
            "fps": round(float(num) / float(den or 1), 3),
            "hdr": v.get("color_transfer") in ("arib-std-b67", "smpte2084"),
            "has_audio": has_audio, "codec": v.get("codec_name")}


def build_proxy(src: Path, dst: Path, hdr: bool):
    if dst.exists():
        return
    tonemap = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
               "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,") if hdr else ""
    vf = f"{tonemap}scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,format=yuv420p"
    res = run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(dst)])
    if res.returncode != 0:
        raise RuntimeError(f"proxy failed {src.name}: {res.stderr[-400:]}")


def build_stills(proxy: Path, thumb: Path, sheet: Path, duration: float):
    if not thumb.exists():
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{duration * 0.4:.2f}", "-i", str(proxy), "-frames:v", "1",
             "-vf", "scale=360:640", "-q:v", "3", str(thumb)])
    if not sheet.exists():
        rate = 12.0 / max(duration, 0.5)
        draw = (f"drawtext=fontfile='{FONT}':text='%{{pts\\:hms}}':x=6:y=6:fontsize=20:"
                "fontcolor=white:box=1:boxcolor=black@0.6")
        vf = f"fps={rate:.4f},scale=240:426,{draw},tile=4x3"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(proxy), "-vf", vf, "-frames:v", "1", "-q:v", "3", str(sheet)])


def _rel(path) -> str:
    return Path(path).relative_to(MVP).as_posix()


def long_clip_entries(path: Path, base: dict) -> list[dict]:
    """Long take (> LONG_CLIP_S, not talking head): one entry per kept candidate window (docs 03 §3.1)."""
    res = segment_long_clip(path, base["id"], base["tech"], MEDIA)
    print(f"  long clip {path.name}: {res['duration_s']}s -> {len(res['segments'])} segments, "
          f"{res['ai_calls']} AI calls, {res['timings_s']}")
    return [{**base, "id": s["id"], "parent_id": base["id"], "source_range": [s["in"], s["out"]], "split": s["split"],
             "crop_x": s["crop_x"], "quality_score": s["quality"], "best_moment_s": s["best_rel"],
             "tech": {**base["tech"], "duration": s["duration"], "width": 720, "height": 1280, "rotation": 0, "hdr": False},
             "proxy": _rel(s["proxy"]), "thumb": _rel(s["thumb"]), "sheet": _rel(s["sheet"])} for s in res["segments"]]


def index_clip(path: Path) -> list[dict]:
    rel = path.relative_to(ROOT).as_posix()
    cid = "c_" + hashlib.sha1(rel.encode()).hexdigest()[:8]
    code, role_hint, rights = folder_info(path)
    tech = probe(path)
    parsed = parse_filename(path.name)
    base = {"id": cid, "file": rel, "name": path.name, "folder": code, "role_hint": role_hint,
            "rights": rights, "product_set": parsed["sku"], "parsed": parsed, "tech": tech}
    split, why = should_segment(tech["duration"], parsed)
    if split:
        return long_clip_entries(path, base)
    proxy, thumb, sheet = (MEDIA / "proxy" / f"{cid}.mp4", MEDIA / "thumbs" / f"{cid}.jpg", MEDIA / "sheets" / f"{cid}.jpg")
    build_proxy(path, proxy, tech["hdr"])
    build_stills(proxy, thumb, sheet, tech["duration"])
    entry = {**base, "proxy": _rel(proxy), "thumb": _rel(thumb), "sheet": _rel(sheet)}
    if why == "talking_head_needs_asr":
        entry["needs_sentence_split"] = True       # production: cut by ASR sentence boundaries, not by motion
    return [entry]


def main():
    for sub in ("proxy", "thumbs", "sheets"):
        (MEDIA / sub).mkdir(parents=True, exist_ok=True)
    files = sorted(p for d in (SOURCE_DIR, CAPCUT_DIR) for p in d.rglob("*") if p.suffix.lower() in VIDEO_EXT)
    print(f"indexing {len(files)} clips ...")
    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = [e for group in pool.map(index_clip, files) for e in group]
    out = MVP / "data" / "media-index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out} ({len(entries)} entries)")


if __name__ == "__main__":
    main()
