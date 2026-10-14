"""Editor actions on an existing job (CapCut-style options): pick alternative / any library clip, speed & zoom,
emotion override + re-voice, job settings, undo. Every action snapshots history, rebuilds the timeline, re-renders.
"""
import copy

from catalog_store import get_clip, public_clip
from job_service import CLIP_FIELDS, _load, _lock, _save, _start_render, get_job
from job_settings import DEFAULTS, VOICE_KEYS, validate
from music_library import track_ids
from timeline_builder import build_timeline
from video_templates import PRODUCT_SET_ROLES
from vo_director import EMOTION_TAGS
from voice_tts import synthesize_parts

HISTORY_LIMIT = 30


def _job_and_part(job_id, part_id=None):
    job = _load(job_id)
    if not job:
        raise KeyError(job_id)
    if part_id is None:
        return job, None
    part = next((p for p in job["parts"] if p["part_id"] == part_id), None)
    if part is None:
        raise KeyError(part_id)
    return job, part


def _snapshot(job):
    return {"choices": {p["part_id"]: copy.deepcopy(p.get("choices", {})) for p in job["parts"]},
            "emotions": {p["part_id"]: p.get("emotion_override") for p in job["parts"]},
            "settings": dict(job.get("settings", DEFAULTS))}


def _push_history(job):
    job.setdefault("history", []).append(_snapshot(job))
    del job["history"][:-HISTORY_LIMIT]


def _revoice(job):
    for part, vo in zip(job["parts"], synthesize_parts(job["parts"], job["settings"]["voice"])):
        part["vo"] = vo


def _commit(job, revoice=False):
    if revoice:
        _revoice(job)          # cached takes make undo/redo of the same voice free
    build_timeline(job)
    _save(job)
    _start_render(job)
    return get_job(job["id"])


def _manual_clip(job, part, clip_id):
    """Validate a clip picked from the library and register it as a candidate of this part."""
    clip = get_clip(clip_id)
    if clip is None or clip["rights"] == "unknown":
        raise ValueError("clip không có trong kho hoặc chưa rõ quyền sử dụng")
    if part["role"] in PRODUCT_SET_ROLES and clip.get("product_set") != job["sku"]:
        raise ValueError("Cảnh sản phẩm/chế tác chỉ dùng footage của đúng sản phẩm (không map chéo SKU)")
    if part["role"] != "outro" and clip["roles"].get("outro", 0) >= 0.8:
        raise ValueError("Clip outro có logo chỉ dùng ở cuối video")
    if not any(c["clip_id"] == clip_id for c in part.get("candidates", [])):
        part.setdefault("candidates", []).insert(0, {"kind": "clip", "clip_id": clip_id, "score": 1.0, "manual": True,
                                                     "scope": "collected" if clip["rights"] == "collected" else "product" if clip.get("product_set") else "shared",
                                                     "text_match": 1.0, "via_alt": False, "reason": "Chọn thủ công từ kho footage"})
        job["clips"][clip_id] = {k: public_clip(clip).get(k) for k in CLIP_FIELDS} | {"tags": clip["tags"]}


def select_option(job_id: str, part_id: str, shot_index: int, option: dict) -> dict:
    with _lock:
        job, part = _job_and_part(job_id, part_id)
        kind = option.get("kind")
        if kind == "clip" and not 0 <= shot_index < max(len(part.get("shots", [])), 1):
            raise ValueError("shot_index out of range for this part")
        value = option.get("clip_id" if kind == "clip" else "gen_id")
        if not isinstance(value, str):
            raise ValueError("missing clip_id / gen_id")
        if kind == "clip" and option.get("manual"):
            _manual_clip(job, part, value)
        allowed = {c["clip_id"] for c in part.get("candidates", [])} if kind == "clip" \
            else {g["gen_id"] for g in part.get("gen_options", [])}
        if value not in allowed:
            raise ValueError("option is not one of this part's suggested alternatives")
        _push_history(job)
        if kind == "gen":
            part["choices"] = {"0": {"kind": "gen", "gen_id": value}}       # generation spans the whole part
        else:
            choice = {"kind": "clip", "clip_id": value}
            for key, lo, hi in (("speed", 0.75, 2.0), ("zoom", 1.0, 1.4)):
                if option.get(key) is not None:
                    choice[key] = round(min(max(float(option[key]), lo), hi), 2)
            kept = {k: v for k, v in part.get("choices", {}).items() if v["kind"] == "clip"}
            part["choices"] = {**kept, str(shot_index): choice}
        return _commit(job)


def set_emotion(job_id: str, part_id: str, emotion: str) -> dict:
    """Override one part's delivery tag ('' = natural, None = automatic) and re-voice the whole take."""
    if emotion is not None and emotion not in EMOTION_TAGS:
        raise ValueError("unsupported emotion tag")
    with _lock:
        job, part = _job_and_part(job_id, part_id)
        if not (part.get("vo_text") or "").strip():
            raise ValueError("phần này không có lời đọc")
        _push_history(job)
        part["emotion_override"] = emotion
        return _commit(job, revoice=True)


def update_settings(job_id: str, partial: dict) -> dict:
    with _lock:
        job, _ = _job_and_part(job_id)
        clean = validate(partial, track_ids())
        if not clean:
            return get_job(job_id)
        _push_history(job)
        revoice = any(k in VOICE_KEYS and clean[k] != job["settings"].get(k) for k in clean)
        job["settings"].update(clean)
        return _commit(job, revoice=revoice)


def undo(job_id: str) -> dict:
    with _lock:
        job, _ = _job_and_part(job_id)
        if not job.get("history"):
            raise ValueError("Không còn thao tác để hoàn tác")
        snap = job["history"].pop()
        revoice = snap["settings"].get("voice") != job["settings"].get("voice") or any(
            snap["emotions"].get(p["part_id"]) != p.get("emotion_override") for p in job["parts"])
        for p in job["parts"]:
            p["choices"] = snap["choices"].get(p["part_id"], {})
            p["emotion_override"] = snap["emotions"].get(p["part_id"])
        job["settings"] = snap["settings"]
        return _commit(job, revoice=revoice)
