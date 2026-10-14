"""Parse VCB NAS file names (quy chuẩn đặt tên NAS) into structured metadata.

Handles the official pattern  YYMMDD_<TYPE>_<KOC>_<SKU>_<Product>_<Action>_<Staff>_<STT>
plus the real-world deviations found in the sample library (SKU joined to product slug,
action after staff code, accented names with spaces, numbered generic clips, junk names).
"""
import re
import unicodedata
from pathlib import Path

TYPE_CODES = {"KB", "CT", "CTX", "ST", "LIVE", "OT", "IT"}
KOC_CODES = {"HK", "NN", "NB", "CB", "HC"}
SKU_RE = re.compile(r"^([A-Z]{1,2}\d{3,6}[A-Z]?(?:-(?:[A-Z]{1,3}|\d{1,3}))*)(?:-(.+))?$")
STAFF_RE = re.compile(r"^[A-Z]{2,4}\d{2}$")
DATE_RE = re.compile(r"^\d{6}$")

# Craft step taxonomy (docs/video-automation/02 §3.2): step_id -> (order, aliases)
CRAFT_STEPS = {
    "thiet_ke": (10, ["thiet-ke", "ve-phac-thao"]),
    "chuan_bi_nguyen_lieu": (20, ["do-nguyen-lieu", "can-bac"]),
    "nung_nau": (30, ["danh-lua", "nung-bac", "tha-bac-vao-bat"]),
    "do_khuon": (40, ["do-khuon"]),
    "dap_can": (50, ["dap-thanh-bac", "dap-tron-thanh-bac", "bua-sao-su"]),
    "cua_cat": (60, ["cua-bac-thua"]),
    "han": (70, ["han-noi"]),
    "dua_mai": (80, ["dua", "dua-hoc-da", "dua-mat-chau-da"]),
    "khoan": (90, ["khoan-hoc-da", "khoan-chi-tiet"]),
    "gan_da_chu": (100, ["gan-da-chu"]),
    "dinh_da": (110, ["dinh-da", "dinh-da-vien", "gan-da-to", "nhin-da"]),
    "danh_bong": (120, ["danh-bong", "lam-sang-bac"]),
    "hoan_thien": (130, ["hoan-thien", "hoan-thanh"]),
}
ALIAS_TO_STEP = {alias: step for step, (_, aliases) in CRAFT_STEPS.items() for alias in aliases}


def slugify_vi(text: str) -> str:
    """Lowercase ASCII slug without Vietnamese diacritics: 'Gắn đá chủ' -> 'gan-da-chu'."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def craft_step_from_action(action: str):
    """Map an action slug/phrase to (step_id, order) or (None, None)."""
    if not action:
        return None, None
    slug = slugify_vi(action)
    slug = re.sub(r"^\d+-", "", slug)          # "12-dua-15" -> "dua-15"
    slug = re.sub(r"-\d+$", "", slug)          # "dua-15" -> "dua"
    step = ALIAS_TO_STEP.get(slug)
    if step:
        return step, CRAFT_STEPS[step][0]
    return None, None


def parse_filename(filename: str) -> dict:
    """Return parsed fields + parse_confidence (0..1) for one file name."""
    stem = unicodedata.normalize("NFC", Path(filename).stem).strip()
    tokens = [t.strip() for t in stem.split("_") if t.strip()]
    out = {"raw": stem, "date": None, "type": None, "koc": None, "sku": None,
           "product": None, "action": None, "staff": None, "stt": None}
    rest = []
    for tok in tokens:
        up = tok.upper()
        if out["date"] is None and DATE_RE.match(tok):
            out["date"] = tok
        elif out["type"] is None and up in TYPE_CODES:
            out["type"] = up
        elif out["koc"] is None and up in KOC_CODES:
            out["koc"] = up
        elif out["sku"] is None and SKU_RE.match(tok):
            m = SKU_RE.match(tok)
            out["sku"] = m.group(1)
            if m.group(2):
                out["product"] = m.group(2)
        elif out["staff"] is None and STAFF_RE.match(tok):
            out["staff"] = tok
        else:
            rest.append(tok)
    # trailing sequence number: "2", "(4)", "05"
    stt_tokens = [t for t in rest if re.fullmatch(r"\(?\d{1,3}\)?", t)]
    if stt_tokens:
        out["stt"] = int(stt_tokens[-1].strip("()"))
        rest = [t for t in rest if t not in stt_tokens]
    # remaining text tokens: product name first (if not set), then action
    for tok in rest:
        step, _ = craft_step_from_action(tok)
        if step and out["action"] is None:
            out["action"] = tok
        elif out["product"] is None and out["sku"]:
            out["product"] = tok
        elif out["action"] is None:
            out["action"] = tok
    if out["sku"] is None and out["action"] is None and rest:
        out["action"] = rest[0]   # numbered generic clip, e.g. "12. DUA-15"
    step, order = craft_step_from_action(out["action"] or stem)
    out["craft_step"], out["craft_order"] = step, order
    expected = ["date", "sku", "action", "staff"]
    out["parse_confidence"] = round(sum(1 for k in expected if out[k]) / len(expected), 2)
    return out
