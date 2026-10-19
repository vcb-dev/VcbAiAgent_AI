"""Offline rule-based planner: script text -> ordered video parts following the template rhythm.

Used when no LLM credentials are configured (demo-safe). Output schema is identical to the
Claude planner so the rest of the pipeline does not care which planner ran.
"""
from footage_filename_parser import CRAFT_STEPS, slugify_vi
from video_templates import part_alt_roles
from vietnamese_text import estimate_speech_seconds, split_sentences

CLOSING_MARKERS = ("minh-la-huyk", "den-tu-vien-chi-bao")
HUYK_MARKERS = ("huyk", "minh", "toi", "cam-on", "quy-lam", "dong-vien", "binh-luan", "tin-rang", "comment",
                "tri-an", "cam-nhan", "ca-nhan", "doc-het", "anh-em", "mo-i-nguoi", "moi-nguoi")
CRAFT_MARKERS = ("che-tac", "tho", "gia-cong", "lam-lai", "lap-ghep", "chi-tiet", "cong-doan", "quy-trinh",
                 "sua-di-sua-lai", "xuong", "thao-ra", "lam-hon", "dinh-da", "danh-bong", "khoan", "do-khuon")
PRODUCT_MARKERS = ("chiec-nhan", "mau-nhan", "vong-co", "day-chuyen", "san-pham", "lap-lanh", "chat-lieu",
                   "moissanite", "vang-18k", "thiet-ke", "da-quy", "huy-chuong")
STEP_PHRASES = {  # explicit process phrases -> craft step
    "phac-thao": "thiet_ke", "ban-ve": "thiet_ke", "nung-chay": "nung_nau", "kho-lua": "nung_nau",
    "do-khuon": "do_khuon", "duc": "do_khuon", "dap-bua": "dap_can", "can-bac": "dap_can", "cua-long": "cua_cat",
    "han-noi": "han", "giua": "dua_mai", "khoan": "khoan", "da-chu": "gan_da_chu", "dinh-da": "dinh_da",
    "gan-da": "dinh_da", "lap-ghep": "dinh_da", "danh-bong": "danh_bong", "hoan-thien": "hoan_thien",
}


def _has(slug: str, marker: str) -> bool:
    """Whole-word match on a dash-joined slug ('tho' must not match 'thoi-gian')."""
    return f"-{marker}-" in f"-{slug}-"


def classify(sentence: str) -> str:
    slug = slugify_vi(sentence)
    score = {"huyk": sum(_has(slug, m) for m in HUYK_MARKERS), "craft": sum(_has(slug, m) for m in CRAFT_MARKERS),
             "product": sum(_has(slug, m) for m in PRODUCT_MARKERS)}
    best = max(score, key=score.get)
    return best if score[best] > 0 else "craft"


def explicit_step(sentence: str):
    slug = slugify_vi(sentence)
    return next((step for phrase, step in STEP_PHRASES.items() if _has(slug, phrase)), None)


def _part(role, text, template_id, source_audio=False):
    return {"role": role, "alt_roles": part_alt_roles(template_id, role), "vo_text": text,
            "craft_step": None, "est_seconds": estimate_speech_seconds(text) if text else 0.0,
            # Khối phát tiếng sẵn trong clip thay vì để máy đọc kịch bản (dùng cho outro).
            "source_audio": source_audio}


def _a4_roles(middle):
    roles = []
    for i, s in enumerate(middle):
        cls = classify(s)
        if i == 0:
            role = "huyk_talk"                       # template slot s2: HuyK right after product_hero
        elif i == len(middle) - 1 and cls != "huyk":
            role = "product_final"                   # reveal before outro
        elif cls == "huyk" and roles and roles[-1] != "huyk_talk":
            role = "huyk_talk"
        elif cls == "product":
            role = "product_hero"
        else:
            role = "craft"
        roles.append(role)
    return roles


def _a1_roles(middle):
    # content decides: questions / first-person lines -> HuyK on camera, descriptive lines -> illustration
    return ["huyk_talk" if ("?" in s or classify(s) == "huyk") else "content_illustration" for s in middle]


def assign_craft_steps(parts, available_steps):
    """Gán 4 ô chế tác trải đều quy trình 1→N, không nhảy lùi vì chữ trong kịch bản."""
    craft = [p for p in parts if p["role"] == "craft"]
    steps = sorted(available_steps, key=lambda s: CRAFT_STEPS[s][0])
    if not craft or not steps:
        return
    for i, p in enumerate(craft):
        idx = round(i * (len(steps) - 1) / max(len(craft) - 1, 1)) if len(craft) > 1 else 0
        p["craft_step"] = steps[idx]


def plan_with_rules(script: str, template_id: str, family: str, available_steps) -> list:
    sents = split_sentences(script)
    if not sents:
        return []
    # Outro phát tiếng sẵn trong clip nên không lấy câu nào của kịch bản; chỉ tuyến kiến thức
    # mới tách câu chào kết thành lời đọc riêng.
    closing = sents[-1] if family != "A4" and len(sents) > 1 and any(
        _has(slugify_vi(sents[-1]), m) for m in CLOSING_MARKERS) else None
    middle = sents[1:-1] if closing else sents[1:]
    first_role = "product_hero" if family == "A4" else "hook"
    roles = _a4_roles(middle) if family == "A4" else _a1_roles(middle)
    parts = [_part(first_role, sents[0], template_id)]
    for role, text in zip(roles, middle):
        if parts and text and estimate_speech_seconds(text) < 1.3:
            parts[-1]["vo_text"] += " " + text      # merge tiny sentences into the previous part
            parts[-1]["est_seconds"] = estimate_speech_seconds(parts[-1]["vo_text"])
            continue
        parts.append(_part(role, text, template_id))
    # Cảnh khoe thành phẩm là đổi vai của câu áp chót chứ không phải thêm một khối câm:
    # mọi khối đều phải có lời đọc thì tổng thời lượng video mới bằng tổng lời đọc.
    if family == "A4" and not any(p["role"] == "product_final" for p in parts) and len(parts) > 1:
        parts[-1]["role"] = "product_final"
        parts[-1]["alt_roles"] = part_alt_roles(template_id, "product_final")
    if family == "A4":
        parts.append(_part("outro", "", template_id, source_audio=True))
    elif closing:
        parts.append(_part("outro", closing, template_id))
    assign_craft_steps(parts, available_steps)
    for n, p in enumerate(parts, 1):
        p["part_id"] = f"p{n}"
        p["on_screen_text"] = " ".join(p["vo_text"].split()[:8]) if n == 1 else ""
    return parts
