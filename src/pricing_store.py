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
