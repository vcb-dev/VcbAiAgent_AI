"""FastAPI app for the VCB Video Agent AI service (planner, footage matching, timeline, render).

Called server-to-server by VCB_BE with the X-Assistant-Secret header; /media is public so the
browser can stream proxies and renders through the gateway.

Run (from VCB_AI):  python main.py
"""
import json
from contextlib import contextmanager
from typing import Literal, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app_paths import DATA, MEDIA
from catalog_store import load_catalog, product_sets, public_clip
from internal_auth import require_internal_secret
from job_edit_service import select_option, set_emotion, undo, update_settings
from job_package_export import build_package
from job_service import CLIP_FIELDS, create_job, get_job
from job_settings import DEFAULTS
from music_library import public_tracks
from pricing_store import load_benchmark, load_pricing
from script_planner_claude import claude_available
from video_templates import TEMPLATES
from vo_director import EMOTION_TAGS
from voice_tts import eleven_enabled

app = FastAPI(title="VCB Video Agent AI")
api = APIRouter(prefix="/api", dependencies=[Depends(require_internal_secret)])


class JobRequest(BaseModel):
    script: str = Field(min_length=10, max_length=6000)
    sku: str = ""
    template_id: str = "auto"
    planner: str = "rules"


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
            "emotions": EMOTION_TAGS, "settings_defaults": DEFAULTS,
            "claude_available": claude_available(), "eleven_available": eleven_enabled()}


@api.post("/jobs")
def new_job(req: JobRequest):
    with api_errors():
        return create_job(req.script.strip(), req.sku.strip(), req.template_id, req.planner)


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


@api.get("/ai-models")
def ai_models():
    return {"pricing": load_pricing(), "benchmark": load_benchmark()}


@app.get("/health")
def health():
    return {"status": "ok", "service": "vcb-ai", "claude": claude_available(), "eleven": eleven_enabled()}


app.include_router(api)
app.mount("/media", StaticFiles(directory=MEDIA), name="media")
