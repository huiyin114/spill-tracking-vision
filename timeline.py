"""把衛星過境、無人機出勤與沉沒時間放到同一條時間軸，找出可以互相驗證的配對。

每次衛星過境一列，欄位包含距沉沒幾小時，以及時間最近的無人機日。
用法：
  python timeline.py --s1 data/raw/stac_s1.json --s2 data/raw/stac_s2.json \
      --drone data/drone/angel_drone_exif.csv --out data/timeline.csv
"""
import argparse

import pandas as pd

from catalog import group_passes, load_items
from drone import daily_summary, load_photos
from event import SINKING_TIME

# 配對的時間差上限（小時）。油在一天內會漂很遠，超過就不拿來配對。
# 時間差會保留在表裡，要更嚴格可以自己再篩。
MAX_GAP_HOURS = 24

PASS_COLUMNS = ["sensor", "time_tw", "time_utc", "orbit_state", "mode", "covers_wreck", "cloud_cover_min"]


def gap_hours(t, start, end):
    """無人機出勤時段 [start, end] 相對衛星時間 t 的時間差（小時），為「無人機減衛星」。

    正值：無人機在衛星之後；負值：無人機在衛星之前；t 落在時段內為 0。
    """
    if t < start:
        return (start - t).total_seconds() / 3600
    if t > end:
        return -(t - end).total_seconds() / 3600
    return 0.0


def nearest_drone_day(t, days):
    """時間最近的無人機日，回傳 (日期, 時間差, 離沉船 1 km 內張數)；沒有任何無人機日則回傳 None。"""
    best = None
    for _, day in days.iterrows():
        gap = gap_hours(t, day["start_utc"], day["end_utc"])
        if best is None or abs(gap) < abs(best[1]):
            best = (day["date"], gap, day["n_near"])
    return best


def load_passes(s1_json, s2_json):
    """讀兩份 STAC 搜尋結果，合併成「每次過境一列」，依時間排序。"""
    s1 = group_passes(load_items(s1_json)).assign(sensor="S1")
    s2 = group_passes(load_items(s2_json)).assign(sensor="S2")
    for passes in (s1, s2):
        passes["cloud_cover_min"] = passes["cloud_cover_min"].astype("float64")  # S1 沒有雲量，全是空值
    both = pd.concat([s1[PASS_COLUMNS], s2[PASS_COLUMNS]], ignore_index=True)
    return both.sort_values("time_utc").reset_index(drop=True)


def build_timeline(passes, days, max_gap_hours=MAX_GAP_HOURS):
    """每次過境一列：距沉沒幾小時，以及配對到的無人機日。

    - 沒有涵蓋沉船的過境保留在表裡（時間軸才完整），但不配對，因為它拍不到沉船附近。
    - 離沉船 1 km 內沒有照片的無人機日（例如 7/30）不參與配對。
    - 時間差超過 max_gap_hours 就不配對。
    """
    near_days = days[days["n_near"] > 0]
    rows = []
    for _, p in passes.sort_values("time_utc").iterrows():
        row = {
            "sensor": p["sensor"],
            "time_tw": p["time_tw"],
            "time_utc": p["time_utc"],
            "hours_since_sinking": round((p["time_utc"] - SINKING_TIME).total_seconds() / 3600, 1),
            "orbit_state": p["orbit_state"],
            "mode": p["mode"],
            "covers_wreck": bool(p["covers_wreck"]),
            "cloud_cover_min": p["cloud_cover_min"],
            "drone_date": None,
            "drone_gap_hours": float("nan"),
            "drone_n_near": float("nan"),
        }
        if row["covers_wreck"]:
            best = nearest_drone_day(p["time_utc"], near_days)
            if best is not None and abs(best[1]) <= max_gap_hours:
                row["drone_date"] = best[0]
                row["drone_gap_hours"] = round(best[1], 1)
                row["drone_n_near"] = best[2]
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description="衛星過境與無人機出勤的時間軸對齊")
    ap.add_argument("--s1", required=True, help="Sentinel-1 的 STAC 搜尋結果 JSON")
    ap.add_argument("--s2", required=True, help="Sentinel-2 的 STAC 搜尋結果 JSON")
    ap.add_argument("--drone", required=True, help="無人機 EXIF 清單 CSV")
    ap.add_argument("--max-gap-hours", type=float, default=MAX_GAP_HOURS)
    ap.add_argument("--out", help="輸出 CSV 路徑")
    args = ap.parse_args()

    passes = load_passes(args.s1, args.s2)
    days = daily_summary(load_photos(args.drone))
    timeline = build_timeline(passes, days, args.max_gap_hours)

    n_paired = int(timeline["drone_date"].notna().sum())
    print(f"{len(timeline)} 次過境，其中 {n_paired} 次配對到無人機日（時間差上限 {args.max_gap_hours:g} 小時）")
    print(timeline.drop(columns=["time_utc"]).to_string(index=False))
    if args.out:
        timeline.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"已寫入 {args.out}")


if __name__ == "__main__":
    main()
