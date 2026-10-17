#!/bin/bash
# Canh ổ NAS: khi được gắn lại thì kéo tiếp clip chế tác, mất kết nối thì chờ và chạy lại.
# Tự dừng khi tới mốc giờ trong DEADLINE (dạng HH:MM, bỏ trống = chạy tới khi xong).
cd /Users/macbook/vcb-video-agent/VCB_AI || exit 1
NAS="/Volumes/MEDIA VCB folder"
WORKERS="${WORKERS:-10}"
DEADLINE="${DEADLINE:-}"

stop_at=0
if [ -n "$DEADLINE" ]; then
  stop_at=$(date -j -f "%Y-%m-%d %H:%M" "$(date '+%Y-%m-%d') $DEADLINE" "+%s" 2>/dev/null)
  echo "[$(date '+%H:%M:%S')] sẽ tự dừng lúc $DEADLINE, chạy $WORKERS luồng"
fi

expired() { [ "$stop_at" -gt 0 ] && [ "$(date '+%s')" -ge "$stop_at" ]; }

while true; do
  if expired; then
    echo "[$(date '+%H:%M:%S')] tới mốc $DEADLINE — dừng"
    exit 0
  fi

  if [ -d "$NAS" ] && ls "$NAS" >/dev/null 2>&1; then
    echo "[$(date '+%H:%M:%S')] ổ NAS đã gắn — bắt đầu kéo clip chế tác"
    env -u PORT -u HOST python3 -u indexer/preload_proxies.py \
      --kinds craft --per-folder 0 --max-steps 0 --workers "$WORKERS" &
    pull=$!

    # Canh mốc giờ trong lúc kéo: hết giờ thì cắt ngay chứ không đợi kéo xong.
    while kill -0 "$pull" 2>/dev/null; do
      if expired; then
        echo "[$(date '+%H:%M:%S')] tới mốc $DEADLINE — dừng tiến trình đang kéo"
        pkill -P "$pull" 2>/dev/null
        kill "$pull" 2>/dev/null
        sleep 3
        pkill -f 'ffmpeg.*MEDIA VCB' 2>/dev/null
        exit 0
      fi
      sleep 10
    done

    wait "$pull"; code=$?
    if [ $code -eq 0 ]; then
      echo "[$(date '+%H:%M:%S')] kéo xong toàn bộ"
      exit 0
    fi
    echo "[$(date '+%H:%M:%S')] dừng giữa chừng (mã $code) — chờ ổ NAS rồi chạy lại"
  else
    echo "[$(date '+%H:%M:%S')] chưa thấy ổ NAS, chờ 15 giây..."
  fi
  sleep 15
done
