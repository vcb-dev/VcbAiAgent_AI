"""Single-pass decode + per-frame signals for the long-clip branch (docs 03 §3.1).

The original (often 4K HEVC) is decoded exactly once (hardware decode when available). One ffmpeg process writes:
  - a master proxy (long side 1280, original aspect, SDR, 30 fps) for review and for cutting segment proxies
  - 4 fps 256x256 gray frames on stdout for analysis (aspect is squashed on purpose: signals are relative)
Everything after that runs on the small frames with numpy only, so it costs CPU seconds, never AI money.
"""
from __future__ import annotations  # cho phép cú pháp 'X | None' trên Python 3.9

import subprocess
from pathlib import Path

import numpy as np

ANALYSIS_FPS = 4
GRID = 256
MARGIN = 16                       # ignore borders when diffing (camera shift wraps pixels around)
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
_HANN = np.outer(np.hanning(GRID), np.hanning(GRID)).astype(np.float32)


def single_pass_decode(src: Path, master: Path, hdr: bool) -> np.ndarray:
    """Decode once -> master proxy file + gray analysis frames [N, GRID, GRID] uint8."""
    fit = "scale='if(gt(iw,ih),1280,-2)':'if(gt(iw,ih),-2,1280)'"
    graph = (f"[0:v]{TONEMAP if hdr else ''}split=2[p][a];"
             f"[p]{fit},fps=30,format=yuv420p[pv];"
             f"[a]fps={ANALYSIS_FPS},scale={GRID}:{GRID},format=gray[av]")
    cmd = ["ffmpeg", "-y", "-v", "error", "-hwaccel", "auto", "-i", str(src), "-filter_complex", graph,
           "-map", "[pv]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(master),
           "-map", "[av]", "-f", "rawvideo", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"decode failed {src.name}: {proc.stderr.decode(errors='ignore')[-400:]}")
    return np.frombuffer(proc.stdout, dtype=np.uint8).reshape(-1, GRID, GRID)


def _camera_shift(prev: np.ndarray, cur: np.ndarray):
    """Global translation (dy, dx) between two frames by phase correlation = camera movement."""
    r = np.fft.fft2(prev * _HANN) * np.conj(np.fft.fft2(cur * _HANN))
    corr = np.fft.ifft2(r / (np.abs(r) + 1e-6)).real
    dy, dx = np.unravel_index(int(np.argmax(corr)), corr.shape)
    return (dy - GRID if dy > GRID // 2 else dy), (dx - GRID if dx > GRID // 2 else dx)


def frame_signals(frames: np.ndarray) -> dict:
    """Per-frame arrays: sharpness, brightness, clipping, camera speed, subject motion, frame correlation, motion columns."""
    f = frames.astype(np.float32)
    n = len(f)
    sharp = np.array([(4 * x[1:-1, 1:-1] - x[:-2, 1:-1] - x[2:, 1:-1] - x[1:-1, :-2] - x[1:-1, 2:]).var()
                      for x in f])                                               # Laplacian variance per frame
    small = f.reshape(n, 32, GRID // 32, 32, GRID // 32).mean(axis=(2, 4)).reshape(n, -1)
    spread = small.std(axis=1)
    z = (small - small.mean(axis=1, keepdims=True)) / (spread[:, None] + 1e-3)
    corr = np.r_[1.0, (z[1:] * z[:-1]).mean(axis=1)]                             # ~1 same scene, <0.3 new scene
    cam, resid = np.zeros(n, np.float32), np.zeros(n, np.float32)
    cols = np.zeros((n, GRID - 2 * MARGIN), np.float32)
    m = slice(MARGIN, GRID - MARGIN)
    for t in range(1, n):
        dy, dx = _camera_shift(f[t - 1], f[t])
        raw = np.abs(f[t] - f[t - 1])[m, m]
        diff = np.abs(f[t] - np.roll(f[t - 1], (-dy, -dx), axis=(0, 1)))[m, m]   # motion left after camera compensation
        # it is camera motion only if the global shift explains most of the change (a spinning polishing wheel does not)
        cam[t] = np.hypot(dy, dx) if diff.mean() < 0.85 * raw.mean() else 0.0
        resid[t], cols[t] = diff.mean(), diff.mean(axis=0)
    if n > 1:
        cam[0], resid[0], cols[0] = cam[1], resid[1], cols[1]
    p90 = np.percentile(frames.reshape(n, -1), 90, axis=1)                      # brightest parts: jewel on black velvet is fine
    return {"sharp": sharp, "bright": f.mean(axis=(1, 2)), "p90": p90, "spread": spread,
            "hi": (frames > 245).mean(axis=(1, 2)), "lo": (frames < 12).mean(axis=(1, 2)),
            "cam": cam, "resid": resid, "corr": corr, "cols": cols}


def hard_cuts(sig: dict, corr_t: float = 0.3, flat: float = 4.0) -> list[int]:
    """Frame indices where a new shot starts: the 32x32 layout of consecutive frames stops correlating.
    Flat frames (black, lens covered) have no layout, so they never trigger a cut by themselves."""
    corr, spread = sig["corr"], sig["spread"]
    cuts = [t for t in range(1, len(corr)) if corr[t] < corr_t and spread[t] > flat and spread[t - 1] > flat]
    keep = []
    for c in cuts:                       # one cut per transition (a flash can trigger 2-3 frames in a row)
        if not keep or c - keep[-1] > 2:
            keep.append(int(c))
    return keep
