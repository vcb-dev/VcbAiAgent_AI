"""Thử nhanh MiniMax: clone giọng từ file mẫu rồi cho đọc một đoạn tiếng Việt.

Chỉ dùng để kiểm tra key và chất lượng giọng, không nằm trong luồng chạy của dịch vụ.
  python VCB_AI/indexer/minimax_probe.py [file_mau.wav]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voice_minimax import clone_voice, enabled, synthesize_take  # noqa: E402

TEXT = ("Đây là một mẫu nhẫn mà mỗi lần khách đặt, thợ nhà HuyK chỉ biết nhìn nhau rồi đòi bỏ nghề. "
        "Chiếc này khó tới mức chỉ cần lệch một chi tiết nhỏ thôi là gần như bỏ cả sản phẩm. "
        "Có hôm anh em làm hơn mười tiếng, tới công đoạn cuối mới phát hiện lỗi.")


def main():
    if not enabled():
        sys.exit("chưa có MINIMAX_API_KEY trong local-secrets.json")
    sample = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    voice_id = clone_voice(sample) if sample else None
    print("voice_id:", voice_id or "(giọng mẫu sẵn có)")
    take = synthesize_take(TEXT, voice_id)
    print("audio:", take["audio"], f"{take['duration']}s")
    print("mốc chữ đầu:", json.dumps(take["words"][:6], ensure_ascii=False))
    print("số mốc:", len(take["words"]))


if __name__ == "__main__":
    main()
