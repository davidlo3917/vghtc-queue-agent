#!/usr/bin/env bash
# 每天備份 SQLite 到 bucket；每月 2 號（或本月檔還沒有時）順便存一份門診手冊。VM 上由 systemd timer 執行。
set -euo pipefail
DIR=/opt/vghtc
DB=$DIR/data/vghtc_calllight.db
BUCKET=${BUCKET:?需要 BUCKET，例如 gs://vghtc-calllight-2026}
TODAY=$(date +%F)
MONTH=$(date +%Y-%m)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$DB" "$tmp/vghtc_calllight_$TODAY.db" <<'EOF'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)   # 線上備份，不影響正在寫入的收集器
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
EOF
gzip -f "$tmp/vghtc_calllight_$TODAY.db"
gcloud storage cp "$tmp/vghtc_calllight_$TODAY.db.gz" "$BUCKET/backups/"
echo "備份完成 $TODAY"

mkdir -p "$DIR/schedules"
PDF=$DIR/schedules/handbook_$MONTH.pdf
if [ "$(date +%d)" = "02" ] || [ ! -f "$PDF" ]; then
  if curl -fsSL -A "Mozilla/5.0" -o "$PDF.part" https://www3.vghtc.gov.tw/cc4f/reg_schedular.pdf; then
    mv "$PDF.part" "$PDF"
    gcloud storage cp "$PDF" "$BUCKET/schedules/"
    echo "門診手冊 $MONTH 已存檔"
  else
    rm -f "$PDF.part"
    echo "門診手冊下載失敗，下次再試" >&2
  fi
fi
