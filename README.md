# VGHTC Queue Agent

以臺中榮民總醫院**公開看診進度（燈號）資料**預測門診叫號時間、在該出門時主動提醒的 Domain AI Agent。

國立中興大學 人工智慧學位學程・課程「人工智慧與資訊安全」期末專題・指導教授：陳煥
組員：羅志緯（5115050039）、鄭博仁（5115050003）、張佳筑（5115050030）

> 目前階段：**Proposal（2026-11-02 繳交）**。收集器已於 2026-10-22 上線累積資料；Agent、模型與 LINE Bot 尚未實作。

## 這個專題在解什麼問題

同樣是「前面還有 10 號」，可能等 10 分鐘，也可能等一個多小時：各診間每叫一號的時間相差近 10 倍（1.0–9.3 分鐘），單一下午全院有 89 次超過 20 分鐘的停滯，而現場已報到人數中位數只占剩餘號碼的 18%。病人要的不是「現在看到幾號」，而是**「我幾點會被叫到」**與**「我幾點該出門」**，而且答案會隨代診、延誤、速度變化而改變。

VGHTC Queue Agent 只用醫院公開的看診進度 API（不登入、不碰個資），持續監看、預測叫號時間區間（P20/P50/P80）、在狀態改變時重新推理，並透過 LINE 主動推播。

三個情境：

| 情境 | 內容 |
|---|---|
| S1 掛號前查詢 | 這位醫師平常多快、常在幾點卡住、通常幾點看完 |
| S2 掛號後訂閱（核心） | 給診間、午別、號碼、交通時間；Agent 監看、預測、在該出門時推播 |
| S3 變化提醒 | 代診、延誤、速度異常、預測大幅改變、已叫到、診次結束時重新推理並通知 |

不掛號、不換診、不查個人掛號資料；所有提醒皆為建議。

## 文件

| 文件 | 內容 |
|---|---|
| [`DESIGN.md`](DESIGN.md) | 系統設計文件（規範要求自 Proposal 階段起維護） |
| [`docs/proposal/VGHTC-Queue-Agent-Proposal.pdf`](docs/proposal/VGHTC-Queue-Agent-Proposal.pdf) | Proposal 完整版（IEEE 雙欄，9 頁） |
| [`docs/proposal/VGHTC-Queue-Agent-Proposal-lean.pdf`](docs/proposal/VGHTC-Queue-Agent-Proposal-lean.pdf) | Proposal 精簡版（8 頁） |
| [`docs/proposal/slides-src/`](docs/proposal/slides-src/) | Proposal 簡報原始檔（25 頁） |
| [`collector/README.md`](collector/README.md) | 燈號收集器：API 欄位意義、資料怪癖、資料庫結構、部署 |

## 目錄結構

```
vghtc-queue-agent/
├── README.md                 本文件
├── DESIGN.md                 系統設計文件
├── collector/                燈號收集器（已上線）
│   ├── vghtc_collector.py    純標準函式庫，每 60 秒全院一次，只存變化到 SQLite
│   ├── dashboard/            監控網頁（Cloud Run + IAP）
│   ├── deploy/               GCP 建置、安裝、部署、備份腳本
│   └── docs/HANDOFF.md       收集器交接文件
└── docs/proposal/            Proposal 文件與簡報
    ├── main.tex / main-lean.tex   XeLaTeX 原始檔（build.sh 建置）
    ├── figures/              架構圖、流程圖（TikZ 原始檔 + PNG）、監控網頁截圖
    ├── slides-src/           簡報原始檔
    ├── sources/              引用的官方統計原始檔（健保署、內政部）
    └── drafts/               撰寫過程的 Markdown 草稿（內容以 PDF 為準）
```

預計於 Final 階段新增：`agent/`（監看迴圈、LINE Bot）、`model/`（特徵工程、LightGBM 分位數回歸、回測）、`notebooks/`（資料分析）。

## 資料來源

臺中榮總官網[門診看診進度](https://www.vghtc.gov.tw/OutpatientProcess/5986)背後的公開 JSON API，欄位：目前看診號次、最末號、已報到待看診人次、過號看診號、醫師、公告。輪詢頻率與官網自動刷新相同（60 秒），每輪一次請求。欄位意義與驗證過程見 [`collector/README.md`](collector/README.md)。

Introduction 引用的官方統計：
- 衛生福利部中央健康保險署，「2025 年國人平均每人門診就醫次數前二十大疾病」（全國合計 16.32 次／人）— [連結](https://www.nhi.gov.tw/ch/cp-6015-0907b-3023-1.html)，原始檔 `docs/proposal/sources/`
- 內政部統計處，「02-01 人口年齡分配按單齡」2025 年底（65 歲以上 20.06%）— [連結](https://statis.moi.gov.tw/micst/webMain.aspx?k=menuy)，原始檔 `docs/proposal/sources/`

## How to Run

### 收集器（Python 3.9+，無第三方套件）

```bash
cd collector
python vghtc_collector.py once     # 跑一輪確認連得上
python vghtc_collector.py run      # 持續收集（週一至週六 07:30–22:30，每 60 秒）
python vghtc_collector.py stats    # 資料庫概況
```

正式環境部署在 GCP 免費層（自動重啟、每日備份、監控網頁），步驟見 [`collector/README.md`](collector/README.md)。

### Proposal PDF

```bash
cd docs/proposal && ./build.sh    # 需 XeLaTeX + Noto CJK 字型
```

## 資料倫理與資安

- 只使用無需登入的公開 API；**不使用**同頁面的「以身分證／病歷號查詢掛號」API。
- 不蒐集身分證、病歷號、定位；Final 階段的 LINE Bot 在訂閱結束後刪除使用者 ID，只保留去識別化的（診間、號碼、預測、實際叫號時間）。
- 收集器主機不開對外連接埠，SSH 僅經 IAP；監控網頁以 Google 登入保護。
- 若要對外公開服務，先徵詢醫院資訊室。

## 狀態

| 項目 | 狀態 |
|---|---|
| 燈號收集器 | 2026-10-22 上線，GCP e2-micro，24/7 |
| 累積資料 | 截至 10/29 共 5 個門診日、約 5.7 萬筆變化；完整門診日每天約 1.4–1.7 萬筆（10/27 16,736、10/28 15,871、10/29 14,301）。10/22 僅下午 5 小時、10/23 颱風日資料偏少、10/24–26 連假停診 |
| Proposal 文件與簡報 | 完成 |
| Agent／模型／LINE Bot | Final 階段 |
