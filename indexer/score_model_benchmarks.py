"""Score the Claude model benchmark (Haiku / Sonnet / Opus) on two AI-spend tasks of the system.

T1 vision tagging: 12 gold clips, contact sheet only (no filename hints) vs verified ground truth.
T2 script planning: 3 real VCB scripts -> part plans, checked by deterministic rules.
Output: mvp/data/benchmark-results.json (consumed by the MVP "So sánh model AI" tab and the report).
"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]
B = MVP / "data" / "benchmarks"
MODELS = ["haiku", "sonnet", "opus"]
MODEL_IDS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
PRICE = {"haiku": (0.10, 0.50), "sonnet": (2.0, 10.0), "opus": (4.0, 20.0)}   # USD / 1M in, out (Anthropic, 2026-10)
STEP_ORDER = {s: i for i, s in enumerate("thiet_ke chuan_bi_nguyen_lieu nung_nau do_khuon dap_can cua_cat han dua_mai "
                                         "khoan gan_da_chu dinh_da danh_bong hoan_thien".split())}
ROLE_OK = {"craft": {"craft", "craft_macro", "craft_pov"}, "product_final": {"product_final", "product_hero"},
           "product_hero": {"product_hero", "product_final"}, "huyk_talk": {"huyk_talk"}, "outro": {"outro"}}
# API cost model per unit of work (same assumptions for every model): 1 contact sheet ≈ 1,600 image tokens
TAG_TOKENS = (2800, 450)       # per clip: image + instructions, JSON output
PLAN_TOKENS = (3500, 2500)     # per script: task + script, plan JSON (+ thinking)


def norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def score_tagging(model, gold):
    rows = {r["id"]: r for r in json.loads((B / f"tag_{model}.json").read_text(encoding="utf-8"))}
    role = step = step_near = huyk = text = n_step = n_text = 0
    misses = []
    for cid, g in gold.items():
        r = rows.get(cid, {})
        top = max(r.get("roles", [{}]), key=lambda x: x.get("conf", 0)).get("role")
        role += top in ROLE_OK[g["role"]]
        huyk += bool(r.get("huyk_present")) == g["huyk_present"]
        if g.get("craft_step"):
            n_step += 1
            got = r.get("craft_step")
            step += got == g["craft_step"]
            step_near += got in STEP_ORDER and abs(STEP_ORDER[got] - STEP_ORDER[g["craft_step"]]) <= 1
            if got != g["craft_step"]:
                misses.append(f"{cid}: {g['craft_step']} → {got}")
        if g.get("text_or_watermark"):
            n_text += 1
            text += r.get("text_or_watermark") == g["text_or_watermark"]
    n = len(gold)
    return {"role_acc": round(role / n, 3), "craft_step_acc": round(step / n_step, 3),
            "craft_step_within_1": round(step_near / n_step, 3), "huyk_acc": round(huyk / n, 3),
            "watermark_logo_acc": round(text / n_text, 3), "step_misses": misses,
            "api_cost_per_1000_clips_usd": round(1000 * (TAG_TOKENS[0] * PRICE[model][0] + TAG_TOKENS[1] * PRICE[model][1]) / 1e6, 3)}


def score_plan(plan, script_text, family):
    parts = plan.get("parts", [])
    joined = norm(" ".join(p.get("vo_text", "") for p in parts))
    verbatim = SequenceMatcher(None, joined, norm(script_text)).ratio()
    steps = [STEP_ORDER[p["craft_step"]] for p in parts if p.get("craft_step") in STEP_ORDER]
    checks = {"verbatim": verbatim >= 0.98, "hook_first": parts and parts[0].get("role") in ("hook_visual", "product_hero"),
              "craft_monotonic": steps == sorted(steps), "has_huyk": any(p.get("role") == "huyk_talk" for p in parts)}
    if family == "A4":
        checks["outro_last"] = bool(parts) and parts[-1].get("role") == "outro" and "Mình là HuyK" in parts[-1].get("vo_text", "")
        finals = [p for p in parts if p.get("role") == "product_final"]
        checks["gap_detected"] = bool(finals) and all((p.get("needs_generation") or {}).get("type") == "product_video" for p in finals)
    else:
        content = [p for p in parts if p.get("role") == "content_illustration"]
        checks["gap_detected"] = bool(content) and all((p.get("needs_generation") or {}).get("type") in ("illustration", "broll")
                                                        for p in content)
    return {"parts": len(parts), "verbatim_ratio": round(verbatim, 3), **{k: bool(v) for k, v in checks.items()},
            "score": round(100 * sum(bool(v) for v in checks.values()) / len(checks))}


def load_scripts():
    text = (B / "planning_task.md").read_text(encoding="utf-8")
    blocks = re.findall(r"### script_id = (\S+)[^\n]*\n(.+?)(?=\n### |\Z)", text, re.S)
    return {sid: norm(body) for sid, body in blocks}


def main():
    gold = json.loads((B / "gold_truth.json").read_text(encoding="utf-8"))
    stats = json.loads((B / "run_stats.json").read_text(encoding="utf-8"))
    scripts = load_scripts()
    out = {"date": "2026-10-10", "models": {}, "assumptions": {"tag_tokens_per_clip": TAG_TOKENS, "plan_tokens_per_script": PLAN_TOKENS,
                                                                 "price_usd_per_1M": PRICE}}
    for m in MODELS:
        plans = {p["script_id"]: p for p in json.loads((B / f"plan_{m}.json").read_text(encoding="utf-8"))}
        plan_scores = {sid: score_plan(plans.get(sid, {}), txt, "A1_A3" if sid == "A2" else "A4") for sid, txt in scripts.items()}
        out["models"][m] = {"model_id": MODEL_IDS[m], "tagging": score_tagging(m, gold), "planning": plan_scores,
                            "planning_avg_score": round(sum(s["score"] for s in plan_scores.values()) / len(plan_scores)),
                            "api_cost_per_1000_scripts_usd": round(1000 * (PLAN_TOKENS[0] * PRICE[m][0] + PLAN_TOKENS[1] * PRICE[m][1]) / 1e6, 2),
                            "run_stats": {"tagging": stats["tagging"].get(m), "planning": stats["planning"].get(m)}}
    (MVP / "data" / "benchmark-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for m, r in out["models"].items():
        t = r["tagging"]
        print(m, "| role", t["role_acc"], "step", t["craft_step_acc"], "±1", t["craft_step_within_1"], "huyk", t["huyk_acc"],
              "wm", t["watermark_logo_acc"], "| plan", r["planning_avg_score"], {k: v["score"] for k, v in r["planning"].items()})
        print("   misses:", t["step_misses"])


if __name__ == "__main__":
    main()
