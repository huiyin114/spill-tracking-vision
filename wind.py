"""讀取氣象署 CODiS 的「單項逐時月報表」（風速／風向），找出每次衛星過境時各測站的風。

月報表是「日 × 時」的表格，每一格寫成「風速 / 風向」。依 CODiS 觀測資料說明（Ver.2025.12.31）：
  - 逐時的風速、風向是整點前 10 分鐘的平均；
  - 風速 ≦ 0.2 m/s 時風向記為 0，北風記為 360；
  - 符號：-- 無觀測、x 儀器故障、V 風向不定、/ 不明。
說明沒有寫明時間標籤 01–24 的時區，也沒有說第 24 欄代表什麼。這裡視為台灣時間、
第 24 欄為隔天 00:00（推論，待核對）。

用法：
  python wind.py --raw data/raw/codis --stations data/stations.csv --timeline data/timeline.csv \
      --out-hourly data/wind_hourly.csv --out data/wind_at_passes.csv
"""
import argparse
import calendar
import re
from pathlib import Path

import numpy as np
import pandas as pd

from drone import haversine_km
from event import TAIWAN, WRECK_LAT, WRECK_LON
from timeline import gap_hours

# 風速在此值以下，資料說明規定風向記為 0（不是北風），所以風向視為沒有。
CALM_MS = 0.2

# 逐時值代表整點前 10 分鐘的平均。
WINDOW_MIN = 10

# 離過境多少分鐘內的觀測才列出。相鄰兩個觀測窗口相隔 50 分鐘，所以任何過境離最近的窗口
# 最遠 25 分鐘：門檻 ≧ 25 保證每次過境至少有一筆，< 50 保證最多兩筆。
MAX_GAP_MIN = 30

# 檔名開頭是站碼與年月，例：C0V690-2023-07-WindSpeed,WindDirection-hour.csv
FILENAME = re.compile(r"^(?P<station>[0-9A-Z]{6})-(?P<year>\d{4})-(?P<month>\d{2})-")

# 風速或風向欄出現這些符號，表示沒有可用的值。其他讀不懂的內容一律報錯，不默默略過。
MISSING_SYMBOLS = {"--", "x", "V", "/"}

OUT_COLUMNS = ["sensor", "time_tw", "covers_wreck", "station", "station_name", "dist_km",
               "obs_time_tw", "gap_min", "ws_ms", "wd_deg"]


def _number(text):
    text = text.strip()
    return float("nan") if text in MISSING_SYMBOLS else float(text)


def parse_cell(text):
    """「風速 / 風向」→ (風速 m/s, 風向度)。沒有的值是 NaN；風速 ≦ 0.2 時風向是 NaN。"""
    parts = text.split(" / ")
    if len(parts) != 2:
        raise ValueError(f"格子應為「風速 / 風向」，實際是：{text!r}")
    ws, wd = _number(parts[0]), _number(parts[1])
    if ws <= CALM_MS:
        wd = float("nan")
    return ws, wd


def load_month(path):
    """讀一個測站一個月的月報表，一個小時一列：station, time_tw, time_utc, ws_ms, wd_deg。

    站碼與年月取自檔名。缺值保留成一列（值為空），所以每月的列數固定是「天數 × 24」。
    """
    path = Path(path)
    m = FILENAME.match(path.name)
    if m is None:
        raise ValueError(f"檔名看不出站碼與年月（預期以 C0V690-2023-07- 這樣的格式開頭）：{path.name}")
    station, year, month = m["station"], int(m["year"]), int(m["month"])

    table = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    day_col = table.columns[0]
    table = table[table[day_col].str.isdigit()]  # 去掉最後的「平均」列
    expected = list(range(1, calendar.monthrange(year, month)[1] + 1))
    if table[day_col].astype(int).tolist() != expected:
        raise ValueError(f"{path.name} 的日期不是 {year}-{month:02d} 的 1–{expected[-1]} 日")
    hours = [str(h) for h in range(1, 25)]
    absent = [h for h in hours if h not in table.columns]
    if absent:
        raise ValueError(f"{path.name} 缺少時欄位：{absent}")

    rows = []
    for _, r in table.iterrows():
        midnight = pd.Timestamp(year=year, month=month, day=int(r[day_col]), tz=TAIWAN)
        for hour in range(1, 25):
            ws, wd = parse_cell(r[str(hour)])
            rows.append((station, midnight + pd.Timedelta(hours=hour), ws, wd))  # 第 24 欄 = 隔天 00:00
    out = pd.DataFrame(rows, columns=["station", "time_tw", "ws_ms", "wd_deg"])
    out.insert(2, "time_utc", out["time_tw"].dt.tz_convert("UTC"))
    return out


def load_wind(folder):
    """讀資料夾裡所有 *-hour.csv，合併成一張表，依測站、時間排序。"""
    files = sorted(Path(folder).glob("*-hour.csv"))
    if not files:
        raise ValueError(f"{folder} 底下沒有 *-hour.csv")
    wind = pd.concat([load_month(f) for f in files], ignore_index=True)
    if wind.duplicated(["station", "time_utc"]).any():
        raise ValueError("同一測站同一時間出現多次，是不是放了重複的月份檔？")
    return wind.sort_values(["station", "time_utc"]).reset_index(drop=True)


def winds_at_pass(wind, t, max_gap_min=MAX_GAP_MIN):
    """離衛星過境時間 t 不超過 max_gap_min 分鐘的觀測，加上欄位 gap_min。

    每個觀測的窗口是 [整點前 10 分鐘, 整點]。gap_min 是窗口相對過境的時間差（分鐘），
    符號與 timeline.gap_hours 相同：正值代表觀測在衛星之後，負值在之前，
    過境落在窗口內為 0。傳入的 wind 只該含一個測站；t 必須帶時區。
    """
    t = pd.Timestamp(t)
    if t.tzinfo is None:
        raise ValueError("過境時間必須帶時區")
    ends = wind["time_utc"]
    starts = ends - pd.Timedelta(minutes=WINDOW_MIN)
    gap = pd.Series([gap_hours(t, s, e) * 60 for s, e in zip(starts, ends)], index=wind.index, dtype="float64")
    near = wind[gap.abs() <= max_gap_min].copy()
    near["gap_min"] = gap[near.index].round(1)
    return near


def build_wind_at_passes(timeline, wind, stations, max_gap_min=MAX_GAP_MIN):
    """每次過境、每個測站列出時間上最近的觀測（一到兩筆），附測站離沉船的距離。

    某測站在該過境附近沒有任何觀測時，仍保留一列（觀測欄位為空），讓缺口看得見。
    """
    times = pd.to_datetime(timeline["time_utc"], utc=True)
    rows = []
    for (_, p), t in zip(timeline.iterrows(), times):
        for _, s in stations.iterrows():
            base = {
                "sensor": p["sensor"],
                "time_tw": p["time_tw"],
                "covers_wreck": bool(p["covers_wreck"]),
                "station": s["code"],
                "station_name": s["name"],
                "dist_km": round(float(haversine_km(s["lat"], s["lon"], WRECK_LAT, WRECK_LON)), 1),
            }
            near = winds_at_pass(wind[wind["station"] == s["code"]], t, max_gap_min)
            if near.empty:
                rows.append({**base, "obs_time_tw": pd.NaT, "gap_min": np.nan, "ws_ms": np.nan, "wd_deg": np.nan})
            for _, o in near.iterrows():
                rows.append({**base, "obs_time_tw": o["time_tw"], "gap_min": o["gap_min"],
                             "ws_ms": o["ws_ms"], "wd_deg": o["wd_deg"]})
    return pd.DataFrame(rows, columns=OUT_COLUMNS)


def main():
    ap = argparse.ArgumentParser(description="CODiS 逐時風速／風向與衛星過境的對齊")
    ap.add_argument("--raw", required=True, help="放月報表 CSV 的資料夾")
    ap.add_argument("--stations", required=True, help="測站清單 CSV（data/stations.csv）")
    ap.add_argument("--timeline", required=True, help="時間軸 CSV（data/timeline.csv）")
    ap.add_argument("--max-gap-min", type=float, default=MAX_GAP_MIN)
    ap.add_argument("--out-hourly", help="輸出逐時風速表 CSV 路徑")
    ap.add_argument("--out", help="輸出各次過境的風 CSV 路徑")
    args = ap.parse_args()

    wind = load_wind(args.raw)
    stations = pd.read_csv(args.stations, encoding="utf-8-sig")
    timeline = pd.read_csv(args.timeline, encoding="utf-8-sig")

    for code, g in wind.groupby("station"):
        print(f"{code}：{len(g)} 筆，缺值 {int(g['ws_ms'].isna().sum())} 筆，"
              f"風速 {g['ws_ms'].min():g}–{g['ws_ms'].max():g} m/s")
    absent = sorted(set(stations["code"]) - set(wind["station"]))
    if absent:
        print(f"注意：測站清單裡的 {absent} 在資料夾裡沒有資料")

    result = build_wind_at_passes(timeline, wind, stations, args.max_gap_min)
    print(f"\n{len(timeline)} 次過境 × {len(stations)} 站 → {len(result)} 列（時間差上限 {args.max_gap_min:g} 分鐘）")
    print(result.drop(columns=["time_tw"]).to_string(index=False))

    if args.out_hourly:
        wind.to_csv(args.out_hourly, index=False, encoding="utf-8-sig")
        print(f"已寫入 {args.out_hourly}")
    if args.out:
        result.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"已寫入 {args.out}")


if __name__ == "__main__":
    main()
