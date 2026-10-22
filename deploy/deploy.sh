#!/usr/bin/env bash
# 在 Mac 上執行：把程式部署／更新到 VM，並把本機的門診手冊上傳到 bucket。
set -euo pipefail
export CLOUDSDK_ACTIVE_CONFIG_NAME=nchu
cd "$(dirname "$0")/.."

PROJECT=${PROJECT:-vghtc-calllight-2026}
ZONE=us-west1-b
VM=vghtc-collector
BUCKET=gs://$PROJECT
SSH=(gcloud compute ssh "$VM" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap --quiet)

"${SSH[@]}" --command="mkdir -p /tmp/vghtc/schedules"
gcloud compute scp --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap --quiet \
  vghtc_collector.py deploy/status.py deploy/backup.sh deploy/install.sh "$VM:/tmp/vghtc/"
gcloud compute scp --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap --quiet \
  schedules/*.pdf "$VM:/tmp/vghtc/schedules/" 2>/dev/null || true
"${SSH[@]}" --command="sudo BUCKET=$BUCKET bash /tmp/vghtc/install.sh /tmp/vghtc"

gcloud storage cp --no-clobber schedules/*.pdf "$BUCKET/schedules/" 2>/dev/null || true
echo "部署完成。看 log：gcloud compute ssh $VM --project=$PROJECT --zone=$ZONE --tunnel-through-iap -- journalctl -u vghtc-collector -f"
