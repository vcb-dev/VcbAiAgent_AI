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
from typing import Optional

from app_paths import JOBS_DIR
from catalog_store import STEP_LABELS_VI, available_steps, get_clip, product_sets, public_clip
from final_mix_renderer import render_job
from footage_filename_parser import CRAFT_STEPS, craft_step_from_action
from footage_matcher import rank_candidates, variant_order
from generation_suggestions import generation_options, vo_estimate
from job_settings import DEFAULTS, validate
from music_library import track_ids
from pricing_store import recommended
from script_planner_claude import claude_available, plan_with_claude
from script_planner_rules import plan_with_rules
from timeline_builder import build_timeline, part_duration
from video_templates import ROLE_LABELS_VI, TEMPLATES, part_alt_roles, template_or_default
from voice_tts import synthesize_parts

_jobs, _lock = {}, threading.RLock()
CLIP_FIELDS = ("id", "name", "folder", "thumb", "proxy", "description_vi", "product_set", "craft_step", "rights",
               "usable", "best_moment_s", "craft_step_source")
# Dựng hàng loạt: mỗi vai này dùng clip riêng cho tới khi hết kho của đúng vai đó, lúc đó mới
# quay vòng. product_hero cũng tách — không để 10 video mở đầu bằng một clip.
UNIQUE_ROLES = {"product_hero", "craft", "huyk_talk", "outro", "product_final"}


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


# Tuyến A4 mặc định — ô đầu là cảnh sản phẩm, không phải hook.
_DEFAULT_A4_ROLES = [
    "product_hero", "huyk_talk", "craft", "craft", "craft", "huyk_talk", "craft", "product_final", "outro",
]


def _slot_role(slot: dict) -> str:
    kind = (slot or {}).get("from")
    if kind == "product":
        return "product_final" if slot.get("variant") == "final" else "product_hero"
    if kind == "huyk":
        return "huyk_talk"
    if kind == "craft":
        return "craft"
    return "outro"


def _roles_from_plan(plan: dict) -> list:
    slots = plan.get("slots") or []
    if slots:
        return [_slot_role(s) for s in slots if isinstance(s, dict)]
    if plan.get("craft") or plan.get("huyk"):
        return list(_DEFAULT_A4_ROLES)
    return []


def _align_parts_to_route(parts: list, roles: list, template_id: str) -> None:
    """Gán vai từng khối kịch bản theo đúng ô tuyến A4 (Sản phẩm → HuyK → chế tác…), không bịa hook."""
    spoken_roles = [r for r in roles if r != "outro"]
    spoken = [p for p in parts if not p.get("source_audio") and p.get("role") != "outro"]
    if not spoken or not spoken_roles:
        return
    n_p, n_s = len(spoken), len(spoken_roles)
    if n_p == n_s:
        chosen = spoken_roles
    elif n_p < n_s:
        chosen = spoken_roles[: max(n_p - 1, 0)] + [spoken_roles[-1]]
    else:
        chosen = spoken_roles[:-1] + [None] * (n_p - n_s) + [spoken_roles[-1]]
    for part, role in zip(spoken, chosen):
        if not role:
            continue
        part["role"] = role
        part["alt_roles"] = part_alt_roles(template_id, role)
        if role != "craft":
            part["craft_step"] = None


def _craft_process_order(src: dict) -> int:
    """Thứ tự quy trình của một ô chế tác trên tuyến A4 (số folder trên ổ không đáng tin)."""
    step = src.get("step")
    if step not in CRAFT_STEPS:
        step, _ = craft_step_from_action((src.get("name") or "").strip())
    return CRAFT_STEPS[step][0] if step in CRAFT_STEPS else 999


def _apply_nas_plan(parts, plan, template_id: str = "A4_v1"):
    """Khóa vai + công đoạn theo đúng footage editor đã chọn trên tuyến A4.

    Planner hay gắn câu đầu thành hook; tuyến nội dung thì ô đầu là cảnh sản phẩm.
    Bốn ô chế tác luôn gán theo thứ tự quy trình, không theo thứ tự thư mục trên ổ.
    """
    if not isinstance(plan, dict):
        return
    _align_parts_to_route(parts, _roles_from_plan(plan), template_id)
    crafts = [p for p in parts if p["role"] == "craft"]
    sources = [s for s in (plan.get("craft") or []) if isinstance(s, dict)]
    sources.sort(key=_craft_process_order)
    for part, src in zip(crafts, sources):
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
    taken = list(dict.fromkeys(job.get("exclude_clips") or []))
    taken_set = set(taken)
    for part, vo in zip(job["parts"], vos):
        part["vo"] = vo
        part["role_label"] = ROLE_LABELS_VI.get(part["role"], part["role"])
        part.setdefault("visual_intent", f"{part['role_label']} {STEP_LABELS_VI.get(part.get('craft_step') or '', '')}")
        skip = taken if part["role"] in UNIQUE_ROLES else []
        ranked = rank_candidates(part, sku, used=set(), exclude=skip)
        wrapping = bool(skip) and ranked and ranked[0]["clip_id"] in taken_set
        # Còn source mới thì xáo nhẹ để mỗi video khác nhau; lúc quay vòng giữ đúng thứ tự đã dùng.
        part["candidates"] = ranked if wrapping else variant_order(ranked, part["part_id"], job.get("variant", 0))
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


def _job_settings(partial: Optional[dict]) -> dict:
    """DEFAULTS + nhạc/giọng chọn lúc tạo job, để bản render đầu đã đúng nhạc nền."""
    cfg = dict(DEFAULTS)
    extra = {k: v for k, v in (partial or {}).items() if v not in (None, "")}
    if extra:
        cfg.update(validate(extra, track_ids()))
    return cfg


def create_job(script: str, sku: str, template_id: str, planner: str, plan: dict = None,
               voice_clone: dict = None, variant: int = 0, exclude_clips: list = None,
               settings: dict = None) -> dict:
    sku = sku or None
    if sku and sku not in {s["sku"] for s in product_sets()}:
        raise ValueError(f"Không có bộ footage cho sản phẩm {sku}")
    template_id = template_or_default(template_id, bool(sku))
    parts, used_planner = _plan(script, sku, template_id, planner)
    if not parts:
        raise ValueError("Kịch bản không tách được thành phần nào")
    _apply_nas_plan(parts, plan, template_id)
    job = {"id": "j_" + uuid.uuid4().hex[:8], "created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "script": script,
           "sku": sku, "product_name": _product_name(sku), "template_id": template_id,
           "template_label": TEMPLATES[template_id]["label"], "planner": used_planner, "parts": parts,
           "settings": _job_settings(settings), "history": [], "render": {"status": "idle", "revision": 0, "url": None},
           # Công đoạn chế tác / cảnh HuyK editor chọn từ ổ NAS, lưu kèm để bàn giao.
           "nas_plan": plan or None,
           # Giọng editor tải lên đã được học, dùng để đọc kịch bản.
           "voice_clone": voice_clone or None,
           # Dựng hàng loạt: số thứ tự biến thể và các clip video trước trong lô đã dùng.
           "variant": variant, "exclude_clips": list(exclude_clips or [])}
    _enrich_parts(job)
    build_timeline(job)
    _refresh_costs(job)
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


def _vo_provider(job: dict) -> str:
    """Giọng đã nướng vào phần — MiniMax / ElevenLabs / bản thu / máy, không lấy recommended TTS."""
    return next(((p.get("vo") or {}).get("provider") or "" for p in job.get("parts") or []
                 if (p.get("vo") or {}).get("provider")), "")


def _refresh_costs(job: dict) -> None:
    chars = sum(len(p.get("vo_text") or "") for p in job.get("parts") or [])
    llm = 0.0 if (job.get("planner") or "rules") == "rules" else recommended("script_llm").get("cost_per_unit_usd", 0)
    costs = dict(job.get("costs") or {})
    costs["vo"] = vo_estimate(chars, _vo_provider(job))
    costs["script_llm"] = llm
    job["costs"] = costs


def get_job(job_id: str) -> dict:
    with _lock:
        job = _load(job_id)
        if not job:
            return None
        out = copy.deepcopy(job)
    _refresh_costs(out)
    return out
