"""Read-only access to the tagged footage catalog (simulates the Media Hub Catalog API)."""
import json
from functools import lru_cache

from app_paths import DATA
from footage_filename_parser import CRAFT_STEPS
from vietnamese_text import keyword_tokens

STEP_LABELS_VI = {
    "thiet_ke": "Thiết kế", "chuan_bi_nguyen_lieu": "Chuẩn bị nguyên liệu", "nung_nau": "Nung chảy",
    "do_khuon": "Đổ khuôn", "dap_can": "Đập/cán phôi", "cua_cat": "Cưa cắt", "han": "Hàn",
    "dua_mai": "Giũa mài", "khoan": "Khoan", "gan_da_chu": "Gắn đá chủ", "dinh_da": "Đính đá",
    "danh_bong": "Đánh bóng", "hoan_thien": "Hoàn thiện",
}


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    clips = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    for c in clips:
        text = " ".join([c.get("description_vi", ""), " ".join(c.get("keywords_vi", [])),
                         STEP_LABELS_VI.get(c.get("craft_step") or "", "")])
        c["_tokens"] = keyword_tokens(text)
    return {c["id"]: c for c in clips}


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
                                  "has_final": False})
        s["clips"] += 1
        if c.get("craft_step") and c["craft_step"] != "hoan_thien":
            s["steps"].add(c["craft_step"])
        if "product_final" in c["roles"]:
            s["has_final"] = True
    out = []
    for s in sorted(sets.values(), key=lambda x: -x["clips"]):
        steps = sorted(s["steps"], key=lambda st: CRAFT_STEPS[st][0])
        out.append({**s, "steps": steps, "step_labels": [STEP_LABELS_VI[st] for st in steps]})
    return out


def available_steps(sku: str) -> list:
    for s in product_sets():
        if s["sku"] == sku:
            return s["steps"]
    return []
