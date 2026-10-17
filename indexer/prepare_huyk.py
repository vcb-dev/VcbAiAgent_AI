"""Kéo trước proxy cho kho hành động HuyK.

Khác với cảnh chế tác (gắn với từng mã sản phẩm), hành động HuyK dùng chung cho mọi
video, nên kéo một lần là tuyến A4 của mã nào cũng chọn được. Mỗi thư mục chỉ lấy vài
clip đại diện — tuyến A4 chỉ chèn 2 cảnh HuyK nên không cần cả 895 clip.

Thời gian gần như toàn bộ là chờ đọc qua SMB chứ không phải nén, nên chạy nhiều luồng
cùng lúc nhanh hơn hẳn chạy lần lượt.
"""
import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_media_index as indexer  # noqa: E402
from catalog_store import load_catalog  # noqa: E402
from nas_browser import HUYK_ROOT, _subdirs, videos_in  # noqa: E402
from nas_prepare import MAX_BYTES, MIN_BYTES, _append_to_catalog, _catalog_entry  # noqa: E402

print_lock = threading.Lock()


def pick_clips(folder: Path, want: int) -> list:
    """Vài clip nhỏ nhất trong khoảng hợp lệ — nhỏ thì tải nhanh mà vẫn đủ dùng."""
    sized = sorted((p.stat().st_size, p) for p in map(Path, videos_in(str(folder))))
    good = [p for size, p in sized if MIN_BYTES <= size <= MAX_BYTES]
    return (good or [p for _, p in sized])[:want]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-folder", type=int, default=2, help="số clip lấy mỗi thư mục hành động")
    ap.add_argument("--workers", type=int, default=6, help="số clip tải song song")
    args = ap.parse_args()

    have = {c["file"] for c in load_catalog().values()}
    jobs = []
    for d in _subdirs(HUYK_ROOT):
        chosen = [p for p in pick_clips(d, args.per_folder) if str(p) not in have]
        jobs.extend((d.name, p) for p in chosen)

    print(f"{len(jobs)} clip cần kéo từ {HUYK_ROOT.name}, chạy {args.workers} luồng song song")
    if not jobs:
        return

    # index_clip đọc cờ này ở cấp module; đặt sẵn một lần để các luồng không phải tráo
    # biến dùng chung giữa chừng.
    indexer.CATALOG_ONLY = False
    indexer.should_segment = lambda *a, **k: (False, "on_demand")

    added, failed = [], []

    def run(job):
        name, path = job
        return name, _catalog_entry(path, "huyk", name)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run, j): j for j in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            name, path = futures[fut]
            try:
                _, entries = fut.result()
                added.extend(entries)
                status = f"+{len(entries)}"
            except (RuntimeError, OSError, ValueError) as exc:
                failed.append({"folder": name, "error": str(exc)[:160]})
                status = "lỗi"
            with print_lock:
                print(f"  [{i}/{len(jobs)}] {name} · {path.name} · {status}", flush=True)

    if added:
        _append_to_catalog(added)
    print(f"\nxong: thêm {len(added)} clip · lỗi {len(failed)}")
    for f in failed[:10]:
        print(f"  {f['folder']}: {f['error']}")


if __name__ == "__main__":
    main()
