"""ElevenLabs setup helper: list TTS models, build a clean HuyK voice sample, create an Instant Voice Clone,
and transcribe audio with Scribe (QC). The API key is read from mvp/local-secrets.json (gitignored), never argv.

Usage (from repo root):
  uv run --project mvp python mvp/indexer/elevenlabs_voice_setup.py models
  uv run --project mvp python mvp/indexer/elevenlabs_voice_setup.py sample <video> [<video> ...]
  uv run --project mvp python mvp/indexer/elevenlabs_voice_setup.py clone "HuyK - Vien Chi Bao (IVC)"
  uv run --project mvp python mvp/indexer/elevenlabs_voice_setup.py transcribe <audio>
"""
import json
import subprocess
import sys
from pathlib import Path

import httpx

MVP = Path(__file__).resolve().parents[1]
SECRETS = MVP / "local-secrets.json"
SAMPLE_DIR = MVP / "media" / "voice-samples"
API = "https://api.elevenlabs.io"


def _secrets() -> dict:
    return json.loads(SECRETS.read_text(encoding="utf-8"))


def _save_secret(key: str, value: str):
    data = _secrets()
    data[key] = value
    SECRETS.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _headers():
    return {"xi-api-key": _secrets()["ELEVENLABS_API_KEY"]}


def list_models():
    res = httpx.get(f"{API}/v1/models", headers=_headers(), timeout=30)
    res.raise_for_status()
    for m in res.json():
        if not m.get("can_do_text_to_speech"):
            continue
        langs = [lang.get("language_id") for lang in m.get("languages", [])]
        print(f"{m['model_id']:<28} vi={'vi' in langs} style={m.get('can_use_style')} "
              f"max_chars={m.get('maximum_text_length_per_request')} | {m.get('name')}")


def build_sample(videos):
    """Extract speech-only, loudness-normalised mono audio (silences trimmed) from talking-head clips."""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    outs = []
    for i, video in enumerate(videos):
        out = SAMPLE_DIR / f"huyk_sample_{i}.mp3"
        af = ("highpass=f=80,lowpass=f=12000,afftdn=nf=-25,"
              "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=1.0:stop_threshold=-50dB,"
              "loudnorm=I=-18:TP=-2:LRA=7,alimiter=limit=0.84")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "44100", "-af", af,
                        "-b:a", "192k", str(out)], check=True)
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                             capture_output=True, text=True, check=True).stdout.strip()
        print(f"{out.name}: {float(dur):.1f}s")
        outs.append(out)
    return outs


def clone(name: str):
    files = sorted(SAMPLE_DIR.glob("huyk_sample_*.mp3"))
    if not files:
        sys.exit("no samples: run 'sample' first")
    multipart = [("files", (f.name, f.read_bytes(), "audio/mpeg")) for f in files]
    data = {"name": name, "remove_background_noise": "true",
            "description": "HuyK (Viễn Chí Bảo) - Vietnamese male, warm storyteller. Consent given by HuyK.",
            "labels": json.dumps({"language": "vi", "accent": "northern Vietnamese", "use_case": "narration"})}
    res = httpx.post(f"{API}/v1/voices/add", headers=_headers(), data=data, files=multipart, timeout=180)
    if res.status_code >= 400:
        sys.exit(f"clone failed {res.status_code}: {res.text[:400]}")
    voice_id = res.json()["voice_id"]
    _save_secret("ELEVENLABS_VOICE_ID", voice_id)
    print(f"voice created: {voice_id} (saved to local-secrets.json)")


def transcribe(audio: str):
    with open(audio, "rb") as fh:
        res = httpx.post(f"{API}/v1/speech-to-text", headers=_headers(), timeout=180,
                         data={"model_id": "scribe_v2", "language_code": "vi"}, files={"file": (Path(audio).name, fh)})
    if res.status_code >= 400:
        sys.exit(f"transcribe failed {res.status_code}: {res.text[:300]}")
    print(res.json().get("text", ""))


if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else "models"), sys.argv[2:]
    {"models": lambda: list_models(), "sample": lambda: build_sample(args),
     "clone": lambda: clone(args[0] if args else "HuyK - Vien Chi Bao (IVC)"),
     "transcribe": lambda: transcribe(args[0])}[cmd]()
