#!/bin/bash
# Kéo toàn bộ source về proxy: outro, HuyK thao tác, cảnh sản phẩm và chế tác.
#
# Chỉ kéo 52 mã đã có footage chế tác trên ổ (data/ma-co-che-tac.csv). 282 mã còn lại
# không có folder công đoạn nên bỏ qua, để toàn bộ băng thông dồn vào nhóm dựng được.
#
# Mất ổ giữa chừng thì chờ gắn lại rồi kéo tiếp đúng đợt đang dở. Clip nào đã có trong
# catalog thì bỏ qua, nên chạy lại bao nhiêu lần cũng được.
cd /Users/macbook/vcb-video-agent/VCB_AI || exit 1
NAS="${VCB_NAS_ROOT:-/Volumes/MEDIA VCB folder}"
WORKERS="${WORKERS:-14}"

mounted() { [ -d "$NAS" ] && ls "$NAS" >/dev/null 2>&1; }

wait_nas() {
  local waited=0
  until mounted; do
    [ $((waited % 60)) -eq 0 ] && echo "[$(date '+%H:%M:%S')] chưa thấy ổ NAS — chờ bạn kết nối lại…"
    sleep 15
    waited=$((waited + 15))
  done
}

# Chạy một đợt tới khi thật sự xong. Ổ rụng giữa chừng thì script python vẫn thoát bình
# thường (mọi clip đều lỗi đọc), nên phải tự kiểm tra ổ còn gắn thì mới coi là xong.
run_wave() {
  local label="$1"; shift
  while true; do
    wait_nas
    echo "[$(date '+%H:%M:%S')] ▶ $label"
    env -u PORT -u HOST python3 -u indexer/preload_proxies.py --workers "$WORKERS" "$@"
    mounted && break
    echo "[$(date '+%H:%M:%S')] mất ổ giữa chừng — chờ gắn lại rồi kéo tiếp: $label"
    sleep 15
  done
  echo "[$(date '+%H:%M:%S')] ✔ xong: $label"
}

SKUS="data/ma-co-che-tac.csv"
echo "[$(date '+%H:%M:%S')] kéo hết 52 mã có chế tác · $WORKERS luồng · ổ: $NAS"
run_wave "outro — kho chung"                         --kinds outro   --per-folder 0
run_wave "sản phẩm hoàn thiện — hết clip của 52 mã"  --kinds product --per-folder 0 --skus-file "$SKUS"
run_wave "HuyK — toàn bộ clip"                       --kinds huyk    --per-folder 0
run_wave "chế tác — hết clip của 52 mã"              --kinds craft   --per-folder 0 --max-steps 0 --skus-file "$SKUS"
echo "[$(date '+%H:%M:%S')] ✅ kéo xong 52 mã có chế tác"
