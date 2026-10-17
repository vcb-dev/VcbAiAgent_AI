"""Kéo sẵn footage tuyến A4 cho vài mã để có cái test ngay.

Kho HuyK và outro dùng chung cho mọi sản phẩm nên chỉ kéo một lần; mỗi mã sau đó chỉ
cần thêm 4 cảnh chế tác và 1 cảnh sản phẩm. Chạy trực tiếp, không qua BE, để không bị
timeout HTTP khi ổ mạng chậm.

    python3 indexer/prepare_test_products.py N0017 N0012 --category 1
"""
import argparse
import random
import sys
import time
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MVP / "src"))

import nas_browser as nb          # noqa: E402
from nas_prepare import prepare   # noqa: E402

CRAFT_SLOTS = 4
HUYK_SLOTS = 2


def spread_pick(items, count):
    """Chia thành `count` chặng rồi bốc mỗi chặng một cái, để trải đều quy trình."""
    if len(items) <= count:
        return items
    size = len(items) / count
    out = []
    for i in range(count):
        start, end = int(i * size), max(int(i * size) + 1, int((i + 1) * size))
        out.append(random.choice(items[start:end]))
    return out


def plan_for(category: str, sku: str) -> list:
    steps = nb.craft_steps(category, sku)
    if not steps:
        return []
    shoot = random.choice(sorted({s["shoot"] for s in steps}))
    in_shoot = [s for s in steps if s["shoot"] == shoot]

    sources = [{"slot": "craft", "folder": s["path"], "name": s["name"]}
               for s in spread_pick(in_shoot, CRAFT_SLOTS)]
    sources += [{"slot": "huyk", "folder": a["path"], "name": a["name"]}
                for a in random.sample(nb.huyk_actions(), HUYK_SLOTS)]
    for p in nb.products(category):
        if p["sku"] == sku:
            sources += [{"slot": "product", "folder": f, "name": sku} for f in p["paths"]]
            break
    return sources


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("skus", nargs="+")
    ap.add_argument("--category", default="1")
    args = ap.parse_args()

    for sku in args.skus:
        t0 = time.time()
        print(f"\n=== {sku} ===", flush=True)
        sources = plan_for(args.category, sku)
        if not sources:
            print("  không có source chế tác, bỏ qua", flush=True)
            continue
        print(f"  {len(sources)} thư mục nguồn, đang kéo về…", flush=True)
        res = prepare(sku, sources)
        print(f"  thêm {res['added']} clip · bỏ qua {res['skipped']} · lỗi {len(res['failed'])} "
              f"· {time.time() - t0:.0f}s", flush=True)
        for f in res["failed"]:
            print(f"    lỗi: {f['error'][:120]}", flush=True)


if __name__ == "__main__":
    main()
