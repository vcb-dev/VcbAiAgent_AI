"""Chọn hoặc dựng giọng HuyK dùng chung cho cả hệ thống.

Khác giọng nhân bản của từng dự án (editor tự tải mẫu lên), giọng này cố định: đặt một lần
rồi mọi dự án chọn "Giọng HuyK" đều dùng. voice_id lưu vào local-secrets.json.

Tài khoản MiniMax thường đã có sẵn giọng clone từ trước, nên xem `list` trước khi clone mới.

  python VCB_AI/indexer/huyk_voice_setup.py list
  python VCB_AI/indexer/huyk_voice_setup.py compare <voice_id> [<voice_id> ...]
  python VCB_AI/indexer/huyk_voice_setup.py use <voice_id>
  python VCB_AI/indexer/huyk_voice_setup.py sample "<video HuyK nói>" [<video> ...]
  python VCB_AI/indexer/huyk_voice_setup.py clone
  python VCB_AI/indexer/huyk_voice_setup.py demo "Câu muốn nghe thử"
"""
import json
import subprocess
import sys
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MVP / "src"))

from voice_minimax import SAMPLE_MIN_SECONDS, clone_voice, enabled, list_voices, synthesize_take  # noqa: E402

SECRETS = MVP / "local-secrets.json"
SAMPLE_DIR = MVP / "media" / "voice-samples"
SAMPLE = SAMPLE_DIR / "huyk_voice_sample.mp3"
DEMO_TEXT = "Chào anh chị, mình là HuyK. Mỗi sản phẩm ở xưởng đều làm thủ công từ đầu tới cuối."
# Lọc ồn xưởng, cắt quãng lặng, cân âm lượng: mẫu càng sạch thì giọng học ra càng giống.
CLEAN = ("highpass=f=80,lowpass=f=12000,afftdn=nf=-25,"
         "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=1.0:stop_threshold=-50dB,"
         "loudnorm=I=-18:TP=-2:LRA=7,alimiter=limit=0.84")


def _duration(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return round(float(out.strip() or 0), 2)


def _secrets() -> dict:
    return json.loads(SECRETS.read_text(encoding="utf-8")) if SECRETS.exists() else {}


def build_sample(sources):
    """Tách lời HuyK từ các video, nối lại thành một mẫu giọng sạch."""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, src in enumerate(sources):
        out = SAMPLE_DIR / f"huyk_part_{i}.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "44100",
                        "-af", CLEAN, "-b:a", "192k", str(out)], check=True)
        print(f"  {out.name}: {_duration(out)}s  ({Path(src).name})")
        parts.append(out)

    if len(parts) == 1:
        parts[0].replace(SAMPLE)
    else:
        listing = SAMPLE_DIR / "parts.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", str(SAMPLE)], check=True)
        listing.unlink()
    seconds = _duration(SAMPLE)
    print(f"\nmẫu giọng: {SAMPLE} — {seconds}s")
    if seconds < SAMPLE_MIN_SECONDS:
        print(f"CẢNH BÁO: ngắn hơn {SAMPLE_MIN_SECONDS:.0f}s, thêm video nữa cho đủ")
    return SAMPLE


def clone():
    if not enabled():
        sys.exit("chưa có MINIMAX_API_KEY trong local-secrets.json")
    if not SAMPLE.exists():
        sys.exit("chưa có mẫu giọng: chạy lệnh 'sample' trước")
    voice_id = clone_voice(SAMPLE, "HuyK")
    data = _secrets()
    data["MINIMAX_HUYK_VOICE_ID"] = voice_id
    SECRETS.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"đã học giọng HuyK: {voice_id} (ghi vào local-secrets.json)")
    return voice_id


def use(voice_id: str):
    """Đặt một giọng có sẵn trên MiniMax làm giọng HuyK của hệ thống."""
    known = {v["voice_id"] for v in list_voices()}
    if voice_id not in known:
        sys.exit(f"không có giọng '{voice_id}' trên tài khoản; xem lệnh 'list'")
    data = _secrets()
    data["MINIMAX_HUYK_VOICE_ID"] = voice_id
    SECRETS.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"giọng HuyK của hệ thống: {voice_id}")


def show_list():
    current = _secrets().get("MINIMAX_HUYK_VOICE_ID")
    for v in sorted(list_voices(), key=lambda v: v.get("created_time", "")):
        mark = " ← đang dùng" if v["voice_id"] == current else ""
        print(f"  {v.get('created_time', ''):<12}{v['voice_id']}{mark}")


def compare(voice_ids, text: str = DEMO_TEXT):
    """Cho từng giọng đọc cùng một câu, để nghe rồi chọn."""
    out = MVP / "media" / "voice-samples" / "so-sanh"
    out.mkdir(parents=True, exist_ok=True)
    for voice_id in voice_ids:
        try:
            take = synthesize_take(text, voice_id)
        except Exception as exc:                       # giọng hỏng không được chặn các giọng còn lại
            print(f"  {voice_id:<28} LỖI: {exc}")
            continue
        dst = out / f"{voice_id}.wav"
        dst.write_bytes((MVP / take["audio"]).read_bytes())
        print(f"  {voice_id:<28}{take['duration']:>6.2f}s  {dst}")


def demo(text: str = DEMO_TEXT):
    voice_id = _secrets().get("MINIMAX_HUYK_VOICE_ID")
    if not voice_id:
        sys.exit("chưa có giọng HuyK: chạy lệnh 'use' hoặc 'clone' trước")
    take = synthesize_take(text, voice_id)
    print(f"nghe thử: {MVP / take['audio']} — {take['duration']}s")


if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else "list"), sys.argv[2:]
    {"list": show_list, "use": lambda: use(args[0]), "compare": lambda: compare(args),
     "sample": lambda: build_sample(args), "clone": clone,
     "demo": lambda: demo(args[0] if args else DEMO_TEXT)}[cmd]()
