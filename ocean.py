"""模型海流與模型風：u/v 換算成速度與方向、讀沉船處的逐時表、對齊到衛星過境。

資料來源（皆為 Copernicus Marine 的模式／再分析產品，不是現場觀測）：
  海流  GLOBAL_ANALYSISFORECAST_PHY_001_024 的 uo、vo（表層，1/12 度）
  風    WIND_GLO_PHY_L4_MY_012_006 的 eastward_wind、northward_wind（0.125 度，
        屬 stress-equivalent wind，不是一般的 10 m 風）

方向定義（兩者相反，變數名稱已寫明，不要混用）：
  海流方向 current_direction_to       水往哪個方向流，0 為北、順時針、範圍 [0, 360)
  風向     model_wind_direction_from  風從哪個方向來，0 為北、順時針、範圍 [0, 360)
  u、v 的速度為 0 時方向沒有意義，值為空。注意：這裡北風是 0，CODiS 的 wind_direction 北風是 360。

對齊規則：每次過境取「時間差絕對值最小」的那一個整點（正值代表模型時間在衛星之後），
超過 max_gap_min 就不產生該次過境的資料；剛好一樣近時取較早的。只取一個整點，不內插。

用法：
  python ocean.py --timeline data/timeline.csv --ocean data/ocean_at_wreck.csv \
      --out data/ocean_at_passes.csv
"""
import argparse

import numpy as np
import pandas as pd

MAX_GAP_MIN = 30
SOURCE_CURRENT = "cmems_phy_001_024"
SOURCE_WIND = "cmems_wind_012_006"

# 沉船處逐時表（data/ocean_at_wreck.csv）必要的欄位；其餘（格點位置、距離）是附註。
REQUIRED_COLUMNS = ["time_utc", "current_u", "current_v", "wind_u", "wind_v"]
OCEAN_COLUMNS = REQUIRED_COLUMNS + ["current_lat", "current_lon", "current_dist_km",
                                    "wind_lat", "wind_lon", "wind_dist_km"]
ALIGNED_COLUMNS = ["sensor", "time_tw", "obs_time_utc", "gap_min", "current_speed",
                   "current_direction_to", "model_wind_speed", "model_wind_direction_from"]


def speed(u, v):
    """速度 = sqrt(u² + v²)。可傳數字或陣列；有缺值的結果是 NaN。"""
    return np.hypot(np.asarray(u, dtype=float), np.asarray(v, dtype=float))


def direction_to(u, v):
    """向量指向的方向（度，0 為北、順時針、[0, 360)）。速度為 0 或有缺值時是 NaN。"""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    d = np.degrees(np.arctan2(u, v)) % 360.0
    d = np.where(d >= 360.0, 0.0, d)  # 浮點誤差可能讓 -1e-15 % 360 剛好等於 360
    return np.where((u == 0) & (v == 0), np.nan, d)


def direction_from(u, v):
    """向量來自的方向（度，0 為北、順時針、[0, 360)）= 指向的方向加 180 度。"""
    return (direction_to(u, v) + 180.0) % 360.0


def load_ocean(path):
    """讀沉船處的逐時表，時間轉 UTC、依時間排序。缺必要欄位或時間重複就報錯。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} 缺少欄位：{missing}")
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    if df["time_utc"].duplicated().any():
        raise ValueError(f"{path} 的時間有重複")
    return df.sort_values("time_utc").reset_index(drop=True)


def ocean_at_passes(timeline, ocean, max_gap_min=MAX_GAP_MIN):
    """每次過境取最近的整點，換算成速度與方向。

    輸出一次過境一列（沒有模型資料的過境不出現）。gap_min = 模型時間 − 過境時間（分鐘）。
    模型的 u 或 v 是空的，就留一列、值為空，不補 0。
    """
    times = pd.to_datetime(timeline["time_utc"], utc=True)
    obs = pd.to_datetime(ocean["time_utc"], utc=True).reset_index(drop=True)
    rows = []
    for (_, p), t in zip(timeline.iterrows(), times):
        if obs.empty:
            break
        gap = (obs - t).dt.total_seconds() / 60.0
        order = pd.DataFrame({"abs": gap.abs(), "gap": gap}).sort_values(["abs", "gap"])
        k = order.index[0]
        if order["abs"].iloc[0] > max_gap_min:
            continue
        o = ocean.iloc[k]
        rows.append({
            "sensor": p["sensor"], "time_tw": p["time_tw"], "obs_time_utc": obs.iloc[k],
            "gap_min": float(gap.iloc[k]),
            "current_speed": float(speed(o["current_u"], o["current_v"])),
            "current_direction_to": float(direction_to(o["current_u"], o["current_v"])),
            "model_wind_speed": float(speed(o["wind_u"], o["wind_v"])),
            "model_wind_direction_from": float(direction_from(o["wind_u"], o["wind_v"])),
        })
    return pd.DataFrame(rows, columns=ALIGNED_COLUMNS)


def main():
    ap = argparse.ArgumentParser(description="把沉船處的模型海流與風對齊到衛星過境")
    ap.add_argument("--timeline", required=True, help="時間軸 CSV（data/timeline.csv）")
    ap.add_argument("--ocean", required=True, help="沉船處逐時表 CSV（data/ocean_at_wreck.csv）")
    ap.add_argument("--max-gap-min", type=float, default=MAX_GAP_MIN)
    ap.add_argument("--out", help="輸出 CSV 路徑")
    args = ap.parse_args()

    timeline = pd.read_csv(args.timeline, encoding="utf-8-sig")
    aligned = ocean_at_passes(timeline, load_ocean(args.ocean), args.max_gap_min)
    print(f"{len(timeline)} 次過境中 {len(aligned)} 次有模型資料（最大時間差 {args.max_gap_min:g} 分鐘）")
    if args.out:
        aligned.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"已寫入 {args.out}")


if __name__ == "__main__":
    main()
