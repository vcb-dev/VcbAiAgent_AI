"""Build the MVP media index from the VCB real sample library.

For every source clip: ffprobe -> proxy 720x1280 SDR 30fps (tone-maps HLG, auto-rotates)
-> thumbnail -> 12-frame contact sheet (for AI tagging) -> filename parse -> folder role hints.
Takes longer than 30 s (e.g. raw 2-3 min 4K) go through long_clip_segmenter: one entry per kept window.
Output: mvp/data/media-index.json. Idempotent: existing proxies/sheets are reused.

Run:  python3.11 mvp/indexer/build_media_index.py
"""
from __future__ import annotations  # cho phép cú pháp 'X | None' trên Python 3.9

import argparse
import hashlib
import json
import os
import subprocess
import sys
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Vai trò suy ra từ đường dẫn: ổ NAS đã tự chia theo loại nội dung, nên chỉ cần khớp
# một đoạn đường dẫn là biết clip là chế tác, HuyK hay cảnh sản phẩm.
# Khớp theo thứ tự, cái nào trúng trước thì lấy. (đoạn đường dẫn, mã, role_hint, bản quyền)
PATH_RULES = [
    ("HUYK0/VIDEO-CHE-TAC", "CHETAC", "craft", "owned"),
    ("SOURCE 4K/Chế tác", "CHETAC", "craft", "owned"),
    ("SOURCE 4K/Stock anh HuyK", "HUYK", "huyk", "owned"),
    ("SOURCE 4K/Beauty Shot", "BEAUTY", "product_hero", "owned"),
    ("SOURCE 4K/Stock Video SP", "STOCKSP", "product_hero", "owned"),
    ("SOURCE 4K/Stock video sản phẩm", "STOCKSP", "product_hero", "owned"),
    ("SOURCE 4K/Kịch bản", "KICHBAN", "content_illustration", "owned"),
    ("SOURCE 4K/Đi triển lãm", "TRIENLAM", "stock_action", "owned"),
    ("SOURCE 4K/Youtube Global", "YTGLOBAL", "content_illustration", "collected"),
    ("Source AI Minh Data", "MINHDATA", "content_illustration", "collected"),
    # Bộ sample cũ: thư mục đánh số V1..V8.
    ("/V1.", "V1", "hook_visual", "owned"), ("/V2.", "V2", "craft", "owned"),
    ("/V3.", "V3", "huyk", "owned"), ("/V4.", "V4", "craft_pov", "owned"),
    ("/V6.", "V6", "product_final", "owned"), ("/V7.", "V7", "outro", "owned"),
    ("/V8.", "V8", "craft", "owned"),
]


FORCED_ROLE = None      # đặt bởi --role khi footage nằm ngoài cây thư mục chuẩn của NAS


def folder_info(path: Path):
    if FORCED_ROLE:
        return FORCED_ROLE
    rel = unicodedata.normalize("NFC", path.as_posix())  # macOS trả tên dạng NFD
    if path.is_relative_to(CAPCUT_DIR):
        return "CAPCUT", "craft", "owned"
    if "/V5." in rel:
        return ("V5-SUUTAM", "stock_action", "collected") if "Sưu tầm" in rel else ("V5-TUQUAY", "craft", "owned")
    for needle, code, role, rights in PATH_RULES:
        if unicodedata.normalize("NFC", needle) in rel:
            return code, role, rights
    return "OTHER", "unknown", "unknown"


INHERITED = ("sku", "product", "date", "action", "craft_step", "craft_order", "type", "koc")


def parse_with_path(path: Path, scan_root: Path) -> dict:
    """Trên NAS, thông tin hay nằm ở tên thư mục cha chứ không phải tên file:
    'Stock Video SP/D000856_Dây chuyền liên hoa S990/v1.mp4' hay
    'Chế tác/260616_CHETAC_Lắc tay tennis/clip1.mp4'. Nên khi tên file thiếu gì thì
    lấy bù từ thư mục cha gần nhất, dò ngược lên tới thư mục quét."""
    parsed = parse_filename(path.name)
    if parsed["sku"] and parsed["date"]:
        return parsed

    # Tên file do máy quay đặt ('C0001', 'clip1') thì không mang thông tin gì đáng giữ.
    weak_name = parsed["camera_name"] or not (parsed["date"] or parsed["sku"])

    # Chủ đề = tên thư mục chứa file, dùng làm từ khoá khi khớp cảnh ('Gold', 'Thach anh toc vang').
    parsed["topic"] = unicodedata.normalize("NFC", path.parent.name)

    for folder in path.parents:
        if not folder.is_relative_to(scan_root) or folder == scan_root:
            break
        from_folder = parse_filename(unicodedata.normalize("NFC", folder.name))
        # Chỉ thư mục buổi quay (có ngày hoặc SKU ở tên) mới đáng kế thừa. Thư mục phân loại
        # chung như 'SOURCE 4K' hay 'Chế tác' không mang thông tin sản phẩm.
        if not (from_folder["sku"] or from_folder["date"]):
            continue
        for key in INHERITED:
            if from_folder.get(key) and (parsed.get(key) is None or (weak_name and key in ("product", "action"))):
                parsed[key] = from_folder[key]
        parsed["from_folder"] = folder.name
        break

    expected = ("date", "sku", "action", "staff")
    parsed["parse_confidence"] = round(sum(1 for k in expected if parsed[k]) / len(expected), 2)
    return parsed


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _has_drawtext() -> bool:
    """ffmpeg build thiếu libfreetype sẽ không có drawtext; lúc đó contact sheet vẫn dựng
    được nhưng không có mốc thời gian trên từng khung."""
    return " drawtext " in run(["ffmpeg", "-hide_banner", "-filters"]).stdout


HAS_DRAWTEXT = _has_drawtext()


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


def encode_atomic(cmd_without_output, dst: Path, label: str):
    """Dựng ra file tạm rồi mới đổi tên: ffmpeg bị giết giữa chừng sẽ không để lại file
    dở dang mà lần chạy sau tưởng là đã xong."""
    tmp = dst.with_name(f"{dst.stem}.{uuid.uuid4().hex[:6]}.tmp{dst.suffix}")
    try:
        res = run([*cmd_without_output, str(tmp)])
        if res.returncode != 0:
            raise RuntimeError(f"{label}: {res.stderr[-400:]}")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def build_proxy(src: Path, dst: Path, hdr: bool):
    if dst.exists():
        return
    tonemap = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
               "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,") if hdr else ""
    vf = f"{tonemap}scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,format=yuv420p"
    encode_atomic(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart"],
                  dst, f"proxy failed {src.name}")


def build_stills(proxy: Path, thumb: Path, sheet: Path, duration: float):
    if not thumb.exists():
        encode_atomic(["ffmpeg", "-y", "-v", "error", "-ss", f"{duration * 0.4:.2f}", "-i", str(proxy),
                       "-frames:v", "1", "-vf", "scale=360:640", "-q:v", "3"],
                      thumb, f"thumbnail failed {proxy.name}")
    if not sheet.exists():
        rate = 12.0 / max(duration, 0.5)
        draw = (f"drawtext=fontfile='{FONT}':text='%{{pts\\:hms}}':x=6:y=6:fontsize=20:"
                "fontcolor=white:box=1:boxcolor=black@0.6,") if HAS_DRAWTEXT else ""
        vf = f"fps={rate:.4f},scale=240:426,{draw}tile=4x3"
        encode_atomic(["ffmpeg", "-y", "-v", "error", "-i", str(proxy), "-vf", vf, "-frames:v", "1", "-q:v", "3"],
                      sheet, f"contact sheet failed {proxy.name}")


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


def index_clip(args) -> list[dict]:
    path, scan_root = args
    # Footage có thể nằm ngoài repo (ổ NAS), lúc đó giữ nguyên đường dẫn tuyệt đối.
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    cid = "c_" + hashlib.sha1(rel.encode()).hexdigest()[:8]
    code, role_hint, rights = folder_info(path)
    tech = probe(path)
    parsed = parse_with_path(path, scan_root)
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
    ap = argparse.ArgumentParser(description="Đánh chỉ mục footage: ffprobe + proxy + thumbnail + contact sheet.")
    ap.add_argument("roots", nargs="*", help="thư mục footage (mặc định: bộ sample trong repo)")
    ap.add_argument("--out", default="media-index.json", help="tên file kết quả trong VCB_AI/data/")
    ap.add_argument("--limit", type=int, help="chỉ xử lý N clip đầu, để chạy thử")
    # Khi footage được copy ra khỏi NAS, đường dẫn không còn khớp PATH_RULES nữa.
    ap.add_argument("--role", help="ép role_hint (craft, huyk, product_hero, content_illustration...)")
    ap.add_argument("--code", help="ép mã thư mục đi kèm --role (CHETAC, HUYK, STOCKSP...)")
    # Clip 4K dài ngốn nhiều RAM lẫn băng thông; chạy 4 luồng song song dễ bị hệ điều hành giết.
    ap.add_argument("--workers", type=int, default=2, help="số clip xử lý song song (mặc định 2)")
    ap.add_argument("--restart", action="store_true", help="bỏ kết quả cũ, đánh chỉ mục lại từ đầu")
    opts = ap.parse_args()

    if opts.role:
        global FORCED_ROLE
        FORCED_ROLE = (opts.code or opts.role.upper(), opts.role, "owned")

    out = MVP / "data" / opts.out
    limit = opts.limit
    roots = [Path(a).expanduser().resolve() for a in opts.roots] or [SOURCE_DIR, CAPCUT_DIR]

    missing = [r for r in roots if not r.is_dir()]
    if missing:
        sys.exit("Không thấy thư mục: " + ", ".join(str(m) for m in missing))

    for sub in ("proxy", "thumbs", "sheets"):
        (MEDIA / sub).mkdir(parents=True, exist_ok=True)

    # Giữ kèm scan_root của từng file để parse_with_path biết dừng ở đâu khi dò SKU ngược lên.
    jobs = sorted(((p, root) for root in roots for p in root.rglob("*") if p.suffix.lower() in VIDEO_EXT),
                  key=lambda j: j[0].as_posix())
    if limit:
        jobs = jobs[:limit]

    # Quét qua ổ mạng mất nhiều giờ và có thể đứt giữa chừng, nên giữ lại kết quả cũ
    # và bỏ qua những clip đã xong để chạy tiếp được.
    entries = [] if opts.restart or not out.exists() else json.loads(out.read_text(encoding="utf-8"))
    done = {e["file"] for e in entries}
    todo = [j for j in jobs if (j[0].as_posix() not in done
                                and (j[0].relative_to(ROOT).as_posix() if j[0].is_relative_to(ROOT) else j[0].as_posix()) not in done)]
    print(f"indexing {len(todo)} clips from {len(roots)} root(s)"
          f"{f' (bỏ qua {len(jobs) - len(todo)} clip đã xong)' if len(todo) < len(jobs) else ''} ...", flush=True)

    out.parent.mkdir(parents=True, exist_ok=True)

    def save():
        tmp = out.with_suffix(".json.tmp")      # ghi ra file tạm rồi đổi tên, tránh hỏng file khi bị ngắt
        tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(out)

    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, opts.workers)) as pool:
        futures = {pool.submit(index_clip, j): j[0] for j in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            src = futures[fut]
            try:
                entries.extend(fut.result())
            except Exception as exc:            # một clip hỏng không được làm dừng cả mẻ
                failed += 1
                print(f"  [{i}/{len(todo)}] LỖI {src.name}: {exc}", flush=True)
                continue
            save()                              # chốt sau từng clip: đứt giữa chừng vẫn giữ được phần đã làm
            print(f"  [{i}/{len(todo)}] {src.name} -> {len(entries)} entries", flush=True)

    save()
    print(f"wrote {out} ({len(entries)} entries, {failed} lỗi)")
    by_role = {}
    for e in entries:
        by_role[e["role_hint"]] = by_role.get(e["role_hint"], 0) + 1
    print("  theo vai trò:", ", ".join(f"{k}={v}" for k, v in sorted(by_role.items())))


if __name__ == "__main__":
    main()
