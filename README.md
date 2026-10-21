# spill-tracking-vision

天使輪（Angel）2023 高雄外海沉船油汙事件的多源遙測整合。（課程作業 HW2）

把 Sentinel-1/2 衛星過境、無人機空拍與氣象署測站風，整合到同一條時間軸與一個介面頁。AI（Claude）協助撰寫，協作過程記錄在 [AI_LOG.md](AI_LOG.md)。

## 快速開始

```
pip install -r requirements.txt
pytest                      # 全部測試，都自己造資料，不讀 data/
```

直接看成果：用瀏覽器打開 `site/index.html`（資料已嵌在檔案裡，不需要網路）。

從資料重新產生全部輸出（原始資料不在倉庫，來源與下載方式見下方「資料來源與查詢方式」）：

```
python timeline.py --s1 data/raw/stac_s1.json --s2 data/raw/stac_s2.json --drone data/drone/angel_drone_exif.csv --out data/timeline.csv
python wind.py --raw data/raw/codis --stations data/stations.csv --timeline data/timeline.csv --out-hourly data/wind_hourly.csv --out data/wind_at_passes.csv
# 模型海流與風：extract_ocean.py 要在 opendrift 環境執行（需要 xarray、netCDF4），輸入的 NetCDF 不在倉庫
python extract_ocean.py --current-nc data/raw/cmems/<海流檔>.nc --wind-nc data/raw/cmems/<風檔>.nc --out data/ocean_at_wreck.csv
python ocean.py --timeline data/timeline.csv --ocean data/ocean_at_wreck.csv --out data/ocean_at_passes.csv
python features.py --timeline data/timeline.csv --wind data/wind_at_passes.csv --ocean data/ocean_at_passes.csv --out-passes data/passes.csv --out data/features_long.csv --out-wide data/features_wide.csv
python reference.py --reference data/reference_observations.csv --passes data/passes.csv --out data/reference_matched.csv
# 漂移模擬：drift_sim.py 要在 opendrift 環境執行；粒子表是模擬輸出，執行一次約幾分鐘
python drift_sim.py --current-nc data/raw/cmems/<海流檔>.nc --wind-nc data/raw/cmems/<風檔>.nc --wind-drift-factor 0.03 --out data/drift_particles_base.csv
python drift_sim.py --current-nc data/raw/cmems/<海流檔>.nc --wind-nc data/raw/cmems/<風檔>.nc --wind-drift-factor 0.02 --out data/drift_particles_wind002.csv
python drift_compare.py --particles base=data/drift_particles_base.csv wind002=data/drift_particles_wind002.csv --matched data/reference_matched.csv --passes data/passes.csv --out data/drift_vs_reference.csv
python build_page.py --data data --template site/template.html --out site/index.html
```

## 專案結構

| 檔案 | 作用 |
|---|---|
| `event.py` | 事件參數（位置、期間、發生時間），預設天使輪 |
| `catalog.py` | 讀 STAC 搜尋結果，合併成每次衛星過境一列 |
| `extract_drone_exif.py`、`drone.py` | 讀無人機照片 EXIF 清單、每日摘要（照片原檔不在倉庫，EXIF 清單在 `data/drone/`） |
| `timeline.py` | 衛星過境、無人機出勤、事件時間放到同一條時間軸 |
| `wind.py` | 氣象署測站逐時風，與各次過境對齊 |
| `extract_ocean.py`、`ocean.py` | 模型海流與模型風：抽沉船最近格點的逐時序列、換算速度與方向、對齊到各次過境 |
| `drift_sim.py` | 用 OpenDrift 的 OpenOil 模擬沉船處釋放的油漂移（在 opendrift 環境執行） |
| `drift_compare.py` | 模擬的粒子位置與文獻的方向、最遠距離並列 |
| `features.py` | 整成長格式特徵表 |
| `reference.py` | 外部文獻估計值與過境的對應 |
| `page_data.py`、`build_page.py`、`site/` | 產生統一介面頁 |
| `test_*.py` | 單元測試，與上面的模組一一對應 |
| `AI_LOG.md` | AI 協作紀錄；`HANDOFF.md` 是給新對話接手用的交接說明 |

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

## 目標與實際完成範圍

原本的目標有三項，實際完成的範圍如下（2026-10-12 評估時間與資料後，決定縮小範圍，把已有的部分做完整、可驗證，並讓事件與變數可以替換）：

1. 事件期間所有可用的衛星過境與無人機出勤，放到同一條時間軸：**完成**。
2. 為每個觀測補上同時間的物理條件：**已完成風（氣象署測站）、模型海流與模型風（Copernicus Marine，沉船最近格點）**。氣象署公開的海象資料只有最近 48 小時與 30 天，取不到 2023 年，所以海流改用 Copernicus Marine。模型資料只下載 2023-07-20 至 07-29，所以 18 次過境中只有 3 次（7/22 S1、7/24 S2、7/27 S1）有模型值。潮汐沒有另外處理，所用的海流資料集是否含潮流尚未確認。
3. 以沉船為污染源做漂移模擬並與觀測比對：**程式完成，正式結果待產生**（OpenDrift；只比方向與距離，見「漂移模擬」）。
4. 另外評估過、**未做**：雷達暗區偽陽性過濾。

因為沒有油膜面積的自動偵測，專案裡沒有任何「驗證」文獻數字的結果；文獻估計值只是並列顯示。

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


### 模型海流與模型風（Copernicus Marine）

- 下載日期 2026-10-21，用 Marine Data Store 網頁的 Subset 表單下載（需免費帳號），NetCDF 放在 `data/raw/cmems/`（不納入版控）。
- 海流：產品 GLOBAL_ANALYSISFORECAST_PHY_001_024 的資料集 `cmems_mod_glo_phy_anfc_0.083deg_PT1H-m`（檔案屬性標示版本 `_202406`），變數 `uo`、`vo`，表層（深度 0.494 m），1/12°。範圍經度 119.83–121.17、緯度 22.0–23.17，時間 2023-07-20 00:00 至 07-29 00:00 UTC，逐時 217 筆。
- 風：產品 WIND_GLO_PHY_L4_MY_012_006（KNMI）的資料集 `cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H`（檔案屬性標示版本 `_202211`），變數 `eastward_wind`、`northward_wind`，0.125°，同樣的時間範圍。檔案的變數說明是「stress-equivalent wind … at 10 m」，不是一般的 10 m 風。文獻：Trindade et al. (2020)，doi:10.1109/TGRS.2019.2946019（檔案屬性）。
- 時間：檔案以「seconds since 1970-01-01」編碼，視為 UTC（推論，檔案沒有寫時區）。
- 沉船附近：海流有陸地遮罩，離沉船最近的有效格點是 22.5833°N、120.1667°E（5.01 km）；風最近的格點 22.5625°N、120.1875°E（5.54 km），沒有缺值。程式取「最近的有效格點」，不內插；這是假設，不是沉船位置的值。

## 程式與輸出說明

### 漂移模擬（`drift_sim.py`、`drift_compare.py`）

用 OpenDrift 1.14.12 的 `OpenOil`，在沉船位置一次釋放粒子，用上面的模型海流與風推動，輸出粒子位置表；`drift_compare.py` 再把粒子位置和文獻的方向、最遠距離並列。設定（都是假設，不是觀測）：

- 釋放：沉船位置、沉沒時間 2023-07-20 21:30 UTC、一次釋放 1000 顆。油實際何時、漏多久、漏多少都不知道；粒子數只影響統計平滑度，不代表油量。船上油量 491.848 t 是總載量，不是外洩量。
- 油種：`AMSA Average Very Low Sulfur Fuel Oil (VLSFO)`。依據：Taiwan News（2023-07-22）報導天使輪沉沒時載有低硫燃油 393.4 t、輕柴油 98.1 t、潤滑油 0.348 t；「低硫燃油 = VLSFO」是我們的對應，不是報導寫的。輕柴油（約 20%）沒有模擬。
- 風漂移係數：OpenDrift 1.14.12 預設 0.03（風向量的 3%，另加海流與 Stokes drift；我們用單元測試確認過 3% 的語意）。沒有海浪資料，Stokes drift 用內建備用值 0，所以實際只有這個係數。事先固定兩組：0.03 與 0.02，看結果之後不追加、不挑選。
- 其他用 OpenDrift 預設：海流隨機擾動 0.05 m/s、風擾動 0.5 m/s、岸邊擱淺、風化過程全開；隨機種子固定為 0，結果可重現。計算步長 15 分鐘，輸出每小時。
- 擱淺：OpenDrift 的結果在粒子擱淺後位置會消失，但油還在岸上；`result_to_table` 讓擱淺粒子保留最後位置。飄出資料範圍的粒子（`missing_data`）位置維持空。
- 比對：只比方向與 7/27 的最遠距離。不比面積（模擬沒有對應的量）。方向只列「重心方位與東南（135 度）差幾度」，不做通過／不通過的判定；最遠距離同時列最遠一顆與 95% 分位數。結果在 `data/drift_vs_reference.csv`。這是並列，不是驗證：文獻數字是研究者的判釋估計。
- 方向與文獻不一致時照實寫；可能原因（推測，未驗證）包括海流 1/12° 的解析度、沒有海浪、風來源是 stress-equivalent wind、釋放時間假設。不為了接近文獻調整參數。

### 模型海流與風（`extract_ocean.py`、`ocean.py`）

- `extract_ocean.py`：從兩個 NetCDF 取沉船最近有效格點的逐時 u、v，存成 `data/ocean_at_wreck.csv`（217 列）。這是唯一用到 xarray 的程式，在 `opendrift` 環境執行；專案其餘部分只用 pandas。有效格點 = 整段時間 u、v 都沒有缺值的格點。
- `ocean.py`：把 u、v 換算成速度與方向，並對每次過境取時間最近的整點（差距上限 30 分鐘，一樣近取較早的，不內插），輸出 `data/ocean_at_passes.csv`。
- 方向定義（兩者相反，變數名稱已寫明）：`current_direction_to` 是水往哪邊流，`model_wind_direction_from` 是風從哪邊來；都是 0 為北、順時針、範圍 [0, 360)。速度為 0 時方向為空。注意北風在這裡是 0，CODiS 的 `wind_direction` 北風是 360。
- 進長格式特徵表的變數：`current_speed`、`current_direction_to`（來源 `cmems_phy_001_024`）、`model_wind_speed`、`model_wind_direction_from`（來源 `cmems_wind_012_006`），`gap_min` = 模型時間 − 過境時間。模型風與測站風用不同的變數名稱，不會在寬表裡混在一起。
- 這些值只是過境當下的環境條件，不用來「驗證」文獻。介面頁目前不顯示這些變數。

### 特徵表（`features.py`）

把時間軸、風與模型海流整成兩張表，之後加新變數只要多一個讀取程式和多幾列，不必改欄位。

- `data/passes.csv`：每次過境一列，只放不變的屬性（感測器、時間、軌道、是否涵蓋、配對的無人機日）。過境識別碼 `pass_id` = 感測器 + UTC 時間（到秒）。
- `data/features_long.csv`：每次過境、每個變數、每個來源一列（`pass_id, variable, source, value, unit, gap_min`）。這次過境不適用的變數沒有列；有查但沒值就留一列、值為空，不用 0 代替。
- `data/features_wide.csv`：每次過境一列的寬表，欄名為「變數@來源」。同一過境有兩筆觀測時（Sentinel-2 都夾在兩個整點之間）取時間差絕對值較小的一筆，一樣近取較早的；這只是暫時的取法，不代表最適合，長表保留兩筆。
- 變數與單位登記在 `features.VARIABLES`。

指令（`--ocean` 選填，不給就沒有模型海流與風）：`python features.py --timeline data/timeline.csv --wind data/wind_at_passes.csv --ocean data/ocean_at_passes.csv --out-passes data/passes.csv --out data/features_long.csv --out-wide data/features_wide.csv`

### 換成其他事件（`event.py`）

事件由 `Event` 描述：
- 必填：參考位置 `lat`、`lon`（十進位度）與分析期間 `start`、`end`（含頭尾兩天）。
- 選填：事件發生時間 `time`（沒有就不算「距事件幾小時」，`hours_since_event` 留空，不會是 0）、名稱 `name`、時區 `tz`（用來解讀 start、end 與命令列給的沒有時區的時間，預設 Asia/Taipei）。
- 沒指定事件時一律用天使輪（`event.ANGEL`），所以原本的指令與輸出不變。

`catalog.py`、`timeline.py`、`wind.py` 的命令列都接受 `--lat --lon --start --end`（換事件時四個都要給）與選填的 `--event-time "YYYY-MM-DD HH:MM"`、`--event-name`、`--tz`。`timeline.py` 的 `--drone` 是選填，不給就沒有無人機欄位。程式裡則是各函式的 `event=` 參數。

例（虛構位置，只示範參數）：
`python timeline.py --s1 s1.json --s2 s2.json --lat 28.7 --lon -88.4 --start 2030-01-10 --end 2030-01-20 --event-time "2030-01-12 05:00" --tz UTC --out timeline.csv`

限制：
- 風資料只能用氣象署 CODiS，也就是只涵蓋台灣的測站；別的地區要另寫風資料的讀取程式（例如 ERA5），表格欄位不用改。
- 表裡的欄位名稱沿用天使輪時的叫法（`covers_wreck`、`time_tw`）；換事件時 `covers_wreck` 指「涵蓋事件位置」。
- 分析期間目前只用來篩衛星過境；風與無人機資料用你給的檔案，不另外裁切。

### 外部參考觀測（`reference.py`）

`data/reference_observations.csv` 放文獻裡別人估計的數字，長格式、一個數字一列：`ref_id, sensor, date, variable, value, unit, source, note`。目前三筆都來自 JpGU 2025 摘要（Chu, Chen & Wu）：
- 2023-07-24 Sentinel-2：油膜面積 20.3 km²（往東南）
- 2023-07-27 Sentinel-1：油膜面積 10.7 km²（往東南）
- 2023-07-27 Sentinel-1：距沉船最遠 26.5 km

這些是會議摘要裡研究者的判釋估計，方法未公開，不是地面真值；本專案目前沒有油膜面積的自動偵測，所以不拿它們「驗證」我們的結果，只用來並列顯示與討論。

文獻只給日期，沒給時間，也沒說是哪個時區的日期。`match_passes` 對應過境的規則：同感測器、且過境的 UTC 日期或台灣日期任一等於該日期才算候選；候選剛好一個才配對，沒有或有多個就不猜（`no_pass`／`ambiguous`）。結果在 `data/reference_matched.csv`：三筆都配對到唯一一次過境（7/24 的 S2 為 `S2_20230724T022541Z`；7/27 的 S1 為 `S1_20230726T220124Z`，UTC 日期是 7/26、台灣日期是 7/27，只有台灣日期對得上，所以文獻的 7/27 很可能是台灣日期，這是推論）。新增變數時先登記在 `reference.VARIABLES`（含單位）。

### 介面頁（`site/index.html`）

一個自成一體的 HTML 檔，用瀏覽器直接打開就能看（資料已嵌在檔案裡，圖用內嵌 SVG 畫，不需要網路或伺服器）。內容：標題與限制提醒、時間軸（Sentinel-1／Sentinel-2 過境、無人機出勤日、文獻估計）、各次過境表、選取的過境（風、無人機配對）、三個測站的逐時風速、外部參考觀測。點選任一次過境，各區同步標示；Sentinel-2 夾在兩個整點之間的兩筆風都列出，各自標示時間差。

產生方式：
- `page_data.py`：把 `passes.csv`、`features_long.csv`、`reference_matched.csv`、`wind_hourly.csv`、`stations.csv` 與無人機每日摘要整理成頁面用的 JSON（資料處理都在這裡，有單元測試）。
- `build_page.py`：把 JSON 嵌進 `site/template.html`，輸出 `site/index.html`。
- 指令：`python build_page.py --data data --template site/template.html --out site/index.html`；換事件時加 `--lat --lon --start --end`。

限制：頁面本身的畫圖程式（`template.html` 裡的 JavaScript）沒有自動化測試，只用瀏覽器實際打開、點選與游標移動檢查過；有測試的是資料整理與嵌入的部分。沒有地圖，因為沒有可顯示的油膜範圍資料。

### 怎麼擴充

**換成別的事件**：用 `Event` 或命令列的 `--lat --lon --start --end`（見上方「換成其他事件」）。衛星目錄要先用 STAC 另外查詢該事件的範圍與期間；風資料目前只有台灣測站。

**加新的變數**（例如海流）：
1. 寫一個讀取程式，把來源資料整理成與衛星過境對齊的表（參考 `wind.py` 的 `winds_at_pass`：每次過境、每個來源一到幾列，附與過境的時間差）。
2. 在 `features.VARIABLES` 登記變數名稱與單位，並在 `features.build_features_long` 把新表轉成長格式的列（`pass_id, variable, source, value, unit, gap_min`）。欄位不變，只是多幾列。
3. 在 `page_data.py` 與 `site/template.html` 決定要不要顯示。頁面目前只畫風，新變數不會自動出現。
4. 為新的讀取程式寫測試（自己造資料；做突變檢查確認測試真的會失敗）。

**加新的外部參考觀測**：在 `data/reference_observations.csv` 多加列（要寫出處），新的變數先登記在 `reference.VARIABLES`。

**風資料換來源**：例如 ERA5 是格點資料，沒有測站座標；需要新的讀取程式，輸出格式比照 `wind_hourly.csv`（`station, time_tw, time_utc, ws_ms, wd_deg`，把「測站」換成格點代號）。這只是可行的做法，專案沒有做過。

## 進度

- [x] 文獻起點：JpGU 2025 摘要
- [x] 事件參數（官方沉沒時間與沉船位置）
- [x] 衛星目錄：Sentinel-1/2 過境與是否涵蓋沉船
- [x] 無人機清單與每日摘要
- [x] 時間軸對齊：衛星過境與無人機出勤
- [x] 風：CODiS 三個測站的逐時風與各次過境的風
- [x] 長格式特徵表（`features.py`）：各次過境的所有變數整成一張表
- [x] 統一介面頁（`site/index.html`）：時間軸、過境、風與參考觀測
- [x] 外部參考觀測表（`reference.py`）：JpGU 摘要的三個數字與對應過境
- [x] 事件參數可替換（`event.py`）：位置、期間、發生時間可換；無人機選填；`hours_since_sinking` 改名 `hours_since_event`
- [x] 模型海流與模型風（`extract_ocean.py`、`ocean.py`）：沉船最近格點，對齊到各次過境
- [ ] 潮汐（沒有另外處理）
- [ ] 雷達暗區偽陽性過濾（未做）
- [x] 漂移模擬與比對的程式（`drift_sim.py`、`drift_compare.py`）：單元測試與突變檢查完成
- [ ] 漂移模擬的正式結果（待重新下載較大範圍的海流與風後執行）

## 參考資料

- Chu, C.-H., Chen, C.-F., & Wu, C.-C. (2025). Application of Remote Sensing Technology in Monitoring Oil Pollution from Ship Grounding Incidents. JpGU Meeting 2025, U03-P04. https://pub.confit.atlas.jp/ja/event/jpgu2025/presentation/U03-P04
- Taiwan News（2023-07-22）。Doksuri could hamper efforts to recover 600 containers from sunken ship off south Taiwan. https://www.taiwannews.com.tw/en/news/4951068 （報導杜蘇芮影響打撈；同篇記載船上燃油：低硫燃油 393.4 t、輕柴油 98.1 t、潤滑油 0.348 t）
- 公視新聞（2023-08-02）。天使輪沉沒貨櫃漂流 海保署持續清除外溢油污。 https://news.pts.org.tw/article/649308
- 國家運輸安全調查委員會。1120720 ANGEL貨櫃船高雄港外海沉沒事故. https://www.ttsb.gov.tw/1243/22344/38984/post （沉沒時間、事故經過）
- 交通部航港局。礙航公告(南區)「天使輪」於高雄港第二錨區沉船位置更新（2023-08-01）. https://www.motcmpb.gov.tw/Information/Detail/90093f9c-34af-4a8c-82a3-7018cc21d57e?SiteId=1&NodeId=483 （沉船座標）
- Copernicus Data Space Ecosystem. STAC product catalogue. https://documentation.dataspace.copernicus.eu/APIs/STAC.html （端點網址、可用資料集、舊端點棄用說明）
- Copernicus Data Space Ecosystem. CDSE STAC API 根頁面. https://stac.dataspace.copernicus.eu/v1/ （`conformsTo` 宣告支援 Item Search；查詢日期 2026-10-10）
- Copernicus Data Space Ecosystem. CDSE STAC API 的 OpenAPI 描述. https://stac.dataspace.copernicus.eu/v1/api （`/search` 的 collections、bbox、datetime、limit 參數說明；互動版為 https://stac.dataspace.copernicus.eu/v1/api.html ）
- STAC API – Item Search 規範. https://github.com/radiantearth/stac-api-spec/blob/main/item-search/README.md （上述參數的標準定義，以及 bbox 順序、datetime 區間與 next 連結的規則）
- Copernicus Marine Service. Global Ocean Hourly Reprocessed Sea Surface Wind and Stress from Scatterometer and Model（WIND_GLO_PHY_L4_MY_012_006），DOI 10.48670/moi-00185. https://data.marine.copernicus.eu/product/WIND_GLO_PHY_L4_MY_012_006/ （產品名稱與代碼；資料集名稱、變數與 stress-equivalent 說明取自下載檔的屬性）
- OpenDrift 1.14.12（`OpenOil` 的設定名稱、預設值與油品資料庫取自該版本本身的設定）. https://github.com/OpenDrift/opendrift
- Copernicus Marine Service. Global Ocean Physics Analysis and Forecast（GLOBAL_ANALYSISFORECAST_PHY_001_024）. https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_PHY_001_024/ （逐時表層海流資料集；2023 年 7 月資料實際下載確認存在）
- 中央氣象署. 氣候觀測資料查詢服務（CODiS）. https://codis.cwa.gov.tw/ （測站清單、逐時風速與風向月報表；查詢日期 2026-10-11）
- 中央氣象署. 氣候觀測資料查詢服務—觀測資料說明（Ver.2025.12.31）. 於 CODiS 測站資料頁的「資料說明」下載 （站碼意義、逐時風的定義、符號說明）
- 中央氣象署. 氣象資料開放平臺. https://opendata.cwa.gov.tw/ （海象監測資料 O-B0075-001／002 僅提供最近 48 小時與 30 天；查詢日期 2026-10-11）
