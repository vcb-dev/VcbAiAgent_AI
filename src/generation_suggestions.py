"""Suggest AI generation options for a video part (docs 08 AI Asset Studio), with cost and guardrails.

The MVP produces a generation *spec* (provider, prompt, duration, estimated cost) and shows a labelled
placeholder in the video; the real provider call happens in the production AI Asset Studio.
Guardrail: never generate the craft process of a specific SKU — request a reshoot instead.
"""
import math

from catalog_store import STEP_LABELS_VI
from pricing_store import recommended, short_name, unit_price

PRODUCT_ROLES = {"hook", "product_hero", "product_final"}


def _video_gen(part, prompt, label_type, duration, guardrail):
    opt = recommended("video_gen")
    secs = min(8, max(4, math.ceil(duration)))
    return {"kind": "gen", "type": label_type, "provider": short_name(opt), "prompt": prompt, "duration": secs,
            "est_cost_usd": round(secs * unit_price(opt, "per_second_video"), 3), "guardrail": guardrail}


def generation_options(part: dict, product_name: str, sku: str, duration: float) -> list:
    role, text = part["role"], part.get("vo_text", "")
    options = []
    if role in PRODUCT_ROLES and sku:
        prompt = (f"Image-to-video từ ảnh thật của {product_name} ({sku}): macro, xoay chậm, ánh sáng studio ấm, "
                  f"nền tối, giữ nguyên màu đá và hình dáng, 9:16, không chữ, không logo.")
        options.append(_video_gen(part, prompt, "product_video", duration,
                                  "Bắt buộc duyệt độ trung thực sản phẩm (màu đá, số chấu, kim loại) trước khi dùng."))
    if role == "huyk_talk" or "huyk_talk" in part.get("alt_roles", []):
        opt = recommended("avatar_video")
        minutes = max(duration, 3.0) / 60
        options.append({"kind": "gen", "type": "huyk_avatar", "provider": short_name(opt),
                        "prompt": f"Avatar HuyK nói tại hình (giọng clone, khớp môi): «{text or '...'}»",
                        "duration": round(max(duration, 3.0), 1),
                        "est_cost_usd": round(minutes * unit_price(opt, "per_minute_video"), 3),
                        "guardrail": "Chỉ nói đúng câu trong kịch bản đã duyệt."})
    if role == "craft":
        step = STEP_LABELS_VI.get(part.get("craft_step") or "", "công đoạn chế tác")
        options.append({"kind": "gen", "type": "shoot_request", "provider": "Phiếu quay bổ sung (đội quay VCB)",
                        "prompt": f"Quay bổ sung {product_name or sku}: {step} — 3 góc cận (macro tay thợ, cận dụng cụ, toàn bàn thợ).",
                        "duration": round(duration, 1), "est_cost_usd": 0.0,
                        "guardrail": "Không dùng AI để tạo quá trình chế tác của sản phẩm cụ thể."})
    if role in ("content_illustration", "hook") and not sku:
        prompt = f"B-roll minh họa 9:16, điện ảnh, ánh sáng ấm, không chữ: {text[:140]}"
        options.append(_video_gen(part, prompt, "illustration", duration,
                                  "Không tái tạo người thật, logo hay thương hiệu khác."))
    for n, o in enumerate(options, 1):
        o["gen_id"] = f"{part['part_id']}_g{n}"
    return options


def vo_estimate(total_chars: int) -> dict:
    """Production VO cost (recommended TTS) for the whole script, one language."""
    opt = recommended("tts")
    return {"provider": short_name(opt), "chars": total_chars,
            "est_cost_usd": round(total_chars / 1000 * unit_price(opt, "per_1K_chars"), 4)}
