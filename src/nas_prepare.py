"""Kéo footage của một tuyến A4 từ ổ NAS về máy để dựng được.

Kho trên ổ chỉ được lập mục lục chứ không tải về (800 GB qua đường 1,5 MB/s thì mất
gần 8 ngày). Nên lúc editor bấm dựng một mã chưa từng dùng, ta lấy đúng số cảnh tuyến
A4 cần: mỗi thư mục công đoạn một clip, nén thành proxy 720×1280 rồi ghi vào catalog.
Khoảng 9 clip, vài phút — và chỉ phải làm một lần cho mỗi mã.
"""
import json
import sys
import unicodedata
from pathlib import Path

from app_paths import DATA
from catalog_store import load_catalog
from footage_filename_parser import craft_step_from_action
from nas_browser import VIDEO_EXT, videos_in

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "indexer"))

# Vai trò gán theo nhánh kho mà clip được lấy ra; người gọi biết rõ mình đang lấy cảnh
# gì nên không cần đoán lại từ đường dẫn.
SLOT_ROLES = {
    "craft": {"craft": 0.9},
    "huyk": {"huyk_talk": 0.85},
    "product": {"product_hero": 0.9, "product_final": 0.85},
    "outro": {"outro": 0.9},
}
# Clip quá ngắn thường là cảnh hỏng; quá dài thì tải lâu mà cũng chỉ dùng vài giây.
MIN_BYTES = 3 * 1048576
MAX_BYTES = 80 * 1048576


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _videos_under(folder: str) -> list:
    """Video trong thư mục, hoặc trong các thư mục con nếu tầng ngoài không có file nào.

    Thư mục công đoạn chứa video trực tiếp, còn thư mục cảnh sản phẩm lại bọc thêm một
    lớp buổi quay ('N0006_Nhan-tang-hinh/260701_N0006_..._DTA01/').
    """
    direct = videos_in(folder)
    if direct:
        return direct
    root = Path(folder)
    if not root.is_dir():
        return []
    return [str(p) for sub in sorted(root.iterdir()) if sub.is_dir() for p in sorted(sub.iterdir())
            if p.suffix.lower() in VIDEO_EXT]


def pick_clip(folder: str) -> str:
    """Chọn một clip đại diện cho thư mục: nhỏ nhất trong khoảng hợp lệ để tải cho nhanh."""
    files = [Path(p) for p in _videos_under(folder)]
    if not files:
        return ""
    sized = sorted(((f.stat().st_size, f) for f in files), key=lambda x: x[0])
    good = [f for size, f in sized if MIN_BYTES <= size <= MAX_BYTES]
    return str(good[0] if good else sized[0][1])


def _catalog_entry(path: Path, slot: str, step_name: str = "", sku: str = "") -> dict:
    """Index một clip (dựng proxy + ảnh) rồi bồi các trường mà catalog cần.

    Clip kéo về theo nhu cầu thì chưa qua bước gắn nhãn bằng AI, nên điền phần tối thiểu
    để bộ chọn footage dùng được: vai trò, công đoạn và khoảng hình dùng được.
    """
    import build_media_index as indexer

    indexer.CATALOG_ONLY = False
    # Tuyến A4 chỉ dùng 3-5 giây mỗi cảnh, nên không cắt clip dài thành nhiều đoạn:
    # bước đó giải mã trọn clip (hơn 100 giây mỗi file) và còn gọi thêm AI, trong khi ta
    # chỉ cần đúng một đoạn dùng được.
    no_split = (False, "on_demand")
    original, indexer.should_segment = indexer.should_segment, lambda *a, **k: no_split
    try:
        entries = indexer.index_clip((path, path.parent))
    finally:
        indexer.should_segment = original
    out = []
    for e in entries:
        dur = e["tech"]["duration"]
        step = e["parsed"].get("craft_step")
        if not step and step_name:
            step, _ = craft_step_from_action(step_name)
        out.append({
            **e,
            # Indexer suy quyền dùng từ đường dẫn và không biết các nhánh kho trên ổ, nên
            # trả về 'unknown' — mà bộ chọn footage chỉ nhận 'owned', thành ra loại sạch
            # cảnh vừa kéo về. Kho NAS toàn là footage VCB tự quay nên khẳng định luôn.
            "rights": "owned",
            # Cảnh HuyK và outro dùng chung cho mọi mã; bộ chọn coi 'product_set' rỗng là
            # footage chung, có mã lẻ vào đây là hết đường khớp.
            "product_set": sku if slot in ("craft", "product") else None,
            "craft_step": step if slot == "craft" else ("hoan_thien" if slot == "product" else None),
            "craft_step_source": "filename",
            "usable": [0.0, round(dur, 2)],
            "best_moment_s": round(dur / 2, 2),
            "roles": dict(SLOT_ROLES[slot]),
            "tags": {},
            "description_vi": "",
            "keywords_vi": [],
            "tagged": False,
        })
    return out


def prepare(sku: str, sources: list) -> dict:
    """Kéo về và ghi vào catalog các cảnh của một tuyến A4.

    `sources` là danh sách `{slot, folder, name}` với slot thuộc SLOT_ROLES. Thư mục nào
    đã có clip trong catalog thì bỏ qua, nên bấm dựng lại lần hai là chạy ngay.
    """
    catalog = load_catalog()
    done = {c["file"] for c in catalog.values()}
    added, skipped, failed = [], [], []

    for src in sources:
        folder = src.get("folder") or ""
        slot = src.get("slot")
        if slot not in SLOT_ROLES or not folder:
            continue
        if any(_nfc(f).startswith(_nfc(folder)) for f in done):
            skipped.append(folder)
            continue

        clip = pick_clip(folder)
        if not clip:
            failed.append({"folder": folder, "error": "thư mục không có video"})
            continue
        try:
            added.extend(_catalog_entry(Path(clip), slot, src.get("name", ""), sku))
        except (RuntimeError, OSError, ValueError) as exc:
            failed.append({"folder": folder, "error": str(exc)[:200]})

    if added:
        _append_to_catalog(added)
    return {"sku": sku, "added": len(added), "skipped": len(skipped), "failed": failed,
            "clips": [{"id": c["id"], "name": c["name"], "roles": c["roles"]} for c in added]}


def _append_to_catalog(entries: list):
    """Ghi thêm vào catalog.json rồi bỏ nhớ đệm để lần dựng tiếp theo thấy clip mới."""
    path = DATA / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    known = {c["id"] for c in catalog}
    catalog.extend(e for e in entries if e["id"] not in known)

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    load_catalog.cache_clear()
