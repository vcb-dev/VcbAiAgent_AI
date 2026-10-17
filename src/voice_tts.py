"""Voice-over synthesis with measured durations.

Provider order: giọng nhân bản MiniMax từ bản thu editor tải lên (khi dự án đã học giọng)
-> ElevenLabs (khi có ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID — giọng HuyK chính thức)
-> giọng tiếng Việt "Linh" của macOS `say` (bản demo chạy offline). Kết quả cache theo nội dung.
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
from pathlib import Path

import voice_minimax
from app_paths import (ELEVENLABS_API_KEY, ELEVENLABS_MODEL, ELEVENLABS_SETTINGS, ELEVENLABS_VOICE_ID,
                       MACOS_RATE, MACOS_VOICE, MINIMAX_HUYK_VOICE_ID, MVP, TTS_DIR)
from vo_director import direct_parts, pronounce


def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {res.stderr[-300:]}")
    return res


def audio_duration(path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).stdout
    return round(float(out.strip() or 0), 3)


def to_wav(src, dst):
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
            to_wav(raw, wav)
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


# Định dạng ffmpeg đọc được và editor hay có sẵn; nhận cả file quay có tiếng để tách lời.
UPLOAD_EXT = {".mp3", ".wav", ".m4a", ".aac", ".aiff", ".aif", ".flac", ".ogg", ".opus", ".mp4", ".mov", ".webm"}


def import_recording(raw: bytes, filename: str) -> dict:
    """Nhận file ghi âm tải từ máy lên, dùng thay lời đọc máy của một phần.

    Chuyển về đúng wav 48k mono như giọng tổng hợp, để khâu trộn tiếng và đo thời lượng
    không phải phân biệt nguồn. Đặt tên theo nội dung file nên tải lại cùng một file
    không sinh thêm bản sao.
    """
    name = Path(filename or "").name or "ghi-am"
    ext = Path(name).suffix.lower()
    if ext not in UPLOAD_EXT:
        raise ValueError(f"không nhận định dạng {ext or 'này'}; dùng mp3, wav, m4a hoặc aac")
    if not raw:
        raise ValueError("file rỗng")

    wav = TTS_DIR / f"upload_{hashlib.sha1(raw).hexdigest()[:16]}.wav"
    if not wav.exists():
        src = wav.with_name(f"{wav.stem}.{uuid.uuid4().hex[:6]}{ext}")
        try:
            src.write_bytes(raw)
            to_wav(src, wav)
        except RuntimeError as exc:
            raise ValueError("không đọc được âm thanh trong file này") from exc
        finally:
            src.unlink(missing_ok=True)

    duration = audio_duration(wav)
    if duration <= 0:
        raise ValueError("file không có tiếng")
    return {"audio": wav.relative_to(MVP).as_posix(), "duration": duration,
            "provider": "upload", "upload_name": name[:80]}


def _silence_mids(wav) -> list:
    """Điểm giữa của các quãng lặng trong bản thu — chỗ người đọc ngắt giữa hai đoạn."""
    res = subprocess.run(["ffmpeg", "-v", "info", "-i", str(wav), "-af", "silencedetect=noise=-32dB:d=0.22",
                          "-f", "null", "-"], capture_output=True, text=True, check=False)
    mids, start = [], None
    for line in res.stderr.splitlines():
        try:
            if "silence_start:" in line:
                start = float(line.rsplit("silence_start:", 1)[1].strip())
            elif "silence_end:" in line and start is not None:
                mids.append((start + float(line.rsplit("silence_end:", 1)[1].split("|")[0].strip())) / 2)
                start = None
        except ValueError:
            start = None
    return mids


def stored_recording(audio_rel: str, upload_name: str = "") -> dict:
    """Bản thu đã tải lên trước đó, tra lại theo đường dẫn.

    Đường dẫn do trình duyệt gửi lên nên chỉ nhận đúng file do `import_recording` tạo ra
    và chỉ tìm trong thư mục tts, không cho trỏ ra chỗ khác trên máy.
    """
    name = Path(audio_rel or "").name
    if not (name.startswith("upload_") and name.endswith(".wav")):
        raise ValueError("file giọng đọc không hợp lệ")
    wav = TTS_DIR / name
    if not wav.exists():
        raise ValueError("file giọng đọc không còn trên máy chủ, tải lại giúp tôi")
    return {"audio": wav.relative_to(MVP).as_posix(), "duration": audio_duration(wav),
            "provider": "upload", "upload_name": (upload_name or name)[:80]}


def split_recording(base: dict, parts: list) -> list:
    """Chia một bản thu cả kịch bản thành lời đọc từng phần: [(chỉ số phần, vo)].

    Ranh giới đặt theo tỉ lệ số chữ của từng phần, rồi nắn về quãng lặng gần nhất: người
    đọc tự ngắt hơi giữa các đoạn nên đó là chỗ cắt sát thực tế nhất mà không cần nhận
    dạng tiếng nói. Quãng lặng nào lệch quá 1,5 giây so với mốc tính theo chữ thì bỏ, vì
    nhiều khả năng đó là chỗ ngắt giữa câu chứ không phải hết đoạn.
    """
    wav, total = MVP / base["audio"], base["duration"]
    voiced = [i for i, p in enumerate(parts) if (p.get("vo_text") or "").strip()]
    if not voiced:
        raise ValueError("kịch bản chưa có phần nào có lời đọc")
    if len(voiced) == 1:
        return [(voiced[0], base)]

    weights = [len((parts[i].get("vo_text") or "").strip()) or 1 for i in voiced]
    gaps, cuts, prev, acc = _silence_mids(wav), [], 0.0, 0
    for weight in weights[:-1]:
        acc += weight
        target = total * acc / sum(weights)
        usable = [g for g in gaps if prev + 0.4 < g < total - 0.4]
        near = min(usable, key=lambda g: abs(g - target)) if usable else None
        pick = near if near is not None and abs(near - target) <= 1.5 else target
        prev = min(max(pick, prev + 0.4), total - 0.4)
        cuts.append(round(prev, 3))

    bounds = [0.0] + cuts + [total]
    out = []
    for n, index in enumerate(voiced):
        seg = TTS_DIR / f"{wav.stem}_p{index}.wav"
        if not seg.exists():
            _cut(wav, bounds[n], bounds[n + 1], seg)
        out.append((index, {"audio": seg.relative_to(MVP).as_posix(), "duration": audio_duration(seg),
                            "provider": "upload", "upload_name": base["upload_name"]}))
    return out


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


def learn_voice(base: dict) -> dict:
    """Học giọng trong bản thu tải lên, để giọng đó đọc kịch bản thay vì dùng thẳng bản thu.

    Trả về phần mô tả giọng cất vào dự án. Bản thu gốc giữ lại để nghe đối chiếu trên giao diện.
    """
    name = base.get("upload_name", "")
    voice_id = voice_minimax.clone_voice(MVP / base["audio"], name)
    return {"voice_id": voice_id, "audio": base["audio"], "duration": base["duration"],
            "label": name, "upload_name": name, "provider": "minimax"}


def available_voices() -> list:
    """Giọng nhân bản có sẵn trên tài khoản, để chọn người đọc cho video."""
    if not voice_minimax.enabled():
        return []
    return [{"voice_id": v["voice_id"], "created_time": v.get("created_time", ""),
             "default": v["voice_id"] == MINIMAX_HUYK_VOICE_ID} for v in voice_minimax.list_voices()]


def pick_voice(voice_id: str) -> dict:
    """Chọn một giọng có sẵn trên tài khoản làm người đọc của dự án."""
    if not voice_minimax.enabled():
        raise ValueError("chưa cấu hình MiniMax nên không chọn được giọng")
    if voice_id not in {v["voice_id"] for v in voice_minimax.list_voices()}:
        raise ValueError(f"không có giọng '{voice_id}' trên tài khoản")
    return {"voice_id": voice_id, "label": voice_id, "provider": "minimax"}


def _cloned_vo(part: dict, voice_id: str):
    """Lời đọc một phần bằng giọng đã nhân bản."""
    text = (part.get("vo_text") or "").strip()
    if not text:
        return None
    take = voice_minimax.synthesize_take(pronounce(text), voice_id)
    return {"audio": take["audio"], "duration": take["duration"], "provider": take["provider"]}


def _cloned_performance(parts: list, voice_id: str) -> list:
    """Đọc riêng từng phần thay vì một lượt dài rồi cắt.

    MiniMax chỉ trả mốc thời gian tới mức câu, mà ranh giới câu không trùng ranh giới phần,
    nên cắt theo mốc đó sẽ lệch. Đọc riêng thì thời lượng mỗi phần là đo thật, và sửa chữ
    ở một phần cũng chỉ phải đọc lại đúng phần đó.
    """
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(lambda p: _cloned_vo(p, voice_id), parts))


def huyk_voice_enabled() -> bool:
    """Giọng HuyK dùng chung đã học sẵn chưa (xem indexer/huyk_voice_setup.py)."""
    return bool(MINIMAX_HUYK_VOICE_ID and voice_minimax.enabled())


def _try_clone(parts: list, voice_id: str, label: str):
    try:
        return _cloned_performance(parts, voice_id)
    except voice_minimax.MinimaxError as exc:
        print(f"[tts] {label} lỗi ({exc}); lùi về giọng kế tiếp")
        return None


def synthesize_parts(parts: list, voice: str = "huyk", clone_voice_id: str = "") -> list:
    """VO for every part, theo thứ tự ưu tiên: giọng editor tải lên -> giọng HuyK -> giọng máy.

    Giọng HuyK chính thức là bản ElevenLabs khi có key; không thì dùng bản học từ footage
    HuyK nói trên ổ NAS.
    """
    if clone_voice_id and voice_minimax.enabled():
        vos = _try_clone(parts, clone_voice_id, "giọng nhân bản của dự án")
        if vos:
            return vos
    if voice == "huyk":
        if eleven_enabled():
            try:
                return _performance(parts)
            except (urllib.error.URLError, RuntimeError, OSError, KeyError, ValueError) as exc:
                print(f"[tts] ElevenLabs performance failed ({exc}); falling back to per-part voices")
        if huyk_voice_enabled():
            vos = _try_clone(parts, MINIMAX_HUYK_VOICE_ID, "giọng HuyK")
            if vos:
                return vos
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(lambda p: synthesize(p.get("vo_text", "")), parts))
