"""把漂移模擬的粒子位置，和文獻（外部參考觀測）的方向與最遠距離並列。

輸入是 drift_sim.py 輸出的粒子表（data/drift_particles_<run>.csv，長格式）：
  time_utc, particle, lon, lat, status
粒子被停用後沒有位置（lon、lat 為空）。stranded（擱淺在岸上）的粒子保留位置，算進統計並另外計數。

對每個模擬、每個「文獻有對應過境」的過境，取最近的輸出時間（差距上限 30 分鐘），算：
  重心位置、重心相對沉船的方位（0 為北、順時針）與 8 方位名稱、
  重心與最遠一顆粒子離沉船的距離、95% 分位數距離。
再附上文獻的方向（東南 = SE）與最遠距離（有的話）。

這只是並列，不是驗證：文獻數字是研究者的判釋估計；模擬的釋放時間、釋放量、風漂移係數都是假設。
油膜面積不比，模擬沒有對應的量。方向只給「和文獻方位中心（東南 = 135 度）差幾度」，不做通過／不通過的判定。

用法：
  python drift_compare.py --particles base=data/drift_particles_base.csv wind002=data/drift_particles_wind002.csv \
      --matched data/reference_matched.csv --passes data/passes.csv --out data/drift_vs_reference.csv
"""
import argparse

import numpy as np
import pandas as pd

from drone import haversine_km
from event import ANGEL

PARTICLE_COLUMNS = ["time_utc", "particle", "lon", "lat", "status"]
STATUS_STRANDED = "stranded"
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
COMPASS_CENTER = {name: i * 45.0 for i, name in enumerate(COMPASS)}

# 文獻的方向（來自 data/reference_observations.csv 的 note：「油膜往東南」）。
# 方向在 note 裡不是數值欄位，所以這裡照 ref_id 對應；新增文獻方向時在這裡加。
REFERENCE_DIRECTION = {
    "jpgu2025-s2-0724-area": "SE",
    "jpgu2025-s1-0727-area": "SE",
}

RESULT_COLUMNS = ["run_id", "pass_id", "pass_time_utc", "sim_time_utc", "gap_min",
                  "n_particles", "n_with_position", "n_stranded",
                  "centroid_lat", "centroid_lon", "centroid_distance_km",
                  "centroid_bearing_deg", "centroid_compass",
                  "max_distance_km", "p95_distance_km",
                  "ref_direction", "bearing_diff_to_ref_deg", "ref_max_distance_km"]


def bearing_deg(lat1, lon1, lat2, lon2):
    """從點 1 看點 2 的初始方位（度，0 為北、順時針、[0, 360)）。兩點相同時是 NaN。"""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2, dtype=float) - lon1)
    x = np.sin(dl) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    b = np.degrees(np.arctan2(x, y)) % 360.0
    return np.where((np.abs(x) < 1e-15) & (np.abs(y) < 1e-15), np.nan, b)


def angle_diff_deg(a, b):
    """兩個方位的最小夾角（度，0 到 180）。"""
    return np.abs((np.asarray(a, dtype=float) - np.asarray(b, dtype=float) + 180.0) % 360.0 - 180.0)


def compass8(deg):
    """方位換成 8 方位名稱，每個方位涵蓋以它為中心的 45 度（N 是 337.5 到 22.5）。缺值回傳 None。"""
    if deg is None or not np.isfinite(deg):
        return None
    return COMPASS[int(((deg + 22.5) % 360.0) // 45.0)]


def load_particles(path):
    """讀粒子表。缺欄位、同一時間同一粒子重複都報錯。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = [c for c in PARTICLE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} 缺少欄位：{missing}")
    df = df[PARTICLE_COLUMNS].copy()
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    if df.duplicated(["time_utc", "particle"]).any():
        raise ValueError(f"{path} 同一時間同一粒子出現多次")
    return df.sort_values(["time_utc", "particle"]).reset_index(drop=True)


def nearest_output_time(particles, t, max_gap_min=30):
    """離 t 最近的輸出時間與時間差（分鐘，輸出時間減 t）；差距超過上限或沒有輸出時回傳 None。一樣近取較早的。"""
    t = pd.Timestamp(t)
    times = pd.Series(particles["time_utc"].unique())
    if times.empty:
        return None
    gap = (times - t).dt.total_seconds() / 60.0
    order = pd.DataFrame({"abs": gap.abs(), "gap": gap}).sort_values(["abs", "gap"])
    k = order.index[0]
    if order["abs"].iloc[0] > max_gap_min:
        return None
    return times.iloc[k], float(gap.iloc[k])


def summarize_at(particles, t, wreck_lat, wreck_lon, max_gap_min=30):
    """取最近的輸出時間（差距上限 max_gap_min 分鐘）的粒子統計。沒有符合的時間回傳 None。"""
    found = nearest_output_time(particles, t, max_gap_min)
    if found is None:
        return None
    when, gap_min = found
    rows = particles[particles["time_utc"] == when]
    pos = rows[np.isfinite(rows["lon"]) & np.isfinite(rows["lat"])]
    out = {"sim_time_utc": when, "gap_min": gap_min,
           "n_particles": int(particles["particle"].nunique()),
           "n_with_position": int(len(pos)),
           "n_stranded": int((pos["status"] == STATUS_STRANDED).sum())}
    if pos.empty:
        nan = {c: np.nan for c in ("centroid_lat", "centroid_lon", "centroid_distance_km", "centroid_bearing_deg",
                                   "max_distance_km", "p95_distance_km")}
        return {**out, **nan, "centroid_compass": None}
    clat, clon = float(pos["lat"].mean()), float(pos["lon"].mean())
    dist = np.asarray(haversine_km(wreck_lat, wreck_lon, pos["lat"].to_numpy(), pos["lon"].to_numpy()))
    bearing = float(bearing_deg(wreck_lat, wreck_lon, clat, clon))
    return {**out, "centroid_lat": clat, "centroid_lon": clon,
            "centroid_distance_km": float(haversine_km(wreck_lat, wreck_lon, clat, clon)),
            "centroid_bearing_deg": bearing, "centroid_compass": compass8(bearing),
            "max_distance_km": float(dist.max()), "p95_distance_km": float(np.percentile(dist, 95))}


def compare_runs(runs, matched, passes, wreck_lat=ANGEL.lat, wreck_lon=ANGEL.lon, max_gap_min=30):
    """runs: {run_id: 粒子表}。對每個模擬、每個有配對到過境的文獻項目算一列。

    matched 是 reference_matched.csv，passes 是 passes.csv（用 pass_id 查過境的 UTC 時間）。
    """
    pass_time = dict(zip(passes["pass_id"], pd.to_datetime(passes["time_utc"], utc=True)))
    ok = matched[matched["match"] == "matched"]
    rows = []
    for run_id, particles in runs.items():
        for pass_id, grp in ok.groupby("pass_id", sort=True):
            if pass_id not in pass_time:
                raise ValueError(f"參考觀測對應的過境 {pass_id} 不在過境表裡，兩份輸入對不上")
            dirs = sorted({REFERENCE_DIRECTION[r] for r in grp["ref_id"] if r in REFERENCE_DIRECTION})
            if len(dirs) > 1:
                raise ValueError(f"過境 {pass_id} 的文獻方向互相矛盾：{dirs}")
            ref_dir = dirs[0] if dirs else None
            dist = grp.loc[grp["variable"] == "oil_max_distance", "value"]
            if len(dist) > 1:
                raise ValueError(f"過境 {pass_id} 有多個文獻最遠距離，無法決定用哪一個")
            s = summarize_at(particles, pass_time[pass_id], wreck_lat, wreck_lon, max_gap_min)
            row = {"run_id": run_id, "pass_id": pass_id, "pass_time_utc": pass_time[pass_id],
                   "ref_direction": ref_dir,
                   "ref_max_distance_km": float(dist.iloc[0]) if len(dist) else np.nan}
            if s is not None:
                row.update(s)
                row["bearing_diff_to_ref_deg"] = (
                    float(angle_diff_deg(s["centroid_bearing_deg"], COMPASS_CENTER[ref_dir]))
                    if ref_dir else np.nan)
            rows.append(row)
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def main():
    ap = argparse.ArgumentParser(description="漂移模擬與文獻的方向、最遠距離並列")
    ap.add_argument("--particles", nargs="+", required=True, metavar="RUN=PATH", help="模擬名稱=粒子表 CSV，可多個")
    ap.add_argument("--matched", required=True, help="data/reference_matched.csv")
    ap.add_argument("--passes", required=True, help="data/passes.csv")
    ap.add_argument("--max-gap-min", type=float, default=30)
    ap.add_argument("--out", help="輸出 CSV 路徑")
    args = ap.parse_args()

    runs = {}
    for item in args.particles:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            ap.error(f"--particles 要寫成 名稱=路徑，收到 {item!r}")
        if name in runs:
            ap.error(f"模擬名稱重複：{name}")
        runs[name] = load_particles(path)
    matched = pd.read_csv(args.matched, encoding="utf-8-sig")
    passes = pd.read_csv(args.passes, encoding="utf-8-sig")
    out = compare_runs(runs, matched, passes, max_gap_min=args.max_gap_min)
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(out[["run_id", "pass_id", "gap_min", "n_with_position", "n_stranded", "centroid_compass",
                   "centroid_bearing_deg", "centroid_distance_km", "max_distance_km", "p95_distance_km",
                   "ref_direction", "ref_max_distance_km"]].round(2).to_string(index=False))
    if args.out:
        out.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"已寫入 {args.out}")


if __name__ == "__main__":
    main()
