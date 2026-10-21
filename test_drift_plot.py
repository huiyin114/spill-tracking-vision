"""drift_plot.py 的純計算部分的測試。畫圖本身沒有單元測試，用眼睛檢查圖。
陸地遮罩那個測試需要 roaring_landmask（OpenDrift 附帶），沒裝就跳過。"""
import numpy as np
import pandas as pd
import pytest

import drift_plot as dp
from drone import haversine_km

LAT0, LON0 = 22.6, 120.2


# ---- destination / circle ----

def test_destination_cardinal_directions():
    n = dp.destination(LAT0, LON0, 0, 50.0)
    s = dp.destination(LAT0, LON0, 180, 50.0)
    e = dp.destination(LAT0, LON0, 90, 50.0)
    w = dp.destination(LAT0, LON0, 270, 50.0)
    assert n[0] > LAT0 + 0.4 and abs(n[1] - LON0) < 1e-9
    assert s[0] < LAT0 - 0.4 and abs(s[1] - LON0) < 1e-9
    assert e[1] > LON0 + 0.4 and abs(e[0] - LAT0) < 0.01          # 大圓往東，緯度只會略微降低
    assert w[1] < LON0 - 0.4 and abs(w[0] - LAT0) < 0.01


def test_destination_distance_matches_haversine():
    for b in (0, 37, 135, 250):
        la, lo = dp.destination(LAT0, LON0, b, 26.5)
        assert float(haversine_km(LAT0, LON0, la, lo)) == pytest.approx(26.5, rel=1e-6)


def test_destination_one_degree_north_is_about_111_km():
    la, _ = dp.destination(0.0, 100.0, 0, 111.195)
    assert float(la) == pytest.approx(1.0, abs=0.001)


def test_destination_bearing_roundtrip_with_drift_compare():
    from drift_compare import bearing_deg
    la, lo = dp.destination(LAT0, LON0, 135.0, 45.0)
    assert float(bearing_deg(LAT0, LON0, la, lo)) == pytest.approx(135.0, abs=1e-6)


def test_circle_points_are_all_at_the_radius_and_closed():
    la, lo = dp.circle_points(LAT0, LON0, 50.0, n=37)
    assert len(la) == 37 and la[0] == pytest.approx(la[-1]) and lo[0] == pytest.approx(lo[-1], abs=1e-9)
    assert np.allclose(haversine_km(LAT0, LON0, la, lo), 50.0, rtol=1e-6)


# ---- 範圍 ----

def test_map_extent_pads_and_ignores_nan():
    e = dp.map_extent([120.0, 121.0, np.nan], [22.0, 23.0, 99.0], pad_deg=0.5)
    assert e == (119.5, 121.5, 21.5, 23.5)


def test_map_extent_ignores_points_with_only_one_coordinate():
    e = dp.map_extent([120.0, 121.0, 130.0], [22.0, 23.0, np.nan], pad_deg=0.0)
    assert e == (120.0, 121.0, 22.0, 23.0)


def test_map_extent_without_points_raises():
    with pytest.raises(ValueError, match="沒有任何"):
        dp.map_extent([np.nan], [np.nan])


def km_wh(extent, lat0):
    lo0, lo1, la0, la1 = extent
    return (lo1 - lo0) * np.cos(np.radians(lat0)) * 111.19, (la1 - la0) * 111.19


def test_squarish_extent_widens_a_tall_narrow_extent_symmetrically():
    e = dp.squarish_extent((120.0, 120.5, 22.0, 24.5), 23.0)
    w, h = km_wh(e, 23.0)
    assert w / h == pytest.approx(1 / 1.25, rel=1e-6) or w / h == pytest.approx(1.25, rel=1e-6)
    assert (e[0] + e[1]) / 2 == pytest.approx(120.25) and (e[2], e[3]) == (22.0, 24.5)


def test_squarish_extent_heightens_a_wide_flat_extent_symmetrically():
    e = dp.squarish_extent((118.0, 122.0, 22.0, 22.5), 22.0)
    w, h = km_wh(e, 22.0)
    assert w / h == pytest.approx(1.25, rel=1e-6)
    assert (e[2] + e[3]) / 2 == pytest.approx(22.25) and (e[0], e[1]) == (118.0, 122.0)


def test_squarish_extent_leaves_a_roughly_square_extent_alone():
    e = (120.0, 121.0, 22.0, 22.95)
    assert dp.squarish_extent(e, 22.0) == e


# ---- 動畫的時間與重心軌跡 ----

def hourly(n=10, with_gap=False):
    t = pd.date_range("2023-07-20 21:30", periods=n, freq="h", tz="UTC")
    rows = [(ti, 0, 120.0 + 0.01 * i, 22.0 + 0.02 * i, "active") for i, ti in enumerate(t)]
    rows += [(ti, 1, 120.2 + 0.01 * i, 22.2 + 0.02 * i, "active") for i, ti in enumerate(t)]
    return pd.DataFrame(rows, columns=["time_utc", "particle", "lon", "lat", "status"])


def test_frame_times_every_k_hours_and_does_not_repeat_the_last_time():
    p = hourly(10)                                  # 索引 0 到 9；每 3 小時 → 0、3、6、9，9 剛好是最後一個
    got = dp.frame_times(p, 3)
    assert [t.hour for t in got] == [21, 0, 3, 6] and len(got) == len(set(got)) == 4
    assert got[-1] == p["time_utc"].max()


def test_frame_times_appends_the_last_time_when_it_is_not_on_the_grid():
    p = hourly(11)                                  # 索引 0 到 10；0、3、6、9 之後補上 10
    got = dp.frame_times(p, 3)
    assert len(got) == 5 and got[-1] == p["time_utc"].max() and got[-2] - got[-3] == pd.Timedelta(hours=3)
    assert got[-1] - got[-2] == pd.Timedelta(hours=1)


def test_frame_times_uses_the_output_step_not_one_hour():
    t = pd.date_range("2023-07-20 21:30", periods=9, freq="30min", tz="UTC")
    p = pd.DataFrame({"time_utc": t, "particle": 0, "lon": 1.0, "lat": 1.0, "status": "active"})
    got = dp.frame_times(p, 2)                     # 每 2 小時 = 每 4 個輸出
    assert [(b - a) for a, b in zip(got[:-1], got[1:])] == [pd.Timedelta(hours=2)] * (len(got) - 1)


def test_frame_times_at_least_every_output_and_single_time():
    assert len(dp.frame_times(hourly(5), 0.1)) == 5
    one = hourly(1)
    assert dp.frame_times(one, 3) == [one["time_utc"].iloc[0]]


def test_centroid_track_is_mean_per_time_up_to_until():
    p = hourly(5)
    p.loc[(p["time_utc"] == p["time_utc"].iloc[2]) & (p["particle"] == 1), ["lon", "lat"]] = np.nan
    tr = dp.centroid_track(p, p["time_utc"].iloc[3])
    assert len(tr) == 4 and tr["time_utc"].is_monotonic_increasing
    assert tr["lon"].iloc[0] == pytest.approx(120.1) and tr["lat"].iloc[0] == pytest.approx(22.1)
    assert tr["lon"].iloc[2] == pytest.approx(120.02) and tr["lat"].iloc[2] == pytest.approx(22.04)   # 只剩粒子 0
    assert tr["time_utc"].iloc[-1] == p["time_utc"].iloc[3]


def test_centroid_track_without_positions_is_empty():
    p = hourly(3).assign(lon=np.nan, lat=np.nan)
    assert dp.centroid_track(p, p["time_utc"].max()).empty


# ---- 陸地遮罩 ----

def test_land_grid_marks_known_land_and_sea():
    pytest.importorskip("roaring_landmask")
    lons, lats, mask = dp.land_grid((119.9, 120.9, 22.4, 22.8), res_deg=0.05)
    assert mask.shape == (len(lats), len(lons))
    at = lambda lo, la: mask[int(np.abs(lats - la).argmin()), int(np.abs(lons - lo).argmin())]
    assert not at(119.95, 22.5)        # 台灣海峽
    assert at(120.7, 22.7)             # 屏東


def test_frame_times_step_is_the_typical_step_not_the_largest_gap():
    t = list(pd.date_range("2023-07-20 21:30", periods=5, freq="h", tz="UTC")) + \
        list(pd.date_range("2023-07-21 05:30", periods=3, freq="h", tz="UTC"))      # 中間缺 3 小時
    p = pd.DataFrame({"time_utc": t, "particle": 0, "lon": 1.0, "lat": 1.0, "status": "active"})
    assert len(dp.frame_times(p, 2)) == 5          # 典型步長 1 小時 → 每 2 個輸出取一個（0、2、4、6）加最後一個


def test_centroid_track_needs_both_lon_and_lat():
    t = pd.Timestamp("2023-07-20 21:30", tz="UTC")
    p = pd.DataFrame({"time_utc": [t, t], "particle": [0, 1], "lon": [120.0, 130.0], "lat": [22.0, np.nan],
                      "status": "active"})
    tr = dp.centroid_track(p, t)
    assert tr["lon"].iloc[0] == 120.0 and tr["lat"].iloc[0] == 22.0


def test_centroid_track_is_the_mean_not_the_median():
    t = pd.Timestamp("2023-07-20 21:30", tz="UTC")
    p = pd.DataFrame({"time_utc": [t] * 3, "particle": [0, 1, 2], "lon": [120.0, 120.0, 121.5],
                      "lat": [22.0, 22.0, 22.0], "status": "active"})
    assert dp.centroid_track(p, t)["lon"].iloc[0] == pytest.approx(120.5)
