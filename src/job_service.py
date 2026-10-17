"""Job lifecycle: plan -> VO -> candidates -> generation suggestions -> timeline -> background render.

Jobs live in memory (guarded by one re-entrant lock) and are persisted atomically to data/jobs/<id>.json.
Renders work on a deep-copied snapshot so concurrent edits never mix two timelines in one video.
Public functions return deep copies, so callers (FastAPI serialisation) never see a dict being mutated.
"""
import copy
import json
import os
import threading
import time
import uuid

from app_paths import JOBS_DIR
from catalog_store import STEP_LABELS_VI, available_steps, get_clip, product_sets, public_clip
from final_mix_renderer import render_job
from footage_filename_parser import CRAFT_STEPS, craft_step_from_action
from footage_matcher import rank_candidates, variant_order
from generation_suggestions import generation_options, vo_estimate
from job_settings import DEFAULTS
from pricing_store import recommended
from script_planner_claude import claude_available, plan_with_claude
from script_planner_rules import plan_with_rules
from timeline_builder import build_timeline, part_duration
from video_templates import ROLE_LABELS_VI, TEMPLATES, template_or_default
from voice_tts import synthesize_parts

_jobs, _lock = {}, threading.RLock()
CLIP_FIELDS = ("id", "name", "folder", "thumb", "proxy", "description_vi", "product_set", "craft_step", "rights",
               "usable", "best_moment_s", "craft_step_source")
# Dựng hàng loạt: các vai này phải dùng clip riêng cho từng video, không được lặp lại giữa các
# video trong lô — kể cả cảnh sản phẩm hoàn thiện.
UNIQUE_ROLES = {"craft", "huyk_talk", "outro", "product_final"}


def _save(job):
    """Atomic write of a consistent snapshot (call with or without the lock held)."""
    with _lock:
        payload = json.dumps(job, ensure_ascii=False)
    path = JOBS_DIR / f"{job['id']}.json"
    tmp = path.with_suffix(f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _product_name(sku):
    entry = next((s for s in product_sets() if s["sku"] == sku), None)
    return (entry["name"].replace("-", " ") if entry else "") or sku or ""


def _narrated(parts):
    """Bỏ khối câm: chúng kéo dài video quá thời lượng đọc nội dung.

    Khối phát tiếng gốc của clip (outro) vẫn giữ — nó có tiếng, chỉ là tiếng không do máy đọc.
    """
    return [p for p in parts if (p.get("vo_text") or "").strip() or p.get("source_audio")]


def _plan(script, sku, template_id, planner):
    family = TEMPLATES[template_id]["family"]
    steps = available_steps(sku) if sku else []
    if planner == "claude" and claude_available():
        try:
            parts = _narrated(plan_with_claude(script, template_id, family, steps))
            if parts:
                return parts, "claude"
        except Exception as exc:   # network/auth/refusal -> keep the demo running
            print(f"[planner] Claude failed, using rules: {exc}")
    return _narrated(plan_with_rules(script, template_id, family, steps)), "rules"


def _apply_nas_plan(parts, plan):
    """Khóa công đoạn chế tác (và tên cảnh HuyK) theo đúng footage editor đã chọn trên tuyến A4.

    Planner tự gán bước từ kho catalog nên tên trên timeline dễ lệch với bảng A4. Kế hoạch NAS
    là nguồn sự thật: bốn ô chế tác map lần lượt bốn khối craft, hai ô HuyK map hai khối nói.
    """
    if not isinstance(plan, dict):
        return
    crafts = [p for p in parts if p["role"] == "craft"]
    for part, src in zip(crafts, plan.get("craft") or []):
        if not isinstance(src, dict):
            continue
        step = src.get("step")
        name = (src.get("name") or "").strip()
        if step not in CRAFT_STEPS and name:
            step, _ = craft_step_from_action(name)
        if step in CRAFT_STEPS:
            part["craft_step"] = step
            part["craft_step_lock"] = True
            part["craft_label"] = name or STEP_LABELS_VI.get(step, step)
    for part, src in zip((p for p in parts if p["role"] == "huyk_talk"), plan.get("huyk") or []):
        if isinstance(src, dict) and src.get("name"):
            part["huyk_label"] = src["name"]


def _enrich_parts(job):
    sku = job["sku"]
    # Dự án đã học giọng của editor thì chính giọng đó đọc kịch bản, không thì giọng HuyK / giọng demo.
    vos = synthesize_parts(job["parts"], job["settings"]["voice"], (job.get("voice_clone") or {}).get("voice_id", ""))
    taken = frozenset(job.get("exclude_clips") or [])
    for part, vo in zip(job["parts"], vos):
        part["vo"] = vo
        part["role_label"] = ROLE_LABELS_VI.get(part["role"], part["role"])
        part.setdefault("visual_intent", f"{part['role_label']} {STEP_LABELS_VI.get(part.get('craft_step') or '', '')}")
        skip = taken if part["role"] in UNIQUE_ROLES else frozenset()
        part["candidates"] = variant_order(rank_candidates(part, sku, used=set(), exclude=skip),
                                           part["part_id"], job.get("variant", 0))
        part["gen_options"] = generation_options(part, _product_name(sku), sku, part_duration(part))


def _clips_payload(job):
    ids = {c["clip_id"] for p in job["parts"] for c in p.get("candidates", [])}
    return {cid: {k: public_clip(get_clip(cid)).get(k) for k in CLIP_FIELDS} | {"tags": get_clip(cid)["tags"]} for cid in ids}


def _start_render(job):
    with _lock:
        job["render"]["revision"] += 1
        job["render"]["status"] = "rendering"
        rev = job["render"]["revision"]
        snapshot = copy.deepcopy(job)

    def work():
        t0 = time.time()
        try:
            url = render_job(snapshot, rev)
            result = {"status": "done", "url": url, "poster": url.replace(".mp4", ".jpg"),
                      "seconds": round(time.time() - t0, 1), "error": None}
        except Exception as exc:
            result = {"status": "error", "error": str(exc)[-600:]}
        with _lock:
            if job["render"]["revision"] != rev:          # a newer render superseded this one
                return
            job["render"].update(result)
        _save(job)
    threading.Thread(target=work, daemon=True).start()


def create_job(script: str, sku: str, template_id: str, planner: str, plan: dict = None,
               voice_clone: dict = None, variant: int = 0, exclude_clips: list = None) -> dict:
    sku = sku or None
    if sku and sku not in {s["sku"] for s in product_sets()}:
        raise ValueError(f"Không có bộ footage cho sản phẩm {sku}")
    template_id = template_or_default(template_id, bool(sku))
    parts, used_planner = _plan(script, sku, template_id, planner)
    if not parts:
        raise ValueError("Kịch bản không tách được thành phần nào")
    _apply_nas_plan(parts, plan)
    job = {"id": "j_" + uuid.uuid4().hex[:8], "created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "script": script,
           "sku": sku, "product_name": _product_name(sku), "template_id": template_id,
           "template_label": TEMPLATES[template_id]["label"], "planner": used_planner, "parts": parts,
           "settings": dict(DEFAULTS), "history": [], "render": {"status": "idle", "revision": 0, "url": None},
           # Công đoạn chế tác / cảnh HuyK editor chọn từ ổ NAS, lưu kèm để bàn giao.
           "nas_plan": plan or None,
           # Giọng editor tải lên đã được học, dùng để đọc kịch bản.
           "voice_clone": voice_clone or None,
           # Dựng hàng loạt: số thứ tự biến thể và các clip video trước trong lô đã dùng.
           "variant": variant, "exclude_clips": list(exclude_clips or [])}
    _enrich_parts(job)
    build_timeline(job)
    chars = sum(len(p.get("vo_text", "")) for p in parts)
    job["costs"] = {"vo": vo_estimate(chars), "script_llm": recommended("script_llm").get("cost_per_unit_usd", 0)}
    job["clips"] = _clips_payload(job)
    with _lock:
        _jobs[job["id"]] = job
    _save(job)
    _start_render(job)
    return get_job(job["id"])


def _load(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if job is None and (JOBS_DIR / f"{job_id}.json").exists():
            job = json.loads((JOBS_DIR / f"{job_id}.json").read_text(encoding="utf-8"))
            _jobs[job_id] = job
        return job


def get_job(job_id: str) -> dict:
    with _lock:
        job = _load(job_id)
        return copy.deepcopy(job) if job else None
