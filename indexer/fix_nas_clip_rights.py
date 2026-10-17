"""Sửa quyền dùng cho những clip đã kéo từ ổ NAS về trước khi vá nas_prepare.

Indexer suy quyền dùng từ đường dẫn, mà các nhánh kho trên ổ không nằm trong bảng luật
của nó nên mọi clip kéo theo nhu cầu đều mang 'unknown'. Bộ chọn footage chỉ nhận
'owned', nên tuy catalog có cảnh sản phẩm và cảnh HuyK thì khi dựng vẫn báo thiếu.

Chạy một lần: python3 indexer/fix_nas_clip_rights.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app_paths import DATA  # noqa: E402
from nas_browser import NAS  # noqa: E402

SHARED_SLOTS = ("huyk_talk", "huyk_silent", "outro")


def main():
    path = DATA / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    nas = NAS.as_posix()

    rights_fixed = shared_fixed = 0
    for clip in catalog:
        if not str(clip.get("file", "")).startswith(nas):
            continue
        if clip.get("rights") != "owned":
            clip["rights"] = "owned"
            rights_fixed += 1
        # Cảnh dùng chung mà đeo mã sản phẩm thì bộ chọn xếp nhầm sang nhóm 'đúng SKU'
        # và không bao giờ khớp được với slot HuyK hay outro.
        if any(r in (clip.get("roles") or {}) for r in SHARED_SLOTS) and clip.get("product_set"):
            clip["product_set"] = None
            shared_fixed += 1

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    print(f"đặt lại quyền dùng: {rights_fixed} clip · bỏ mã khỏi cảnh dùng chung: {shared_fixed} clip")


if __name__ == "__main__":
    main()
