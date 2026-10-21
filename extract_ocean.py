"""從 Copernicus Marine 的 NetCDF 抽出沉船最近有效格點的逐時 u/v，存成小 CSV。

為什麼要這一步：讀 NetCDF 需要 xarray 與 netCDF4，專案其餘部分只用 pandas。先抽成
data/ocean_at_wreck.csv，其他程式就只讀 CSV。這支程式是唯一要用 xarray 的地方，
在 opendrift 環境執行（那裡已經有）；沒裝 xarray 時，本檔的純計算函式照樣能 import 與測試。

取格點的規則：
  - 有效格點 = 整段時間 u 與 v 都沒有缺值的格點（陸地遮罩的格點整段都是缺值）。
  - 取離事件位置最近的有效格點，不內插。距離會寫進輸出，海流與風各自一欄。
  - 時間照 NetCDF 的 "seconds since 1970-01-01" 當 UTC（推論，檔案沒有寫時區）。

用法（在 opendrift 環境）：
  python extract_ocean.py --current-nc data/raw/cmems/<海流>.nc --wind-nc data/raw/cmems/<風>.nc \
      --out data/ocean_at_wreck.csv
"""
import argparse

import numpy as np
import pandas as pd

from drone import haversine_km
from event import add_event_args, event_from_args
from ocean import OCEAN_COLUMNS


def valid_mask(*arrays):
    """格點是否有效：所有陣列（時間, 緯度, 經度）在整段時間都沒有缺值。"""
    ok = None
    for a in arrays:
        m = np.all(np.isfinite(np.asarray(a, dtype=float)), axis=0)
        ok = m if ok is None else ok & m
    return ok


def nearest_valid_cell(lats, lons, valid, lat, lon):
    """離 (lat, lon) 最近的有效格點，回傳 (緯度索引, 經度索引, 距離公里)。

    距離相同時取索引較小者；完全沒有有效格點就報錯。
    """
    la, lo = np.meshgrid(np.asarray(lats, dtype=float), np.asarray(lons, dtype=float), indexing="ij")
    d = np.where(valid, haversine_km(lat, lon, la, lo), np.inf)
    if not np.isfinite(d).any():
        raise ValueError("沒有任何有效格點（整張都是缺值）")
    i, j = np.unravel_index(np.argmin(d), d.shape)
    return int(i), int(j), float(d[i, j])


def series_at_point(times, lats, lons, u, v, lat, lon):
    """由陣列取最近有效格點的逐時 u、v。回傳 (DataFrame[time_utc, u, v], 格點緯度, 格點經度, 距離公里)。"""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    i, j, dist = nearest_valid_cell(lats, lons, valid_mask(u, v), lat, lon)
    df = pd.DataFrame({"time_utc": pd.to_datetime(times, utc=True), "u": u[:, i, j], "v": v[:, i, j]})
    return df, float(np.asarray(lats)[i]), float(np.asarray(lons)[j]), dist


def read_point_series(path, u_name, v_name, lat, lon):
    """讀 NetCDF 並取最近有效格點。有 depth 維度時必須只有一層（表層）。"""
    import xarray as xr  # 只有這裡需要 xarray

    with xr.open_dataset(path) as ds:
        arrays = []
        for name in (u_name, v_name):
            a = ds[name]
            if "depth" in a.dims:
                if a.sizes["depth"] != 1:
                    raise ValueError(f"{path} 的 {name} 有 {a.sizes['depth']} 層深度，這裡只接受表層一層")
                a = a.isel(depth=0)
            arrays.append(a.transpose("time", "latitude", "longitude").values)
        return series_at_point(ds["time"].values, ds["latitude"].values, ds["longitude"].values,
                               arrays[0], arrays[1], lat, lon)


def build_ocean_table(current, wind):
    """合併海流與風。兩者各自傳入 series_at_point 的回傳值；時間取聯集，缺的小時留空。"""
    (cdf, clat, clon, cdist), (wdf, wlat, wlon, wdist) = current, wind
    out = (cdf.rename(columns={"u": "current_u", "v": "current_v"})
           .merge(wdf.rename(columns={"u": "wind_u", "v": "wind_v"}), on="time_utc", how="outer")
           .sort_values("time_utc").reset_index(drop=True))
    out["current_lat"], out["current_lon"], out["current_dist_km"] = clat, clon, cdist
    out["wind_lat"], out["wind_lon"], out["wind_dist_km"] = wlat, wlon, wdist
    return out[OCEAN_COLUMNS]


def main():
    ap = argparse.ArgumentParser(description="抽出沉船最近有效格點的模型海流與風")
    ap.add_argument("--current-nc", required=True, help="海流 NetCDF（變數 uo、vo）")
    ap.add_argument("--wind-nc", required=True, help="風 NetCDF（變數 eastward_wind、northward_wind）")
    ap.add_argument("--out", required=True, help="輸出 CSV 路徑")
    add_event_args(ap)
    args = ap.parse_args()
    event = event_from_args(ap, args)

    cur = read_point_series(args.current_nc, "uo", "vo", event.lat, event.lon)
    wnd = read_point_series(args.wind_nc, "eastward_wind", "northward_wind", event.lat, event.lon)
    table = build_ocean_table(cur, wnd)
    print(f"海流格點 ({cur[1]:.4f}, {cur[2]:.4f})，距事件 {cur[3]:.2f} km")
    print(f"風格點   ({wnd[1]:.4f}, {wnd[2]:.4f})，距事件 {wnd[3]:.2f} km")
    print(f"{len(table)} 筆，{table['time_utc'].min()} → {table['time_utc'].max()}")
    table.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"已寫入 {args.out}")


if __name__ == "__main__":
    main()
