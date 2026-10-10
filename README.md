# spill-tracking-vision

天使輪（Angel）2023 高雄外海沉船油汙事件的多源遙測整合。（課程作業 HW2）

## 為什麼做這個

海上油汙常用衛星影像監測，但兩種影像各有限制：雷達影像上的暗區不一定是油，會受海面粗糙度（風浪）影響；光學影像則常被雲遮住。要判斷「這塊暗區是不是油、之後會漂到哪」，需要把影像和風、海流等物理條件放在一起看。目前這些資料分散在不同網站與格式，每次分析都要手動整合。

## 事件背景

帛琉籍貨櫃輪天使輪（Angel）於 2023-07-21 00:19（台灣時間）在高雄港外沉沒，船上燃油外洩（來源：JpGU 2025 U03-P04）。報導指出，杜蘇芮與卡努颱風預期會影響打撈與除污作業。

## 現有研究

中央大學太空及遙測研究中心（Chu et al., 2025）曾用 Sentinel-1/2、Landsat-8/9 與無人機監測此事件，整理見 [docs/jpgu2025.md](docs/jpgu2025.md)。

## 本專案想做的（暫定，會隨進度修正）

1. 整理事件期間所有可用的衛星過境與無人機出勤，放到同一條時間軸。
2. 為每個觀測補上同時間的物理條件（風、海流等）。
3. 以已知污染源（沉船）做漂移模擬，並與觀測比對。

## 進度

- [x] 文獻起點：JpGU 2025 摘要

## 參考資料

- Chu, C.-H., Chen, C.-F., & Wu, C.-C. (2025). Application of Remote Sensing Technology in Monitoring Oil Pollution from Ship Grounding Incidents. JpGU Meeting 2025, U03-P04. https://pub.confit.atlas.jp/ja/event/jpgu2025/presentation/U03-P04
- Taiwan News（2023-07-22）。Doksuri could hamper efforts to recover 600 containers from sunken ship off south Taiwan. https://www.taiwannews.com.tw/en/news/4951068
- 公視新聞（2023-08-02）。天使輪沉沒貨櫃漂流 海保署持續清除外溢油污。 https://news.pts.org.tw/article/649308
