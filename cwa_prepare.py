"""把氣象署 OCM 流場（UCURRd10/VCURRd10）與 WRF 10 m 風（U10M/V10M）整理成 drift_sim.py 讀得懂的檔案。

整理內容（都是我們的選擇，不是氣象署做的）：
  1. 流場缺的時段（d10 的 U 分量缺 2023-07-22 01:00 至 07-23 00:00 共 24 小時）用前後時間線性內插。
  2. 流場的陸地（整段都是缺值的格點）與海陸交界的缺值，用最近的有值格點補，
     否則靠岸的粒子會因為讀不到海流被停用。沉船點離岸只約 6 km，這一步會影響結果。
  3. 加上 CF 標準名稱，OpenDrift 才認得（eastward_sea_water_velocity 等）。

用法：
  python cwa_prepare.py --currents data/raw/cwa/cwa_d10.nc --wind data/raw/cwa/cwa_forcing_U10M_V10M.nc \
      --out-current data/raw/cwa/cwa_current_prepared.nc --out-wind data/raw/cwa/cwa_wind_prepared.nc
"""

import argparse

import numpy as np

CUR_ATTR = {"x": ("uo", "eastward_sea_water_velocity"), "y": ("vo", "northward_sea_water_velocity")}


def fill_nearest(field):
    """二維場：缺值用最近的有值格點補。全缺或沒有缺值時原樣回傳。"""
    from scipy.ndimage import distance_transform_edt

    mask = np.isnan(field)
    if not mask.any() or mask.all():
        return field
    idx = distance_transform_edt(mask, return_distances=False, return_indices=True)
    return field[tuple(idx)]


def fill_cube(cube):
    """(time, lat, lon) 陣列：先沿時間線性內插（整段缺的時間步），再逐時間步用最近格點補空間缺值。"""
    import xarray as xr

    t = np.arange(cube.shape[0])
    filled = xr.DataArray(cube, dims=("t", "y", "x"), coords={"t": t}).interpolate_na("t", method="linear").values
    return np.stack([fill_nearest(f) for f in filled]).astype("float32")


def _coords(time, lat, lon):
    return {"time": time,
            "latitude": ("latitude", lat, {"standard_name": "latitude", "units": "degrees_north"}),
            "longitude": ("longitude", lon, {"standard_name": "longitude", "units": "degrees_east"})}


def prepare_current(ds, x="UCURRd10", y="VCURRd10"):
    import xarray as xr

    dims = ("time", "latitude", "longitude")
    data = {CUR_ATTR[k][0]: (dims, fill_cube(ds[v].values), {"standard_name": CUR_ATTR[k][1], "units": "m s-1"})
            for k, v in (("x", x), ("y", y))}
    return xr.Dataset(data, coords=_coords(ds.time.values, ds.lat.values, ds.lon.values))


def prepare_wind(ds, x="U10M", y="V10M"):
    import xarray as xr

    dims = ("time", "latitude", "longitude")
    data = {"eastward_wind": (dims, ds[x].values, {"standard_name": "eastward_wind", "units": "m s-1"}),
            "northward_wind": (dims, ds[y].values, {"standard_name": "northward_wind", "units": "m s-1"})}
    return xr.Dataset(data, coords=_coords(ds.time.values, ds.lat.values, ds.lon.values))


def main():
    import xarray as xr

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--currents", required=True)
    ap.add_argument("--wind", required=True)
    ap.add_argument("--out-current", required=True)
    ap.add_argument("--out-wind", required=True)
    a = ap.parse_args()
    prepare_current(xr.open_dataset(a.currents)).to_netcdf(a.out_current)
    prepare_wind(xr.open_dataset(a.wind)).to_netcdf(a.out_wind)
    print("已寫入", a.out_current, a.out_wind)


if __name__ == "__main__":
    main()
