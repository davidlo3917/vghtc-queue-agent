# Handoff — 台中榮總門診燈號收集器（vghtc_collector）

寫於 2026-10-26。給接手的 agent。使用者是 David（以中文溝通，zh-TW）。

## 一句話

一支純標準函式庫的 Python 收集器，每分鐘從台中榮總公開 API 抓全院門診燈號存 SQLite，2026-10-22 12:20 起在 GCP 免費層上 24/7 跑；目標是之後訓練「給定診間、午別、號碼 N，預測 N 還要多久被叫到」的模型。目前階段：**收資料，等一兩週後開始分析／建模**。

## 先讀這些（不要重複讀整個對話的內容，都在檔案裡）

- `/Users/david/Desktop/0_myprojects/vghtc_collector/README.md` — 專案的唯一知識庫：API 欄位與**已驗證的欄位意義**、資料怪癖、資料庫結構、分析時的約定、部署方式與所有指令、第一天的觀察。**先讀完它。**
- `vghtc_collector.py`（收集器）、`deploy/`（gcp-setup / install / deploy / status.py / backup.sh）、`dashboard/app.py`（監控網頁）。每支非平凡的程式都有 `--selftest`。
- 原始部署計畫：`/Users/david/.claude/plans/rippling-honking-clover.md`
- git：本機 repo，`main`，2 個 commit（`52421fe` 初始、`15afa54` 第一天發現）。**沒有 remote**，使用者還沒說要推去哪。
- 記憶：`~/.claude/projects/-Users-david-Desktop-0-myprojects-vghtc-collector/memory/`（目前一條：David 要求在執行前與完工時做 review / double-check）。

## 現在的狀態

- 收集器：GCP 專案 `vghtc-calllight-2026`，VM `vghtc-collector`（us-west1-b, e2-micro），gcloud 設定名稱 **`nchu`**（學校帳號 `davidlo@smail.nchu.edu.tw`）。所有 gcloud 指令要加 `--configuration=nchu` 或 `CLOUDSDK_ACTIVE_CONFIG_NAME=nchu`；使用者的預設設定是公司的 `company`，**不要改掉**。
- 監控網頁（IAP，只開給學校帳號）：https://vghtc-dashboard-552588620281.us-west1.run.app（`/`、`/data`、`/data.csv`、`/backup/latest`、`/status.json`）。
- Bucket `gs://vghtc-calllight-2026`：`status.json`（每 5 分鐘）、`backups/`（每天 23:30，保留 60 天）、`schedules/handbook_YYYY-MM.pdf`（每月 2 號）。
- 10/22 收了 5 小時：301 輪零失敗、5,310 筆變化；之後幾天的狀況請開監控網頁或下載備份確認（我沒看過 10/23 之後的資料）。

## 關鍵決定與理由（README 沒有完整寫到「為什麼」的部分）

1. **每輪只打一次 API**（`OPDSection=""` 回全院）而非 53 科逐科查：實測內容一致，只少 13 間檢查室（沒午別沒號碼）；對醫院負擔降 50 倍，全院同秒取樣。
2. **只存變化 + `seen_since`**：變化精確落在 `(seen_since, ts]`，不用存每輪快照。
3. **診次 key 含 `section`**：防同一診間被兩科列出時互相覆蓋。
4. **監控網頁讀 bucket 不連 VM**：VM 死掉時頁面仍可開並變紅。
5. **GCP 而非 Oracle/Fly/Hetzner**：學校帳號有試用額度 + 永久免費層；e2-micro 只在 us-west1/central1/east1 免費。
6. **IAP 直接掛 Cloud Run**（`--iap`），不需負載平衡器、不自己寫登入。

## 沒寫在 README 的研究摘要（10/22 做的文獻與外部資料調查）

- 文獻一致：最強特徵是即時佇列狀態；滾動平均是所有論文的 baseline；要用分位數（P80），低估比高估傷人；模型在醫院間不可移植 → 醫師／診間個別效應必須學。
  - Ang et al. 2016 Q-Lasso (M&SOM) https://pubsonline.informs.org/doi/10.1287/msom.2015.0560
  - Pak, Gannon, Staib 2021（ML + 分位數）https://researchonline.jcu.edu.au/65500/
  - 韓國門診 SHAP 2024 https://link.springer.com/article/10.1007/s10729-024-09676-5
  - JMIR Med Inform 2025 兒童醫院 https://medinform.jmir.org/2025/1/e77297
  - Senderovich Queue Mining（多類別插隊，最貼近榮總結構）https://aviman.technion.ac.il/files/References/paper_multiclass.pdf
- 外部資料結論：唯一「不存就沒了」的是每月門診手冊 PDF（已自動存檔）；假日、天氣、疫情都可事後補、價值小；掛號系統預約人數沒有公開 API、牽涉個資，**不要爬**。
- 叫號規則：找到的是**台北榮總**公告（85 歲以上，每看 2 位正常號後依序 1 位榮民長者、1 位非榮民長者、1 位過號者）。台中榮總的規則**未驗證**；README 開頭「83 歲」是使用者自己的說法，來源不明。
- 台灣沒有找到用看診進度資料做預測的論文；各醫院的「預估看診時間」都註明僅供參考、沒公開算法。

## 待辦與風險（按重要性）

1. **⚠ 2026-12-20 前**要在 GCP Console 把試用帳單帳戶「啟用完整帳戶」，否則 VM 會停。監控網頁有倒數。
2. 兩天後看帳單，確認除了 VM 外部 IPv4（最多 US$3.65/月）之外是 0。
3. 收滿一週後重跑 10/22 那套分析（上午診、週六是否一樣；每號分鐘、跳號比例、停滯），**那套分析是臨時腳本沒存進 repo**，重做時建議存成 `analysis/first_look.py`。
4. 之後的建模順序（README「下一步」）：每位醫師看診速度 → baseline（前面人數 × 今天速率）→ LightGBM 分位數。注意 `CUR_WAITING_CNT` 是「現場人數」不是「前面人數」，`DELAY_WAITING_CNT` 多餘，`CURSEQ−TOTSEQ=5` 是「追上最末號」的狀態。
5. git 沒有 remote；使用者若要推 GitHub，問 repo 名或用 `gh` 建 private repo。
6. 檢查室（ENDO、PSON）預設不收，若要收用 `--sections ENDO,PSON` 另跑一個 instance 或改成兩個 instance。

## 使用者的工作方式

- 中文回覆。偏好先給結論再給細節；表格好用。
- **執行前要 review / double-check**，他會直接要求「review and double check」；主動做並列出查了什麼、修了什麼。
- Ponytail 模式（最少程式碼、標準函式庫優先）有啟用；但安全、備份、錯誤處理不省。
- Commit：Conventional Commits、一行、**不要任何 Co-Authored-By 或 generated-by footer**，只在他要求時 commit；commit 前要 `git status` + `git diff`。
- 動到會花錢或外部可見的東西先問。

## 建議下一個 session 用的 skills

- `ponytail`（已是預設）、`code-review` 在改收集器後、`dataviz` 若要畫分析圖、`handoff` 結束時。
