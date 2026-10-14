"""Video templates (docs/video-automation/04 §3) reduced to what the MVP planner needs.

"X" in the client diagrams = interchangeable sources -> alt_roles on a part.
"""

# Per-role timing rules (seconds): min part length, preferred max shot length, min usable clip length
ROLE_TIMING = {
    "hook": {"min": 3.0, "shot_max": 2.2},
    "product_hero": {"min": 2.5, "shot_max": 2.6},
    "product_final": {"min": 4.0, "shot_max": 3.0},
    "huyk_talk": {"min": 2.5, "shot_max": 4.5},
    "craft": {"min": 2.5, "shot_max": 2.2},
    "content_illustration": {"min": 3.0, "shot_max": 3.0},
    "outro": {"min": 3.0, "shot_max": 5.0},
}

TEMPLATES = {
    "A4_v1": {"label": "A4 v1 · Quá trình chế tác (1 nguồn/slot)", "family": "A4", "alt_roles": {}},
    "A4_v2": {"label": "A4 v2 · Chế tác + 'X' HuyK/cận thao tác", "family": "A4",
              "alt_roles": {"craft": ["huyk_talk"], "huyk_talk": ["craft"]}},
    "A4_v3": {"label": "A4 v3 · Sản phẩm 'X' HuyK (ít chế tác)", "family": "A4",
              "alt_roles": {"product_hero": ["huyk_talk"], "huyk_talk": ["product_hero"], "craft": ["product_hero"]}},
    "A1_A3": {"label": "A1–A3 · Kiến thức / câu chuyện", "family": "A1_A3",
              "alt_roles": {"content_illustration": ["huyk_talk"], "huyk_talk": ["content_illustration"]}},
}

ROLE_LABELS_VI = {
    "hook": "Hook mở đầu", "product_hero": "Sản phẩm", "product_final": "Sản phẩm hoàn thiện",
    "huyk_talk": "HuyK nói", "craft": "Chế tác", "content_illustration": "Nội dung minh họa", "outro": "Outro",
}

# Roles whose footage MUST come from the job's own product footage set (no cross-mapping between SKUs)
PRODUCT_SET_ROLES = {"product_hero", "product_final", "craft"}


def template_or_default(template_id: str, has_product: bool) -> str:
    if template_id in TEMPLATES:
        return template_id
    return "A4_v1" if has_product else "A1_A3"


def part_alt_roles(template_id: str, role: str) -> list:
    return TEMPLATES.get(template_id, {}).get("alt_roles", {}).get(role, [])
