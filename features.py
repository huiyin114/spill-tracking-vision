"""把時間軸與風整合成「長格式」特徵表，之後加新變數（海流、潮汐…）不必改欄位。

兩張表：
  passes.csv         每次衛星過境一列，只放不會變的屬性（感測器、時間、軌道、是否涵蓋、配對的無人機日）。
  features_long.csv  每次過境、每個變數、每個來源一列：pass_id, variable, source, value, unit, gap_min。

規則：
  - 這次過境「不適用」的變數沒有列（例如 Sentinel-1 沒有雲量、沒配對到無人機日就沒有無人機欄位）。
  - 來源有查、但沒有值，就留一列、值為空（例如測站在該時段沒有觀測）。
  - source 是測站代碼時，位置可到 data/stations.csv 查。
  - gap_min 是觀測相對衛星過境的時間差（分鐘，正值代表觀測在衛星之後），非觀測類的變數為空。

用法：
  python features.py --timeline data/timeline.csv --wind data/wind_at_passes.csv \
      --out-passes data/passes.csv --out data/features_long.csv
"""
import argparse

import numpy as np
import pandas as pd

# 變數登記表：變數名 → (單位, 說明)。新增變數時先在這裡登記，輸出表的 unit 欄由它而來。
VARIABLES = {
    "hours_since_event": ("h", "過境距事件發生時間的小時數（負值為事件之前）"),
    "cloud_cover_min": ("%", "涵蓋事件位置的圖幅中最小的雲量；是整個圖幅的平均，不是事件處的雲量"),
    "drone_gap_hours": ("h", "最近的無人機日相對過境的時間差（無人機減衛星，正值為無人機在後）"),
    "drone_n_near": ("photos", "該無人機日拍在事件位置附近（1 km 內）的照片張數"),
    "wind_speed": ("m/s", "測站逐時風速（整點前 10 分鐘平均）"),
    "wind_direction": ("deg", "測站逐時風向（360 為北風；風速 ≦ 0.2 m/s 時為空）"),
}

PASS_COLUMNS = ["pass_id", "sensor", "time_tw", "time_utc", "orbit_state", "mode", "covers_wreck", "drone_date"]
LONG_COLUMNS = ["pass_id", "variable", "source", "value", "unit", "gap_min"]


def make_pass_id(sensor, t):
    """過境的識別碼：感測器加 UTC 時間（到秒），例如 S2_20230724T022539Z。

    同一感測器兩次過境不會在同一秒內（目錄以 10 分鐘間隔合併），所以不會重複。
    """
    t = pd.Timestamp(t)
    if t.tzinfo is None:
        raise ValueError("過境時間必須帶時區")
    return f"{sensor}_{t.tz_convert('UTC').strftime('%Y%m%dT%H%M%SZ')}"


def build_passes(timeline):
    """每次過境一列，依時間排序。"""
    times = pd.to_datetime(timeline["time_utc"], utc=True)
    out = timeline[PASS_COLUMNS[1:]].copy()
    out.insert(0, "pass_id", [make_pass_id(s, t) for s, t in zip(timeline["sensor"], times)])
    if out["pass_id"].duplicated().any():
        raise ValueError("時間軸裡有重複的過境")
    order = times.sort_values().index
    return out.loc[order].reset_index(drop=True)


def build_features_long(timeline, wind_at_passes):
    """時間軸與風合成長表。風表裡的過境必須都在時間軸裡，否則報錯（兩份輸入不一致）。"""
    known = set(build_passes(timeline)["pass_id"])
    rows = []

    def add(pass_id, variable, source, value, gap=np.nan):
        rows.append({"pass_id": pass_id, "variable": variable, "source": source,
                     "value": float(value), "gap_min": gap})

    times = pd.to_datetime(timeline["time_utc"], utc=True)
    for (_, p), t in zip(timeline.iterrows(), times):
        pid = make_pass_id(p["sensor"], t)
        if pd.notna(p["hours_since_sinking"]):
            add(pid, "hours_since_event", "event", p["hours_since_sinking"])
        if pd.notna(p["cloud_cover_min"]):
            add(pid, "cloud_cover_min", "stac", p["cloud_cover_min"])
        if pd.notna(p["drone_gap_hours"]):
            add(pid, "drone_gap_hours", "drone", p["drone_gap_hours"])
            add(pid, "drone_n_near", "drone", p["drone_n_near"])

    for _, w in wind_at_passes.iterrows():
        pid = make_pass_id(w["sensor"], pd.to_datetime(w["time_tw"], utc=True))
        if pid not in known:
            raise ValueError(f"風表裡的過境 {pid} 不在時間軸裡，兩份輸入對不上")
        add(pid, "wind_speed", w["station"], w["ws_ms"], w["gap_min"])
        add(pid, "wind_direction", w["station"], w["wd_deg"], w["gap_min"])

    out = pd.DataFrame(rows, columns=[c for c in LONG_COLUMNS if c != "unit"])
    out.insert(4, "unit", out["variable"].map({k: v[0] for k, v in VARIABLES.items()}))
    if out.duplicated(["pass_id", "variable", "source", "gap_min"]).any():
        raise ValueError("同一過境、變數、來源、時間差出現多次，輸入有重複")
    return out.sort_values(["pass_id", "variable", "source", "gap_min"]).reset_index(drop=True)


def to_wide(features, pick="nearest"):
    """長表轉成每次過境一列，欄名是「變數@來源」，例如 wind_speed@C0V690。

    同一過境、變數、來源有多筆時（例如 Sentinel-2 夾在兩個整點觀測之間），pick="nearest"
    取時間差絕對值最小的一筆；剛好一樣近時取較早的（gap_min 較小）。選到的值是空就保持空，
    不會改拿另一筆。要平均或內插，之後再加，這裡不替使用者決定。
    """
    if pick != "nearest":
        raise ValueError(f"不支援的 pick：{pick!r}")
    f = features.copy()
    f["_abs"] = f["gap_min"].abs().fillna(0.0)
    f["_gap"] = f["gap_min"].fillna(0.0)
    f = f.sort_values(["pass_id", "variable", "source", "_abs", "_gap"])
    f = f.drop_duplicates(["pass_id", "variable", "source"], keep="first")
    f["column"] = f["variable"] + "@" + f["source"]
    wide = f.pivot(index="pass_id", columns="column", values="value")
    wide.columns.name = None
    return wide.reset_index()


def main():
    ap = argparse.ArgumentParser(description="時間軸與風的長格式特徵表")
    ap.add_argument("--timeline", required=True, help="時間軸 CSV（data/timeline.csv）")
    ap.add_argument("--wind", required=True, help="各次過境的風 CSV（data/wind_at_passes.csv）")
    ap.add_argument("--out-passes", help="輸出過境表 CSV 路徑")
    ap.add_argument("--out", help="輸出長格式特徵表 CSV 路徑")
    ap.add_argument("--out-wide", help="另外輸出每次過境一列的寬表 CSV 路徑（取時間最近的一筆）")
    args = ap.parse_args()

    timeline = pd.read_csv(args.timeline, encoding="utf-8-sig")
    wind = pd.read_csv(args.wind, encoding="utf-8-sig")
    passes = build_passes(timeline)
    features = build_features_long(timeline, wind)

    print(f"{len(passes)} 次過境 → {len(features)} 列特徵")
    print(features.groupby(["variable", "source"]).size().to_string())
    for path, table in ((args.out_passes, passes), (args.out, features),
                        (args.out_wide, to_wide(features) if args.out_wide else None)):
        if path:
            table.to_csv(path, index=False, encoding="utf-8-sig")
            print(f"已寫入 {path}")


if __name__ == "__main__":
    main()
