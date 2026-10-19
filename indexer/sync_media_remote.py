"""Đẩy lên server chỉ file proxy/thumbs chưa có — không up lại cả kho.

Khi vài mã mới đủ source: nén proxy local rồi chạy script này. SSH so list
trên volume với máy, tar từng lô nhỏ những file thiếu.

  python indexer/sync_media_remote.py
  python indexer/sync_media_remote.py --host vcb-ai --batch 10

Cần SSH host (mặc định `vcb-ai` trong ~/.ssh/config sau `railway ssh config`).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "media"


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S "), msg, sep="", flush=True)


def ssh_cmd(host: str, identity: str | None) -> list[str]:
    cmd = [
        "ssh",
        "-o", "ServerAliveInterval=10",
        "-o", "ServerAliveCountMax=8",
        "-o", "ConnectTimeout=30",
        "-o", "TCPKeepAlive=yes",
        host,
    ]
    if identity:
        cmd[1:1] = ["-i", identity]
    return cmd


def remote_list(ssh: list[str], directory: str) -> set[str]:
    out = subprocess.check_output(ssh + [f"mkdir -p {directory} && ls {directory}"], text=True, timeout=90)
    return {line.strip() for line in out.splitlines() if line.strip()}


def missing(local_dir: Path, remote_names: set[str]) -> list[str]:
    return sorted(n for n in os.listdir(local_dir) if n not in remote_names and not n.startswith("."))


def upload_batch(ssh: list[str], local_dir: Path, remote_dir: str, names: list[str]) -> None:
    env = os.environ.copy()
    env["COPYFILE_DISABLE"] = "1"
    tar = subprocess.Popen(["tar", "-cf", "-", *names], cwd=local_dir, stdout=subprocess.PIPE, env=env)
    remote = subprocess.Popen(ssh + [f"mkdir -p {remote_dir} && tar xf - -C {remote_dir}"], stdin=tar.stdout)
    if tar.stdout:
        tar.stdout.close()
    ssh_code = remote.wait()
    tar_code = tar.wait()
    if ssh_code != 0 or tar_code != 0:
        raise RuntimeError(f"tar={tar_code} ssh={ssh_code}")


def sync_dir(ssh: list[str], kind: str, local_dir: Path, remote_dir: str, batch: int) -> None:
    if not local_dir.is_dir():
        log(f"bỏ {kind}: không có {local_dir}")
        return
    while True:
        have_remote = remote_list(ssh, remote_dir)
        left = missing(local_dir, have_remote)
        log(f"{kind}: trên server {len(have_remote)} · thiếu {len(left)}")
        if not left:
            return
        chunk = left[:batch]
        delay = 8
        for attempt in range(1, 8):
            try:
                log(f"{kind}: up {len(chunk)} file (vd {chunk[0]}) lần {attempt}")
                upload_batch(ssh, local_dir, remote_dir, chunk)
                log(f"{kind}: ok")
                break
            except Exception as exc:
                log(f"{kind}: lỗi {exc}")
                if attempt == 7:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 90)


def main() -> int:
    p = argparse.ArgumentParser(description="Chỉ đẩy proxy/thumbs chưa có trên volume.")
    p.add_argument("--host", default=os.environ.get("VCB_SSH_HOST", "vcb-ai"))
    p.add_argument("--identity", default=os.environ.get("VCB_SSH_IDENTITY", str(Path.home() / ".ssh/railway_vcb")))
    p.add_argument("--remote-media", default=os.environ.get("VCB_REMOTE_MEDIA", "/app/media"))
    p.add_argument("--batch", type=int, default=10)
    args = p.parse_args()
    identity = args.identity if args.identity and Path(args.identity).exists() else None
    ssh = ssh_cmd(args.host, identity)
    try:
        sync_dir(ssh, "thumbs", MEDIA / "thumbs", f"{args.remote_media.rstrip('/')}/thumbs", args.batch)
        sync_dir(ssh, "music", MEDIA / "music", f"{args.remote_media.rstrip('/')}/music", args.batch)
        sync_dir(ssh, "proxy", MEDIA / "proxy", f"{args.remote_media.rstrip('/')}/proxy", args.batch)
    except subprocess.CalledProcessError as exc:
        log(f"không SSH được {args.host}: {exc}")
        return 1
    log("xong — chỉ file mới được đẩy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
