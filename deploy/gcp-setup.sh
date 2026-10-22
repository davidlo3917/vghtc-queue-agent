#!/usr/bin/env bash
# 建立收集器需要的 GCP 資源（學校帳號，gcloud 設定 nchu）。可重複執行，已存在的資源會跳過。
set -euo pipefail
export CLOUDSDK_ACTIVE_CONFIG_NAME=nchu
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

PROJECT=${PROJECT:-vghtc-calllight-2026}
ORG=258021590271
BILLING=01440F-C4ADA7-7F7A92
REGION=us-west1          # 永久免費層的 e2-micro 只在 us-west1 / us-central1 / us-east1
ZONE=us-west1-b
BUCKET=gs://$PROJECT

g() { gcloud --project="$PROJECT" "$@"; }

echo "== 專案"
gcloud projects describe "$PROJECT" >/dev/null 2>&1 \
  || gcloud projects create "$PROJECT" --name="VGHTC Call-Light Collector" --organization="$ORG"
gcloud config set project "$PROJECT"
gcloud config set compute/zone "$ZONE"
gcloud config set compute/region "$REGION"
gcloud billing projects link "$PROJECT" --billing-account="$BILLING"

echo "== API"
g services enable compute.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com iap.googleapis.com

echo "== 網路（自建，不依賴 default 網路；只開 IAP 來源的 SSH）"
g compute networks describe vghtc-net >/dev/null 2>&1 \
  || g compute networks create vghtc-net --subnet-mode=custom
g compute networks subnets describe vghtc-subnet --region="$REGION" >/dev/null 2>&1 \
  || g compute networks subnets create vghtc-subnet --network=vghtc-net --region="$REGION" \
       --range=10.10.0.0/24 --enable-private-ip-google-access
g compute firewall-rules describe vghtc-allow-iap-ssh >/dev/null 2>&1 \
  || g compute firewall-rules create vghtc-allow-iap-ssh --network=vghtc-net --direction=INGRESS \
       --allow=tcp:22 --source-ranges=35.235.240.0/20

echo "== 服務帳號"
for sa in vghtc-vm vghtc-dashboard; do
  g iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com" >/dev/null 2>&1 \
    || g iam service-accounts create "$sa" --display-name="$sa"
done

echo "== Bucket（狀態、備份、門診手冊）"
gcloud storage buckets describe "$BUCKET" >/dev/null 2>&1 \
  || gcloud storage buckets create "$BUCKET" --project="$PROJECT" --location="$REGION" \
       --uniform-bucket-level-access --public-access-prevention
lifecycle=$(mktemp)
echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":60,"matchesPrefix":["backups/"]}}]}' > "$lifecycle"
gcloud storage buckets update "$BUCKET" --lifecycle-file="$lifecycle"
rm -f "$lifecycle"
gcloud storage buckets add-iam-policy-binding "$BUCKET" \
  --member="serviceAccount:vghtc-vm@$PROJECT.iam.gserviceaccount.com" --role=roles/storage.objectAdmin >/dev/null
gcloud storage buckets add-iam-policy-binding "$BUCKET" \
  --member="serviceAccount:vghtc-dashboard@$PROJECT.iam.gserviceaccount.com" --role=roles/storage.objectViewer >/dev/null

echo "== VM（e2-micro 免費層）"
g compute instances describe vghtc-collector --zone="$ZONE" >/dev/null 2>&1 \
  || g compute instances create vghtc-collector --zone="$ZONE" --machine-type=e2-micro \
       --image-family=debian-12 --image-project=debian-cloud \
       --boot-disk-size=30GB --boot-disk-type=pd-standard \
       --network=vghtc-net --subnet=vghtc-subnet \
       --service-account="vghtc-vm@$PROJECT.iam.gserviceaccount.com" --scopes=cloud-platform \
       --shielded-secure-boot

echo "== 完成"
g compute instances list
