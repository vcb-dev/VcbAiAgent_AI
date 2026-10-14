"""Voice-over synthesis with measured durations.

Provider order: ElevenLabs (when ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID are set — production HuyK voice)
-> macOS `say` Vietnamese voice "Linh" (offline demo voice). Results are cached by text hash.
"""
import base64
import hashlib
import json
import os
import subprocess
import uuid
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from app_paths import (ELEVENLABS_API_KEY, ELEVENLABS_MODEL, ELEVENLABS_SETTINGS, ELEVENLABS_VOICE_ID, MACOS_RATE,
                       MACOS_VOICE, MVP, TTS_DIR)
from vo_director import direct_parts, pronounce


def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {res.stderr[-300:]}")
    return res


def audio_duration(path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).stdout
    return round(float(out.strip() or 0), 3)


def _to_wav(src, dst):
    tmp = dst.with_name(f"{dst.stem}.{uuid.uuid4().hex[:6]}.tmp.wav")      # atomic: never cache a partial file
    try:
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-ar", "48000", "-ac", "1", str(tmp)])
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def _eleven_request(text: str, with_timestamps: bool) -> bytes:
    path = "/with-timestamps" if with_timestamps else ""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}{path}?output_format=mp3_44100_128"
    body = json.dumps({"text": text, "model_id": ELEVENLABS_MODEL, "language_code": "vi",
                       "voice_settings": ELEVENLABS_SETTINGS}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def _elevenlabs(text, raw_path):
    raw_path.write_bytes(_eleven_request(pronounce(text), with_timestamps=False))


def _macos_say(text, raw_path):
    _run(["say", "-v", MACOS_VOICE, "-r", str(MACOS_RATE), "-o", str(raw_path), "--", text])   # '--': text is never an option


def _cached_path(provider: str, text: str):
    return TTS_DIR / f"{hashlib.sha1(f'{provider}|{MACOS_RATE}|{text}'.encode()).hexdigest()[:16]}.wav"


def _render(provider: str, engine, text: str, ext: str):
    wav = _cached_path(provider, text)
    if not wav.exists():
        raw = wav.with_name(f"{wav.stem}.{uuid.uuid4().hex[:6]}.{ext}")
        try:
            engine(text, raw)
            _to_wav(raw, wav)
        finally:
            raw.unlink(missing_ok=True)
    return wav


def synthesize(text: str) -> dict:
    """Return {'audio': rel_path, 'duration': seconds, 'provider': name} or None for empty text."""
    text = (text or "").strip()
    if not text:
        return None
    say_provider = f"macos_say:{MACOS_VOICE}"
    if ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID:
        provider = f"elevenlabs:{ELEVENLABS_MODEL}"
        try:
            wav = _render(provider, _elevenlabs, text, "mp3")
        except (urllib.error.URLError, RuntimeError, OSError) as exc:
            print(f"[tts] ElevenLabs failed ({exc}); falling back to macOS voice")
            provider, wav = say_provider, _render(say_provider, _macos_say, text, "aiff")
    else:
        provider, wav = say_provider, _render(say_provider, _macos_say, text, "aiff")
    return {"audio": wav.relative_to(MVP).as_posix(), "duration": audio_duration(wav), "provider": provider}


def eleven_enabled() -> bool:
    return bool(ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID)


def _cut(src, start: float, end: float, dst):
    """Cut [start, end) from the full performance into a part wav with 15 ms fades (no clicks at the seams)."""
    tmp = dst.with_name(f"{dst.stem}.{uuid.uuid4().hex[:6]}.tmp.wav")
    fade_out = max(end - start - 0.015, 0)
    try:
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src), "-ar", "48000",
              "-ac", "1", "-af", f"afade=t=in:d=0.015,afade=t=out:st={fade_out:.3f}:d=0.015", str(tmp)])
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def _performance(parts: list) -> list:
    """One continuous eleven_v4 take of the whole script (emotion carries across parts), split per part."""
    directed = direct_parts(parts)
    full = " ".join(text for _, text in directed)
    provider = f"elevenlabs:{ELEVENLABS_MODEL}"
    key = hashlib.sha1(f"{provider}|{ELEVENLABS_VOICE_ID}|{json.dumps(ELEVENLABS_SETTINGS)}|{full}".encode()).hexdigest()[:16]
    take, meta_path = TTS_DIR / f"take_{key}.mp3", TTS_DIR / f"take_{key}.json"
    if not (take.exists() and meta_path.exists()):
        data = json.loads(_eleven_request(full, with_timestamps=True))
        take.write_bytes(base64.b64decode(data["audio_base64"]))
        meta_path.write_text(json.dumps(data["alignment"]), encoding="utf-8")
    starts = json.loads(meta_path.read_text(encoding="utf-8"))["character_start_times_seconds"]
    total, offsets, pos = audio_duration(take), [], 0
    for _, text in directed:
        offsets.append(pos)
        pos += len(text) + 1                      # +1 for the joining space
    vos = [None] * len(parts)
    for n, ((i, text), off) in enumerate(zip(directed, offsets)):
        start = 0.0 if n == 0 else starts[min(off, len(starts) - 1)]
        end = total if n == len(directed) - 1 else starts[min(offsets[n + 1], len(starts) - 1)]
        wav = TTS_DIR / f"take_{key}_p{i}.wav"
        if not wav.exists():
            _cut(take, start, end, wav)
        vos[i] = {"audio": wav.relative_to(MVP).as_posix(), "duration": audio_duration(wav), "provider": provider,
                  "direction": text.split("]")[0] + "]" if text.startswith("[") else ""}
    return vos


def synthesize_parts(parts: list, voice: str = "huyk") -> list:
    """VO for every part: one emotional ElevenLabs take (voice='huyk', when configured), else per-part demo voice."""
    if voice == "huyk" and eleven_enabled():
        try:
            return _performance(parts)
        except (urllib.error.URLError, RuntimeError, OSError, KeyError, ValueError) as exc:
            print(f"[tts] ElevenLabs performance failed ({exc}); falling back to per-part voices")
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(lambda p: synthesize(p.get("vo_text", "")), parts))
