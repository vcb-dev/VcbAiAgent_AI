"""FastAPI app for the VCB Video Agent AI service (planner, footage matching, timeline, render).

Called server-to-server by VCB_BE with the X-Assistant-Secret header; /media is public so the
browser can stream proxies and renders through the gateway.

Run (from VCB_AI):  python main.py
"""
import json
from contextlib import contextmanager
from typing import Literal, Optional

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app_paths import DATA, MEDIA
from catalog_store import craft_step_choices, load_catalog, product_sets, public_clip, set_clip_craft_step
from internal_auth import require_internal_secret
from job_edit_service import (clear_job_voice_clone, clear_job_voice_upload, clear_voice_upload, select_option,
                              set_craft_plan, set_craft_step, set_emotion, set_job_voice_clone, set_job_voice_upload,
                              set_voice_upload, undo, update_settings)
from job_package_export import build_package
from job_service import CLIP_FIELDS, create_job, get_job
from job_settings import DEFAULTS
import nas_browser
from music_library import public_tracks
from nas_prepare import prepare
from pricing_store import load_benchmark, load_pricing
from script_planner_claude import claude_available
from video_templates import TEMPLATES
from vo_director import EMOTION_TAGS
import voice_minimax
from voice_minimax import MinimaxError
from voice_tts import (available_voices, eleven_enabled, huyk_voice_enabled, import_recording, learn_voice,
                       pick_voice, stored_recording)

app = FastAPI(title="VCB Video Agent AI")
api = APIRouter(prefix="/api", dependencies=[Depends(require_internal_secret)])


class StoredVoice(BaseModel):
    audio: str = Field(max_length=200)        # đường dẫn trả về từ /voice-uploads
    upload_name: str = Field(default="", max_length=120)


class JobRequest(BaseModel):
    script: str = Field(min_length=10, max_length=6000)
    sku: str = ""
    template_id: str = "auto"
    planner: str = "rules"
    # Công đoạn chế tác và cảnh HuyK người dùng chọn từ ổ NAS cho tuyến A4.
    plan: Optional[dict] = None
    # Mẫu giọng editor tải lên trước khi dựng: học giọng rồi đọc kịch bản bằng giọng đó.
    voice: Optional[StoredVoice] = None
    # Hoặc chọn thẳng một giọng đã có trên tài khoản MiniMax (xem GET /voices).
    voice_id: str = Field(default="", max_length=64)
    # Dựng hàng loạt: số thứ tự biến thể, để mỗi video trong lô bốc cảnh khác nhau.
    variant: int = Field(default=0, ge=0, le=99)
    # Clip các video trước trong lô đã dùng: video này tránh ra cho khỏi trùng cảnh.
    exclude_clips: list[str] = Field(default_factory=list, max_length=400)


class Option(BaseModel):
    kind: Literal["clip", "gen"]
    clip_id: Optional[str] = Field(default=None, max_length=64)
    gen_id: Optional[str] = Field(default=None, max_length=64)
    manual: bool = False                                   # picked from the footage library, not the suggestions
    speed: Optional[float] = Field(default=None, ge=0.75, le=2.0)
    zoom: Optional[float] = Field(default=None, ge=1.0, le=1.4)


class SelectRequest(BaseModel):
    part_id: str = Field(max_length=16)
    shot_index: int = Field(ge=0, le=20)
    option: Option


class EmotionRequest(BaseModel):
    emotion: Optional[str] = Field(default=None, max_length=40)   # None = automatic, "" = natural


class CraftStepRequest(BaseModel):
    craft_step: str = Field(min_length=1, max_length=80)          # id công đoạn, tên thư mục NAS, hoặc "random"
    label: str = Field(default="", max_length=120)                # tên footage A4 hiện trên timeline
    path: str = Field(default="", max_length=400)                 # thư mục NAS vừa chọn, để bảng A4 không nhảy về ô cũ


class CraftPlanRequest(BaseModel):
    steps: list[str] = Field(default_factory=list, max_length=8)
    labels: list[str] = Field(default_factory=list, max_length=8)
    paths: list[str] = Field(default_factory=list, max_length=8)


@contextmanager
def api_errors():
    """Map service exceptions to HTTP errors."""
    try:
        yield
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job or part not found") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@api.get("/bootstrap")
def bootstrap():
    samples = json.loads((DATA / "sample-scripts.json").read_text(encoding="utf-8"))
    library = [{k: public_clip(c).get(k) for k in CLIP_FIELDS} | {"roles": list(c["roles"])[:3], "tags": c["tags"]}
               for c in load_catalog().values()]
    return {"products": product_sets(), "templates": [{"id": k, **v} for k, v in TEMPLATES.items()],
            "samples": samples, "clip_count": len(library), "library": library, "music": public_tracks(),
            "emotions": EMOTION_TAGS, "settings_defaults": DEFAULTS, "craft_steps": craft_step_choices(),
            "claude_available": claude_available(), "eleven_available": eleven_enabled(),
            "voice_clone_available": voice_minimax.enabled(), "huyk_voice_available": huyk_voice_enabled()}


@api.get("/voices")
def voices():
    """Giọng nhân bản có trên tài khoản MiniMax, để chọn người đọc cho video."""
    return {"voices": available_voices()}


@api.post("/jobs")
def new_job(req: JobRequest):
    with api_errors():
        if req.voice:
            clone = learn_voice(stored_recording(req.voice.audio, req.voice.upload_name))
        else:
            clone = pick_voice(req.voice_id) if req.voice_id else None
        return create_job(req.script.strip(), req.sku.strip(), req.template_id, req.planner, req.plan, clone,
                          req.variant, req.exclude_clips)


@api.get("/jobs/{job_id}")
def read_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@api.post("/jobs/{job_id}/select")
def choose(job_id: str, req: SelectRequest):
    with api_errors():
        return select_option(job_id, req.part_id, req.shot_index, req.option.model_dump(exclude_none=True))


@api.post("/jobs/{job_id}/parts/{part_id}/emotion")
def emotion(job_id: str, part_id: str, req: EmotionRequest):
    with api_errors():
        return set_emotion(job_id, part_id, req.emotion)


@api.post("/jobs/{job_id}/parts/{part_id}/craft-step")
def craft_step(job_id: str, part_id: str, req: CraftStepRequest):
    """Đổi công đoạn chế tác của một khối: chọn cụ thể hoặc bốc ngẫu nhiên, rồi lấy source mới."""
    with api_errors():
        return set_craft_step(job_id, part_id, req.craft_step, req.label, req.path)


@api.post("/jobs/{job_id}/craft-plan")
def craft_plan(job_id: str, req: CraftPlanRequest):
    """Đổi cả dãy công đoạn chế tác theo footage A4, chỉ dựng lại một lần."""
    with api_errors():
        return set_craft_plan(job_id, req.steps, req.labels, req.paths)


MAX_VO_UPLOAD = 25 * 1024 * 1024


def _read_upload(file: UploadFile) -> bytes:
    raw = file.file.read(MAX_VO_UPLOAD + 1)
    if len(raw) > MAX_VO_UPLOAD:
        raise HTTPException(status_code=413, detail="file lớn hơn 25 MB")
    return raw


@api.post("/voice-uploads")
def voice_store(file: UploadFile = File(...)):
    """Cất bản thu lên máy chủ trước khi có dự án, đồng thời học luôn giọng trong đó.

    Học ngay lúc tải lên để editor biết liền giọng dùng được hay không (file quá ngắn,
    hết hạn mức…), thay vì dựng video xong mới báo lỗi.
    """
    raw = _read_upload(file)
    with api_errors():
        base = import_recording(raw, file.filename or "")
    try:
        return {**base, "clone": learn_voice(base)}
    except (MinimaxError, ValueError) as exc:
        return {**base, "clone": None, "clone_error": str(exc)}


@api.post("/jobs/{job_id}/voice-upload")
def job_voice_upload(job_id: str, file: UploadFile = File(...)):
    """Một bản thu cả kịch bản, cắt ra cho từng phần (route đồng bộ: ffmpeg chạy ở threadpool)."""
    raw = _read_upload(file)
    with api_errors():
        return set_job_voice_upload(job_id, import_recording(raw, file.filename or ""))


@api.post("/jobs/{job_id}/voice-upload/apply")
def job_voice_apply(job_id: str, req: StoredVoice):
    """Dùng bản thu đã cất sẵn (editor chọn từ trước khi dựng) cho cả video."""
    with api_errors():
        return set_job_voice_upload(job_id, stored_recording(req.audio, req.upload_name))


@api.post("/jobs/{job_id}/voice-clone/apply")
def job_voice_clone_apply(job_id: str, req: StoredVoice):
    """Học giọng trong bản thu đã cất, rồi cho giọng đó đọc lại cả kịch bản."""
    with api_errors():
        return set_job_voice_clone(job_id, stored_recording(req.audio, req.upload_name))


@api.post("/jobs/{job_id}/voice-clone")
def job_voice_clone(job_id: str, file: UploadFile = File(...)):
    """Tải mẫu giọng lên và cho giọng đó đọc kịch bản (route đồng bộ: chạy ở threadpool)."""
    raw = _read_upload(file)
    with api_errors():
        return set_job_voice_clone(job_id, import_recording(raw, file.filename or ""))


@api.post("/jobs/{job_id}/voice-clone/clear")
def job_voice_clone_clear(job_id: str):
    with api_errors():
        return clear_job_voice_clone(job_id)


@api.post("/jobs/{job_id}/voice-upload/clear")
def job_voice_upload_clear(job_id: str):
    with api_errors():
        return clear_job_voice_upload(job_id)


@api.post("/jobs/{job_id}/parts/{part_id}/voice-upload")
def voice_upload(job_id: str, part_id: str, file: UploadFile = File(...)):
    """Tải file ghi âm lên làm lời đọc của một phần."""
    raw = _read_upload(file)
    with api_errors():
        return set_voice_upload(job_id, part_id, raw, file.filename or "")


@api.post("/jobs/{job_id}/parts/{part_id}/voice-upload/clear")
def voice_upload_clear(job_id: str, part_id: str):
    with api_errors():
        return clear_voice_upload(job_id, part_id)


@api.patch("/jobs/{job_id}/settings")
def settings(job_id: str, partial: dict):
    with api_errors():
        return update_settings(job_id, partial)


@api.post("/jobs/{job_id}/undo")
def undo_last(job_id: str):
    with api_errors():
        return undo(job_id)


@api.get("/jobs/{job_id}/package")
def package(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    with api_errors():
        path = build_package(job)
    return FileResponse(path, filename=f"VCB_{job_id}_r{job['render']['revision']}.zip", media_type="application/zip")


class ClipStepBody(BaseModel):
    craft_step: Optional[str] = Field(default=None, max_length=40)


@api.patch("/clips/{clip_id}")
def label_clip(clip_id: str, body: ClipStepBody):
    """Gắn công đoạn chế tác cho clip đã kéo về (nung/đánh lửa, cưa, hàn…)."""
    with api_errors():
        return set_clip_craft_step(clip_id, body.craft_step)


@api.get("/ai-models")
def ai_models():
    return {"pricing": load_pricing(), "benchmark": load_benchmark()}


# Quét ổ NAS. Chậm (liệt kê một loại mất khoảng 30 giây) nên chỉ BE gọi lúc đồng bộ,
# web luôn đọc bản đã lưu trong Postgres.
@api.get("/nas/status")
def nas_status():
    return {"mounted": nas_browser.available(), "root": str(nas_browser.NAS)}


@api.get("/nas/scan/products")
def nas_scan_products():
    _require_nas()
    return {"categories": nas_browser.scan_products()}


@api.get("/nas/scan/craft-steps")
def nas_scan_craft_steps(category: str, sku: str):
    _require_nas()
    return {"category": category, "sku": sku, "steps": nas_browser.craft_steps(category, sku)}


@api.get("/nas/scan/huyk-actions")
def nas_scan_huyk_actions():
    _require_nas()
    return {"actions": nas_browser.huyk_actions()}


@api.get("/nas/videos")
def nas_videos(path: str):
    _require_nas()
    return {"videos": nas_browser.videos_in(path)}


class PrepareSource(BaseModel):
    slot: Literal["craft", "huyk", "product", "outro"]
    folder: str = Field(max_length=500)
    name: str = Field(default="", max_length=200)


class PrepareRequest(BaseModel):
    sku: str = Field(max_length=64)
    sources: list[PrepareSource] = Field(max_length=20)


@api.post("/nas/prepare")
def nas_prepare(req: PrepareRequest):
    """Kéo footage của tuyến A4 về máy và dựng proxy. Chậm: mỗi clip vài chục giây."""
    _require_nas()
    sources = [s.model_dump() for s in req.sources]
    if not any(s["slot"] == "outro" for s in sources):
        sources.append({"slot": "outro", "folder": str(nas_browser.OUTRO_ROOT), "name": "outro"})
    with api_errors():
        return prepare(req.sku.strip(), sources)


def _require_nas():
    if not nas_browser.available():
        raise HTTPException(status_code=503, detail="chưa kết nối ổ NAS")


@app.get("/health")
def health():
    return {"status": "ok", "service": "vcb-ai", "claude": claude_available(), "eleven": eleven_enabled()}


app.include_router(api)
app.mount("/media", StaticFiles(directory=MEDIA), name="media")
