"""把 HYCOM 一天一個檔的 NetCDF 合併成一個檔，供 drift_sim.py 當海流。

為什麼要這一步：HYCOM 的 NCSS 網站一次只准抓一天，下載會得到好幾個檔，相鄰兩檔的交界時刻
（隔天 00:00）會重複出現。這支程式把它們依時間排好、重複的時刻只留一個，並檢查時間間隔
是否固定（中間沒有缺一天）。重複時刻的 u、v 若不相同就報錯，不默默挑一個。

需要 xarray 與 netCDF4，在 opendrift 環境執行；沒裝 xarray 時，時間處理的純計算函式
照樣能 import 與測試。

用法（在 opendrift 環境）：
  python merge_hycom.py --inputs data/raw/hycom/hycom_07*.nc --out data/raw/hycom/hycom_merged.nc
"""
import argparse

import numpy as np

VARIABLES = ("water_u", "water_v")


def merge_plan(times_per_file):
    """每個檔的時間陣列 → 合併計畫。

    回傳 (選取, 重複)：
      選取：依時間排序的 [(檔索引, 該檔內的時間索引)]，同一時刻只留最先出現的檔；
      重複：[(第一次出現的 (檔, 索引), 後來出現的 (檔, 索引))]，供呼叫端核對數值。
    """
    first = {}
    dups = []
    for f, times in enumerate(times_per_file):
        for i, t in enumerate(np.asarray(times, dtype="datetime64[ns]")):
            key = t.astype("int64")
            if key in first:
                dups.append((first[key], (f, i)))
            else:
                first[key] = (f, i)
    return [first[k] for k in sorted(first)], dups


def check_regular(times, step_hours):
    """時間必須至少兩筆，且相鄰間隔都等於 step_hours 小時，否則報錯（缺了一天就會在這裡被抓到）。"""
    t = np.asarray(times, dtype="datetime64[ns]")
    if len(t) < 2:
        raise ValueError("時間少於兩筆，無法檢查間隔")
    steps = np.unique(np.diff(t).astype("timedelta64[s]").astype(int))
    expected = int(step_hours * 3600)
    if len(steps) != 1 or steps[0] != expected:
        raise ValueError(f"時間間隔不是固定 {step_hours} 小時：出現 {sorted(steps.tolist())} 秒")


def merge_files(paths, out, step_hours=3):
    """讀入多個 HYCOM 檔，合併後寫到 out。回傳合併後的時間陣列。"""
    import xarray as xr  # 只有這裡需要 xarray

    datasets = [xr.open_dataset(p).load() for p in paths]
    for p, d in zip(paths, datasets):
        missing = [v for v in VARIABLES if v not in d]
        if missing:
            raise ValueError(f"{p} 缺少變數 {missing}")
        if "depth" in d.dims and d.sizes["depth"] != 1:
            raise ValueError(f"{p} 的 depth 不是單一層（{d.sizes['depth']} 層），請下載時只選表層")
    plan, dups = merge_plan([d["time"].values for d in datasets])
    for (f1, i1), (f2, i2) in dups:
        for v in VARIABLES:
            a = datasets[f1][v].isel(time=i1).values
            b = datasets[f2][v].isel(time=i2).values
            if not np.allclose(a, b, equal_nan=True):
                raise ValueError(f"{paths[f1]} 與 {paths[f2]} 的重複時刻 {v} 數值不同")
    offsets = np.cumsum([0] + [d.sizes["time"] for d in datasets])
    merged = xr.concat(datasets, dim="time")
    merged = merged.isel(time=[int(offsets[f] + i) for f, i in plan])
    check_regular(merged["time"].values, step_hours)
    merged.to_netcdf(out)
    return merged["time"].values


def main():
    ap = argparse.ArgumentParser(description="合併 HYCOM 一天一個檔的 NetCDF")
    ap.add_argument("--inputs", nargs="+", required=True, help="HYCOM NetCDF 檔（可多個）")
    ap.add_argument("--out", required=True, help="輸出的合併檔")
    ap.add_argument("--step-hours", type=float, default=3, help="預期的時間間隔（小時）")
    args = ap.parse_args()
    times = merge_files(sorted(args.inputs), args.out, args.step_hours)
    print(f"{len(times)} 個時刻，{times[0]} → {times[-1]}，已寫入 {args.out}")


if __name__ == "__main__":
    main()
