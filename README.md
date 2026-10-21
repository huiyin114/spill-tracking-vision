# spill-tracking-vision

天使輪（Angel）2023 高雄外海沉船油汙事件的多源遙測整合。（課程作業 HW2）

## 為什麼做這個

海上油汙常用衛星影像監測，但兩種影像各有限制：雷達影像上的暗區不一定是油，會受海面粗糙度（風浪）影響；光學影像則常被雲遮住。要判斷「這塊暗區是不是油、之後會漂到哪」，需要把影像和風、海流等物理條件放在一起看。目前這些資料分散在不同網站與格式，每次分析都要手動整合。

## 事件背景

帛琉籍貨櫃輪天使輪（Angel）2023-07-20 在高雄港第二錨區失去動力，2023-07-21 05:30 沉沒，船上燃油外洩。

本專案的事件參數以官方公告為準：

- 沉沒時間：2023-07-21 05:30（運安會調查頁面）。原文未註明時區；同頁的失去動力時間 10:09 在英文頁標示為當地時間（UTC 02:09），因此視為台灣時間。
- 沉船位置：22°36.54′N、120°12.41′E（航港局 2023-08-01 礙航公告「沉船位置更新」；公告未註明座標系）。
- JpGU 2025 摘要記載沉沒時間為 00:19，與運安會不一致，不採用。

報導指出，杜蘇芮與卡努颱風預期會影響打撈與除污作業。

## 現有研究

中央大學太空及遙測研究中心（Chu et al., 2025）曾用 Sentinel-1/2、Landsat-8/9 與無人機監測此事件，整理見 [jpgu2025.md](jpgu2025.md)。

## 本專案想做的（暫定，會隨進度修正）

1. 整理事件期間所有可用的衛星過境與無人機出勤，放到同一條時間軸。
2. 為每個觀測補上同時間的物理條件（風、海流等）。
3. 以已知污染源（沉船）做漂移模擬，並與觀測比對。

## 資料來源與查詢方式

### 衛星影像目錄（Copernicus STAC）

- 服務：Copernicus Data Space Ecosystem 的 STAC 目錄。這是較新的端點（舊端點已於 2025-11-17 起棄用），目錄內容與行為日後可能變動，所以原始回應另存成檔案，並記錄查詢日期。
- 查詢日期：2026-10-10。搜尋不需登入（以無痕視窗實測）。
- Sentinel-1：
  `https://stac.dataspace.copernicus.eu/v1/search?collections=sentinel-1-grd&bbox=120.1,22.45,120.4,22.75&datetime=2023-07-15T00:00:00Z/2023-08-31T23:59:59Z&limit=50`
- Sentinel-2：把 `collections` 換成 `sentinel-2-l2a`，`limit` 改為 100。
- 回傳的 JSON 存為 `data/raw/stac_s1.json`、`data/raw/stac_s2.json`（原始檔不納入版控，可由上列網址重現）。
- 查詢方式的由來：「如何得知事件期間有哪些衛星影像可用」是請 AI（Claude）協助的：查詢網址由 AI 依 STAC 通用知識組成，經實際執行確認有效，再以下列文件事後核對。bbox 範圍與日期範圍為本專案自行決定。
- 查詢依據：STAC 是公開標準，搜尋方式由 STAC API 的 Item Search 規範定義。CDSE 端點根頁面的 `conformsTo` 欄位宣告支援 `https://api.stacspec.org/v1.0.0/item-search`，其 OpenAPI 描述（`/v1/api`）列出 `/search` 的 `collections`、`bbox`、`datetime`、`limit` 參數並連到該規範。
- 參數用法：`bbox` 順序為西、南、東、北，`datetime` 區間以 `/` 分隔，回應沒有 `next` 連結即為最後一頁（依 Item Search 規範）。

### 風資料（氣象署 CODiS 測站）

- 來源：中央氣象署「氣候觀測資料查詢服務」（CODiS，https://codis.cwa.gov.tw/）測站資料的「單項逐時月報表」風速與風向，2023 年 7、8 月。下載日期：2026-10-11。原始 CSV 放在 `data/raw/codis/`（不納入版控）。
- 測站：鼓山 C0V690（離沉船 7.2 km）、前鎮 C0V890（11.5 km）、蚵仔寮 C0V850（13.8 km），清單見 `data/stations.csv`，距離由測站清單座標與官方沉船座標計算。選法：CODiS 高雄市共 67 站，依資料說明只有 46、C0、C2 開頭的站有風（C1 是雨量站），再依距離排序，並取不同位置的三站（鼓山地址為臨海一路，靠海是依路名的推測）。
- 資料定義（CODiS 觀測資料說明 Ver.2025.12.31）：逐時風速、風向為整點前 10 分鐘的平均；風速 ≦ 0.2 m/s 時風向記為 0，北風記為 360。
- 時間：資料說明沒有寫明時區，也沒有說第 24 欄的意義。這裡視為台灣時間，第 24 欄為隔天 00:00（推論，待核對）。
- 限制：三站都在陸地或港區，離沉船 7–14 km，不是沉船位置的風。風弱時三站彼此差異很大（例如 2023-08-03 06 時為 3.5、4.6、6.9 m/s），所以三站並列，不取平均。
- 查證後不採用的來源：CODiS 氣候格點資料（2.5 km）只有氣溫、降水量、氣壓、相對溼度、露點溫度，沒有風；氣象資料開放平臺的海象監測資料（O-B0075-001／002）只提供最近 48 小時與 30 天，取不到 2023 年。
- 處理：`wind.py` 讀月報表，輸出逐時表 `data/wind_hourly.csv`，並對每次衛星過境、每個測站列出時間最近的一到兩筆觀測 `data/wind_at_passes.csv`（時間差上限 30 分鐘）。Sentinel-2 的過境皆約在台灣時間 10:25，介於 10 時與 11 時兩筆觀測之間，所以兩筆都列出。


### 特徵表（`features.py`）

把時間軸與風整成兩張表，之後加新變數（海流、潮汐…）只要多一個讀取程式和多幾列，不必改欄位。

- `data/passes.csv`：每次過境一列，只放不變的屬性（感測器、時間、軌道、是否涵蓋、配對的無人機日）。過境識別碼 `pass_id` = 感測器 + UTC 時間（到秒）。
- `data/features_long.csv`：每次過境、每個變數、每個來源一列（`pass_id, variable, source, value, unit, gap_min`）。這次過境不適用的變數沒有列；有查但沒值就留一列、值為空，不用 0 代替。
- `data/features_wide.csv`：每次過境一列的寬表，欄名為「變數@來源」。同一過境有兩筆觀測時（Sentinel-2 都夾在兩個整點之間）取時間差絕對值較小的一筆，一樣近取較早的；這只是暫時的取法，不代表最適合，長表保留兩筆。
- 變數與單位登記在 `features.VARIABLES`。

指令：`python features.py --timeline data/timeline.csv --wind data/wind_at_passes.csv --out-passes data/passes.csv --out data/features_long.csv --out-wide data/features_wide.csv`

## 進度

- [x] 文獻起點：JpGU 2025 摘要
- [x] 事件參數（官方沉沒時間與沉船位置）
- [x] 衛星目錄：Sentinel-1/2 過境與是否涵蓋沉船
- [x] 無人機清單與每日摘要
- [x] 時間軸對齊：衛星過境與無人機出勤
- [x] 風：CODiS 三個測站的逐時風與各次過境的風
- [x] 長格式特徵表（`features.py`）：各次過境的所有變數整成一張表
- [ ] 海流與潮汐
- [ ] 雷達暗區偽陽性過濾
- [ ] 漂移模擬與比對

## 參考資料

- Chu, C.-H., Chen, C.-F., & Wu, C.-C. (2025). Application of Remote Sensing Technology in Monitoring Oil Pollution from Ship Grounding Incidents. JpGU Meeting 2025, U03-P04. https://pub.confit.atlas.jp/ja/event/jpgu2025/presentation/U03-P04
- Taiwan News（2023-07-22）。Doksuri could hamper efforts to recover 600 containers from sunken ship off south Taiwan. https://www.taiwannews.com.tw/en/news/4951068
- 公視新聞（2023-08-02）。天使輪沉沒貨櫃漂流 海保署持續清除外溢油污。 https://news.pts.org.tw/article/649308
- 國家運輸安全調查委員會。1120720 ANGEL貨櫃船高雄港外海沉沒事故. https://www.ttsb.gov.tw/1243/22344/38984/post （沉沒時間、事故經過）
- 交通部航港局。礙航公告(南區)「天使輪」於高雄港第二錨區沉船位置更新（2023-08-01）. https://www.motcmpb.gov.tw/Information/Detail/90093f9c-34af-4a8c-82a3-7018cc21d57e?SiteId=1&NodeId=483 （沉船座標）
- Copernicus Data Space Ecosystem. STAC product catalogue. https://documentation.dataspace.copernicus.eu/APIs/STAC.html （端點網址、可用資料集、舊端點棄用說明）
- Copernicus Data Space Ecosystem. CDSE STAC API 根頁面. https://stac.dataspace.copernicus.eu/v1/ （`conformsTo` 宣告支援 Item Search；查詢日期 2026-10-10）
- Copernicus Data Space Ecosystem. CDSE STAC API 的 OpenAPI 描述. https://stac.dataspace.copernicus.eu/v1/api （`/search` 的 collections、bbox、datetime、limit 參數說明；互動版為 https://stac.dataspace.copernicus.eu/v1/api.html ）
- STAC API – Item Search 規範. https://github.com/radiantearth/stac-api-spec/blob/main/item-search/README.md （上述參數的標準定義，以及 bbox 順序、datetime 區間與 next 連結的規則）
- 中央氣象署. 氣候觀測資料查詢服務（CODiS）. https://codis.cwa.gov.tw/ （測站清單、逐時風速與風向月報表；查詢日期 2026-10-11）
- 中央氣象署. 氣候觀測資料查詢服務—觀測資料說明（Ver.2025.12.31）. 於 CODiS 測站資料頁的「資料說明」下載 （站碼意義、逐時風的定義、符號說明）
- 中央氣象署. 氣象資料開放平臺. https://opendata.cwa.gov.tw/ （海象監測資料 O-B0075-001／002 僅提供最近 48 小時與 30 天；查詢日期 2026-10-11）
