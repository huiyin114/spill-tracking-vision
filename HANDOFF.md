# 交接說明

給下一次對話的 Claude：請先讀這份、`README.md`、`AI_LOG.md`，再繼續。更新日期：2026-10-21。

## 作業

- HW2「AI 輔助程式設計專案」，占 40%，截止 2026-11-01 23:59:59。
- 交付：報告（專案目的、與 AI 協作的過程、軟體工程實踐如單元測試）、GitHub git log（私人倉庫至少要讓助教看得到程式）、AI 協作紀錄（`AI_LOG.md`）。選做 MCP server（加 10%）：**決定不做**。作業投影片沒有指定報告格式與頁數；可能被邀請上課報告。
- 題目：天使輪（Angel）2023-07-21 在高雄外海沉沒事件，整合 Sentinel-1/2、無人機照片與物理條件。
- 2026-10-12 使用者擔心做不完，決定縮小範圍（路線 A）：把已有的部分做完整、可驗證，不做漂移模擬、雷達偽陽性過濾、海流與潮汐，在報告裡如實寫「評估過、因資料與時間限制未做」；另外只加「事件參數可替換」的彈性。

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
| 長格式特徵表 | `features.py`、`test_features.py`、`data/passes.csv`、`data/features_long.csv`、`data/features_wide.csv` |
| 外部參考觀測（JpGU 三個數字）與過境對應 | `reference.py`、`test_reference.py`、`data/reference_observations.csv`、`data/reference_matched.csv` |
| 統一介面頁 | `page_data.py`、`build_page.py`、`site/template.html`、`site/index.html`、`test_page_data.py`、`test_build_page.py` |
| README（快速開始、專案結構、目標與實際完成範圍、擴充指南）、`requirements.txt` | `README.md`、`requirements.txt` |

共 202 個測試。原始資料（STAC JSON、CODiS CSV）放在 `data/raw/`，不進版控。README 的重現指令已在乾淨副本實際執行，輸出與已提交的檔案逐位元相同。

## 已定的規則

- 沉沒時間 2023-07-21 05:30（運安會，時區視為台灣時間）；沉船位置 22°36.54′N、120°12.41′E（航港局公告）。JpGU 的 00:19 不採用。分析期間 2023-07-19 至 2023-08-31。
- 衛星過境用 10 分鐘間隔合併 frame／tile；是否涵蓋事件位置用影像的實際多邊形判斷，不用外框。欄名沿用 `covers_wreck`、`time_tw`。
- 時間差一律「對方減衛星」，正值代表在衛星之後。
- 無人機：離事件位置 1 km 內算拍在附近；與衛星配對的時間差上限 24 小時。
- 風：鼓山 C0V690、前鎮 C0V890、蚵仔寮 C0V850 三站並列，不取平均；風速 ≦ 0.2 m/s 時風向視為無；對每次過境列出 30 分鐘內的觀測；Sentinel-2 夾在兩個整點之間，長表與頁面兩筆都留，寬表暫取時間差較小的一筆。
- 缺值保持為空，不用 0 代替。
- 外部參考觀測是文獻估計，不是地面真值；對應過境規則為「UTC 或台灣日期任一相同，候選剛好一個才配對」。

## 待辦

1. 報告（階段 10 的 B）：預計做成可匯出 Word／PDF 的文件（Docs）。要如實寫入：範圍縮減與原因、資料限制、AI 協作中 AI 出的錯（見 `AI_LOG.md`）。
2. 繳交前使用者自己確認：GitHub 倉庫能被助教開啟（用無痕視窗測）、git log 清楚、在自己的 Windows 環境 `pip install -r requirements.txt` 後 `python -m pytest` 全過。

## 刻意沒做的事（報告要如實寫）

- 海流與潮汐：台灣來源（CODiS 格點、氣象資料開放平臺海象資料）取不到 2023 年；候選為 Copernicus Marine、eo-tides，尚未選定。
- ERA5 風、雷達暗區偽陽性過濾、漂移模擬與比對。
- MCP server、GeoJSON／CSV 匯出。
- 頁面的 JavaScript 沒有自動化測試，只用瀏覽器實際操作檢查。

## 待核對

- 運安會沉沒時間與航港局座標未註明時區與座標系。
- CODiS 逐時資料的時區與第 24 欄（視為隔天 00:00）是推論，說明文件沒寫。
- JpGU 摘要的 12 景雷達影像到 9/22，我們的查詢只到 8/31。
- JpGU 的三個數字只讀過中文轉述，沒核對英文原文；文獻只給日期，7/27 很可能是台灣日期（推論）。
- 三個風站都在陸地或港區，離沉船 7–14 km，不是沉船位置的風。
