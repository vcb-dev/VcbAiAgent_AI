"""Merge media-index.json (technical + filename parse) with AI tags (data/tags/*.json) into catalog.json.

Rules (docs 02/03): filename craft step wins when parse confidence is high; third-party text/watermark
or the 'Sưu tầm' folder => rights 'collected'; a 'hoan_thien' step adds the product_final role.
"""
import json
import sys
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MVP / "src"))
from footage_filename_parser import CRAFT_STEPS  # noqa: E402
FOLDER_ROLE = {"V1": "hook_visual", "V2": "craft", "V4": "craft_pov", "V6": "product_final", "V7": "outro",
               "V8": "craft", "CAPCUT": "craft", "V5-TUQUAY": "craft", "V5-SUUTAM": "stock_action"}


def merge_roles(entry, tags):
    roles = {r["role"]: float(r.get("conf", 0.5)) for r in tags.get("roles", []) if r.get("role")}
    # role_hint do indexer suy ra từ đường dẫn; bảng FOLDER_ROLE chỉ còn để đọc các mã cũ (V1..V8).
    hint = entry.get("role_hint") if entry.get("role_hint") not in (None, "unknown") else None
    hint = hint or FOLDER_ROLE.get(entry["folder"])
    if entry["folder"] == "V3":
        hint = "huyk_talk" if entry["parsed"].get("type") == "KB" else "huyk_silent"
    if entry.get("rights") == "collected" and hint == "craft":
        hint = None                     # third-party clip: never treat as VCB craft footage
        roles.pop("craft", None)
    if hint:
        roles[hint] = max(roles.get(hint, 0), 0.8)
    if entry.get("craft_step") == "hoan_thien":
        roles["product_final"] = max(roles.get("product_final", 0), 0.85)
        roles["product_hero"] = max(roles.get("product_hero", 0), 0.7)
    if tags.get("huyk_present") and tags.get("person_speaking_to_camera"):
        roles["huyk_talk"] = max(roles.get("huyk_talk", 0), 0.75)
    return dict(sorted(roles.items(), key=lambda kv: -kv[1]))


def main():
    index = json.loads((MVP / "data" / "media-index.json").read_text(encoding="utf-8"))
    catalog = []
    for e in index:
        tag_path = MVP / "data" / "tags" / f"{e['id']}.json"
        tags = json.loads(tag_path.read_text(encoding="utf-8")) if tag_path.exists() else {}
        p = e["parsed"]
        use_filename = p.get("craft_step") and p.get("parse_confidence", 0) >= 0.75
        # a long take can hold several steps: for its segments a confident AI step overrides the file name
        if e.get("parent_id") and tags.get("craft_step") and tags.get("craft_step_conf", 0) >= 0.7:
            use_filename = False
        step = p["craft_step"] if use_filename else (tags.get("craft_step") if tags.get("craft_step_conf", 0) >= 0.5 else None)
        e["craft_step"] = step if step in CRAFT_STEPS else None   # never trust an AI value outside the taxonomy
        e["craft_step_source"] = "filename" if use_filename else ("ai" if step else None)
        third_party = tags.get("text_or_watermark") == "third_party"
        if third_party or e["folder"] == "V5-SUUTAM":
            e["rights"], e["product_set"] = "collected", None
        dur = e["tech"]["duration"]
        lo = max(0.0, float(tags.get("usable_from_s", 0) or 0))
        hi = min(dur, float(tags.get("usable_to_s", dur) or dur))
        if hi - lo < 1.0:
            lo, hi = 0.0, dur
        e["usable"] = [round(lo, 2), round(hi, 2)]
        default_best = e.get("best_moment_s", (lo + hi) / 2)      # long-clip segments: computed from signals
        e["best_moment_s"] = min(max(float(tags.get("best_moment_s", default_best) or 0), lo), hi)
        e["roles"] = merge_roles(e, tags)
        e["tags"] = {k: tags.get(k) for k in ("shot_size", "camera", "subject", "huyk_present", "person_speaking_to_camera",
                                              "product_visible", "product_type", "metal", "stone_color", "lighting",
                                              "text_or_watermark", "motion_level", "aesthetic")}
        e["description_vi"] = tags.get("description_vi", "")
        e["keywords_vi"] = tags.get("keywords_vi", [])
        e["tagged"] = bool(tags)
        catalog.append(e)
    out = MVP / "data" / "catalog.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"catalog: {len(catalog)} clips, tagged {sum(c['tagged'] for c in catalog)}, "
          f"collected {sum(c['rights'] == 'collected' for c in catalog)}")


if __name__ == "__main__":
    main()
