"""Rank catalog clips for one video part: hard filters (role, product footage set, rights) then scoring.

Scopes: 'product' = the job's own footage set (mandatory for product/craft roles — no cross-SKU),
'shared' = VCB footage without SKU (HuyK, intro, outro), 'collected' = third-party footage (hook only).
"""
from catalog_store import STEP_LABELS_VI, load_catalog
from footage_filename_parser import CRAFT_STEPS
from vietnamese_text import keyword_tokens

ROLE_POOLS = {
    "hook": [("product_hero", "product"), ("product_final", "product"), ("craft_macro", "product"),
             ("hook_visual", "shared"), ("product_hero", "collected")],
    "product_hero": [("product_hero", "product"), ("product_final", "product"), ("craft_macro", "product")],
    "product_final": [("product_final", "product"), ("product_hero", "product")],
    "craft": [("craft", "product"), ("craft_macro", "product"), ("craft_pov", "product"), ("craft", "shared")],
    "huyk_talk": [("huyk_talk", "shared"), ("huyk_silent", "shared")],
    "content_illustration": [("product_hero", "collected"), ("hook_visual", "shared"), ("stock_action", "shared"),
                             ("product_final", "collected")],
    "outro": [("outro", "shared")],
}
SCOPE_PENALTY = {"product": 0.0, "shared": 0.08, "collected": 0.22}
MIN_SCORE = 0.30


def _in_scope(clip, scope, sku):
    if scope == "product":
        return bool(sku) and clip.get("product_set") == sku and clip["rights"] == "owned"
    if scope == "shared":
        return clip.get("product_set") is None and clip["rights"] == "owned"
    return clip["rights"] == "collected"


def _step_score(clip_step, want):
    if not want:
        return 0.5
    if clip_step == want:
        return 1.0
    if clip_step and abs(CRAFT_STEPS[clip_step][0] - CRAFT_STEPS[want][0]) <= 10:
        return 0.45
    return 0.0


def rank_candidates(part: dict, sku: str, used: set, limit: int = 8) -> list:
    tokens = keyword_tokens(part.get("vo_text", "") + " " + part.get("visual_intent", ""))
    pools = [(r, s, 0.0) for r, s in ROLE_POOLS.get(part["role"], [])]
    for alt in part.get("alt_roles", []):
        pools += [(r, s, 0.1) for r, s in ROLE_POOLS.get(alt, [])]   # 'X' alternatives, slight penalty
    best = {}
    for clip in load_catalog().values():
        for cat_role, scope, alt_pen in pools:
            conf = clip["roles"].get(cat_role, 0)
            if conf < 0.3 or not _in_scope(clip, scope, sku):
                continue
            if part["role"] != "outro" and clip["roles"].get("outro", 0) >= 0.8:
                continue                      # branded outro clips only belong at the end
            huyk_bonus = 0.15 if part["role"] in ("outro", "huyk_talk") and clip["tags"].get("huyk_present") else 0.0
            text = min(1.0, len(tokens & clip["_tokens"]) / 3.0)
            quality = (clip["tags"].get("aesthetic") or 3) / 5.0
            step = _step_score(clip.get("craft_step"), part.get("craft_step"))
            if part["role"] == "craft":
                score = 0.40 * step + 0.20 * conf + 0.15 * text + 0.20 * quality + 0.05 * ((clip["tags"].get("motion_level") or 1) / 3)
            else:
                score = 0.35 * conf + 0.30 * text + 0.35 * quality
            score += huyk_bonus
            score -= SCOPE_PENALTY[scope] + alt_pen + (0.3 if clip["id"] in used else 0)
            if score > best.get(clip["id"], {}).get("score", -1):
                best[clip["id"]] = {"kind": "clip", "clip_id": clip["id"], "score": round(score, 3),
                                    "role_used": cat_role, "scope": scope, "text_match": round(text, 2), "via_alt": alt_pen > 0, "reason": _reason(clip, scope, cat_role, conf, part)}
    ranked = sorted(best.values(), key=lambda c: -c["score"])
    return [c for c in ranked if c["score"] >= MIN_SCORE][:limit]


def _reason(clip, scope, role, conf, part):
    label ={"product": f"Đúng bộ footage {clip.get('product_set')}", "shared": "Footage chung VCB",
             "collected": "Footage sưu tầm — chỉ dùng làm hook/minh họa"}[scope]
    parts = [label, f"nhãn AI {role} {conf:.0%}", f"đẹp {clip['tags'].get('aesthetic') or '?'}/5"]
    if clip.get("craft_step"):
        same = clip["craft_step"] == part.get("craft_step")
        parts.insert(1, ("✓ " if same else "") + "công đoạn " + STEP_LABELS_VI[clip["craft_step"]])
    return " · ".join(parts)
