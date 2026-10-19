"""Claude planner (production path): script -> parts via structured outputs.

Enabled only when Anthropic credentials are present (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN).
Same output schema as script_planner_rules.plan_with_rules so the pipeline is planner-agnostic.
"""
import json
import os

from app_paths import PLANNER_MODEL
from footage_filename_parser import CRAFT_STEPS
from video_templates import part_alt_roles
from vietnamese_text import estimate_speech_seconds

ROLES = ["hook", "product_hero", "product_final", "huyk_talk", "craft", "content_illustration", "outro"]
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["parts"],
    "properties": {"parts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["role", "vo_text", "on_screen_text", "visual_intent", "craft_step"],
        "properties": {"role": {"type": "string", "enum": ROLES}, "vo_text": {"type": "string"},
                       "on_screen_text": {"type": "string"}, "visual_intent": {"type": "string"},
                       "craft_step": {"type": "string", "enum": ["none", *CRAFT_STEPS.keys()]}}}}},
}
SYSTEM = ("Bạn là đạo diễn dựng video ngắn 9:16 cho thương hiệu trang sức Viễn Chí Bảo (KOL HuyK). "
          "Chia kịch bản thành các phần theo template, giữ NGUYÊN VĂN lời đọc theo đúng thứ tự, "
          "không bịa thông tin sản phẩm, công đoạn chế tác không đi lùi.")


def claude_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _prompt(script, family, steps):
    rhythm = ("product_hero (cảnh sản phẩm) → HuyK nói → chế tác → chế tác → HuyK → ... → product_final → outro (mỗi phần 3–6s). Không dùng role hook."
              if family == "A4" else "hook → nội dung minh họa / HuyK nói xen kẽ (6–12s) → HuyK kết → outro")
    first = ("Phần 1 là product_hero, on_screen_text ≤ 8 từ; các phần khác để rỗng."
             if family == "A4" else "Phần 1 có on_screen_text ≤ 8 từ (hook); các phần khác để rỗng.")
    return (f"Template: {family}: {rhythm}.\nCông đoạn có footage cho sản phẩm này: {', '.join(steps) or 'không có'}.\n"
            f"{first} craft_step = 'none' nếu không phải chế tác. "
            f"Câu 'Mình là HuyK đến từ Viễn Chí Bảo' (nếu có) thuộc phần outro.\n\nKịch bản:\n{script}")


def plan_with_claude(script: str, template_id: str, family: str, available_steps) -> list:
    import anthropic   # imported lazily so the offline demo works without the SDK configured

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=PLANNER_MODEL, max_tokens=16000, system=SYSTEM,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": _prompt(script, family, available_steps)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the planning request")
    text = next(b.text for b in response.content if b.type == "text")
    parts = json.loads(text)["parts"]
    for n, p in enumerate(parts, 1):
        p["part_id"] = f"p{n}"
        p["craft_step"] = None if p["craft_step"] == "none" else p["craft_step"]
        p["alt_roles"] = part_alt_roles(template_id, p["role"])
        p["est_seconds"] = estimate_speech_seconds(p["vo_text"]) if p["vo_text"] else 0.0
    return parts
