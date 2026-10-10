# spill-tracking-vision

天使輪（Angel）2023 高雄外海沉船油汙事件的多源遙測整合。（課程作業 HW2）

## 為什麼做這個

海上油汙常用衛星影像監測，但兩種影像各有限制：雷達影像上的暗區不一定是油，會受海面粗糙度（風浪）影響；光學影像則常被雲遮住。要判斷「這塊暗區是不是油、之後會漂到哪」，需要把影像和風、海流等物理條件放在一起看。目前這些資料分散在不同網站與格式，每次分析都要手動整合。

## 事件背景

帛琉籍貨櫃輪天使輪（Angel）於 2023-07-21 00:19（台灣時間）在高雄港外沉沒，船上燃油外洩（來源：JpGU 2025 U03-P04）。報導指出，杜蘇芮與卡努颱風預期會影響打撈與除污作業。

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

## 進度

- [x] 文獻起點：JpGU 2025 摘要

## 參考資料

- Chu, C.-H., Chen, C.-F., & Wu, C.-C. (2025). Application of Remote Sensing Technology in Monitoring Oil Pollution from Ship Grounding Incidents. JpGU Meeting 2025, U03-P04. https://pub.confit.atlas.jp/ja/event/jpgu2025/presentation/U03-P04
- Taiwan News（2023-07-22）。Doksuri could hamper efforts to recover 600 containers from sunken ship off south Taiwan. https://www.taiwannews.com.tw/en/news/4951068
- 公視新聞（2023-08-02）。天使輪沉沒貨櫃漂流 海保署持續清除外溢油污。 https://news.pts.org.tw/article/649308
- Copernicus Data Space Ecosystem. STAC product catalogue. https://documentation.dataspace.copernicus.eu/APIs/STAC.html （端點網址、可用資料集、舊端點棄用說明）
- Copernicus Data Space Ecosystem. CDSE STAC API 根頁面. https://stac.dataspace.copernicus.eu/v1/ （`conformsTo` 宣告支援 Item Search；查詢日期 2026-10-10）
- Copernicus Data Space Ecosystem. CDSE STAC API 的 OpenAPI 描述. https://stac.dataspace.copernicus.eu/v1/api （`/search` 的 collections、bbox、datetime、limit 參數說明；互動版為 https://stac.dataspace.copernicus.eu/v1/api.html ）
- STAC API – Item Search 規範. https://github.com/radiantearth/stac-api-spec/blob/main/item-search/README.md （上述參數的標準定義，以及 bbox 順序、datetime 區間與 next 連結的規則）
