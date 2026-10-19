"""Background music: bundled bed + mp3/wav in media/music (and data/music cũ)."""
import subprocess
from functools import lru_cache
from pathlib import Path

from app_paths import DEFAULT_MUSIC, LEGACY_MUSIC_DIR, MEDIA, MUSIC_DIR

ALLOWED_EXT = {".mp3", ".wav", ".m4a"}
_UNSAFE = set('<>:"/\\|?*') | {chr(0)}


def _duration(path) -> float:
    res = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=False)
    try:
        return round(float(res.stdout.strip()), 1)
    except ValueError:
        return 0.0


def _dirs() -> list[Path]:
    seen, out = set(), []
    for d in (MUSIC_DIR, LEGACY_MUSIC_DIR):
        key = str(d.resolve()) if d.exists() else str(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _files() -> list[Path]:
    files = []
    for d in _dirs():
        if not d.is_dir():
            continue
        for ext in ("*.mp3", "*.wav", "*.m4a"):
            files.extend(p for p in d.glob(ext) if not p.name.startswith("_"))
    return sorted(files, key=lambda p: p.name.lower())


@lru_cache(maxsize=8)
def _tracks_for(signature: tuple) -> list:
    tracks = [{"id": "default", "name": "Nhạc nền mẫu (mock, không bản quyền thương mại)", "file": str(DEFAULT_MUSIC),
               "duration": _duration(DEFAULT_MUSIC)}]
    for path in _files():
        tracks.append({"id": path.name, "name": path.stem.replace("_", " "), "file": str(path),
                       "duration": _duration(path)})
    return tracks


def list_tracks() -> list:
    _ensure_default_alias()
    sig = tuple((p.name, int(p.stat().st_mtime)) for p in _files())
    return _tracks_for(sig)


def track_ids() -> set:
    return {t["id"] for t in list_tracks()}


def resolve(track_id: str):
    return next((t["file"] for t in list_tracks() if t["id"] == track_id), str(DEFAULT_MUSIC))


def _ensure_default_alias() -> Path:
    """Cho trình duyệt stream bài mặc định qua /media/music (file gốc nằm ở assets)."""
    alias = MUSIC_DIR / "_default.wav"
    if not DEFAULT_MUSIC.exists():
        return alias
    # StaticFiles không theo symlink; copy một bản để /media/music/_default.wav mở được.
    if alias.is_symlink() or not alias.exists():
        if alias.exists() or alias.is_symlink():
            alias.unlink()
        alias.write_bytes(DEFAULT_MUSIC.read_bytes())
    return alias


def _public_url(track: dict) -> str:
    if track["id"] == "default":
        _ensure_default_alias()
        return "media/music/_default.wav"
    path = Path(track["file"]).resolve()
    try:
        return "media/" + path.relative_to(MEDIA.resolve()).as_posix()
    except ValueError:
        return f"media/music/{path.name}"


def public_tracks() -> list:
    return [{k: t[k] for k in ("id", "name", "duration")} | {"url": _public_url(t)} for t in list_tracks()]


def import_track(raw: bytes, filename: str) -> dict:
    """Cất file nhạc lên volume. Job chỉ lưu id; FFmpeg mix từ file này."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("Chỉ nhận mp3, wav hoặc m4a")
    if not raw:
        raise ValueError("File trống")
    stem = "".join(c for c in Path(filename).stem if c not in _UNSAFE).strip(" .")[:100] or "nhac-nen"
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    dest = MUSIC_DIR / f"{stem}{ext}"
    n = 2
    while dest.exists():
        dest = MUSIC_DIR / f"{stem}-{n}{ext}"
        n += 1
    dest.write_bytes(raw)
    _tracks_for.cache_clear()
    track = next((t for t in list_tracks() if t["id"] == dest.name), None)
    if not track:
        raise RuntimeError("Không đọc được bài vừa tải lên")
    return {k: track[k] for k in ("id", "name", "duration")}
