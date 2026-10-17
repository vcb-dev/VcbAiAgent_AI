"""Giọng đọc MiniMax: nhân bản giọng từ bản thu của editor rồi cho chính giọng đó đọc kịch bản.

Khác với bản thu tải lên dùng thẳng làm lời đọc, ở đây file tải lên chỉ là *mẫu giọng*:
MiniMax học giọng (`/v1/voice_clone`) rồi đọc nội dung do editor viết (`/v1/t2a_v2`).
Nhờ vậy sửa chữ trong kịch bản là có ngay lời đọc mới, không phải thu lại.

MiniMax trả kèm mốc thời gian từng chữ, nên cắt bản thu dài thành lời đọc của từng phần
là cắt đúng chỗ chứ không phải đoán theo quãng lặng.
"""
import hashlib
import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from app_paths import MINIMAX_API_KEY, MINIMAX_HOST, MINIMAX_MODEL, MVP, TTS_DIR

# MiniMax yêu cầu mẫu giọng 10 giây tới 5 phút, không quá 20 MB.
SAMPLE_MIN_SECONDS = 10.0
SAMPLE_MAX_SECONDS = 300.0
SAMPLE_MAX_BYTES = 20 * 1024 * 1024
TIMEOUT = 180


def enabled() -> bool:
    return bool(MINIMAX_API_KEY)


class MinimaxError(RuntimeError):
    """Lỗi phía MiniMax — luôn kèm câu tiếng Việt đọc được để hiện thẳng lên giao diện."""


def _read(req) -> dict:
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
    except urllib.error.HTTPError as exc:
        raise MinimaxError(f"MiniMax trả lỗi {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise MinimaxError(f"không gọi được MiniMax ({exc})") from exc
    resp = data.get("base_resp") or {}
    if resp.get("status_code"):
        raise MinimaxError(f"MiniMax: {resp.get('status_msg') or resp['status_code']}")
    return data


def _post_json(path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{MINIMAX_HOST}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {MINIMAX_API_KEY}",
                                          "Content-Type": "application/json"})
    return _read(req)


def _post_file(path: str, fields: dict, file: Path) -> dict:
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    chunks = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
              for k, v in fields.items()]
    chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file.name}\"\r\n"
                  f"Content-Type: {mime}\r\n\r\n".encode())
    chunks += [file.read_bytes(), f"\r\n--{boundary}--\r\n".encode()]
    req = urllib.request.Request(f"{MINIMAX_HOST}{path}", data=b"".join(chunks), method="POST",
                                 headers={"Authorization": f"Bearer {MINIMAX_API_KEY}",
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _read(req)


def clone_voice(sample: Path, label: str = "") -> str:
    """Học giọng trong file mẫu, trả về voice_id dùng cho mọi lần đọc sau.

    voice_id suy ra từ nội dung file nên tải lại đúng bản thu cũ là dùng lại giọng đã học,
    không tốn thêm một lượt nhân bản.
    """
    from voice_tts import audio_duration        # nhập tại chỗ: voice_tts cũng gọi ngược sang đây

    sample = Path(sample)
    if not sample.exists():
        raise MinimaxError("không tìm thấy file mẫu giọng")
    if sample.stat().st_size > SAMPLE_MAX_BYTES:
        raise MinimaxError("file mẫu giọng quá 20 MB")
    seconds = audio_duration(sample)
    if seconds < SAMPLE_MIN_SECONDS:
        raise MinimaxError(f"mẫu giọng chỉ {seconds:.1f} giây, cần ít nhất {SAMPLE_MIN_SECONDS:.0f} giây để nhân bản")
    if seconds > SAMPLE_MAX_SECONDS:
        raise MinimaxError("mẫu giọng dài quá 5 phút")

    # voice_id chỉ nhận chữ và số, phải có cả hai và bắt đầu bằng chữ cái.
    voice_id = "vcb" + hashlib.sha1(sample.read_bytes()).hexdigest()[:16]
    done = TTS_DIR / f"voice_{voice_id}.json"
    if done.exists():
        return voice_id

    uploaded = _post_file("/v1/files/upload", {"purpose": "voice_clone"}, sample)
    file_id = (uploaded.get("file") or {}).get("file_id")
    if not file_id:
        raise MinimaxError("MiniMax không nhận file mẫu giọng")
    _post_json("/v1/voice_clone", {"file_id": file_id, "voice_id": voice_id, "model": MINIMAX_MODEL})
    done.write_text(json.dumps({"voice_id": voice_id, "sample": sample.name, "label": label,
                                "seconds": seconds}, ensure_ascii=False), encoding="utf-8")
    return voice_id


def list_voices() -> list:
    """Các giọng đã nhân bản trên tài khoản — tài khoản thường có sẵn giọng clone từ trước."""
    return _post_json("/v1/get_voice", {"voice_type": "all"}).get("voice_cloning") or []


def _words(subtitle_url: str) -> list:
    """Mốc thời gian từng chữ, đổi về giây. Thiếu mốc thì trả rỗng và bên gọi tự chia theo tỉ lệ."""
    if not subtitle_url:
        return []
    try:
        items = json.loads(urllib.request.urlopen(subtitle_url, timeout=60).read())
    except (urllib.error.URLError, OSError, ValueError):
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        text = item.get("text", "")
        begin, end = item.get("time_begin"), item.get("time_end")
        if begin is None or end is None:
            continue
        out.append({"text": text, "start": round(begin / 1000, 3), "end": round(end / 1000, 3)})
    return out


def synthesize_take(text: str, voice_id: str, speed: float = 1.0) -> dict:
    """Một lượt đọc liền mạch cả đoạn, kèm mốc thời gian từng chữ.

    Kết quả cache theo giọng + model + tốc độ + nội dung, nên dựng lại hay hoàn tác về
    đúng kịch bản cũ là không tốn thêm lượt gọi.
    """
    from voice_tts import audio_duration, to_wav

    key = hashlib.sha1(f"{voice_id}|{MINIMAX_MODEL}|{speed}|{text}".encode()).hexdigest()[:16]
    wav, meta = TTS_DIR / f"mm_{key}.wav", TTS_DIR / f"mm_{key}.json"
    if not (wav.exists() and meta.exists()):
        data = _post_json("/v1/t2a_v2", {
            "model": MINIMAX_MODEL, "text": text, "language_boost": "Vietnamese", "output_format": "hex",
            "subtitle_enable": True, "subtitle_type": "word",
            "voice_setting": {"voice_id": voice_id, "speed": speed, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        })
        hex_audio = (data.get("data") or {}).get("audio")
        if not hex_audio:
            raise MinimaxError("MiniMax không trả về âm thanh")
        raw = wav.with_name(f"{wav.stem}.{uuid.uuid4().hex[:6]}.mp3")
        try:
            raw.write_bytes(bytes.fromhex(hex_audio))
            to_wav(raw, wav)
        finally:
            raw.unlink(missing_ok=True)
        meta.write_text(json.dumps(_words((data.get("data") or {}).get("subtitle_file", "")),
                                   ensure_ascii=False), encoding="utf-8")
    return {"audio": wav.relative_to(MVP).as_posix(), "duration": audio_duration(wav),
            "words": json.loads(meta.read_text(encoding="utf-8")), "provider": f"minimax:{MINIMAX_MODEL}"}
