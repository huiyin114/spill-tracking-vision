"""extract_ocean.py 的測試：自己造小陣列。讀 NetCDF 的那個測試需要 xarray，沒裝就跳過。"""
import numpy as np
import pandas as pd
import pytest

import extract_ocean as eo

LATS = np.array([22.0, 22.1, 22.2])
LONS = np.array([120.0, 120.1, 120.2])


def field(value, land=()):
    """3 個時間 × 3×3 格點，land 裡的 (i, j) 整段時間都是缺值（陸地遮罩）。"""
    a = np.full((3, 3, 3), float(value))
    for i, j in land:
        a[:, i, j] = np.nan
    return a


def test_valid_mask_marks_cells_missing_at_any_time():
    a = field(1.0)
    a[1, 0, 2] = np.nan            # 只有一個時間缺值，這格也算無效
    m = eo.valid_mask(a)
    assert not m[0, 2] and m.sum() == 8


def test_valid_mask_requires_all_arrays():
    m = eo.valid_mask(field(1.0, land=[(0, 0)]), field(1.0, land=[(2, 2)]))
    assert not m[0, 0] and not m[2, 2] and m.sum() == 7


def test_nearest_valid_cell_picks_closest():
    valid = np.ones((3, 3), dtype=bool)
    i, j, d = eo.nearest_valid_cell(LATS, LONS, valid, 22.09, 120.11)
    assert (i, j) == (1, 1) and d < 2.0


def test_nearest_valid_cell_skips_land():
    valid = np.ones((3, 3), dtype=bool)
    valid[1, 1] = False
    i, j, d = eo.nearest_valid_cell(LATS, LONS, valid, 22.1, 120.1)
    assert (i, j) != (1, 1)
    assert d == pytest.approx(0.1 * 111.19 * np.cos(np.radians(22.1)), rel=0.01)  # 東西相鄰格（0.1° 經度）比南北相鄰近


def test_nearest_valid_cell_distance_is_in_km():
    valid = np.ones((3, 3), dtype=bool)
    _, _, d = eo.nearest_valid_cell(LATS, LONS, valid, 22.0, 120.0 + 0.05)
    assert d == pytest.approx(0.05 * 111.19 * np.cos(np.radians(22.0)), rel=0.01)


def test_nearest_valid_cell_all_land_raises():
    with pytest.raises(ValueError, match="有效格點"):
        eo.nearest_valid_cell(LATS, LONS, np.zeros((3, 3), dtype=bool), 22.1, 120.1)


def test_series_at_point_extracts_the_right_cell_and_time():
    times = pd.to_datetime(["2023-07-20 00:00", "2023-07-20 01:00", "2023-07-20 02:00"])
    u = np.zeros((3, 3, 3)); v = np.zeros((3, 3, 3))
    u[:, 1, 2] = [1, 2, 3]; v[:, 1, 2] = [4, 5, 6]
    df, lat, lon, dist = eo.series_at_point(times, LATS, LONS, u, v, 22.1, 120.2)
    assert (lat, lon) == (22.1, 120.2) and dist == pytest.approx(0.0, abs=1e-9)
    assert list(df["u"]) == [1, 2, 3] and list(df["v"]) == [4, 5, 6]
    assert str(df["time_utc"].dt.tz) == "UTC"
    assert df["time_utc"].iloc[1] == pd.Timestamp("2023-07-20 01:00:00+00:00")


def test_series_at_point_falls_back_to_nearest_valid_when_target_is_land():
    times = pd.to_datetime(["2023-07-20 00:00", "2023-07-20 01:00", "2023-07-20 02:00"])
    u = field(1.0, land=[(1, 1)]); v = field(2.0, land=[(1, 1)])
    df, lat, lon, dist = eo.series_at_point(times, LATS, LONS, u, v, 22.1, 120.1)
    assert (lat, lon) != (22.1, 120.1) and dist > 5
    assert not df[["u", "v"]].isna().any().any()


def test_build_ocean_table_merges_on_time_and_keeps_missing_hours_empty():
    t = pd.to_datetime(["2023-07-20 00:00", "2023-07-20 01:00"], utc=True)
    cur = (pd.DataFrame({"time_utc": t, "u": [1.0, 2.0], "v": [3.0, 4.0]}), 22.58, 120.17, 5.0)
    wnd = (pd.DataFrame({"time_utc": t[1:], "u": [9.0], "v": [8.0]}), 22.56, 120.19, 2.0)
    out = eo.build_ocean_table(cur, wnd)
    assert list(out.columns) == eo.OCEAN_COLUMNS
    assert list(out["current_u"]) == [1.0, 2.0]
    assert np.isnan(out["wind_u"].iloc[0]) and out["wind_u"].iloc[1] == 9.0
    assert (out["current_dist_km"] == 5.0).all() and (out["wind_lon"] == 120.19).all()


def test_read_point_series_from_netcdf_with_depth_dim(tmp_path):
    xr = pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")
    t = pd.to_datetime(["2023-07-20 00:00", "2023-07-20 01:00", "2023-07-20 02:00"])
    u = field(1.0, land=[(1, 1)])[:, None, :, :]            # (time, depth, lat, lon)
    ds = xr.Dataset({"uo": (("time", "depth", "latitude", "longitude"), u),
                     "vo": (("time", "depth", "latitude", "longitude"), u * 2)},
                    coords={"time": t, "depth": [0.49], "latitude": LATS, "longitude": LONS})
    p = tmp_path / "c.nc"
    ds.to_netcdf(p)
    df, lat, lon, dist = eo.read_point_series(p, "uo", "vo", 22.1, 120.1)
    assert (lat, lon) != (22.1, 120.1)
    assert (df["v"] == 2 * df["u"]).all() and len(df) == 3


def test_read_point_series_rejects_multiple_depths(tmp_path):
    xr = pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")
    t = pd.to_datetime(["2023-07-20 00:00"])
    a = np.ones((1, 2, 3, 3))
    ds = xr.Dataset({"uo": (("time", "depth", "latitude", "longitude"), a),
                     "vo": (("time", "depth", "latitude", "longitude"), a)},
                    coords={"time": t, "depth": [0.5, 5.0], "latitude": LATS, "longitude": LONS})
    p = tmp_path / "c.nc"
    ds.to_netcdf(p)
    with pytest.raises(ValueError, match="深度"):
        eo.read_point_series(p, "uo", "vo", 22.1, 120.1)
