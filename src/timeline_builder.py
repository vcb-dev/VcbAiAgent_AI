"""Turn planned parts (with measured VO + ranked candidates) into a multi-track timeline.

Tracks: video shots, subtitles, VO, SFX, logo overlay, music bed. User choices per shot are kept
across rebuilds (part['choices'][shot_index] = {'kind': 'clip', 'clip_id'} or {'kind': 'gen', 'gen_id'}).
"""
import math

from catalog_store import get_clip
from video_templates import ROLE_TIMING

ILLUSTRATIVE_ROLES = {"content_illustration"}
SFX_BY_STEP = {"nung_nau": "torch", "han": "torch", "do_khuon": "torch", "dap_can": "hammer"}
ON_TOPIC = 0.67     # >= 2 shared keywords between the line and a clip description


def part_duration(part: dict) -> float:
    rule = ROLE_TIMING.get(part["role"], {"min": 3.0})
    vo = (part.get("vo") or {}).get("duration", 0.0)
    return round(max(vo + 0.45, rule["min"]), 2)


def _window(clip: dict, shot_dur: float, prefer_speed: float, reuse: int = 0):
    """Source in-point + speed around the clip's best moment (a different region when reused). None if too short."""
    lo, hi = clip["usable"]
    avail = hi - lo
    speed = prefer_speed if avail >= shot_dur * prefer_speed else avail / shot_dur
    if speed < 0.75:
        return None
    speed = round(min(speed, 2.0), 3)
    need = shot_dur * speed
    center = clip["best_moment_s"] if not reuse else lo + avail * ((0.5 + 0.37 * reuse) % 1.0)
    src_in = min(max(center - need / 2, lo), hi - need)
    return {"src_in": round(max(src_in, 0.0), 3), "speed": speed}


def _pick_clip(shot_dur, part, used, in_part, forced_id=None, forced_speed=None):
    """Best candidate not yet used in the video; then reuse across parts; never twice inside one part."""
    prefer = forced_speed or (1.25 if part["role"] == "craft" else 1.0)
    ids = [forced_id] if forced_id else [c["clip_id"] for c in part.get("candidates", [])]
    for allow_reuse in (False, True):
        for cid in ids:
            if not forced_id and (cid in in_part or (cid in used and not allow_reuse)):
                continue
            clip = get_clip(cid)
            win = clip and _window(clip, shot_dur, prefer, reuse=used.get(cid, 0))
            if win:
                return {"kind": "clip", "clip_id": cid, **win}
    return None


def _wants_generation(part, job):
    """Illustrative parts with no on-topic library footage default to the AI generation option."""
    if not part.get("gen_options"):
        return False
    if part["role"] not in ILLUSTRATIVE_ROLES and not (part["role"] == "hook" and not job.get("sku")):
        return False
    return not any(c.get("text_match", 0) >= ON_TOPIC and not c.get("via_alt") for c in part.get("candidates", []))


def _select_shots(part, dur, used, job):
    """Return (selections, status). Tries fewer shots when there are not enough distinct clips."""
    choices = part.setdefault("choices", {})
    gen_choice = next((c for c in choices.values() if c["kind"] == "gen"), None)
    if gen_choice:
        return [{"kind": "gen", "gen_id": gen_choice["gen_id"]}], "needs_gen"
    clip_choices = {int(k): v for k, v in choices.items() if v["kind"] == "clip"}
    if not clip_choices and _wants_generation(part, job):
        gens = part["gen_options"]
        best = next((g for g in gens if g["type"] in ("illustration", "product_video")), gens[0])   # same kind as the part
        return [{"kind": "gen", "gen_id": best["gen_id"]}], "needs_gen"
    rule = ROLE_TIMING.get(part["role"], {"shot_max": 3.0})
    n_max = 1 if part["role"] == "outro" else max(1, math.ceil(dur / rule["shot_max"]), max(clip_choices, default=-1) + 1)
    reserved = {v["clip_id"] for v in clip_choices.values()}    # user picks are kept out of auto picks
    n_min = max(clip_choices, default=-1) + 1
    for n in range(n_max, max(n_min, 1) - 1, -1):
        sels, in_part, ok = [], set(), True
        for i in range(n):
            choice = clip_choices.get(i, {})
            forced = choice.get("clip_id")
            sel = _pick_clip(dur / n, part, used, in_part | (set() if forced else reserved), forced_id=forced,
                             forced_speed=choice.get("speed"))
            if sel is None:
                ok = False
                break
            if choice.get("zoom"):
                sel["zoom"] = choice["zoom"]          # user punch-in (1.0-1.4)
            in_part.add(sel["clip_id"])
            sels.append(sel)
        if ok:
            return sels, "ok"
    gens = [g for g in part.get("gen_options", []) if g["type"] != "shoot_request"] or part.get("gen_options", [])
    return [{"kind": "gen", "gen_id": gens[0]["gen_id"]} if gens else {"kind": "missing"}], "gap"


def _subtitle_cues(part):
    words = (part.get("vo_text") or "").split()
    vo_dur = (part.get("vo") or {}).get("duration", 0.0)
    if not words or not vo_dur:
        return []
    t, cues = part["start"] + 0.2, []
    for i in range(0, len(words), 8):
        chunk = words[i:i + 8]
        d = vo_dur * len(chunk) / len(words)
        cues.append({"start": round(t, 2), "end": round(t + d, 2), "text": " ".join(chunk)})
        t += d
    return cues


def build_timeline(job: dict) -> dict:
    t, used, shots, subs, vo, sfx, logo, gen_cost = 0.0, {}, [], [], [], [], [], {}
    gens_by_id = {g["gen_id"]: g for p in job["parts"] for g in p.get("gen_options", [])}
    for part in job["parts"]:
        dur = part_duration(part)
        part["start"], part["duration"] = round(t, 2), dur
        sels, part["status"] = _select_shots(part, dur, used, job)
        shot_dur = round(dur / len(sels), 3)
        part["shots"] = []
        for i, sel in enumerate(sels):
            if sel["kind"] == "clip":
                used[sel["clip_id"]] = used.get(sel["clip_id"], 0) + 1
            elif sel["kind"] == "gen":
                gen_cost[sel["gen_id"]] = gens_by_id.get(sel["gen_id"], {}).get("est_cost_usd", 0.0)
            part["shots"].append({"shot_id": f"{part['part_id']}s{i}", "part_id": part["part_id"], "index": i,
                                  "start": round(t + i * shot_dur, 3), "duration": shot_dur, "selected": sel})
        shots += part["shots"]
        subs += _subtitle_cues(part)
        if part.get("vo"):
            vo.append({"part_id": part["part_id"], "start": round(t + 0.2, 2), **part["vo"]})
        kind = "sparkle" if part["role"] == "product_final" else SFX_BY_STEP.get(part.get("craft_step") or "")
        if kind:
            sfx.append({"kind": kind, "start": round(t + 0.15, 2)})
        if part["role"] == "craft":
            logo.append({"start": round(t, 2), "end": round(t + dur, 2)})
        t += dur
    real = sum(1 for s in shots if s["selected"]["kind"] == "clip")
    job["timeline"] = {"duration": round(t, 2), "shots": shots, "subtitles": subs, "vo": vo, "sfx": sfx, "logo": logo}
    job["totals"] = {"duration": round(t, 2), "shots": len(shots), "real_shots": real, "gen_shots": len(shots) - real,
                     "gen_cost_usd": round(sum(gen_cost.values()), 3)}
    return job
