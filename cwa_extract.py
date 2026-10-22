"""從氣象署個案 zip（約 14 GB）只抽出模擬範圍與期間的海流與風，存成一個小的 NetCDF。

zip 內的檔案沒有壓縮、NetCDF4 每個時間步的整張場是一個分塊，所以用 HTTP Range 只讀需要的列：
每個時間步只下載約 0.3 MB（1/40° 網格、約 100 列）。每個變數用一個行程，一起跑。

輸入場是氣象署 OCM 預報模式（SCHISM，1/40°、逐時）的海流與 10 m 風，2023 年 7 月，時間軸是
hours since 1800-01-01。時間軸的時區檔案沒有寫（推測是 UTC，沒有驗證），輸出檔照原樣存成 datetime，不轉換。
缺值：檔案實際用 -9999（屬性寫 -999），兩個都當缺值。

用法（在 opendrift 環境）：
  python cwa_extract.py --relax-x509 --out data/raw/cwa/cwa_forcing.nc
"""
import argparse
import re
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta

import numpy as np

import cwa_probe as probe

DEFAULT_VARIABLES = ("UCURR", "VCURR", "U10M", "V10M")
MISSING_VALUES = (-9999.0, -999.0)


def parse_hours_since(units):
    """'hours since 1800-01-01 00:00:0.0' → (起算時間 datetime, 每單位幾小時 = 1)。只支援 hours。"""
    m = re.match(r"\s*hours\s+since\s+(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{1,2}):(\d{1,2})(\.\d+)?", units)
    if not m:
        raise ValueError(f"看不懂時間單位：{units!r}（只支援 hours since YYYY-MM-DD hh:mm:ss）")
    base = datetime.strptime(m.group(1), "%Y-%m-%d") + timedelta(hours=int(m.group(2)), minutes=int(m.group(3)),
                                                                  seconds=int(m.group(4)))
    return base


def time_slice(hours, base, start, end):
    """時間陣列（自 base 起算的小時數）中，落在 [start, end]（含）的索引 slice；範圍內沒有資料就報錯。"""
    t = np.asarray(hours, dtype=float)
    lo = (start - base).total_seconds() / 3600.0
    hi = (end - base).total_seconds() / 3600.0
    idx = np.where((t >= lo) & (t <= hi))[0]
    if idx.size == 0:
        raise ValueError(f"時間 {start} 至 {end} 內沒有資料（檔案範圍 {base + timedelta(hours=float(t.min()))}"
                         f" 至 {base + timedelta(hours=float(t.max()))}）")
    return slice(int(idx.min()), int(idx.max()) + 1)


def mask_missing(values):
    """把缺值（-9999、-999）換成 NaN，回傳 float32 陣列。"""
    a = np.asarray(values, dtype="float32").copy()
    for m in MISSING_VALUES:
        a[a == m] = np.nan
    return a


def extract_variable(url, name, bbox, start, end, relax_x509, block_kb, step_batch=24, cache_dir=None):
    """抽出一個變數：回傳 (時間 datetime64 陣列, 緯度, 經度, 值[time, lat, lon], 下載位元組, 屬性)。"""
    import h5py

    session = probe.make_session(relax_x509)
    member = f"{name}.202307.nc"
    sub, whole = probe.open_member(url, member, session=session)
    sub.block = block_kb * 1024
    south, north, west, east = bbox
    with h5py.File(sub, "r") as h5:
        lat_name, lon_name, time_name = probe.coordinate_names(h5)
        lats, lons = h5[lat_name][:], h5[lon_name][:]
        base = parse_hours_since(h5[time_name].attrs["units"].decode()
                                 if isinstance(h5[time_name].attrs["units"], bytes) else h5[time_name].attrs["units"])
        hours = h5[time_name][:]
        ts = time_slice(hours, base, start, end)
        ys = probe.index_window(lats, (south + north) / 2, (north - south) / 2)
        xs = probe.index_window(lons, (west + east) / 2, (east - west) / 2)
        ds = h5[name]
        pieces = []
        t0 = time.time()
        for a in range(ts.start, ts.stop, step_batch):
            b = min(a + step_batch, ts.stop)
            cached = batch_path(cache_dir, name, a, b, bbox)
            if cached is not None and cached.exists():
                pieces.append(np.load(cached))                  # 上次中斷前已經抽完的批次
                print(f"  {name}: {b - ts.start}/{ts.stop - ts.start} 個時間步（用上次的暫存）", flush=True)
                continue
            idx = probe.plane_index(ds.shape, lats.size, lons.size, slice(a, b), ys, xs)
            if idx is None:
                raise ValueError(f"{name} 的形狀 {ds.shape} 最後兩維不是（緯度, 經度）")
            batch = mask_missing(ds[idx])
            if cached is not None:
                cached.parent.mkdir(parents=True, exist_ok=True)
                np.save(cached, batch)
            pieces.append(batch)
            print(f"  {name}: {b - ts.start}/{ts.stop - ts.start} 個時間步，已下載 {(sub.bytes_fetched + whole.bytes_fetched) / 1e6:.0f} MB，"
                  f"{time.time() - t0:.0f} 秒", flush=True)
        times = np.array([np.datetime64(base + timedelta(hours=float(h))) for h in hours[ts]], dtype="datetime64[ns]")
        attrs = {"units": str(h5[name].attrs.get("units", "")), "source_member": member}
    return times, lats[ys].astype("float64"), lons[xs].astype("float64"), np.concatenate(pieces, axis=0), \
        sub.bytes_fetched + whole.bytes_fetched, attrs


def batch_path(cache_dir, name, a, b, bbox):
    """某個變數、某批時間步、某個範圍的暫存檔路徑；沒有指定暫存資料夾回 None。檔名含索引與範圍，換範圍不會誤用。"""
    if cache_dir is None:
        return None
    south, north, west, east = bbox
    return Path(cache_dir) / f"{name}_{a}_{b}_{south:g}_{north:g}_{west:g}_{east:g}.npy"


def _worker(args):
    return args[1], extract_variable(*args)


def group_by_grid(results):
    """依 (緯度, 經度) 網格把變數分組；網格相同的放同一組，順序依首次出現。

    氣象署的流場與風場網格解析度不同，不能硬塞進同一個 Dataset。
    """
    groups = []
    for n, r in results.items():
        for g in groups:
            ref = results[g[0]]
            if ref[1].shape == r[1].shape and ref[2].shape == r[2].shape and np.allclose(ref[1], r[1]) and np.allclose(ref[2], r[2]):
                g.append(n)
                break
        else:
            groups.append([n])
    return groups


def build_dataset(results):
    """同一網格的各變數 → xarray Dataset。

    各變數的時間軸可以不一樣（氣象署的 VCURR 比 UCURR 少了一段），只留所有變數都有的時間；
    緯度、經度必須一致（先用 group_by_grid 分組），否則報錯並印出形狀。沒有共同時間也報錯。
    """
    import xarray as xr

    names = list(results)
    first = results[names[0]]
    for n in names[1:]:
        r = results[n]
        if not (r[1].shape == first[1].shape and r[2].shape == first[2].shape
                and np.allclose(first[1], r[1]) and np.allclose(first[2], r[2])):
            raise ValueError(f"{n} 的座標與 {names[0]} 不一致（緯度 {r[1].shape} vs {first[1].shape}，經度 {r[2].shape} vs {first[2].shape}）")
    common = first[0]
    for n in names[1:]:
        common = np.intersect1d(common, results[n][0])
    if common.size == 0:
        raise ValueError("各變數沒有共同的時間")
    data = {}
    for n in names:
        times, _, _, vals, _, attrs = results[n]
        data[n] = (("time", "lat", "lon"), vals[np.isin(times, common)], attrs)
    return xr.Dataset(data, coords={"time": common, "lat": first[1], "lon": first[2]})


def main():
    ap = argparse.ArgumentParser(description="從氣象署個案 zip 抽出範圍與期間（不下載整包）")
    ap.add_argument("--url", default=probe.DEFAULT_URL)
    ap.add_argument("--variables", nargs="+", default=list(DEFAULT_VARIABLES))
    ap.add_argument("--bbox", nargs=4, type=float, default=(21.0, 23.5, 119.0, 121.5), metavar=("S", "N", "W", "E"))
    ap.add_argument("--start", default="2023-07-19 00:00", help="檔案時間軸上的時間（時區不明，視為與檔案相同）")
    ap.add_argument("--end", default="2023-07-29 00:00")
    ap.add_argument("--block-kb", type=int, default=512, help="Range 請求的區塊大小")
    ap.add_argument("--relax-x509", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache-dir", help="每批時間步的暫存資料夾（預設是輸出檔旁邊的 <輸出檔名>.parts）；中斷後重跑會接著做")
    args = ap.parse_args()
    cache_dir = args.cache_dir or str(Path(args.out).with_suffix("")) + ".parts"
    start, end = datetime.fromisoformat(args.start), datetime.fromisoformat(args.end)
    jobs = [(args.url, v, tuple(args.bbox), start, end, args.relax_x509, args.block_kb, 24, cache_dir) for v in args.variables]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=len(jobs)) as pool:
        results = dict(pool.map(_worker, jobs))
    for n, r in results.items():
        print(f"{n}: {len(r[0])} 個時間步，{r[0][0]} 至 {r[0][-1]}")
    note = ("氣象署 OCM（SCHISM）海流與 10 m 風，2023-07，擷取自個案頁 898.zip；"
            "時間軸時區未知（推測 UTC，未驗證）；缺值已換成 NaN")
    total = sum(r[4] for r in results.values())
    for k, group in enumerate(group_by_grid(results)):
        ds = build_dataset({n: results[n] for n in group})
        print(f"{'+'.join(group)}：網格 {ds.sizes['lat']}×{ds.sizes['lon']}，共同時間 {ds.sizes['time']} 個時間步，"
              f"{ds.time.values[0]} 至 {ds.time.values[-1]}")
        ds.attrs["note"] = note
        out = Path(args.out) if k == 0 else Path(args.out).with_name(f"{Path(args.out).stem}_{'_'.join(group)}.nc")
        out.parent.mkdir(parents=True, exist_ok=True)
        ds.to_netcdf(out)
        print(f"已寫入 {out}：{dict(ds.sizes)}")
    print(f"共下載 {total / 1e6:.0f} MB，花 {time.time() - t0:.0f} 秒")


if __name__ == "__main__":
    main()
