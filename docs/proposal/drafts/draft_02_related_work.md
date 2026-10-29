# Proposal 草稿 v0.1 — Related Work

> 對應作業規範「3. Related Work」：約 1/2 AI Technology + 1/2 Domain Know-how，含 Article Summary Table，最後歸納 Existing Research → Limitations → Research Gap → Our Project。
> 每一篇我都開過原文或出版社頁面確認過作者、年份、方法與結果；標 `[待查]` 的是還沒拿到第一手數字的地方。

---

## 0. 這一輪查到的關鍵事實（影響 Gap 怎麼寫）

| 發現 | 對 Proposal 的影響 |
|---|---|
| **臺中榮總官方 App**（3.4 分、258 評分）的掛號查詢有「**預估報到時間**」欄位，但 App 說明完全沒有叫號提醒、推播、到診提醒 | Gap 不能寫「醫院沒有預估」，要寫成「掛號時的**靜態**估計，不隨當日進度更新、不主動提醒」。`[待查：組員用真實掛號看一次 App，確認它會不會隨進度變]` |
| 臺北榮總 2025 年便民手冊明文：「每看 2 位正常號序後，先排 1 位 85 歲以上高齡長者，接續安插 1 位過號者」 | 這是**公開文件中最清楚的叫號規則**，可直接引用說明「號碼差 ≠ 等待時間」。臺中榮總診間公告只說 83 歲以上自動排序，細節未公開 |
| 臺中榮總網路掛號說明：上午診 08:30、下午診 13:30、夜診 18:00 開診；初診報到截止 11:30／16:30／19:30；最後報到週一至五 20:00、週六 11:30 | 診次生命週期的官方依據，Domain Knowledge 直接引用 |
| 2026 年 BMC Health Services Research 有一篇**台灣**（亞東醫院）的門診抽血佇列長度預測論文 | 證明台灣醫院有人在做同類問題，但用的是院內資料、預測的是人數不是個人等待 |
| 2024 年 HCMS（韓國）明確論證「低估等待比高估更讓病人不滿」，並用非對稱損失訓練 LightGBM | 我們 D2「分位數方向」決定的文獻依據 |
| 2026 年 1 月 arXiv 有 Bayesian + conformal 的分位區間方法；2026 年 AI Review 有 LLM agent 綜述；2026 年 7 月 arXiv 有醫療預約 LLM agent（CareConnect） | 2025–2026 的 AI 來源夠用 |

---

## 3.1 AI Technology

### 3.1.1 候診時間預測：從滾動平均到機器學習

醫院向病人公布等待時間的傳統做法是**滾動平均**（rolling average）。Ang 等人 [1] 在 *M&SOM* 提出 Q-Lasso，把統計學習（Lasso）與排隊理論的流體模型估計量結合，用四家差異很大的醫院急診資料驗證，均方預測誤差比最佳滾動平均低 30% 以上，而且改善主要來自**修正低估**（病人實際等得比預測久）。Pak 等人 [2] 以澳洲公立急診的排隊與服務流程變數加上日內波動做機器學習，比最佳滾動平均的 MSPE 好 20% 以上，並主張因為病人對低估與高估的感受不對稱，應改用**分位數回歸**，結果把嚴重低估的病人數減少 42%，同時建議把「低估比例」列為正式評估指標。

門診方面，Shin 等人 [3] 在韓國大型醫院兩個科別比較線性與非線性模型，LightGBM 最佳；用 TreeSHAP 解釋後，**佇列長度**是最重要特徵，其次是時段與**醫師看診效率**（每小時看幾人）。他們進一步提出「考慮不滿意度」的非對稱損失與 DAES 評分，論證低估等待造成的不滿大於高估。Guo 等人 [4]（JMIR Med Inform 2025）以北京兒童醫院 23 萬筆報到記錄、13 種檢查／檢驗佇列，只用 6 個由排隊理論導出的特徵（排隊人數、到達率、月／日／時／星期）訓練 9 種模型，樹模型最佳，排隊人數是幾乎所有佇列的首要預測因子；但樣本少的佇列表現差（R² 0.11–0.72）。Wang 等人 [5]（BMC HSR 2025）把急診等待改為「是否超過 30 分鐘」的分類問題，17.7 萬筆資料、五種模型 AUROC 0.78–0.81 差異不大，SHAP 顯示**擁擠狀態**是首要因子，並主張臨床上應最小化偽陰性（說不會久等結果久等）。Liu 等人 [6]（BMC HSR 2026）以台灣亞東醫院資料做門診抽血**佇列長度**的多步預測，XGBoost／RF／Lasso 都優於移動平均與「上週同時段」基準線，RF 最佳。

**對本專題的啟示**：(1) 所有研究都以滾動平均或移動平均為基準線，我們也應如此；(2) 即時佇列狀態是最強特徵，醫師個別效率次之；(3) 樹模型（LightGBM／XGBoost／RF）在這類表格資料上穩定優於線性與深度模型，不需要複雜架構；(4) 這些研究全部依賴**院內報到／掛號系統**的資料，病人端拿不到。

### 3.1.2 排隊理論與事件日誌：Queue Mining

Senderovich 等人 [7] 提出 queue mining：從資訊系統的事件日誌中以排隊理論為基礎建構延遲預測器，處理**多類別**服務流程（不同類型的請求以不同方式被處理），在電信與金融資料上大幅優於忽略排隊結構的預測器。這與榮總門診結構高度相似：正常號、過號者、85／83 歲以上長者是三個優先權不同的類別，燈號序列就是一種事件日誌。

### 3.1.3 不確定性量化：分位數、非對稱損失與 Conformal Prediction

Pak [2] 用分位數回歸、Shin [3] 用 Quad-Quad／LINEX 非對稱損失，動機都是「低估比高估傷人」。Shahbazi 等人 [8]（arXiv 2026-01）結合 Bayesian 階層隨機森林與群組感知的 conformal 校準，在 6 萬筆、3,793 家醫院的階層資料上達到 94.3% 覆蓋率（目標 95%），且低不確定性案例的區間窄 21%；單用 Bayesian 不確定性會嚴重低覆蓋（14.1%）。這指出：**區間的覆蓋率要被校準並被報告**，不能只給點估計。我們的資料同樣有階層結構（科別 → 醫師 → 診次），conformal 校準可作為 LightGBM 分位數輸出的後處理。

### 3.1.4 LLM Agent：規劃、工具使用與安全邊界

Chowa 等人 [9]（*AI Review* 2026）綜述 108 篇 2023–2025 的 LLM agent 研究，將 agent 架構拆為核心模型、工具介面、單／多代理框架、推理／規劃／記憶／自省四種認知機制，並指出 agent 在**動態環境**（需追蹤情境、整合外部記憶、調整工具使用）表現仍弱，可靠性與可驗證推理是開放問題。Hasan 等人 [10]（arXiv 2026-07）的 CareConnect 是醫療預約的 LLM agent：function calling 編排 8 個工具、RAG 查資訊，但把緊急偵測與拒絕醫療建議做成**確定性的（deterministic）護欄**，不交給 LLM 裁量；680 個情境達 91.8% 任務完成、96% 安全合規。

**對本專題的啟示**：Agent 的核心迴圈（監看、預測、決策）應該是確定性的程式邏輯，LLM 只做它擅長且可驗證的事（文字分類、生成解釋）；這與 [10] 的「安全優先、範圍受限」設計一致，也回應 [9] 指出的動態環境弱點。

---

## 3.2 Domain Know-how：門診排隊管理

### 3.2.1 台灣的門診需求結構

台灣民眾年均門診超過 15 次 [11][12]，遠高於先進國家 `[待查：OECD Health at a Glance 2025 的 OECD 平均與韓國、日本數字]`；2025 年台灣正式進入超高齡社會（65 歲以上逾 20%）[13]，而高齡者是大型醫院門診的主要使用者，也是最難使用 App、最需要有人幫忙盯進度的族群。健保制度下病人可自由到醫學中心掛號，單一診次掛號上百號是常態（本專題觀測：皮膚科單診最末號達 160）。

### 3.2.2 門診叫號作業規則

臺北榮總 2025 年便民手冊 [14] 載明：病人須先插健保卡報到；系統叫號原則為「每看 2 位正常號序後，先排 1 位 85 歲以上高齡長者，接續安插 1 位過號者，爰此類推」；過號者再報到後依報到時間重新排序。臺中榮總診間公告 [15] 寫明「83 歲以上友善就醫服務，健保卡插卡報到後，燈號機自動排序」，但具體插入順序未公開。臺中榮總網路掛號說明 [16]：上午診 08:30、下午診 13:30、夜間診 18:00 開診；初診報到截止 11:30／16:30／19:30；最後報到時間週一至五 20:00、週六 11:30。

這些規則的直接後果：**燈號上的號碼差不等於等待時間**。未報到的號碼被跳過（本專題觀測單步前進僅 55%）、長者與過號者從側邊插入、報到截止後不再有新病人，而報到率又取決於病人行為。這正是規則型「前 N 號提醒」失準的根本原因。

### 3.2.3 病人行為：未到、遲到與提早到

Toffaha 等人 [17]（*Intelligence-Based Medicine* 2025）回顧 2010–2025 年 52 篇以機器學習預測病人未到（no-show）的研究：邏輯回歸最常用（68%），樹模型與集成方法近年增加，最佳模型 AUC 0.75–0.95；未到行為依醫療場域而異，並點名「整合至既有系統」「跨機構遷移學習」「分析病人行為模式」為研究缺口。對本專題而言，未到與遲到不是要預測的目標，而是**造成跳號與停滯的來源**，模型須從燈號序列間接學到其影響。

### 3.2.4 等候心理與期望管理

Zhang 等人 [18]（BMC HSR 2023）在眼科門診以 297 個情境實驗測試「告知的預期等待時間」與實際等待的關係：告知值最接近實際時滿意度最高（69.4% 非常滿意），差 10 分鐘內（高估或低估）仍顯著優於不告知，差 20 分鐘以上則無改善，病人會覺得「被騙」。Shin [3] 則從模型端證明低估造成的不滿大於高估。兩者合起來給出設計準則：**告知區間而非點估計，寧可略高估，且誤差超過約 20 分鐘就失去意義**。

### 3.2.5 既有系統與應用

| 系統 | 提供什麼 | 沒有什麼 |
|---|---|---|
| 臺中榮總行動服務 App [19] | 依科別或個人查看診進度；掛號查詢顯示「預估報到時間」；抽血進度附預計等候時間 | 叫號提醒、推播、到診提醒；預估報到時間為掛號時的靜態值 `[待查]` |
| 臺北榮總行動就醫服務 App [20] | 到診前 5 號提醒 | 固定號碼差，不換算時間，不考慮醫師速度 |
| 全能掛號王 SeeDoctor [21] | 跨院掛號與看診進度查詢（含臺中榮總） | 到號時間預測；評論指介面不佳 |
| 門診小幫手（LINE，2020）[22] | 訂閱診號、接近時 LINE 通知；訪談 85 位候診病患找出痛點 | 固定號碼差；是否仍營運不明 |
| 看診進度助手（iOS，第三方）[23] | 收藏診間、同時追蹤多個進度 | 支援醫院少、無提醒 |

共同點：**全部以「號碼」為單位提醒或顯示，沒有任何一個把號碼換算成時間、考慮醫師速度與當日狀態、或在狀況改變時主動通知**。

---

## 3.3 Article Summary Table

| Ref. | Year | Problem | AI Method | Domain Knowledge | Dataset | Findings | Limitation |
|---|---|---|---|---|---|---|---|
| [1] Ang et al., M&SOM | 2016 | 急診低急迫病人等待時間預測 | Q-Lasso（Lasso + 排隊流體模型） | 急診分流、排隊理論 | 4 家美國醫院急診歷史資料 | MSPE 比最佳滾動平均低 >30%，主要改善低估 | 急診場域；需院內資料 |
| [2] Pak, Gannon & Staib, IJMI | 2021 | 急診候診室病人等待時間 | ML + 分位數回歸 | 排隊與服務流程變數、日內波動 | 澳洲公立急診 | MSPE 優於滾動平均 >20%；嚴重低估減少 42%；提議「低估比例」指標 | 低急迫病人；日間較準；資料量未載明 |
| [3] Shin et al., HCMS | 2024 | 門診等待時間預測與病人不滿 | LightGBM + TreeSHAP + 非對稱損失（Quad-Quad/LINEX）、DAES 評分 | 佇列長度、醫師看診效率、時段 | 韓國大型醫院 2 科，約 1.1 萬 + 0.4 萬筆 | 非線性模型優於線性；佇列長度最重要；非對稱損失減少低估但犧牲精度 | 單院、4 個月；資料不公開；解釋未經病人驗證 |
| [4] Guo et al., JMIR Med Inform | 2025 | 兒童醫院 13 種檢查／檢驗佇列等待 | 9 種 ML（RF/XGBoost/LightGBM 最佳） | 排隊理論導出特徵：排隊人數、到達率 | 北京兒童醫院 230,864 筆（2024-11 至 2025-03） | 排隊人數為首要因子；檢驗佇列 R² 達 0.93 | 單院、冬季；小樣本佇列差；多模型維運複雜 |
| [5] Wang et al., BMC HSR | 2025 | 急診等待是否超過 30 分鐘 | LR/RF/XGBoost/ANN/SVM + SHAP/PDP | 擁擠狀態、到院方式 | 美國單一急診 177,665 人次（2019–2021） | AUROC 0.78–0.81；擁擠狀態與救護車到院最重要；應最小化偽陰性 | 單院；特徵有限；無公平性評估 |
| [6] Liu et al., BMC HSR | 2026 | 台灣門診抽血佇列長度多步預測 | XGBoost/RF/Lasso vs 移動平均、上週同時段 | 抽血服務類型、輪椅、完成數 | 亞東醫院院內資料 | RF 最佳；ML 均優於傳統基準 | 預測人數非個人等待；院內資料 |
| [7] Senderovich et al., Inf. Systems | 2015 | 多類別服務流程的延遲預測 | Queue mining：排隊理論預測器 + 迴歸 | 多類別優先權、事件日誌 | 電信、金融大型真實日誌 | 大幅優於忽略排隊結構的預測器 | 非醫療資料 |
| [8] Shahbazi et al., arXiv | 2026 | 階層醫療資料的預測區間 | Bayesian 階層 RF + 群組感知 conformal | 醫院／區域階層 | 61,538 筆住院、3,793 家美國醫院 | 覆蓋 94.3%（目標 95%）；低不確定性案例區間窄 21% | 未針對等待時間；預印本 |
| [9] Chowa et al., AI Review | 2026 | LLM agent 綜述 | 單／多代理架構、工具使用、規劃／記憶／自省 | — | 108 篇、68 個基準資料集 | 動態環境表現弱；可靠性與可驗證推理為開放問題 | 綜述 |
| [10] Hasan et al., arXiv | 2026 | 醫療預約 LLM agent | Function calling（8 工具）+ RAG + 確定性護欄 | 預約流程、緊急偵測 | 680 情境基準 | 91.8% 完成、96% 安全合規、每次 $0.03 | 預印本；無規劃與人類監督描述 |
| [17] Toffaha et al., Intell.-Based Med. | 2025 | 病人未到預測綜述 | LR（68%）、樹模型、集成、深度學習 | 未到行為依場域而異 | 52 篇（2010–2025） | 最佳 AUC 0.75–0.95；缺口：系統整合、遷移學習 | 綜述 |
| [18] Zhang et al., BMC HSR | 2023 | 告知預期等待時間對滿意度的影響 | 情境實驗（非 ML） | 等候心理、期望管理 | 眼科門診 297 情境 | 告知值最接近實際最佳；誤差 ≤10 分仍顯著；≥20 分無效 | 假設情境；單院單醫師 |

---

## 3.4 Existing Research → Limitations → Research Gap → Our Project

**Existing Research.** 等待時間預測已有成熟方法：以即時佇列狀態為核心特徵的樹模型 [3][4][6]、分位數與非對稱損失處理不對稱風險 [2][3]、conformal 校準區間 [8]，以及用排隊理論結構化事件日誌 [7]。門診作業規則 [14][15][16] 與病人心理 [18] 也有清楚的文獻與公開文件。LLM agent 的架構與安全設計原則已成形 [9][10]。

**Limitations.**
1. 所有預測研究使用**院內**報到／掛號系統資料 [1]–[6]，病人與第三方無法取得；預測結果也只給醫院管理者，沒有回到病人端的行動建議。
2. 預測對象多為急診或檢查佇列的「等待分鐘數」或「佇列人數」，而非門診叫號制下「我的號碼幾點會到」；跳號、過號插回、長者優先這類**叫號規則造成的非線性**未被建模。
3. 文獻一致指出模型在醫院間不可移植、醫師效應必須個別學習 [1][3]，但沒有研究處理「只能從外部觀測燈號」時如何學到這些效應。
4. 現有病人端工具 [19]–[23] 全部以號碼為單位，沒有時間換算、沒有不確定性、沒有狀態變化時的主動通知；臺中榮總 App 的「預估報到時間」是掛號時的靜態值。
5. LLM agent 在醫療領域的應用集中在預約對話 [10]，沒有把 agent 用於「持續監看並在對的時間主動提醒」這類動態任務，而這正是綜述 [9] 指出 agent 最弱的情境。

**Research Gap.** 缺少一個**只用公開燈號資料、從病人端**建立的門診叫號時間預測與主動提醒系統：它要從燈號序列學到醫師速度與叫號規則的效果、以分位數區間表達不確定性、並以 agent 的監看迴圈在狀態改變時重新推理。台灣目前沒有以看診進度資料做預測的公開研究，各醫院的「預估時間」也未公開算法。

**Our Project.** VGHTC Queue Agent 針對上述缺口：(1) 自建每分鐘的全院燈號資料集（已運行）；(2) 以醫師為單位的即時速率與歷史速率特徵，LightGBM 分位數回歸並以 conformal 校準覆蓋率；(3) 把叫號規則、診次生命週期、停診行事曆與公告語意編碼為領域知識層；(4) 確定性的監看—決策迴圈負責何時通知，LLM 只做公告分類與解釋生成；(5) 以「過號率、空等分鐘、通知次數」等病人端指標評估，而非只報 MAE。

---

## References（草稿，定稿轉 IEEE 格式）

[1] S. Ang, S. Kwasnick, M. Bayati, E. Plambeck, M. Aratow, "Accurate Emergency Department Wait Time Prediction," *Manufacturing & Service Operations Management*, 18(1):141–156, 2016. https://pubsonline.informs.org/doi/10.1287/msom.2015.0560
[2] A. Pak, B. Gannon, A. Staib, "Predicting waiting time to treatment for emergency department patients," *Int. J. Medical Informatics*, 145:104303, 2021. https://doi.org/10.1016/j.ijmedinf.2020.104303
[3] J. Shin, D. A. Lee, J. Kim, C. Lim, B.-K. Choi, et al., "Dissatisfaction-considered waiting time prediction for outpatients with interpretable machine learning," *Health Care Management Science*, 27(3):370–390, 2024. https://link.springer.com/article/10.1007/s10729-024-09676-5
[4] L. L. Guo, R. Tang, J. Y. Wang, et al., "Predicting Waiting Times for Medical Tasks in a Pediatric Hospital Using Machine Learning: Comprehensive, Retrospective, Real-World Study," *JMIR Medical Informatics*, 13:e77297, 2025. https://medinform.jmir.org/2025/1/e77297
[5] H. Wang, N. Sambamoorthi, D. Sandlin, U. Sambamoorthi, "Interpretable machine learning models for prolonged Emergency Department wait time prediction," *BMC Health Services Research*, 25:403, 2025. https://doi.org/10.1186/s12913-025-12535-w
[6] T.-C. Liu, M.-S. Chen, Y.-C. Lee, C.-T. Yang, C.-J. Lu, "Developing machine learning multi-step ahead forecasting scheme to predict outpatient queue length in phlebotomy department," *BMC Health Services Research*, 2026. https://link.springer.com/article/10.1186/s12913-026-15327-y
[7] A. Senderovich, M. Weidlich, A. Gal, A. Mandelbaum, "Queue mining for delay prediction in multi-class service processes," *Information Systems*, 53:278–295, 2015. https://spiral.imperial.ac.uk/entities/publication/d67c8300-e486-402b-9b74-cd829dc17564
[8] M. A. Shahbazi, A. Baheri, N. Azadeh-Fard, "Adaptive Conformal Prediction via Bayesian Uncertainty Weighting for Hierarchical Healthcare Data," arXiv:2601.01223, Jan. 2026. https://arxiv.org/abs/2601.01223
[9] S. S. Chowa, R. Alvi, S. S. Rahman, et al., "From language to action: a review of large language models as autonomous agents and tool users," *Artificial Intelligence Review*, 59:71, 2026. https://doi.org/10.1007/s10462-025-11471-9
[10] H. Hasan, S. Salman, A. T. Abou Dargham, A. Mohanna, A. Chehab, "Toward Trustworthy Large Language Model Agents in Healthcare," arXiv:2607.05055, Jul. 2026. https://arxiv.org/abs/2607.05055
[11] 李伯璋（健保署署長），「醫病平台／台灣的健保需要您我共同守護」，聯合報元氣網，2021-09-10（「一年平均門診超過 15 次以上」）。https://health.udn.com/health/story/6001/5736226
[12] Taiwan News, "35,000 Taiwanese visited the doctor more than 90 times last year," 2020-06-05（引用健保統計：年均 15 次）。https://www.taiwannews.com.tw/en/news/3945070 `[待查：換成健保署 2024/2025 統計年報的原始數字]`
[13] 國家發展委員會，人口推估：台灣 2025 年進入超高齡社會。`[待查：換成國發會官網原始頁面]`
[14] 臺北榮民總醫院，《便民手冊》第壹章門診服務，114.04.01 更新（第 11 頁叫號原則）。https://www.vghtpe.gov.tw/vghtpe/files/PDF/peo/CH1-1140401.pdf
[15] 臺中榮民總醫院，門診看診進度診間公告（皮膚科 2525/2526/2527 診，2026-10-22 觀測）：「83 歲以上友善就醫服務，健保卡插卡報到後，燈號機自動排序」。https://www.vghtc.gov.tw/OutpatientProcess/5986
[16] 臺中榮民總醫院，網路預約掛號說明（看診時間與報到截止）。https://register.vghtc.gov.tw/register/regDesc.jsp
[17] K. Toffaha, M. C. E. Simsekler, M. A. Omar, I. ElKebbi, "Predicting patient no-shows using machine learning: A comprehensive review and future research agenda," *Intelligence-Based Medicine*, 11:100229, 2025. https://www.sciencedirect.com/science/article/pii/S2666521225000328
[18] H. Zhang, W.-M. Ma, J.-J. Zhu, et al., "How to adjust the expected waiting time to improve patient's satisfaction?" *BMC Health Services Research*, 23:455, 2023. https://pmc.ncbi.nlm.nih.gov/articles/PMC10169334
[19] 臺中榮民總醫院行動服務 App，App Store（V2.6.6）。https://apps.apple.com/tw/app/id545244802
[20] 臺北榮總行動就醫服務 App，App Store。https://apps.apple.com/tw/app/id1248270462
[21] 全能掛號王 SeeDoctor，App Store。https://apps.apple.com/us/app/id700524371
[22] 工商時報，「門診小幫手 LINE 診號查詢與通知服務平台」，2020-11-25。https://www.ctee.com.tw/news/20201125700295-431204
[23] 看診進度助手，App Store。https://apps.apple.com/tw/app/id6740689310

---

## 待辦

- `[待查]` 臺中榮總 App「預估報到時間」是否隨當日進度更新 → 請有近期掛號的組員實測截圖。
- `[待查]` OECD Health at a Glance 2025「Consultations with doctors」的 OECD 平均與韓、日數字（網頁抓不到正文，需手動開 PDF）。
- `[待查]` [12][13] 換成官方原始統計頁。
- Related Work 定稿時每篇壓縮成 2–3 句，Summary Table 保留 12 列即可。
