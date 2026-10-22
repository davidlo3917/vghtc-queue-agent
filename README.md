# 台中榮總門診燈號收集器

定時記錄台中榮總每個診間的燈號變化，存成 SQLite，作為之後訓練預測模型的資料：**給定診間、午別和一個號碼，預測這個號碼還要多久會被叫到。** 只用 Python 標準函式庫，不需要安裝任何套件。

## 資料來源

台中榮總官網的[門診看診進度](https://www.vghtc.gov.tw/OutpatientProcess/5986)頁面，背後呼叫的是一個公開的 JSON API：

```
POST https://publicmobileappservice20171114025941.azurewebsites.net/api/RegService/CallLightInfo/OPD
Content-Type: application/json

{"OPDSection": "CV", "OPDRoom": "", "OPDTimeFlag": ""}
```

- `OPDSection: ""`（空字串）→ **一次回傳全院所有門診診間**的即時燈號，收集器預設用這個，每輪只打一次。實測內容跟 53 科逐科查完全一致，只少了沒有午別、沒有號碼的檢查室（內視鏡、心臟超音波）。
- `OPDSection: "GETLIST"` → 回傳全部科別清單（目前 53 個科別），只用來填科別名稱
- `OPDSection: "<科別代碼>"` → 回傳該科所有診間的即時燈號（`--sections` 時用）
- `OPDRoom: "<診間號>"` + `OPDTimeFlag: "A/P/N"` → 只查單一診間（之後做查詢服務時用這個）
- 沒有診的時候回 `SRESULT: "FALSE", SMESSAGE: "查無資料"`，這是正常空結果，不是錯誤

### 回傳欄位

| 欄位 | 意義 | 官網顯示名稱 |
|---|---|---|
| `CURSEQ` | 目前看診號次 | 目前看診號次 |
| `TOTSEQ` | 最末號 | 最末號 |
| `CUR_WAITING_CNT` | 已報到、等待看診的人數 | 已報到待看診人次 |
| `MAX_DELAY_OPDSEQ` | 過號看診號 | 過號看診號 |
| `DELAY_WAITING_CNT` | 過號等待人數（推測，官網沒顯示） | — |
| `OPDTIMEFLAG` | 午別：A 上午、P 下午、N 晚上 | — |
| `OPDROOM` / `OPDROOMPLACE` | 診間號 / 位置 | 診間 |
| `DRNMC` | 醫師（代診時會變） | 醫師 |
| `OPDMSG` | 公告（請假、中午不休息、報到截止時間…） | 公告 |
| `SECTIONNMC` | 科別名稱 | 科別 |
| `REGSEQ` / `OPDCaseNo` / `OPDFinishCode` | 抽樣時皆為 `null`，意義不明（可能只在查個人掛號時有值，或在診次結束時出現）。照樣存進 `observations`，以防之後需要 | — |

API 回傳的 15 個欄位全部都有存，沒有丟掉任何資訊。

`CUR_WAITING_CNT` 可能是預測的關鍵：沒報到的號碼會被跳過，所以實際待看人數比號碼相減準。**尚未確認**它算的是「排在某號前面的人」還是「整個診間已報到在等的人」（後者也包含號碼比較後面的人），需要用收集到的資料對照燈號變化來驗證。

### 觀察到的資料怪癖

- 所有數值都是字串，空值是 `""`。
- `CURSEQ > TOTSEQ` 不只出現在「不指定醫師」的診間，一般門診也有，而且常常剛好差 5（2026-10-22 上午抽樣 168 筆中有 30 筆）。原因不明，`TOTSEQ` 不能當成號碼上限。
- 檢查室（內視鏡、心臟超音波等）沒有 `OPDTIMEFLAG`、沒有醫師、沒有號碼，預設不收集；真要收用 `--sections ENDO,PSON`，會以 `time_flag = ?` 存。
- 所有數字欄位如果出現非數字（目前沒看過），會原樣存成字串而不是變成空值，分析時要留意。
- 同一科的回傳偶爾會有兩筆完全相同的診間資料，不影響收集（第二筆會被視為沒變化）。
- 在抽樣資料中 `DELAY_WAITING_CNT` 常常等於 `CUR_WAITING_CNT`，實際意義需要多收幾天資料再確認。
- 83 歲以上長者插卡報到後會被自動往前排序，這會讓燈號偶爾「倒退」或跳動。

## 使用方式

需要 Python 3.9 以上。

```bash
# 1. 先跑一輪確認連得上
python vghtc_collector.py once

# 2. 持續收集（預設週一到週六 07:30–22:30，每 60 秒一輪）
python vghtc_collector.py run

# 只收集特定科別
python vghtc_collector.py run --sections CV,DERM,OPH

# 看資料庫概況
python vghtc_collector.py stats

# 匯出某天資料成 CSV（Excel 可直接開）
python vghtc_collector.py export --date 2026-10-22
```

資料預設存在同一個資料夾的 `vghtc_calllight.db`，可以用 `--db` 指定別的位置。

## 部署（目前的正式環境）

2026-10-22 起跑在 GCP 的永久免費層上，用學校帳號 `davidlo@smail.nchu.edu.tw`（gcloud 設定名稱 `nchu`，所有指令加 `--configuration=nchu` 或 `CLOUDSDK_ACTIVE_CONFIG_NAME=nchu`）。專案 `vghtc-calllight-2026`。

```
VM us-west1-b  vghtc-collector  e2-micro / Debian 12 / 30 GB（免費層）
 ├─ vghtc-collector.service   收集器，當掉自動重啟、開機自動啟動
 ├─ vghtc-status.timer        每 5 分鐘產生 status.json 上傳到 bucket（監控網頁讀這個）
 └─ vghtc-backup.timer        每天 23:30 備份資料庫到 bucket；每月 2 號存門診手冊
Bucket gs://vghtc-calllight-2026   status.json、backups/（保留 60 天）、schedules/
Cloud Run us-west1  vghtc-dashboard   監控網頁，IAP（Google 登入）保護，只開給學校帳號
```

- **監控網頁**：https://vghtc-dashboard-552588620281.us-west1.run.app
  - `/` 總覽（心跳、今天的輪詢與變化、缺口、備份、最近 7 天、警告）
  - `/data` 今天每個診次的最新狀態，`/data.csv` 下載
  - `/backup/latest` 一鍵下載最新的 SQLite 備份（`.db.gz`），解壓後用 [DB Browser for SQLite](https://sqlitebrowser.org/) 或 pandas `read_sql` 看 `observations` 表
- **更新程式**：改完本機檔案後 `bash deploy/deploy.sh`（上傳、重啟服務，約 30 秒）。
- **看 log**：`gcloud compute ssh vghtc-collector --configuration=nchu --zone=us-west1-b --tunnel-through-iap -- journalctl -u vghtc-collector -f`
- **把資料庫抓回本機**：`gcloud storage cp --configuration=nchu gs://vghtc-calllight-2026/backups/vghtc_calllight_<日期>.db.gz .`，或直接從 VM 的 `/opt/vghtc/data/` scp。
- **更新監控網頁**：`gcloud run deploy vghtc-dashboard --configuration=nchu --source dashboard --region us-west1 --iap --set-env-vars BUCKET=vghtc-calllight-2026,TRIAL_END=2026-12-20`（`TRIAL_END` 是網頁上倒數用的試用到期日，請以 Console 顯示的為準）。
- **加人看網頁**：`gcloud beta iap web add-iam-policy-binding --configuration=nchu --resource-type=cloud-run --service=vghtc-dashboard --region=us-west1 --member=user:<email> --role=roles/iap.httpsResourceAccessor`
- 第一次建環境用 `deploy/gcp-setup.sh`，可重跑。VM 沒開任何對外 port，SSH 只走 IAP。
- **費用**：VM、硬碟、bucket、Cloud Run、IAP 都在免費額度內；唯一可能的費用是 VM 的外部 IPv4（最多約 US$3.65/月）。
- **⚠ 試用到期**：這個帳單帳戶是 2026-09-21 開的 $300 試用，**約 2026-12-20 到期前要在 Console 按「啟用完整帳戶」**，否則整個帳戶會被暫停、VM 會停。升級不會損失剩餘額度。

### 時間軸與資料缺口

`polls` 表記錄每一輪，事後可以分辨「燈號沒動」和「收集器沒在跑」。另外觀察到：診間在該診次結束後就會從 API 回傳中消失（中午 12 點多全院只剩 90 幾個診間），所以 `sessions.last_seen` 大致就是診次結束時間。

## 禮貌輪詢

預設每 60 秒一輪（跟官網頁面自己的自動刷新頻率一樣），每輪只打**一次**全院查詢，跟一個人開著官網頁面的負擔差不多。全院所有診間在同一秒取樣，叫號時間的誤差最多 60 秒。只收集門診時段。請不要把間隔調得更短，避免造成醫院伺服器負擔；如果之後要做成公開服務，建議先跟醫院資訊室聯繫。

另外，同一頁面上還有一個「用身分證或病歷號查詢掛號」的 API，**這個收集器刻意不使用**。之後做查詢服務時，只需要讓使用者輸入「診間號、午別、自己的號碼」，不要收集身分證或病歷號。

## 資料庫結構

| 資料表 | 內容 |
|---|---|
| `sections` | 科別代碼與名稱 |
| `sessions` | 一個診次 = 日期 + 午別 + 診間 + 科別，含醫師、最新公告 |
| `observations` | 燈號數值**有變化時**才寫一筆（時間戳 + 目前號、最末號、待看人數、過號資訊、醫師）。`seen_since` 是上一次確認這個診次的時間，所以變化精確發生在 `(seen_since, ts]` 之間 |
| `notice_changes` | 公告文字的變化紀錄（請假、延誤等，之後可當特徵） |
| `polls` | 每一輪輪詢的請求成功/失敗數、變化筆數；`failed_sections` 列出哪些查詢失敗（全院查詢失敗時是 `ALL`）。`finished_at` 為空代表那一輪中途當掉 |

### 之後分析時的約定

- **分析單位是醫師，不是診間。** 診間只是地點，看診速度和習慣跟著醫師走；但護理師是跟著診間配的，所以診間保留當「護理團隊」的代理變數。API 沒有醫師 ID，只有姓名，用 `(section, doctor)` 當 key 避免同名。
- **號碼 N 的叫號時間** = 該診次第一筆 `cur_seq >= N` 的紀錄，真正時間在它的 `seen_since` 和 `ts` 之間。
- **某時刻 t 的狀態** = 該診次 `ts <= t` 的最後一筆（pandas `merge_asof`）。
- **分辨「沒變化」和「沒收到」**：先看 `polls` 那段時間有沒有輪詢，再看 `failed_sections` 有沒有該科。
- `sessions.doctor` 是最後看到的醫師；代診前的醫師在 `observations.doctor` 的早期紀錄裡。
- 診次何時開始、結束：目前只能從第一筆和最後一筆觀察推，`OPDFinishCode` 是否會標記結束要收幾天資料才知道。

## 下一步：從這些資料能算出什麼

目標：在任一時間點，給定診間、午別和號碼 N，預測 N 還要多久會被叫到。

**預測的答案從哪來**：同一診次中，`cur_seq` 第一次大於或等於 N 的那筆 `observations` 的時間戳，就是 N 被叫到的時間。在這之前每一筆觀察的時間，到這個時間點的差距，就是一筆訓練資料的答案。

收集一兩週後，就可以開始做：

1. **確認欄位意義**：`CUR_WAITING_CNT`、`DELAY_WAITING_CNT`、`CURSEQ > TOTSEQ` 的情況分別代表什麼。
2. **每位醫師的看診速度**：`cur_seq` 每前進一號花多少分鐘，依星期幾、午別、時段分組。
3. **基準線預測**：剩餘等待時間 ≈ 前面的人數 × 這位醫師今天的平均每人分鐘數。
4. **機器學習模型**：用 LightGBM 做分位數預測（P50 / P80），特徵包括號碼差距、待看人數、今天已看速度、歷史速度、時段、過號人數、公告是否有「延誤」「請假」等關鍵字。
