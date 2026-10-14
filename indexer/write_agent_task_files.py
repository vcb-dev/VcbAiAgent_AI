"""Write task files for the AI tagging swarm (catalog) and the model benchmark (gold set).

Outputs (in the session scratchpad passed as argv[1]):
  tagging/batch_<n>.md       - catalog tagging batches WITH filename hints (production mode)
  tagging/segments_<n>.md    - long-clip candidates: ONE batch sheet (6 candidates x 2 frames) per AI call
  bench/tagging_gold.md      - 12-clip gold set WITHOUT filename hints (vision-only test)
  bench/gold_truth.json      - ground truth for the gold set (never shown to models)
"""
import json
import sys
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]      # VCB_AI
OUT = Path(sys.argv[1])

TAXONOMY = """## Taxonomy (dùng đúng giá trị enum)
roles (đa trị, mỗi role có conf 0..1): hook_visual (cảnh mở gây tò mò), product_hero (sản phẩm cận/xoay/trên tay),
product_final (sản phẩm hoàn thiện, reveal), huyk_talk (HuyK nói tại hình, thấy miệng), huyk_silent (HuyK xuất hiện không nói),
craft (thao tác chế tác), craft_macro (cận cực gần chi tiết), craft_pov (góc nhìn tay thợ), stock_action (hành động chung không gắn sản phẩm),
content_illustration (hình minh họa chủ đề), outro (kết thương hiệu có logo).
craft_step (1 giá trị hoặc null): thiet_ke (vẽ phác thảo/thiết kế), chuan_bi_nguyen_lieu (cân/đổ hạt kim loại),
nung_nau (khò lửa nung chảy kim loại trong chén), do_khuon (rót kim loại nóng chảy vào khuôn), dap_can (búa đập/cán thỏi, tạo phôi),
cua_cat (cưa lọng, cắt phần thừa), han (hàn nối điểm nhỏ), dua_mai (giũa, mài định hình), khoan (khoan lỗ/hốc đá/chi tiết),
gan_da_chu (gắn viên đá chủ lớn vào ổ), dinh_da (đính đá nhỏ/đá viền, soi kiểm đá), danh_bong (đánh bóng, làm sáng),
hoan_thien (sản phẩm đã xong: trưng bày, đeo thử, xoay).
shot_size: extreme_close|close|medium|wide · camera: static|handheld|pov|gimbal
subject (đa trị): hands|huyk_face|person|product|tool|fire|metal|stone|workshop|paper
product_type: nhan|day_chuyen|lac_tay|bong_tai|khac|none · metal: bac|vang|vang_trang|unknown
lighting: good|dark|overexposed|mixed · text_or_watermark: none|own_logo|third_party|subtitle_text
motion_level: 0..3 · aesthetic: 1..5 (đẹp để lên video quảng cáo trang sức)
"""

SCHEMA = """## Output JSON cho MỖI clip
{"id": "...", "roles": [{"role": "...", "conf": 0.9}], "craft_step": "... hoặc null", "craft_step_conf": 0.8,
 "shot_size": "...", "camera": "...", "subject": ["..."], "huyk_present": true/false, "person_speaking_to_camera": true/false,
 "product_visible": true/false, "product_type": "...", "metal": "...", "stone_color": ["xanh lá"], "lighting": "...",
 "text_or_watermark": "...", "motion_level": 2, "aesthetic": 4, "best_moment_s": 6.0, "usable_from_s": 0.5, "usable_to_s": 14.0,
 "description_vi": "mô tả ≤ 30 từ, tiếng Việt có dấu", "keywords_vi": ["5-10 từ khóa tiếng Việt"]}
best_moment_s / usable_*: đọc từ mốc thời gian in trên từng frame của contact sheet.
"""

HUYK_REF = MVP / "media" / "sheets" / "c_0a8d1c7d.jpg"
INTRO = f"""Bạn là chuyên viên phân loại footage xưởng kim hoàn (thương hiệu Viễn Chí Bảo, KOL HuyK).
Mỗi clip có 1 contact sheet 12 frame (4×3, mốc thời gian in góc trên trái). Dùng Read tool để xem ảnh.
Ảnh tham chiếu HuyK (người đàn ông nói chuyện trong clip này là HuyK): {HUYK_REF}
Chỉ dùng giá trị enum. Không bịa SKU. Nếu không chắc, giảm conf.
"""

GOLD = {  # id -> ground truth (from verified file names / folders / manual check)
    "c_7ad267ac": {"role": "craft", "craft_step": "gan_da_chu", "huyk_present": False},
    "c_fd886a1a": {"role": "craft", "craft_step": "dap_can", "huyk_present": False},
    "c_41a68bc5": {"role": "craft", "craft_step": "nung_nau", "huyk_present": False},
    "c_f74a8bd7": {"role": "craft", "craft_step": "do_khuon", "huyk_present": False},
    "c_9746542f": {"role": "craft", "craft_step": "cua_cat", "huyk_present": False},
    "c_945a3887": {"role": "craft", "craft_step": "han", "huyk_present": False},
    "c_a2dbfeee": {"role": "craft", "craft_step": "khoan", "huyk_present": False},
    "c_37e95497": {"role": "craft", "craft_step": "danh_bong", "huyk_present": False},
    "c_8a5fc438": {"role": "product_final", "craft_step": "hoan_thien", "huyk_present": False},
    "c_0a8d1c7d": {"role": "huyk_talk", "craft_step": None, "huyk_present": True},
    "c_840577db": {"role": "outro", "craft_step": None, "huyk_present": True, "text_or_watermark": "own_logo"},
    "c_71b6151f": {"role": "product_hero", "craft_step": None, "huyk_present": False, "text_or_watermark": "third_party"},
}


SEGMENT_SCHEMA = """## Output JSON cho MỖI ứng viên (không cần best_moment/usable: code đã tính)
{"id": "...", "roles": [{"role": "...", "conf": 0.9}], "craft_step": "... hoặc null", "craft_step_conf": 0.8,
 "shot_size": "...", "camera": "...", "subject": ["..."], "huyk_present": true/false, "person_speaking_to_camera": true/false,
 "product_visible": true/false, "product_type": "...", "metal": "...", "stone_color": ["..."], "lighting": "...",
 "text_or_watermark": "...", "motion_level": 2, "aesthetic": 4, "description_vi": "≤ 30 từ", "keywords_vi": ["..."]}
"""


def segment_batch_prompt(sheet: str, segs: list[dict], out_hint: str) -> str:
    """One AI call labels up to 6 candidate windows cut from the same long take (docs 03 §3.1)."""
    first = segs[0]
    lines = "\n".join(f"- id={s['id']} · mã trên ảnh={s['id'].rsplit('_', 1)[1].upper()} · đoạn gốc "
                      f"{s['source_range'][0]}–{s['source_range'][1]}s" for s in segs)
    return (INTRO.replace("Mỗi clip có 1 contact sheet 12 frame (4×3, mốc thời gian in góc trên trái).",
                          "Contact sheet dưới đây gồm NHIỀU ứng viên cắt từ CÙNG một clip dài: các ô liền nhau cùng mã là cùng một ứng viên, "
                          "xếp theo thời gian (một ô là khoảnh khắc đẹp nhất); mã ứng viên + mốc giây in góc trên trái.")
            + f"Gợi ý từ tên file gốc (cả clip dài, có thể chứa nhiều công đoạn): file=\"{first.get('name', '')}\" · "
              f"parsed_sku={first.get('parsed', {}).get('sku')} · parsed_step={first.get('parsed', {}).get('craft_step')}\n"
              "Gắn nhãn TỪNG ứng viên độc lập theo hình của chính nó.\n\n"
            + TAXONOMY + SEGMENT_SCHEMA + f"\n## Sheet: {sheet}\n## Ứng viên\n{lines}\n\n{out_hint}\n")


def clip_line(e, with_hints):
    base = f"- id={e['id']} · sheet={MVP / e['sheet']} · duration={e['tech']['duration']}s"
    if not with_hints:
        return base
    p = e["parsed"]
    return (f"{base} · folder={e['folder']} · role_hint={e['role_hint']} · file=\"{e['name']}\""
            f" · parsed_sku={p['sku']} · parsed_step={p['craft_step']}")


def main():
    index = json.loads((MVP / "data" / "media-index.json").read_text(encoding="utf-8"))
    (OUT / "tagging").mkdir(parents=True, exist_ok=True)
    (OUT / "bench").mkdir(parents=True, exist_ok=True)
    tags_dir = MVP / "data" / "tags"
    tags_dir.mkdir(parents=True, exist_ok=True)
    segs = [e for e in index if e.get("parent_id")]
    index = [e for e in index if not e.get("parent_id")]
    by_sheet = {}
    for e in segs:
        by_sheet.setdefault(e["sheet"], []).append(e)
    for n, (sheet, group) in enumerate(by_sheet.items(), 1):
        hint = f"Ghi MỖI ứng viên ra 1 file: {tags_dir}/<id>.json (chỉ JSON, UTF-8)."
        (OUT / "tagging" / f"segments_{n}.md").write_text(segment_batch_prompt(str(MVP / sheet), group, hint), encoding="utf-8")
    batches = [index[i:i + 10] for i in range(0, len(index), 10)]
    for n, batch in enumerate(batches, 1):
        body = (INTRO + "Gợi ý từ tên file/thư mục là quy chuẩn NAS của khách (thường đúng, nhưng hãy kiểm bằng hình).\n\n"
                + TAXONOMY + SCHEMA + f"\n## Clips (batch {n})\n" + "\n".join(clip_line(e, True) for e in batch)
                + f"\n\nGhi MỖI clip ra 1 file: {tags_dir}/<id>.json (chỉ JSON, UTF-8).\n")
        (OUT / "tagging" / f"batch_{n}.md").write_text(body, encoding="utf-8")
    gold = [e for e in index if e["id"] in GOLD]
    body = (INTRO + "Đây là bài test chỉ dựa vào hình ảnh: không có tên file hay thư mục.\n\n" + TAXONOMY + SCHEMA
            + "\n## Clips\n" + "\n".join(clip_line(e, False) for e in gold)
            + "\n\nGhi KẾT QUẢ thành 1 file JSON array (mỗi phần tử là object clip ở trên) tại đường dẫn được giao.\n")
    (OUT / "bench" / "tagging_gold.md").write_text(body, encoding="utf-8")
    (OUT / "bench" / "gold_truth.json").write_text(json.dumps(GOLD, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(batches)} catalog batches, {len(by_sheet)} long-clip segment batches, {len(gold)} gold clips")


if __name__ == "__main__":
    main()
