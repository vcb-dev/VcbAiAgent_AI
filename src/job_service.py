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
from footage_matcher import rank_candidates
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


def _plan(script, sku, template_id, planner):
    family = TEMPLATES[template_id]["family"]
    steps = available_steps(sku) if sku else []
    if planner == "claude" and claude_available():
        try:
            parts = plan_with_claude(script, template_id, family, steps)
            if parts:
                return parts, "claude"
        except Exception as exc:   # network/auth/refusal -> keep the demo running
            print(f"[planner] Claude failed, using rules: {exc}")
    return plan_with_rules(script, template_id, family, steps), "rules"


def _enrich_parts(job):
    sku = job["sku"]
    vos = synthesize_parts(job["parts"], job["settings"]["voice"])   # one emotional ElevenLabs take, or demo voice
    for part, vo in zip(job["parts"], vos):
        part["vo"] = vo
        part["role_label"] = ROLE_LABELS_VI.get(part["role"], part["role"])
        part.setdefault("visual_intent", f"{part['role_label']} {STEP_LABELS_VI.get(part.get('craft_step') or '', '')}")
        part["candidates"] = rank_candidates(part, sku, used=set())
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


def create_job(script: str, sku: str, template_id: str, planner: str) -> dict:
    sku = sku or None
    if sku and sku not in {s["sku"] for s in product_sets()}:
        raise ValueError(f"Không có bộ footage cho sản phẩm {sku}")
    template_id = template_or_default(template_id, bool(sku))
    parts, used_planner = _plan(script, sku, template_id, planner)
    if not parts:
        raise ValueError("Kịch bản không tách được thành phần nào")
    job = {"id": "j_" + uuid.uuid4().hex[:8], "created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "script": script,
           "sku": sku, "product_name": _product_name(sku), "template_id": template_id,
           "template_label": TEMPLATES[template_id]["label"], "planner": used_planner, "parts": parts,
           "settings": dict(DEFAULTS), "history": [], "render": {"status": "idle", "revision": 0, "url": None}}
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
