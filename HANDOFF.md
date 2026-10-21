# 交接說明

給下一次對話的 Claude：請先讀這份、`README.md`、`AI_LOG.md`，再繼續。更新日期：2026-10-21。

## 作業

- HW2「AI 輔助程式設計專案」，占 40%，截止 2026-11-01 23:59:59。
- 交付：報告（專案目的、與 AI 協作的過程、軟體工程實踐如單元測試）、GitHub git log（私人倉庫至少要讓助教看得到程式）、AI 協作紀錄（`AI_LOG.md`）。選做 MCP server（加 10%）：**決定不做**。作業投影片沒有指定報告格式與頁數；可能被邀請上課報告。
- 題目：天使輪（Angel）2023-07-21 在高雄外海沉沒事件，整合 Sentinel-1/2、無人機照片與物理條件。
- 2026-10-12 使用者擔心做不完，決定縮小範圍（路線 A）：把已有的部分做完整、可驗證，不做漂移模擬、雷達偽陽性過濾、海流與潮汐，在報告裡如實寫「評估過、因資料與時間限制未做」；另外只加「事件參數可替換」的彈性。

## 範圍變更（2026-10-21，Route A 之後）

使用者決定把目標加回兩項：(1) 以沉船為污染源做漂移模擬並與觀測比對；(2) 物理條件增加替代來源。已做的調查與決定：
- 模擬方法：使用者選 **OpenDrift**（不是自己寫粒子追蹤）。OpenDrift 的風漂移設定來自 GMD 2017 討論稿（預印本，不是最終版）：表層油額外受 2% 風（可設定）、Stokes drift 約 1.5% 風，合計 3.5%（Schwartzberg 1971 的經驗值）；預設值可能已變，使用前要對照現行文件。安裝：文件建議 conda／mamba，另有 Docker；**文件沒有任何作業系統說明，使用者的 Windows 能否裝起來尚未確認**。OpenDrift 應放在獨立環境，核心測試不得依賴它。
- 海流候選：Copernicus Marine 全球分析預報，逐時表層海流 `cmems_mod_glo_phy_anfc_0.083deg_PT1H-m`（uo、vo）與 SMOC `cmems_mod_glo_phy_anfc_merged-uv_PT1H-i`（環流＋潮流＋Stokes drift 與其總和，變數名稱手冊內不一致）。**2023 年 7 月是否可下載未確認**：產品頁寫 2020-11-01 起，產品手冊寫滾動兩年存檔、2016 起需申請。需免費註冊，用 `copernicusmarine` 工具的 `subset` 下載（雲端環境連不到，由使用者下載後放 `data/raw/`）。
- **已確認（2026-10-21）**：使用者用 Marine Data Store 網頁的 Subset 表單，下載了 `cmems_mod_glo_phy_anfc_0.083deg_PT1H-m`（資料集版本標示 `_202406`，MOI GLO12）的 `uo`、`vo`，範圍經度 119.83–121.17、緯度 22.0–23.17，時間 2023-07-20 00:00 至 07-29 00:00（217 筆逐時，單一深度 0.494 m；已涵蓋沉沒時間 07-20 21:30 UTC，取代原本 07-21 起的 193 筆版本），存在 `data/raw/cmems/`（不進版控）。時間以「seconds since 1970-01-01」編碼，視為 UTC（依 CF 慣例的推論，文件這次沒逐字查到）。1/12° 格點，約 43% 為陸地遮罩；離沉船最近的有效格點在 22.583°N 120.167°E（5.0 km）。事件附近海流平均約 0.3 m/s，向西到西北為主，7/27 後轉向西北、最大約 0.8 m/s。
- **OpenDrift 已安裝（2026-10-21）**：使用者在 Windows 用 Miniforge 建立獨立環境 `opendrift`（`mamba create -n opendrift python=3 opendrift`），`import opendrift` 與 `from opendrift.models.openoil import OpenOil` 都成功（安裝路徑 `C:\Users\User\miniforge3\envs\opendrift`）。漂移程式在此環境執行，專案原本的 `.venv` 與測試分開。
- **風已決定並下載（2026-10-21）**：用 Copernicus Marine `WIND_GLO_PHY_L4_MY_012_006`（KNMI，逐時、0.125°、以衛星散射計校正 ERA5）的資料集 `cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H`（檔案標示 `_202211`），只勾 `eastward_wind`、`northward_wind`，範圍與時間同海流（119.56–121.44°E、21.81–23.44°N，2023-07-20 00:00 至 07-29 00:00 UTC，217 筆）。變數說明為「stress-equivalent wind … at 10 m」，不是一般 10 m 風，報告要註明。沉船附近格點沒有缺值；沉船最近格點的風速平均約 4.7 m/s、最大約 20.3 m/s（可能是颱風期間，推論，未對照颱風資料）。備選 ERA5（CDS）與 CODiS 測站未使用（CODiS 只用於頁面對照）。
- 油的實際外洩起始時間未知；模擬若從沉沒時間 2023-07-20 21:30 UTC 釋放，這是假設。
- 潮汐：SMOC 已含潮流，不需另取；pyTMD 模型（GOT、FES 需 AVISO 註冊、TPXO 需申請）是備選。氣象署「即時海況」只有近 48 小時與 30 天，沒有歷史存檔。
- 比對限制（報告必須如實寫）：能比對的只有文獻的方向（東南）與 7/27 最遠距離 26.5 km；粒子模擬無法驗證面積；外洩量不明（船上油量 491.848 t 不是外洩量）；只能寫「與文獻是否一致」，不能寫「驗證」。
- 時程：使用者自行調整檢查點日期。若海流資料取不到，漂移模擬與海流退回「評估過、未做」，並把查到的來源寫進報告。
- 繳交前仍要留最後兩天做報告與最後檢查。

## 使用者的工作方式（必須遵守）

- 一次一步，先說明每個檔案、每個函式為什麼這樣做，再動手。不要一次做很多。
- commit 與 push 由使用者自己做（VS Code，一個階段一次 commit，標題加內文）。Claude 不碰 git，只建議 commit 訊息。
- 每個事實都要有出處，推論要標明是推論。參考資料必須和專案明確相關。
- 文件只留最終決定，不留試錯過程；過程寫在 `AI_LOG.md`，並如實記錄誰提議、誰決定、AI 錯在哪。
- 這個專案不使用 Zotero。
- 測試資料自己造，不讀 `data/`；改完程式要做「故意改錯、確認測試會失敗」的突變檢查。
- 電腦沒連結時只討論，不做檔案工作。

## 環境

- 專案資料夾在使用者電腦 `C:\Users\User\project\spill-tracking-vision`，用 Windows、VS Code、`.venv`。
- Claude 的雲端環境連不到多數資料網站（包含 GitHub 頁面）。資料由使用者在自己電腦下載後上傳；Claude 可透過裝置 shell 讀寫專案資料夾（`~/mnt/spill-tracking-vision`）。
- 檔案是 CRLF（用 LF 寫完再 `sed -i 's/$/\r/'`，不要重複執行）。Linux 端的 `git diff` 要加 `--ignore-cr-at-eol`。
- 測試指令：`python -m pytest`。`requirements.txt` 已產生（在 Linux、Python 3.10 的乾淨環境測過，202 個測試通過）；尚待使用者在自己的 Windows 環境確認。

## 已完成

| 階段 | 檔案 |
|---|---|
| 事件參數：`Event`（位置、期間必填；發生時間、名稱、時區選填），預設天使輪 | `event.py`、`test_event.py` |
| 衛星目錄：Sentinel-1/2 過境、是否涵蓋事件位置、雲量 | `catalog.py`、`test_catalog.py` |
| 無人機清單與每日摘要 | `drone.py`、`test_drone.py`、`extract_drone_exif.py` |
| 時間軸：衛星過境對無人機出勤（無人機選填） | `timeline.py`、`test_timeline.py`、`data/timeline.csv` |
| 風：CODiS 三站逐時風與各次過境的風 | `wind.py`、`test_wind.py`、`data/stations.csv`、`data/wind_hourly.csv`、`data/wind_at_passes.csv` |
| 模型海流與模型風：沉船最近有效格點的逐時 u/v（`extract_ocean.py`，在 opendrift 環境執行）、速度方向換算與對齊過境（`ocean.py`）、進特徵表四個變數 | `extract_ocean.py`、`ocean.py`、`test_extract_ocean.py`、`test_ocean.py`、`data/ocean_at_wreck.csv`、`data/ocean_at_passes.csv` |
| 漂移模擬程式（`drift_sim.py`，OpenDrift OpenOil，在 opendrift 環境執行；擱淺粒子保留位置）與文獻並列（`drift_compare.py`，方向與最遠距離） | `drift_sim.py`、`drift_compare.py`、`test_drift_sim.py`、`test_drift_compare.py` |
| 漂移模擬的圖：過境時刻的靜態圖與動畫（`drift_plot.py`，用 OpenDrift 的陸地遮罩畫陸地） | `drift_plot.py`、`test_drift_plot.py`、`figures/`（使用者在自己電腦執行後產生） |
| 長格式特徵表 | `features.py`、`test_features.py`、`data/passes.csv`、`data/features_long.csv`、`data/features_wide.csv` |
| 外部參考觀測（JpGU 三個數字）與過境對應 | `reference.py`、`test_reference.py`、`data/reference_observations.csv`、`data/reference_matched.csv` |
| 統一介面頁 | `page_data.py`、`build_page.py`、`site/template.html`、`site/index.html`、`test_page_data.py`、`test_build_page.py` |
| README（快速開始、專案結構、目標與實際完成範圍、擴充指南）、`requirements.txt` | `README.md`、`requirements.txt` |

共 325 個測試（沒有 xarray 或 OpenDrift 的環境，5 個相關測試會跳過；在雲端用 OpenDrift 1.14.12 與在有 xarray 的環境都實際跑過）。原始資料（STAC JSON、CODiS CSV）放在 `data/raw/`，不進版控。README 的重現指令已在乾淨副本實際執行，輸出與已提交的檔案逐位元相同。

## 已定的規則

- 沉沒時間 2023-07-21 05:30（運安會，時區視為台灣時間）；沉船位置 22°36.54′N、120°12.41′E（航港局公告）。JpGU 的 00:19 不採用。分析期間 2023-07-19 至 2023-08-31。
- 衛星過境用 10 分鐘間隔合併 frame／tile；是否涵蓋事件位置用影像的實際多邊形判斷，不用外框。欄名沿用 `covers_wreck`、`time_tw`。
- 時間差一律「對方減衛星」，正值代表在衛星之後。
- 無人機：離事件位置 1 km 內算拍在附近；與衛星配對的時間差上限 24 小時。
- 風：鼓山 C0V690、前鎮 C0V890、蚵仔寮 C0V850 三站並列，不取平均；風速 ≦ 0.2 m/s 時風向視為無；對每次過境列出 30 分鐘內的觀測；Sentinel-2 夾在兩個整點之間，長表與頁面兩筆都留，寬表暫取時間差較小的一筆。
- 缺值保持為空，不用 0 代替。
- 外部參考觀測是文獻估計，不是地面真值；對應過境規則為「UTC 或台灣日期任一相同，候選剛好一個才配對」。

## 待辦

1. 階段 11（海流與模型風進特徵表）、階段 13（漂移模擬 `drift_sim.py`、`drift_compare.py`、圖 `drift_plot.py`）已完成並產生正式結果（`data/drift_vs_reference.csv`；海流與風已重新下載成經度 118–122、緯度 21–25，檔名在使用者電腦的 `data/raw/cmems/`，不進版控）。**結果與文獻不一致**：兩組模擬（風漂移係數 0.03、0.02，事先固定）的重心都在沉船北到北北西（338–351°），和文獻的東南差 144–157°，重心距離 58–95 km，文獻最遠距離 26.5 km。報告要照實寫，不調參數去對；可能原因（推測）見 README「漂移模擬」。
   - 下一步：使用者在自己的電腦執行 `drift_plot.py` 產生 `figures/` 並 commit；再決定要不要做階段 14（把粒子位置放進介面頁，工作量大，沒有底圖，需自己處理海岸線）。時間緊的話不做，圖已經足夠放進報告。
   - 預覽圖我用雲端環境畫過並檢查過（資料與使用者跑出的相同）；畫圖程式沒有單元測試，只有純計算部分有。
2. 報告（階段 10 的 B）：預計做成可匯出 Word／PDF 的文件（Docs）。要如實寫入：範圍縮減與原因、資料限制、AI 協作中 AI 出的錯（見 `AI_LOG.md`）。
3. 繳交前使用者自己確認：GitHub 倉庫能被助教開啟（用無痕視窗測）、git log 清楚、在自己的 Windows 環境 `pip install -r requirements.txt` 後 `python -m pytest` 全過。

## 刻意沒做的事（報告要如實寫）

- 潮汐沒有另外處理：台灣來源（CODiS 格點、氣象資料開放平臺海象資料）取不到 2023 年；所用 `PT1H-m` 海流資料集是否含潮流未確認。
- 雷達暗區偽陽性過濾。（漂移模擬在上面的「範圍變更」，進行中。）
- MCP server、GeoJSON／CSV 匯出。
- 頁面的 JavaScript 沒有自動化測試，只用瀏覽器實際操作檢查。

## 待核對

- 運安會沉沒時間與航港局座標未註明時區與座標系。
- CODiS 逐時資料的時區與第 24 欄（視為隔天 00:00）是推論，說明文件沒寫。
- JpGU 摘要的 12 景雷達影像到 9/22，我們的查詢只到 8/31。
- JpGU 的三個數字只讀過中文轉述，沒核對英文原文；文獻只給日期，7/27 很可能是台灣日期（推論）。
- 三個風站都在陸地或港區，離沉船 7–14 km，不是沉船位置的風。
