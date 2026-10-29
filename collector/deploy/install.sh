#!/usr/bin/env bash
# 在 VM 上以 root 執行：安裝／更新收集器與排程。可重複執行。由 deploy.sh 呼叫。
#   sudo BUCKET=gs://xxx bash install.sh /tmp/vghtc
set -euo pipefail
SRC=${1:-/tmp/vghtc}
BUCKET=${BUCKET:?需要 BUCKET，例如 gs://vghtc-calllight-2026}
DIR=/opt/vghtc

timedatectl set-timezone Asia/Taipei
id vghtc >/dev/null 2>&1 || useradd --system --home-dir "$DIR" --shell /usr/sbin/nologin vghtc
mkdir -p "$DIR/data" "$DIR/schedules"
install -m 644 "$SRC/vghtc_collector.py" "$SRC/status.py" "$DIR/"
install -m 755 "$SRC/backup.sh" "$DIR/"
cp -n "$SRC"/schedules/*.pdf "$DIR/schedules/" 2>/dev/null || true
chown -R vghtc:vghtc "$DIR/data"

cat > /etc/systemd/system/vghtc-collector.service <<EOF
[Unit]
Description=VGHTC call-light collector
After=network-online.target
Wants=network-online.target

[Service]
User=vghtc
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $DIR/vghtc_collector.py --db $DIR/data/vghtc_calllight.db run
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/vghtc-status.service <<EOF
[Unit]
Description=VGHTC collector status -> bucket

[Service]
Type=oneshot
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/status.py --db $DIR/data/vghtc_calllight.db --out $DIR/status.json --schedules $DIR/schedules --bucket $BUCKET
EOF

cat > /etc/systemd/system/vghtc-status.timer <<EOF
[Unit]
Description=Run vghtc-status every 5 minutes

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/vghtc-backup.service <<EOF
[Unit]
Description=VGHTC daily backup + monthly handbook

[Service]
Type=oneshot
Environment=BUCKET=$BUCKET
ExecStart=/bin/bash $DIR/backup.sh
EOF

cat > /etc/systemd/system/vghtc-backup.timer <<EOF
[Unit]
Description=Run vghtc-backup daily at 23:30 (Asia/Taipei)

[Timer]
OnCalendar=*-*-* 23:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now vghtc-status.timer vghtc-backup.timer
systemctl enable vghtc-collector.service
systemctl restart vghtc-collector.service
sleep 3
systemctl start vghtc-status.service   # 立刻上傳一份狀態
systemctl --no-pager --lines=3 status vghtc-collector.service || true
