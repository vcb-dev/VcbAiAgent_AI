"""Read-only access to the tagged footage catalog (simulates the Media Hub Catalog API)."""
import json
from functools import lru_cache
from typing import Optional

from app_paths import DATA, MVP
from footage_filename_parser import CRAFT_STEPS
from vietnamese_text import keyword_tokens

STEP_LABELS_VI = {
    "thiet_ke": "Thiết kế", "chuan_bi_nguyen_lieu": "Chuẩn bị nguyên liệu", "nung_nau": "Nung / đánh lửa",
    "do_khuon": "Đổ khuôn", "dap_can": "Đập/cán phôi", "cua_cat": "Cưa cắt", "han": "Hàn",
    "dua_mai": "Giũa mài", "khoan": "Khoan", "gan_da_chu": "Gắn đá chủ", "dinh_da": "Đính đá",
    "danh_bong": "Đánh bóng", "hoan_thien": "Hoàn thiện", "tao_dang": "Uốn tạo dáng",
    "lam_sach": "Làm sạch", "khac_laser": "Khắc laser",
}


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    """Catalog chỉ gồm clip thật sự dựng được.

    Mục lục có thể nhắc tới clip chưa kéo về (chế độ catalog-only) hoặc còn sót lại từ
    lần index bị ngắt giữa chừng. Để lọt vào đây thì khâu render sẽ gãy giữa chừng vì
    thiếu file, nên lọc ngay tại cửa.
    """
    clips = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    usable = [c for c in clips if c.get("proxy") and (MVP / c["proxy"]).exists()]
    for c in usable:
        text = " ".join([c.get("description_vi", ""), " ".join(c.get("keywords_vi", [])),
                         STEP_LABELS_VI.get(c.get("craft_step") or "", "")])
        c["_tokens"] = keyword_tokens(text)
    return {c["id"]: c for c in usable}


def get_clip(clip_id: str) -> dict:
    return load_catalog().get(clip_id)


def public_clip(c: dict) -> dict:
    """Clip fields safe/useful for the UI (drops internal token sets)."""
    return {k: v for k, v in c.items() if not k.startswith("_")}


def product_sets() -> list:
    """One entry per product footage set, richest first (for the product picker)."""
    sets = {}
    for c in load_catalog().values():
        sku = c.get("product_set")
        if not sku:
            continue
        s = sets.setdefault(sku, {"sku": sku, "name": c["parsed"].get("product") or sku, "clips": 0, "steps": set(),
                                  "has_final": False, "step_clips": {}})
        s["clips"] += 1
        if c.get("craft_step") and c["craft_step"] != "hoan_thien":
            s["steps"].add(c["craft_step"])
            s["step_clips"][c["craft_step"]] = s["step_clips"].get(c["craft_step"], 0) + 1
        if "product_final" in c["roles"]:
            s["has_final"] = True
    out = []
    for s in sorted(sets.values(), key=lambda x: -x["clips"]):
        # Bỏ qua công đoạn lạ thay vì làm vỡ cả bộ chọn sản phẩm khi taxonomy được bổ sung.
        steps = sorted((st for st in s["steps"] if st in CRAFT_STEPS), key=lambda st: CRAFT_STEPS[st][0])
        out.append({**s, "steps": steps,
                    "step_labels": [STEP_LABELS_VI.get(st, st) for st in steps],
                    # Dựng sẵn cho UI: tên công đoạn kèm số clip, đã xếp theo trình tự chế tác.
                    "step_detail": [{"step": st, "label": STEP_LABELS_VI.get(st, st),
                                     "clips": s["step_clips"].get(st, 0)} for st in steps]})
    return out


def available_steps(sku: str) -> list:
    for s in product_sets():
        if s["sku"] == sku:
            return s["steps"]
    return []


def craft_step_choices() -> list:
    """Danh sách công đoạn theo thứ tự xưởng, để UI gắn nhãn."""
    return [{"id": step, "label": STEP_LABELS_VI.get(step, step), "order": order}
            for step, (order, _) in sorted(CRAFT_STEPS.items(), key=lambda item: item[1][0])]


def set_clip_craft_step(clip_id: str, step: Optional[str]) -> dict:
    """Gắn (hoặc gỡ) công đoạn cho một clip trong catalog.json.

    Nhãn tay thắng tên thư mục: lần dựng sau bộ chọn footage dùng đúng công đoạn này.
    """
    if step == "":
        step = None
    if step is not None and step not in CRAFT_STEPS:
        raise ValueError(f"Công đoạn '{step}' không có trong danh sách")

    path = DATA / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    clip = next((c for c in catalog if c.get("id") == clip_id), None)
    if clip is None:
        raise KeyError(clip_id)
    clip["craft_step"] = step
    clip["craft_step_source"] = "manual" if step else None

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    load_catalog.cache_clear()
    live = get_clip(clip_id)
    return public_clip(live) if live else public_clip(clip)
