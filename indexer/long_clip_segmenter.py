"""Long-clip branch of the Media Hub index (docs 03 §3.1): raw 2-3 min (4K) takes -> short, scored candidates.

Cost = CPU seconds + about one cheap AI call per 6 kept candidates:
  1. single_pass_decode: the original is decoded once (master proxy + 4 fps analysis frames)
  2. frame_signals + hard_cuts -> shots; inside a continuous take, soft cuts at micro-pauses of the action
  3. dead frames (blurry, dark, blown-out, fast pan, frozen) are dropped -> windows of 1.5-8 s with a best moment
  4. score, dedupe repeated actions (hash of the action area), keep ~1 candidate per 10 s of source
  5. cut 9:16 segment proxies for kept windows only + batch contact sheets (12 tiles: 6 candidates x 2 frames)
Talking-head takes are not split by motion: they need sentence boundaries from ASR (see should_segment).

Run on any file:  uv run --project mvp python mvp/indexer/long_clip_segmenter.py <video> [--out DIR]
"""
from __future__ import annotations  # cho phép cú pháp 'X | None' trên Python 3.9

import argparse
import hashlib
import json
import math
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from long_clip_signals import ANALYSIS_FPS, frame_signals, hard_cuts, single_pass_decode

LONG_CLIP_S = 30.0                      # NAS standard is <= 15 s; longer takes go through this branch
MIN_WIN_S, TARGET_MIN_S, MAX_WIN_S = 1.5, 4.0, 8.0
SECONDS_PER_CANDIDATE = 10.0            # budget: ~1 kept candidate per 10 s of source
QUALITY_FLOOR = 0.3
DUP_BITS, MAX_PER_LOOK = 50, 2          # 256-bit look hash: <= 50 differing bits = same look; keep 2 of each
FRAMES_PER_CANDIDATE = 2                # 2 -> 6 candidates per 4x3 sheet; 4 -> 3 per sheet (multi-step takes, 2x cost)
TALKING_TYPES = {"KB"}                  # NAS type code for HuyK talking to camera
HAIKU_USD_PER_M = (0.10, 0.50)          # in/out per 1M tokens (mvp/data/ai-models-pricing.json, 10/10/2026)
SHEET_TOKENS = (3000, 1200)             # one batch call: 12 small images + prompt in, 6 label objects out
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
# ffmpeg thiếu libfreetype thì không có drawtext: vẫn dựng sheet, chỉ mất nhãn thời gian.
HAS_DRAWTEXT = " drawtext " in subprocess.run(
    ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=False).stdout


def should_segment(duration: float, parsed: dict | None) -> tuple[bool, str]:
    if duration <= LONG_CLIP_S:
        return False, "short"
    if (parsed or {}).get("type") in TALKING_TYPES:
        return False, "talking_head_needs_asr"
    return True, "long"


def _band(ratio):
    """Motion score: 1 inside the 'hands working' band (0.6-2x the clip's typical motion), 0 when idle or chaotic."""
    r = np.asarray(ratio, dtype=np.float32)
    return np.clip(np.minimum((r - 0.15) / 0.45, (4.0 - r) / 2.0), 0.0, 1.0)


def frame_flags(sig: dict) -> np.ndarray:
    """Reason a frame is unusable ('' = usable). Earlier rules win."""
    lit = (sig["p90"] >= 50) & (sig["lo"] < 0.85)        # dark = even the brightest 10% is dim (lens covered, lights off)
    base = float(np.median(sig["sharp"][lit] if lit.any() else sig["sharp"]))
    rules = [("dark", ~lit), ("blown_out", sig["hi"] > 0.30), ("blurry", sig["sharp"] < max(8.0, 0.35 * base)),
             ("fast_pan", sig["cam"] > 12), ("frozen", (sig["resid"] < 0.6) & (sig["cam"] < 0.5))]
    reason = np.full(len(lit), "", dtype=object)
    for name, mask in reversed(rules):
        reason[mask] = name
    return reason


def _split_run(a: int, b: int, motion: np.ndarray) -> list[tuple[int, int]]:
    """Split a usable run [a, b) into 4-8 s windows, cutting where the action pauses (lowest motion)."""
    fps, lo_f, max_f, min_f = ANALYSIS_FPS, int(TARGET_MIN_S * ANALYSIS_FPS), int(MAX_WIN_S * ANALYSIS_FPS), int(MIN_WIN_S * ANALYSIS_FPS)
    out, s = [], a
    while b - s > max_f:
        lo, hi = s + lo_f, min(s + max_f, b - min_f)
        cut = (lo + int(np.argmin(motion[lo:hi + 1]))) if hi > lo else s + max_f
        out.append((s, cut))
        s = cut
    if b - s >= min_f:
        out.append((s, b))
    elif out and b - out[-1][0] <= (MAX_WIN_S + 2) * fps:
        out[-1] = (out[-1][0], b)                     # short tail joins the previous window
    return out


def _look_hash(window_frames: np.ndarray, crop_x: float, landscape: bool) -> np.ndarray:
    """256-bit difference hash of the window's MEAN image over the area that will be on screen:
    central 60% for portrait, the 9:16 crop column for landscape. Averaging over the window makes two takes
    of the same action match even when the hands are at different points."""
    g = window_frames.shape[-1]
    if landscape:
        half = int(g * (9 / 16) / (16 / 9) / 2)
        cx = int(crop_x * g)
        cols = slice(max(0, cx - half), min(g, cx + half))
    else:
        cols = slice(int(g * 0.2), int(g * 0.8))
    c = window_frames[:, int(g * 0.2):int(g * 0.8), cols].astype(np.float32).mean(axis=0)
    img = np.array([[blk.mean() for blk in np.array_split(row, 17, axis=1)] for row in np.array_split(c, 16, axis=0)])
    return (img[:, 1:] > img[:, :-1]).ravel()


def _crop_center(cols: np.ndarray, landscape: bool) -> float:
    """Horizontal centre (0..1) of the action for a 9:16 crop of a landscape source; 0.5 when portrait or static."""
    if not landscape or cols.sum() < 1e-3:
        return 0.5
    energy = cols.sum(axis=0)
    x = float((energy * np.arange(len(energy))).sum() / energy.sum() / len(energy))
    half = (9 / 16) / (16 / 9) / 2                     # crop width / frame width / 2 for a 16:9 source
    return round(min(max(x, half), 1 - half), 3)


def build_windows(sig: dict, frames: np.ndarray, landscape: bool) -> tuple[list[dict], np.ndarray, list[int]]:
    reason = frame_flags(sig)
    good = reason == ""
    good[1:-1] |= (~good[1:-1]) & good[:-2] & good[2:]   # a single bad frame inside an action is noise
    cuts = hard_cuts(sig)
    motion = np.convolve(sig["resid"], np.ones(3) / 3, mode="same")
    ok_sharp = np.sort(sig["sharp"][good]) if good.any() else np.sort(sig["sharp"])
    sharp_rank = np.searchsorted(ok_sharp, sig["sharp"]) / max(len(ok_sharp), 1)
    motion_c = max(float(np.median(sig["resid"][good])) if good.any() else 1.0, 1.0)
    frame_score = sharp_rank * (0.5 + 0.5 * _band(sig["resid"] / motion_c))
    windows, bounds = [], [0, *cuts, len(good)]
    for shot, (s0, s1) in enumerate(zip(bounds[:-1], bounds[1:])):
        idx = np.flatnonzero(good[s0:s1]) + s0
        runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1) if len(idx) else []
        for run in runs:
            for a, b in _split_run(int(run[0]), int(run[-1]) + 1, motion):
                inner = slice(a + 2, b - 2) if b - a > 6 else slice(a, b)
                best = inner.start + int(np.argmax(frame_score[inner]))
                q = (0.35 * float(sharp_rank[a:b].mean()) + 0.2 * (1 - min(1.0, abs(float(sig["p90"][a:b].mean()) - 180) / 120))
                     + 0.3 * float(_band(np.median(sig["resid"][a:b]) / motion_c)) + 0.15 * (1 - min(1.0, float(np.std(sig["cam"][a:b])) / 6)))
                crop_x = _crop_center(sig["cols"][a:b], landscape)
                windows.append({"shot": shot, "a": a, "b": b, "best": best, "quality": round(q, 3),
                                "split": "hard_cut" if (a == s0 and shot > 0) else "soft",
                                "crop_x": crop_x, "hash": _look_hash(frames[a:b], crop_x, landscape)})
    return windows, reason, cuts


def select(windows: list[dict], duration: float) -> list[dict]:
    """Quality floor -> dedupe repeated looks -> best window of every shot -> fill up to the budget by quality."""
    looks = []
    for w in sorted(windows, key=lambda w: -w["quality"]):
        if w["quality"] < QUALITY_FLOOR:
            w["status"] = "low_quality"
            continue
        match = next((lk for lk in looks if np.count_nonzero(lk["hash"] != w["hash"]) <= DUP_BITS), None)
        if match and match["n"] >= MAX_PER_LOOK:
            w["status"] = "duplicate"
            continue
        if match:
            match["n"] += 1
        else:
            looks.append({"hash": w["hash"], "n": 1})
        w["status"] = "candidate"
    cands = sorted((w for w in windows if w["status"] == "candidate"), key=lambda w: -w["quality"])
    picked = {id(next(w for w in cands if w["shot"] == s)) for s in {w["shot"] for w in cands}}
    budget = max(3, math.ceil(duration / SECONDS_PER_CANDIDATE), len(picked))
    for w in cands:
        if len(picked) >= budget:
            break
        picked.add(id(w))
    for w in cands:
        w["status"] = "kept" if id(w) in picked else "over_budget"
    return sorted((w for w in windows if w["status"] == "kept"), key=lambda w: w["a"])


def _ff(args):
    res = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-400:])


def _write_outputs(kept, master: Path, asset_id: str, out: Path, frames_per_cand: int) -> tuple[list[dict], list[str]]:
    """9:16 segment proxies + thumbnails for kept windows only, then batch contact sheets for the AI tagger."""
    for sub in ("proxy", "thumbs", "sheets"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    segs = []
    for n, w in enumerate(kept, 1):
        sid, a, b = f"{asset_id}_s{n:02d}", w["a"] / ANALYSIS_FPS, w["b"] / ANALYSIS_FPS
        crop = (f"crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)':x='max(0,min(iw-ow,{w['crop_x']}*iw-ow/2))':y='(ih-oh)/2',"
                "scale=720:1280,setsar=1")
        proxy, thumb = out / "proxy" / f"{sid}.mp4", out / "thumbs" / f"{sid}.jpg"
        _ff(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(master), "-vf", crop, "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(proxy)])
        best_rel = round(w["best"] / ANALYSIS_FPS - a, 2)
        _ff(["-ss", f"{best_rel:.2f}", "-i", str(proxy), "-frames:v", "1", "-vf", "scale=360:640", "-q:v", "3", str(thumb)])
        segs.append({"id": sid, "in": round(a, 2), "out": round(b, 2), "duration": round(b - a, 2), "best_rel": best_rel,
                     "best_abs": round(w["best"] / ANALYSIS_FPS, 2), "quality": w["quality"], "split": w["split"],
                     "crop_x": w["crop_x"], "proxy": proxy, "thumb": thumb})
    sheets, per_sheet = [], 12 // frames_per_cand
    for k in range(0, len(segs), per_sheet):
        group, sheet = segs[k:k + per_sheet], out / "sheets" / f"{asset_id}_batch{k // per_sheet + 1}.jpg"
        with tempfile.TemporaryDirectory() as tmp:
            tile = 0
            for s in group:                         # frames spread over the window, the nearest one snapped to the best moment
                times = list(np.linspace(0.1, 0.9, frames_per_cand) * s["duration"])
                times[int(np.argmin([abs(t - s["best_rel"]) for t in times]))] = s["best_rel"]
                for t in sorted(times):
                    label = Path(tmp) / f"l{tile}.txt"
                    label.write_text(f"{s['id'].rsplit('_', 1)[1].upper()} · {int((s['in'] + t) // 60):02d}:{(s['in'] + t) % 60:04.1f}")
                    draw = (f",drawtext=fontfile='{FONT}':textfile='{label}':expansion=none:x=6:y=6:fontsize=20:"
                            "fontcolor=white:box=1:boxcolor=black@0.65") if HAS_DRAWTEXT else ""
                    _ff(["-ss", f"{t:.2f}", "-i", str(s["proxy"]), "-frames:v", "1", "-vf",
                         f"scale=240:426{draw}", str(Path(tmp) / f"f_{tile:02d}.jpg")])
                    tile += 1
            _ff(["-framerate", "1", "-i", str(Path(tmp) / "f_%02d.jpg"), "-vf", "tile=4x3", "-frames:v", "1", "-q:v", "3", str(sheet)])
        for s in group:
            s["sheet"] = sheet
        sheets.append(str(sheet))
    return segs, sheets


def segment_long_clip(src: Path, asset_id: str, tech: dict, out: Path, frames_per_cand: int = FRAMES_PER_CANDIDATE) -> dict:
    t0 = time.time()
    (out / "proxy").mkdir(parents=True, exist_ok=True)
    master = out / "proxy" / f"{asset_id}_master.mp4"
    frames = single_pass_decode(src, master, tech.get("hdr", False))
    t1 = time.time()
    sig = frame_signals(frames)
    w, h = tech.get("width") or 1080, tech.get("height") or 1920
    landscape = (w > h) != (abs(tech.get("rotation") or 0) in (90, 270))
    windows, reason, cuts = build_windows(sig, frames, landscape)
    duration = len(frames) / ANALYSIS_FPS
    kept = select(windows, duration)
    t2 = time.time()
    segs, sheets = _write_outputs(kept, master, asset_id, out, frames_per_cand)
    t3 = time.time()
    cost = len(sheets) * (SHEET_TOKENS[0] * HAIKU_USD_PER_M[0] + SHEET_TOKENS[1] * HAIKU_USD_PER_M[1]) / 1e6
    status = {}
    for win in windows:
        status[win["status"]] = status.get(win["status"], 0) + 1
    return {"asset_id": asset_id, "source": str(src), "duration_s": round(duration, 1), "landscape": landscape,
            "timings_s": {"decode_once": round(t1 - t0, 1), "analyse": round(t2 - t1, 1), "cut_and_sheets": round(t3 - t2, 1)},
            "rejected_s": {k: round(float((reason == k).sum()) / ANALYSIS_FPS, 1) for k in set(reason) - {""}},
            "hard_cuts_s": [round(c / ANALYSIS_FPS, 2) for c in cuts], "windows": status,
            "timeline": [{"in": round(x["a"] / ANALYSIS_FPS, 2), "out": round(x["b"] / ANALYSIS_FPS, 2), "status": x["status"],
                          "quality": x["quality"]} for x in sorted(windows, key=lambda x: x["a"])],
            "segments": segs, "sheets": sheets, "ai_calls": len(sheets), "est_ai_cost_usd": round(cost, 5)}


def main():
    from build_media_index import MEDIA, probe        # lazy: build_media_index imports this module
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, default=MEDIA)
    ap.add_argument("--id", default=None)
    ap.add_argument("--frames", type=int, choices=(2, 3, 4), default=FRAMES_PER_CANDIDATE, help="frames per candidate on the sheet")
    args = ap.parse_args()
    asset_id = args.id or "c_" + hashlib.sha1(str(args.video.resolve()).encode()).hexdigest()[:8]
    res = segment_long_clip(args.video, asset_id, probe(args.video), args.out, args.frames)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
