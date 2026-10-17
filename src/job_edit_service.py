"""Editor actions on an existing job (CapCut-style options): pick alternative / any library clip, speed & zoom,
emotion override + re-voice, job settings, undo. Every action snapshots history, rebuilds the timeline, re-renders.
"""
import copy

import random

from catalog_store import STEP_LABELS_VI, available_steps, get_clip, public_clip
from footage_filename_parser import CRAFT_STEPS, craft_step_from_action
from footage_matcher import rank_candidates, variant_order
from job_service import CLIP_FIELDS, _clips_payload, _load, _lock, _save, _start_render, get_job
from job_settings import DEFAULTS, VOICE_KEYS, validate
from music_library import track_ids
from timeline_builder import build_timeline
from video_templates import PRODUCT_SET_ROLES
from vo_director import EMOTION_TAGS
from voice_tts import import_recording, learn_voice, split_recording, stored_recording, synthesize_parts

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
            "uploads": {p["part_id"]: copy.deepcopy(p.get("vo_upload")) for p in job["parts"]},
            "craft": {p["part_id"]: {"craft_step": p.get("craft_step"), "craft_step_lock": p.get("craft_step_lock"),
                                    "craft_label": p.get("craft_label"), "huyk_label": p.get("huyk_label")}
                      for p in job["parts"]},
            "voice_upload": copy.deepcopy(job.get("voice_upload")),
            "voice_clone": copy.deepcopy(job.get("voice_clone")),
            "settings": dict(job.get("settings", DEFAULTS))}


def _push_history(job):
    job.setdefault("history", []).append(_snapshot(job))
    del job["history"][:-HISTORY_LIMIT]


def _revoice(job):
    clone_id = (job.get("voice_clone") or {}).get("voice_id", "")
    for part, vo in zip(job["parts"], synthesize_parts(job["parts"], job["settings"]["voice"], clone_id)):
        part["vo"] = vo
    # Phần nào editor đã tải giọng thật lên thì giữ nguyên, kể cả khi đọc lại cả kịch bản.
    for part in job["parts"]:
        if part.get("vo_upload"):
            part["vo"] = dict(part["vo_upload"])


def _commit(job, revoice=False):
    if revoice:
        _revoice(job)          # cached takes make undo/redo of the same voice free
    build_timeline(job)
    job["clips"] = _clips_payload(job)
    _save(job)
    _start_render(job)
    return get_job(job["id"])


def _rematch_craft(job, part):
    """Bốc lại ứng viên footage cho khối chế tác sau khi đổi công đoạn."""
    used = {
        s["selected"]["clip_id"]
        for other in job["parts"] if other["part_id"] != part["part_id"]
        for s in other.get("shots", [])
        if s.get("selected", {}).get("kind") == "clip"
    }
    part["candidates"] = variant_order(
        rank_candidates(part, job.get("sku"), used=used),
        part["part_id"],
        job.get("variant", 0),
    )
    part["choices"] = {}
    part["visual_intent"] = (
        f"{part.get('role_label', 'Chế tác')} "
        f"{part.get('craft_label') or STEP_LABELS_VI.get(part.get('craft_step') or '', '')}"
    )


def _resolve_craft_step(raw, label=""):
    """Nhận id taxonomy, 'random', hoặc tên thư mục NAS rồi ra id công đoạn."""
    if raw in CRAFT_STEPS or raw == "random":
        return raw
    for text in (raw, label):
        if not text:
            continue
        step, _ = craft_step_from_action(text)
        if step:
            return step
    return raw


def _touch_nas_plan_craft(job, part, step, label, path=""):
    """Giữ nas_plan khớp khối vừa đổi, để bảng A4 và timeline đọc cùng một tên."""
    plan = job.get("nas_plan")
    if not isinstance(plan, dict):
        return
    crafts = [p for p in job["parts"] if p["role"] == "craft"]
    try:
        idx = crafts.index(part)
    except ValueError:
        return
    rows = list(plan.get("craft") or [])
    while len(rows) <= idx:
        rows.append({})
    prev = rows[idx] if isinstance(rows[idx], dict) else {}
    rows[idx] = {**prev, "step": step, "name": label or prev.get("name") or STEP_LABELS_VI.get(step, step)}
    if path:
        rows[idx]["path"] = path
    plan["craft"] = rows
    job["nas_plan"] = plan


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
        if kind == "clip":
            clip = get_clip(value)
            if part["role"] == "craft" and clip and clip.get("craft_step"):
                part["craft_step"] = clip["craft_step"]
                part["craft_step_lock"] = True
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


def set_craft_step(job_id: str, part_id: str, step: str, label: str = "", path: str = "") -> dict:
    """Đổi công đoạn của một khối chế tác rồi bốc source mới từ nhóm đó.

    `step='random'` lấy một công đoạn khác (ưu tiên chưa dùng ở các khối chế tác còn lại).
    `label` là tên thư mục NAS — timeline hiện đúng tên footage A4, không chỉ nhãn taxonomy.
    """
    with _lock:
        job, part = _job_and_part(job_id, part_id)
        if part["role"] != "craft":
            raise ValueError("Chỉ đổi công đoạn trên khối chế tác")
        have = available_steps(job.get("sku") or "") or list(CRAFT_STEPS)
        step = _resolve_craft_step(step, label)
        if step == "random":
            used = {p.get("craft_step") for p in job["parts"]
                    if p["role"] == "craft" and p["part_id"] != part_id}
            pool = [s for s in have if s not in used and s != part.get("craft_step")] or \
                   [s for s in have if s != part.get("craft_step")] or have
            step = random.choice(pool)
        if step not in CRAFT_STEPS:
            raise ValueError(f"Công đoạn '{step}' không có trong danh sách")
        _push_history(job)
        part["craft_step"] = step
        part["craft_step_lock"] = True
        part["craft_label"] = (label or "").strip() or STEP_LABELS_VI.get(step, step)
        _touch_nas_plan_craft(job, part, step, part["craft_label"], path)
        _rematch_craft(job, part)
        return _commit(job)


def set_craft_plan(job_id: str, steps: list, labels: list = None, paths: list = None) -> dict:
    """Đổi cả dãy khối chế tác một lần — nút đổi cảnh A4 — rồi chỉ render một lượt."""
    labels = list(labels or [])
    paths = list(paths or [])
    with _lock:
        job, _ = _job_and_part(job_id)
        crafts = [p for p in job["parts"] if p["role"] == "craft"]
        if not crafts:
            raise ValueError("Không có khối chế tác")
        have = available_steps(job.get("sku") or "") or list(CRAFT_STEPS)
        _push_history(job)
        used = set()
        for i, part in enumerate(crafts):
            raw = steps[i] if i < len(steps) else "random"
            step = _resolve_craft_step(raw or "random", labels[i] if i < len(labels) else "")
            if step == "random":
                pool = [s for s in have if s not in used] or have
                step = random.choice(pool)
            if step not in CRAFT_STEPS:
                raise ValueError(f"Công đoạn '{step}' không có trong danh sách")
            label = (labels[i] if i < len(labels) else "") or STEP_LABELS_VI.get(step, step)
            part["craft_step"] = step
            part["craft_step_lock"] = True
            part["craft_label"] = (label or "").strip()
            used.add(step)
            _touch_nas_plan_craft(job, part, step, part["craft_label"], paths[i] if i < len(paths) else "")
            _rematch_craft(job, part)
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


def set_voice_upload(job_id: str, part_id: str, raw: bytes, filename: str) -> dict:
    """Dùng file ghi âm tải từ máy lên làm lời đọc của một phần.

    Thời lượng phần đó bám theo file vừa tải chứ không còn theo giọng máy, nên timeline
    được dựng lại và video render lại ngay.
    """
    vo = import_recording(raw, filename)        # chuyển mã trước khi giữ khoá: ffmpeg có thể mất vài giây
    with _lock:
        job, part = _job_and_part(job_id, part_id)
        if not (part.get("vo_text") or "").strip():
            raise ValueError("phần này không có lời đọc")
        _push_history(job)
        part["vo_upload"] = vo
        part["vo"] = dict(vo)
        return _commit(job)


def set_job_voice_upload(job_id: str, base: dict) -> dict:
    """Dùng một bản thu cả kịch bản làm lời đọc cho toàn bộ video, cắt ra từng phần."""
    job = _load(job_id)
    if not job:
        raise KeyError(job_id)
    pieces = split_recording(base, job["parts"])            # ffmpeg chạy ngoài khoá
    with _lock:
        job, _ = _job_and_part(job_id)
        _push_history(job)
        job["voice_clone"] = None               # dùng thẳng bản thu thì không qua giọng nhân bản nữa
        for part in job["parts"]:
            part.pop("vo_upload", None)
        for index, vo in pieces:
            job["parts"][index]["vo_upload"] = vo
            job["parts"][index]["vo"] = dict(vo)
        job["voice_upload"] = {**base, "parts": len(pieces)}
        return _commit(job)


def set_job_voice_clone(job_id: str, base: dict) -> dict:
    """Học giọng trong bản thu rồi cho chính giọng đó đọc lại cả kịch bản.

    Khác `set_job_voice_upload` ở chỗ bản thu chỉ là mẫu giọng: nội dung đọc vẫn là kịch
    bản editor viết, nên sửa chữ là có lời đọc mới mà không phải thu lại.
    """
    clone = learn_voice(base)                   # gọi MiniMax ngoài khoá: mất vài giây
    with _lock:
        job, _ = _job_and_part(job_id)
        _push_history(job)
        job["voice_clone"] = clone
        job.pop("voice_upload", None)           # hai cách dùng file loại trừ nhau
        for part in job["parts"]:
            part.pop("vo_upload", None)
        return _commit(job, revoice=True)


def clear_job_voice_clone(job_id: str) -> dict:
    """Thôi dùng giọng nhân bản, quay lại giọng mặc định."""
    with _lock:
        job, _ = _job_and_part(job_id)
        if not job.get("voice_clone"):
            raise ValueError("video chưa dùng giọng nhân bản")
        _push_history(job)
        job["voice_clone"] = None
        return _commit(job, revoice=True)


def clear_job_voice_upload(job_id: str) -> dict:
    """Bỏ bản thu dùng cho cả video, quay lại giọng máy đọc."""
    with _lock:
        job, _ = _job_and_part(job_id)
        if not any(p.get("vo_upload") for p in job["parts"]):
            raise ValueError("video đang dùng giọng máy đọc")
        _push_history(job)
        job.pop("voice_upload", None)
        for part in job["parts"]:
            part.pop("vo_upload", None)
        return _commit(job, revoice=True)


def clear_voice_upload(job_id: str, part_id: str) -> dict:
    """Bỏ file đã tải, quay lại giọng máy đọc của phần đó."""
    with _lock:
        job, part = _job_and_part(job_id, part_id)
        if not part.get("vo_upload"):
            raise ValueError("phần này đang dùng giọng máy đọc")
        _push_history(job)
        part.pop("vo_upload", None)
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
        uploads = snap.get("uploads", {})
        revoice = (snap["settings"].get("voice") != job["settings"].get("voice")
                   or snap.get("voice_clone") != job.get("voice_clone")
                   or any(snap["emotions"].get(p["part_id"]) != p.get("emotion_override")
                          or uploads.get(p["part_id"]) != p.get("vo_upload") for p in job["parts"]))
        craft = snap.get("craft") or {}
        for p in job["parts"]:
            prev = craft.get(p["part_id"])
            if prev:
                p["craft_step"] = prev.get("craft_step")
                p["craft_step_lock"] = prev.get("craft_step_lock")
                if "craft_label" in prev:
                    p["craft_label"] = prev.get("craft_label")
                if "huyk_label" in prev:
                    p["huyk_label"] = prev.get("huyk_label")
                if p["role"] == "craft":
                    _rematch_craft(job, p)
            p["choices"] = snap["choices"].get(p["part_id"], {})
            p["emotion_override"] = snap["emotions"].get(p["part_id"])
            was = uploads.get(p["part_id"])
            p["vo_upload"] = copy.deepcopy(was) if was else None
            if not p["vo_upload"]:
                p.pop("vo_upload")
        if snap.get("voice_upload"):
            job["voice_upload"] = copy.deepcopy(snap["voice_upload"])
        else:
            job.pop("voice_upload", None)
        job["voice_clone"] = copy.deepcopy(snap.get("voice_clone"))
        job["settings"] = snap["settings"]
        return _commit(job, revoice=revoice)
