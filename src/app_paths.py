"""Central filesystem locations and external tool settings for the AI service.

MVP = the VCB_AI service root; ROOT = the repo root (holds the raw NAS sample folder).
"""
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]
# Local, gitignored secrets (ElevenLabs key + cloned voice id). Environment variables take precedence.
_SECRETS = json.loads((MVP / "local-secrets.json").read_text(encoding="utf-8")) if (MVP / "local-secrets.json").exists() else {}


def _setting(name: str, default: str = "") -> str:
    return os.environ.get(name) or _SECRETS.get(name, default)


ROOT = MVP.parent
DATA = MVP / "data"
MEDIA = MVP / "media"
ASSETS = MVP / "assets"          # logo, SFX, nhạc nền mặc định dùng khi render
JOBS_DIR = DATA / "jobs"
TTS_DIR = MEDIA / "tts"
SHOT_CACHE = MEDIA / "cache" / "shots"
RENDERS = MEDIA / "renders"

def _first_font(*paths: str) -> str:
    for path in paths:
        if path and Path(path).exists():
            return path
    return next((p for p in paths if p), "")


# macOS local; Linux/Docker dùng Noto hoặc DejaVu (có dấu tiếng Việt).
FONT_FILE = _first_font(
    os.environ.get("VCB_FONT_FILE", ""),
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
FONT_DIR = os.environ.get("VCB_FONT_DIR") or str(Path(FONT_FILE).parent if FONT_FILE else "")
LOGO_FILE = ASSETS / "logo_huyk_vienchibao.png"
SFX_SPARKLE = ASSETS / "sfx_sparkle.wav"
DEFAULT_MUSIC = ASSETS / "bgm_luxury.wav"
MUSIC_DIR = DATA / "music"          # drop VCB licensed tracks here (mp3/wav) to override the default

# Rendering canvas for the demo preview (proxies are 720x1280 @30fps)
CANVAS_W, CANVAS_H, FPS = 720, 1280, 30

# Optional real AI providers (enabled only when credentials exist)
ELEVENLABS_API_KEY = _setting("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = _setting("ELEVENLABS_VOICE_ID")
ELEVENLABS_MODEL = _setting("ELEVENLABS_MODEL", "eleven_v4")
# eleven_v4 has no style slider; delivery comes from audio tags (vo_director). 0.5 = natural, lower = more expressive.
ELEVENLABS_SETTINGS = {"stability": float(_setting("ELEVENLABS_STABILITY", "0.5")), "similarity_boost": 0.85,
                       "use_speaker_boost": True}
# MiniMax: nhân bản giọng từ bản thu editor tải lên rồi cho giọng đó đọc kịch bản.
MINIMAX_API_KEY = _setting("MINIMAX_API_KEY")
MINIMAX_HOST = _setting("MINIMAX_HOST", "https://api.minimax.io")
MINIMAX_MODEL = _setting("MINIMAX_MODEL", "speech-02-hd")
# Giọng HuyK dùng chung, học sẵn từ footage HuyK nói (xem indexer/huyk_voice_setup.py).
MINIMAX_HUYK_VOICE_ID = _setting("MINIMAX_HUYK_VOICE_ID")
PLANNER_MODEL = os.environ.get("VCB_PLANNER_MODEL", "claude-opus-5-5")
MACOS_VOICE = os.environ.get("VCB_MACOS_VOICE", "Linh")
MACOS_RATE = int(os.environ.get("VCB_MACOS_RATE", "200"))

for _d in (JOBS_DIR, TTS_DIR, SHOT_CACHE, RENDERS, MUSIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=None)
def has_ffmpeg_filter(name: str) -> bool:
    """Bộ lọc chữ (drawtext, ass, subtitles) cần ffmpeg dựng kèm libfreetype/libass, mà
    nhiều bản cài sẵn lại thiếu. Hỏi trước còn hơn để ffmpeg gãy giữa lúc render."""
    try:
        res = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                             capture_output=True, text=True, check=False)
    except OSError:
        return False
    return any(line.split()[1:2] == [name] for line in res.stdout.splitlines() if line.startswith(" "))
