"""Kéo trước proxy cho cả kho, để lúc dựng video không phải chờ ổ NAS nữa.

Chạy một lần (dài, nhưng chạy nền được) thay vì bắt editor chờ vài phút mỗi lần gặp
mã mới. Script dừng giữa chừng rồi chạy lại cũng được: thư mục nào đã có clip trong
catalog thì bỏ qua.

Hai điều quyết định tốc độ:
  - Không hỏi kích thước từng file. Trên SMB mỗi lần hỏi mất cả giây, 900 file là kẹt
    hơn mười phút trước khi tải được clip đầu tiên; cứ lấy file đầu theo thứ tự tên.
  - Chạy nhiều clip song song. Thời gian hầu hết là chờ mạng chứ không phải nén, nên
    tăng số luồng thì thông lượng tăng gần như tuyến tính.
"""
import argparse
import csv
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_media_index as indexer  # noqa: E402
from catalog_store import load_catalog  # noqa: E402
from nas_browser import CATEGORIES, OUTRO_ROOT, craft_steps, huyk_actions, products  # noqa: E402
from nas_prepare import _append_to_catalog, _catalog_entry, _videos_under  # noqa: E402

lock = threading.Lock()


def _pick(folder: str, want: int) -> list:
    """Clip trong thư mục; `want` = 0 nghĩa là lấy hết, không chỉ vài cái đại diện.

    Không gọi stat để khỏi kẹt ở bước quét. Dùng _videos_under chứ không phải videos_in:
    thư mục cảnh sản phẩm bọc thêm một lớp buổi quay ('N0006_Nhan-tang-hinh/260701_N0006
    _..._DTA01/'), nhìn ở tầng ngoài thì tưởng rỗng và bỏ sót gần hết kho.
    """
    found = _videos_under(folder)
    return [Path(p) for p in (found if want <= 0 else found[:want])]


def _spread(steps: list, keep: int) -> list:
    """Giữ lại `keep` công đoạn trải đều từ đầu tới cuối quy trình.

    Mỗi sản phẩm có tới ba chục thư mục công đoạn, mà tuyến A4 chỉ chèn bốn cảnh. Lấy
    trải đều thay vì lấy mấy cái đầu để video vẫn kể được từ phôi thô tới thành phẩm.
    """
    if keep <= 0 or len(steps) <= keep:
        return steps
    return [steps[round(i * (len(steps) - 1) / (keep - 1))] for i in range(keep)]


def _load_skus(path: str) -> set:
    """Đọc danh sách mã từ file: một mã một dòng, hoặc CSV có cột `sku`."""
    if not path:
        return set()
    with Path(path).open(encoding="utf-8", newline="") as fh:
        sample = fh.read(256)
        fh.seek(0)
        if "sku" in sample.splitlines()[0].lower():
            return {row["sku"].strip() for row in csv.DictReader(fh) if row.get("sku")}
        return {ln.split(",")[0].strip() for ln in fh if ln.strip() and not ln.startswith("#")}


def iter_jobs(kinds: set, per_folder: int, limit_products: int, max_steps: int, only_skus: set):
    """Sinh dần (slot, mã sản phẩm, tên công đoạn, file) cần kéo.

    Trả về theo kiểu sinh dần chứ không gom thành danh sách: quét hết 334 sản phẩm trên
    SMB mất rất lâu, mà tải thì có thể bắt đầu ngay từ sản phẩm đầu tiên.
    """
    if "huyk" in kinds:
        for a in huyk_actions():
            for p in _pick(a["path"], per_folder):
                yield "huyk", None, a["name"], p

    # Kho outro dùng chung cho mọi mã, nằm gọn trong một thư mục. Cần nhiều clip vì dựng
    # hàng loạt đòi mỗi video một outro riêng.
    if "outro" in kinds:
        for p in _pick(str(OUTRO_ROOT), per_folder):
            yield "outro", None, "outro", p

    if kinds & {"craft", "product"}:
        for cat in CATEGORIES:
            items = products(cat["id"])
            picked = [p for p in items if not only_skus or p["sku"] in only_skus]
            for prod in picked[:limit_products] if limit_products else picked:
                if "product" in kinds:
                    for folder in prod["paths"]:
                        for p in _pick(folder, per_folder):
                            yield "product", prod["sku"], prod["name"], p
                if "craft" in kinds:
                    for step in _spread(craft_steps(cat["id"], prod["sku"]), max_steps):
                        for p in _pick(step["path"], per_folder):
                            yield "craft", prod["sku"], step["name"], p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", default="huyk,craft,product", help="huyk / craft / product / outro")
    ap.add_argument("--per-folder", type=int, default=1, help="số clip lấy mỗi thư mục; 0 = lấy hết")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit-products", type=int, default=0, help="0 = toàn bộ")
    ap.add_argument("--max-steps", type=int, default=6,
                    help="số công đoạn chế tác giữ lại mỗi sản phẩm, trải đều; 0 = tất cả")
    ap.add_argument("--skus-file", default="", help="chỉ kéo các mã trong file này (CSV có cột sku)")
    args = ap.parse_args()

    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    only_skus = _load_skus(args.skus_file)
    have = {c["file"] for c in load_catalog().values()}

    # index_clip đọc hai cờ này ở cấp module; đặt sẵn một lần để các luồng không tráo
    # biến dùng chung giữa chừng.
    indexer.CATALOG_ONLY = False
    indexer.should_segment = lambda *a, **k: (False, "on_demand")
    indexer.PROXY_MAX_S = 40
    indexer.SKIP_SHEETS = True

    added, failed, started = [], [], time.time()
    pending = {}

    def run(job):
        slot, sku, name, path = job
        return _catalog_entry(path, slot, name, sku or "")

    def harvest(fut):
        slot, sku, name, _ = pending.pop(fut)
        try:
            entries = fut.result()
            with lock:
                added.extend(entries)
                if len(added) % 25 == 0:
                    _append_to_catalog(added[-25:])   # ghi dần, dừng giữa chừng vẫn giữ được
            status = f"+{len(entries)}"
        except (RuntimeError, OSError, ValueError) as exc:
            failed.append({"folder": name, "error": str(exc)[:140]})
            status = "lỗi"
        n = len(added) + len(failed)
        print(f"[{n}] {slot} {sku or ''} · {name[:28]} · {status} "
              f"· {(time.time()-started)/60:.0f}p · {n/max((time.time()-started)/60, .1):.1f} clip/phút",
              flush=True)

    scope = f"{len(only_skus)} mã trong {args.skus_file}" if only_skus else "mọi mã"
    print(f"bắt đầu kéo, {args.workers} luồng · {scope} · {kinds}\n", flush=True)
    seen = skipped = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for job in iter_jobs(kinds, args.per_folder, args.limit_products, args.max_steps, only_skus):
            seen += 1
            if str(job[3]) in have:
                skipped += 1
                # Quét qua phần đã kéo hôm trước thì không tải gì cả. Không báo thì nhìn
                # như treo, vì có khi cả nghìn clip liền nhau đều đã có sẵn.
                if skipped % 100 == 0:
                    print(f"… đã quét {seen}, bỏ qua {skipped} clip có sẵn", flush=True)
                continue
            # Giữ hàng đợi vừa đủ bận: nạp sẵn cả nghìn việc thì quét chặn mất, mà
            # quét tiếp ngay thì luồng tải lại rảnh.
            while len(pending) >= args.workers * 2:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    harvest(fut)
            pending[pool.submit(run, job)] = job

        for fut in as_completed(list(pending)):
            harvest(fut)

    if added:
        _append_to_catalog(added)
    print(f"\nxong: thêm {len(added)} clip · lỗi {len(failed)} · {(time.time()-started)/60:.0f} phút")
    for f in failed[:15]:
        print(f"  {f['folder']}: {f['error']}")


if __name__ == "__main__":
    main()
