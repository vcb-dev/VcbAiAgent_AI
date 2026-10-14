"""Central filesystem locations and external tool settings for the AI service.

MVP = the VCB_AI service root; ROOT = the repo root (holds the raw NAS sample folder).
"""
import json
import os
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

FONT_FILE = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_DIR = "/System/Library/Fonts/Supplemental"
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
PLANNER_MODEL = os.environ.get("VCB_PLANNER_MODEL", "claude-opus-5-5")
MACOS_VOICE = os.environ.get("VCB_MACOS_VOICE", "Linh")
MACOS_RATE = int(os.environ.get("VCB_MACOS_RATE", "200"))

for _d in (JOBS_DIR, TTS_DIR, SHOT_CACHE, RENDERS, MUSIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)
