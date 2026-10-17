"""Duyệt kho footage trên ổ mạng theo luồng chọn: loại → sản phẩm → công đoạn.

Kho được chia ở ba nhánh khác nhau, mỗi nhánh một mục đích:
  Visual  – cảnh sản phẩm, là nguồn danh sách tên sản phẩm
  Chế tác – quay từng công đoạn tại xưởng, chia theo thợ
  Stock   – HuyK thao tác, dùng xen giữa các đoạn chế tác

Ổ mạng chậm — liệt kê 170 thư mục mất hơn 30 giây — nên web không bao giờ đọc thẳng
từ đây. Module này chỉ làm nhiệm vụ quét, kết quả được VCB_BE đồng bộ vào Postgres
và web đọc lại từ đó.
"""
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from footage_filename_parser import craft_step_from_action, parse_filename

NAS = Path(os.getenv("VCB_NAS_ROOT", "/Volumes/MEDIA VCB folder"))
VISUAL_ROOT = NAS / "KHO SP THƯƠNG MẠI" / "KIM HOÀN" / "VIDEO" / "Visual"
BRAND_ROOT = NAS / "THƯƠNG HIỆU" / "1. KIM HOÀN"
# Cảnh chế tác nằm ở hai nhánh: xưởng quay theo thợ, và dự án HuyK quay riêng. Cùng một
# mã hàng có thể xuất hiện ở cả hai, mỗi bên một buổi quay khác nhau, nên gộp cả hai lại
# thay vì chọn một. Chỉ lấy nhánh VN — các nhánh thị trường khác (JP…) không dùng.
CRAFT_ROOTS = [
    BRAND_ROOT / "3. CHẾ TÁC XƯỞNG SẢN XUẤT" / "2. SẢN XUẤT THEO THỢ" / "VN",
    BRAND_ROOT / "2. DỰ ÁN HUYK CHẾ TÁC SP",
]
HUYK_ROOT = BRAND_ROOT / "4. STOCK HÀNH ĐỘNG" / "VIDEO" / "1. VN"
OUTRO_ROOT = BRAND_ROOT / "7. SOURCE OUTRO"

VIDEO_EXT = {".mp4", ".mov"}
# Thư mục hai nhánh viết hoa/thường khác nhau ('1. Nhan' với '1. NHAN') nhưng số đầu thì
# trùng, nên khớp theo số cho chắc.
CATEGORIES = [
    {"id": "1", "label": "Nhẫn"},
    {"id": "2", "label": "Lắc tay"},
    {"id": "3", "label": "Bông tai"},
    {"id": "4", "label": "Dây chuyền"},
]
LEADING_NUMBER = re.compile(r"^\s*(\d+)\s*[.\-_)]\s*(.*)$")
# Mã hàng mở đầu tên thư mục chế tác, cắt ngay trước phần tên tiếng Việt đi sau dấu
# ngăn: 'N0018-Nhan-sanh-doi' -> 'N0018', 'A732_Nhan-trai-tim' -> 'A732'.
CRAFT_SKU_HEAD = re.compile(r"^([A-Za-z]{1,4}\d[\w.]*?)(?=[_-][A-Za-zÀ-ỹ])")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _subdirs(path: Path) -> list:
    if not path.is_dir():
        return []
    return sorted((p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")),
                  key=lambda p: _natural_key(p.name))


def _natural_key(name: str):
    m = LEADING_NUMBER.match(name)
    return (0, int(m.group(1)), "") if m else (1, 0, _nfc(name).lower())


def _count_videos(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for p in path.iterdir() if p.suffix.lower() in VIDEO_EXT)


def _category_dir(root: Path, category_id: str):
    """Tìm thư mục loại theo số đầu tên, bỏ qua khác biệt hoa/thường và dấu."""
    for d in _subdirs(root):
        m = LEADING_NUMBER.match(d.name)
        if m and m.group(1) == str(category_id):
            return d
    return None


def products(category_id: str) -> list:
    """Danh sách sản phẩm của một loại, lấy từ nhánh Visual ('N0006_Nhan-tang-hinh').

    Tên thư mục luôn theo dạng `<mã>_<tên>`, tách thẳng ở gạch dưới đầu tiên để tên
    không bị cắt ở dấu chấm trong cỡ đá ('6.5li').

    Một mã đôi khi có hai thư mục do đặt tên khác nhau giữa các đợt quay
    ('N0011_Nhan-hanh-tinh-xoay' và 'N0011_Nhan-hanh-tinh-Moissanite-xoay'). Đó vẫn
    là một sản phẩm, nên gộp theo mã và giữ lại mọi thư mục làm nguồn cảnh sản phẩm.
    """
    d = _category_dir(VISUAL_ROOT, category_id)
    if not d or not (d / "VN").is_dir():
        return []
    merged = {}
    for p in _subdirs(d / "VN"):
        folder = _nfc(p.name)
        sku, _, name = folder.partition("_")
        if not name:
            parsed = parse_filename(folder)
            sku, name = parsed["sku"] or folder, parsed["product"] or folder
        sku, name = sku.strip(), name.replace("-", " ").strip()

        item = merged.setdefault(sku, {"sku": sku, "name": name, "folders": [], "paths": []})
        item["folders"].append(folder)
        item["paths"].append(str(p))
        if len(name) > len(item["name"]):   # tên dài hơn thường là tên mô tả đủ hơn
            item["name"] = name
    return list(merged.values())


def _slug(text: str) -> str:
    """Rút tên về dạng chỉ còn chữ và số để so khớp bất kể dấu nối hay khoảng trắng."""
    return "".join(ch for ch in _nfc(text).lower() if ch.isalnum())


@lru_cache(maxsize=8)
def _craft_index(category_id: str) -> dict:
    """Bảng tra thư mục chế tác của một loại: theo mã, và theo tên đã rút gọn.

    Dựng một lần rồi nhớ lại. Dò lần lượt cho từng sản phẩm thì mỗi lần phải liệt kê cả
    thư mục loại trên ổ mạng — vài giây một lần, nhân với hơn ba trăm mã là kẹt cả tiếng
    trước khi tải được clip đầu tiên. Thêm thư mục mới trên ổ thì gọi _craft_index.cache_clear().
    """
    by_sku, by_name = {}, {}

    def add(table: dict, key: str, path: Path):
        bucket = table.setdefault(key, [])
        if path not in bucket:
            bucket.append(path)

    for root in CRAFT_ROOTS:
        d = _category_dir(root, category_id)
        for p in _subdirs(d) if d else []:
            folder = _nfc(p.name)
            sku, _, name = folder.partition("_")
            add(by_sku, sku.lower(), p)
            # Phần lớn thư mục ngăn mã với tên bằng gạch dưới, nhưng có cái dùng gạch ngang
            # ('N0018-Nhan-sanh-doi'); tách theo gạch dưới thì cả tên bị nhận là mã.
            head = CRAFT_SKU_HEAD.match(folder)
            if head:
                add(by_sku, head.group(1).lower(), p)
                name = name or folder[head.end():].lstrip("_-")
            if name:
                add(by_name, _slug(name), p)
    return {"sku": by_sku, "name": by_name}


def _craft_product_dirs(category_id: str, sku: str) -> list:
    """Các thư mục chế tác của một sản phẩm; tên thư mục bắt đầu bằng chính mã đó.

    Khoảng một phần sáu thư mục bên nhánh Visual không kèm mã ('Nhan-dai-hoa' thay vì
    'N0017_Nhan-dai-hoa'), nên mã suy ra từ đó lại chính là tên sản phẩm. Khớp hụt thì
    dò tiếp theo phần tên của thư mục chế tác để những sản phẩm đó vẫn có công đoạn.
    """
    index = _craft_index(category_id)
    hit = index["sku"].get(_nfc(sku).lower())
    if hit:
        return list(hit)
    slug = _slug(sku)
    return list(index["name"].get(slug) or []) if len(slug) >= 6 else []


def craft_steps(category_id: str, sku: str) -> list:
    """Các công đoạn chế tác của một sản phẩm, theo đúng thứ tự thợ đánh số.

    Một sản phẩm thường được quay nhiều buổi, mỗi thợ đánh số công đoạn lại từ đầu, nên
    giữ nguyên buổi quay làm nhóm — trộn chung thì sẽ ra hai công đoạn cùng số và sai
    thứ tự thật của quy trình.
    """
    out = []
    for product_dir in _craft_product_dirs(category_id, sku):
        for shoot in _subdirs(product_dir):
            # Có buổi quay bọc thêm một lớp thư mục 'source' trước khi tới các công đoạn.
            levels = [shoot] + [s for s in _subdirs(shoot) if _nfc(s.name).lower() == "source"]
            for level in levels:
                for step_dir in _subdirs(level):
                    if _nfc(step_dir.name).lower() == "source":
                        continue
                    clips = _count_videos(step_dir)
                    if not clips:
                        continue
                    m = LEADING_NUMBER.match(_nfc(step_dir.name))
                    raw = m.group(2) if m else _nfc(step_dir.name)
                    step, _ = craft_step_from_action(raw)
                    out.append({"shoot": _nfc(shoot.name), "index": int(m.group(1)) if m else None,
                                "name": raw.strip(), "folder": _nfc(step_dir.name), "step": step,
                                "clips": clips, "path": str(step_dir)})
    return sorted(out, key=lambda x: (x["shoot"], x["index"] is None, x["index"] or 0))


def huyk_actions() -> list:
    """Kho HuyK thao tác, chia theo hành động ('14. ĐANH BONG')."""
    out = []
    for d in _subdirs(HUYK_ROOT):
        clips = _count_videos(d)
        if not clips:
            continue
        m = LEADING_NUMBER.match(_nfc(d.name))
        raw = m.group(2) if m else _nfc(d.name)
        step, _ = craft_step_from_action(raw)
        out.append({"index": int(m.group(1)) if m else None, "name": raw.strip(),
                    "folder": _nfc(d.name), "step": step, "clips": clips, "path": str(d)})
    return sorted(out, key=lambda x: (x["index"] is None, x["index"] or 0))


def videos_in(path: str) -> list:
    """Các file video trong một thư mục công đoạn / hành động."""
    d = Path(path)
    if not d.is_dir() or not _is_inside_nas(d):
        return []
    return sorted((str(p) for p in d.iterdir() if p.suffix.lower() in VIDEO_EXT),
                  key=lambda s: _natural_key(Path(s).name))


def _is_inside_nas(path: Path) -> bool:
    """Chặn đọc ra ngoài kho: đường dẫn do client gửi lên nên phải kiểm tra."""
    try:
        return path.resolve().is_relative_to(NAS.resolve())
    except (OSError, ValueError):
        return False


def available() -> bool:
    return VISUAL_ROOT.is_dir()


def scan_products() -> list:
    """Toàn bộ loại kèm sản phẩm, dạng BE cần để đồng bộ vào Postgres một lượt."""
    return [{**c, "products": products(c["id"])} for c in CATEGORIES]
