"""Build mvp/data/ai-models-pricing.json: curated model options per AI-spend activity.

Source: data/research/ai-pricing-research-2026-10-10.json (prices checked on vendor pages, with URLs).
Adds per-activity usage assumptions so the UI can compute cost per video / per month.
"""
import json
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]
RESEARCH = MVP / "data" / "research" / "ai-pricing-research-2026-10-10.json"

ACTIVITIES = {  # key -> label, usage per unit of work, unit of work
    "vision_tagging": {"label": "Gắn nhãn footage mới (Media Hub)", "per": "clip mới", "usage": {"in_tok": 2800, "out_tok": 450}},
    "script_llm": {"label": "Viết / lập kế hoạch kịch bản", "per": "video", "usage": {"in_tok": 6000, "out_tok": 2000}},
    "tts": {"label": "Lồng tiếng VO (mỗi ngôn ngữ)", "per": "video", "usage": {"chars": 650}},
    "asr": {"label": "Phiên âm / kiểm phụ đề", "per": "video", "usage": {"minutes": 0.75}},
    "avatar_video": {"label": "HuyK nói (avatar / dịch khớp môi)", "per": "video", "usage": {"minutes": 0.067}},
    "video_gen": {"label": "Sinh b-roll / cảnh sản phẩm", "per": "video", "usage": {"seconds": 3}},
    "sfx_music": {"label": "Sinh SFX / nhạc bổ sung", "per": "video", "usage": {"minutes": 0.05, "generations": 0.02}},
    "embedding": {"label": "Embedding tìm kiếm", "per": "video", "usage": {"tokens": 2000}},
}

PICKS = {  # activity -> [(model substring, tier, recommended)]
    "vision_tagging": [("gemini-2.5-flash-lite", "rẻ", 0), ("gemini-3.5-flash-lite", "rẻ", 0), ("claude-haiku-5-5", "rẻ", 1),
                       ("gpt-6-luna", "rẻ", 0), ("gemini-3.8-flash", "cân bằng", 0), ("gpt-5.4-mini", "cân bằng", 0),
                       ("claude-sonnet-5-5", "cân bằng", 0), ("gemini-3.1-pro-preview", "cao cấp", 0), ("claude-opus-5-5", "cao cấp", 0),
                       ("gpt-6.1-sol", "cao cấp", 0)],
    "script_llm": [("claude-haiku-5-5", "rẻ", 0), ("gpt-6-luna", "rẻ", 0), ("gemini-3.8-flash", "cân bằng", 0),
                   ("claude-sonnet-5-5", "cân bằng", 0), ("gpt-6.1-sol", "cân bằng", 0), ("gemini-3.1-pro-preview", "cao cấp", 0),
                   ("claude-opus-5-5", "cao cấp", 1), ("claude-fable-5-1", "cao cấp", 0), ("gpt-6-astra", "cao cấp", 0)],
    "tts": [("gemini-3.8-flash-tts (per-1K-chars", "rẻ", 0), ("Chirp 3: HD voices", "rẻ", 0), ("tts-1-hd", "rẻ", 0),
            ("Eleven Flash v2.5", "cân bằng", 0), ("Eleven v4 Turbo", "cân bằng", 0), ("speech-2.8-turbo", "cân bằng", 0),
            ("Eleven v4 (model_id", "cao cấp", 1), ("speech-2.8-hd", "cao cấp", 0)],
    "asr": [("whisper-large-v3", "rẻ", 0), ("scribe_v2 (Scribe v2)", "cân bằng", 1), ("gpt-transcribe", "cân bằng", 0),
            ("gemini-3.5-transcribe", "cân bằng", 0), ("whisper-1", "cân bằng", 0)],
    "avatar_video": [("D-ID", "rẻ", 0), ("Video Translation - Speed", "rẻ", 0), ("Synthesia", "cân bằng", 0),
                     ("Hedra", "cân bằng", 0), ("Dubbing v2", "cân bằng", 0), ("Avatar IV (Enterprise", "cao cấp", 1)],
    "video_gen": [("grok_imagine_1_5_lite", "rẻ", 0), ("gen4_turbo", "rẻ", 0), ("veo-3.1-lite", "rẻ", 0),
                  ("kling-video/v3/standard", "rẻ", 0), ("MiniMax-H3", "cân bằng", 0), ("veo-3.1-fast", "cân bằng", 1),
                  ("gen4.5", "cân bằng", 0), ("seedance-2.0/text-to-vid", "cao cấp", 0), ("veo-3.1-generate-preview", "cao cấp", 0)],
    "sfx_music": [("lyria-3.5", "rẻ", 0), ("Sound Effects", "cân bằng", 1), ("Eleven Music", "cân bằng", 0)],
    "embedding": [("text-embedding-3-small", "rẻ", 1), ("voyage-multilingual-2", "cân bằng", 0), ("gemini-embedding-2", "cân bằng", 0)],
}
TESTED = {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}


def unit_cost(rows, usage):
    """USD for one unit of work (one clip / one video) given the vendor price rows of a model."""
    by_unit = {r["unit"]: r["price_usd"] for r in rows if r.get("price_usd") is not None}
    if "per_1M_input_tokens" in by_unit:
        return (usage.get("in_tok", 0) * by_unit["per_1M_input_tokens"] + usage.get("out_tok", 0) * by_unit.get("per_1M_output_tokens", 0)) / 1e6
    if "per_1K_chars" in by_unit:
        return usage.get("chars", 0) / 1000 * by_unit["per_1K_chars"]
    if "per_minute_audio" in by_unit:
        return usage.get("minutes", 0) * by_unit["per_minute_audio"]
    if "per_minute_video" in by_unit:
        return usage.get("minutes", 0) * by_unit["per_minute_video"]
    if "per_second_video" in by_unit:
        return usage.get("seconds", 0) * by_unit["per_second_video"]
    if "per_generation" in by_unit:
        return usage.get("generations", 0) * by_unit["per_generation"]
    if "per_1M_tokens" in by_unit:
        return usage.get("tokens", 0) * by_unit["per_1M_tokens"] / 1e6
    return None


def main():
    research = json.loads(RESEARCH.read_text(encoding="utf-8"))
    options = []
    for act, picks in PICKS.items():
        for needle, tier, rec in picks:
            rows = [r for r in research if r["activity"] == act and (needle in r["model"] or needle in r["provider"])]
            if not rows:
                print("missing:", act, needle)
                continue
            first = rows[0]
            cost = unit_cost(rows, ACTIVITIES[act]["usage"])
            options.append({"id": f"{act}:{needle}", "activity": act, "provider": first["provider"].strip(), "model": first["model"],
                            "tier": tier, "recommended": bool(rec), "tested_in_benchmark": any(t in first["model"] for t in TESTED),
                            "verified_price": all(r.get("verified") for r in rows), "vietnamese": first.get("vietnamese_support"),
                            "prices": [{"unit": r["unit"], "usd": r["price_usd"]} for r in rows],
                            "note": first.get("price_note", ""), "quality_notes": first.get("quality_notes", ""),
                            "source_url": first.get("source_url"), "checked_date": first.get("checked_date"),
                            "cost_per_unit_usd": None if cost is None else round(cost, 6)})
    out = {"checked_date": "2026-10-10", "activities": ACTIVITIES, "options": options}
    (MVP / "data" / "ai-models-pricing.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(options)} options written")


if __name__ == "__main__":
    main()
