"""AI model pricing options (data/ai-models-pricing.json) + benchmark results for cost estimates and the UI."""
import json
from functools import lru_cache

from app_paths import DATA


@lru_cache(maxsize=1)
def load_pricing() -> dict:
    return json.loads((DATA / "ai-models-pricing.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_benchmark() -> dict:
    path = DATA / "benchmark-results.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    blind = DATA / "benchmarks" / "planning_blind_summary.json"
    if blind.exists():
        data["planning_blind"] = json.loads(blind.read_text(encoding="utf-8"))
    return data


def recommended(activity: str) -> dict:
    opts = [o for o in load_pricing()["options"] if o["activity"] == activity]
    return next((o for o in opts if o["recommended"]), opts[0] if opts else {})


def unit_price(option: dict, unit: str) -> float:
    """Vendor price for one unit (e.g. 'per_second_video'); 0.0 when the option has no such price."""
    for p in option.get("prices", []):
        if p["unit"] == unit and p["usd"] is not None:
            return float(p["usd"])
    return 0.0


def short_name(option: dict) -> str:
    model = option.get("model", "").split(" (")[0]
    return f"{option.get('provider', '')} · {model}".strip(" ·")


def tts_option_for(provider: str) -> dict:
    """Chọn dòng giá TTS khớp giọng thật sự đã đọc, không lấy recommended mặc định (ElevenLabs)."""
    raw = (provider or "").lower()
    opts = [o for o in load_pricing()["options"] if o["activity"] == "tts"]
    if raw.startswith("minimax"):
        model = raw.split(":", 1)[-1] if ":" in raw else ""
        minimax = [o for o in opts if o.get("provider") == "MiniMax"]
        if "turbo" in model:
            return next((o for o in minimax if "turbo" in (o.get("model") or "").lower()),
                        minimax[0] if minimax else {})
        return next((o for o in minimax if "hd" in (o.get("model") or "").lower()),
                    minimax[0] if minimax else {})
    if raw.startswith("eleven"):
        eleven = [o for o in opts if o.get("provider") == "ElevenLabs"]
        return next((o for o in eleven if o.get("recommended")), eleven[0] if eleven else {})
    return {}
