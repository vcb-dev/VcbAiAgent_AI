"""Background music choices: the bundled mock bed + any licensed tracks dropped into mvp/data/music/."""
import subprocess
from functools import lru_cache

from app_paths import DEFAULT_MUSIC, MUSIC_DIR


def _duration(path) -> float:
    res = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=False)
    try:
        return round(float(res.stdout.strip()), 1)
    except ValueError:
        return 0.0


@lru_cache(maxsize=1)
def list_tracks() -> list:
    tracks = [{"id": "default", "name": "Nhạc nền mẫu (mock, không bản quyền thương mại)", "file": str(DEFAULT_MUSIC),
               "duration": _duration(DEFAULT_MUSIC)}]
    for path in sorted(p for ext in ("*.mp3", "*.wav", "*.m4a") for p in MUSIC_DIR.glob(ext)):
        tracks.append({"id": path.name, "name": path.stem.replace("_", " "), "file": str(path), "duration": _duration(path)})
    return tracks


def track_ids() -> set:
    return {t["id"] for t in list_tracks()}


def resolve(track_id: str):
    return next((t["file"] for t in list_tracks() if t["id"] == track_id), str(DEFAULT_MUSIC))


def public_tracks() -> list:
    return [{k: t[k] for k in ("id", "name", "duration")} for t in list_tracks()]
